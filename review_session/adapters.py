"""Restricted CLI commands and strict decoding of provider responses.

The runner supplies an empty private working directory and all task text through
stdin. These flags reduce model tools and customizations; administrator policy
and the installed CLI remain trusted, rather than being isolated by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import uuid

from .core import SessionError
from .prompt_policy import AUTOMATED_POLICY


RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "artifact": {"type": "string"},
        "verdict": {"type": "string", "enum": ["comment", "approve", "disagree"]},
        "reviewed_sha256": {"type": "string"},
    },
    "required": ["message", "artifact", "verdict", "reviewed_sha256"],
    "additionalProperties": False,
}


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("Non-finite JSON value")


def _json(text: str) -> object:
    return json.loads(text, object_pairs_hook=_unique_fields, parse_constant=_invalid_constant)


def _session_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Missing provider session ID")
    parsed = uuid.UUID(value)
    if str(parsed) != value.lower():
        raise ValueError("Provider session ID must be a hyphenated UUID")
    return value


def _response(value: object) -> dict:
    fields = RESPONSE_SCHEMA["properties"]
    if not isinstance(value, dict) or value.keys() != fields.keys():
        raise ValueError("Response must contain exactly the required fields")
    if any(not isinstance(value[field], str) for field in fields):
        raise ValueError("Response fields must be strings")
    for text in value.values():
        text.encode("utf-8")
    if not value["message"].strip() or value["verdict"] not in fields["verdict"]["enum"]:
        raise ValueError("Response has an empty message or invalid verdict")
    digest = value["reviewed_sha256"]
    if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Reviewed SHA-256 must be empty or 64 lowercase hexadecimal characters")
    if value["verdict"] == "approve" and not digest:
        raise ValueError("Approval requires the reviewed SHA-256")
    return value


@dataclass(frozen=True)
class Adapter:
    kind: str
    executable: str
    model: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("codex", "claude"):
            raise SessionError("invalid_argument", "Runner provider must be codex or claude.")
        if not isinstance(self.executable, str) or not self.executable.strip():
            raise SessionError("invalid_argument", "Runner executable must not be empty.")
        if self.model is not None and (not isinstance(self.model, str) or not self.model.strip()):
            raise SessionError("invalid_argument", "Runner model must not be empty.")

    def command(self, workdir: Path, schema_path: Path, session_id: str | None = None) -> list[str]:
        if session_id is not None:
            try:
                _session_id(session_id)
            except (ValueError, AttributeError) as error:
                raise SessionError("runner_response", "Invalid saved provider session ID.") from error
        if self.kind == "codex":
            # Global policy flags also apply to resume, which lacks --sandbox.
            command = [self.executable, "--no-daemon", "--sandbox", "read-only",
                       "--ask-for-approval", "never", "--cd", str(workdir)]
            for feature in ("shell_tool", "hooks", "plugins", "apps", "multi_agent",
                            "browser_use", "computer_use", "image_generation", "goals"):
                command += ["--disable", feature]
            for setting in ('web_search="disabled"', "mcp_servers={}",
                            "tools.view_image=false", "project_doc_max_bytes=0"):
                command += ["--config", setting]
            command += ["--config", "developer_instructions=" + json.dumps(AUTOMATED_POLICY)]
            command += ["exec"]
            if session_id is not None:
                command += ["resume"]
            command += ["--json", "--ignore-user-config", "--ignore-rules",
                        "--skip-git-repo-check", "--output-schema", str(schema_path)]
            if self.model is not None:
                command += ["--model", self.model]
            return command + ([session_id] if session_id is not None else []) + ["-"]
        command = [self.executable, "-p", "--output-format", "json", "--json-schema",
                   json.dumps(RESPONSE_SCHEMA, separators=(",", ":")), "--tools", "",
                   "--append-system-prompt", AUTOMATED_POLICY,
                   "--system-prompt-snapshot", "off",
                   "--safe-mode", "--restricted", "--strict-mcp-config", "--mcp-config",
                   '{"mcpServers":{}}', "--disallowedTools", "mcp__*", "--setting-sources", "",
                   "--settings", '{"disableAllHooks":true}',
                   "--disable-slash-commands", "--no-chrome", "--permission-mode", "dontAsk",
                   "--permission-prompts", "none"]
        if self.model is not None:
            command += ["--model", self.model]
        if session_id is not None:
            command += ["--resume", session_id]
        return command

    def decode(self, stdout: str) -> tuple[str, dict]:
        try:
            if not isinstance(stdout, str) or not stdout.strip():
                raise ValueError("Provider returned no output")
            if self.kind == "claude":
                result = _json(stdout)
                if not isinstance(result, dict):
                    raise ValueError("Claude result must be an object")
                if result.get("is_error") is not False or result.get("subtype") != "success":
                    raise SessionError("runner_provider", "Claude did not report a successful turn.")
                if result.get("type") != "result" or result.get("permission_denials"):
                    raise SessionError("runner_provider", "Claude reported a tool request or invalid result.")
                if result.get("tool_calls") or result.get("tool_use"):
                    raise SessionError("runner_provider", "Claude returned an unexpected tool request.")
                return _session_id(result.get("session_id")), _response(result.get("structured_output"))
            session_id = None
            response = None
            completed = False
            # JSONL records use LF. Other Unicode line separators may occur
            # literally inside valid JSON strings and must remain unchanged.
            for line in stdout.split('\n'):
                if not line.strip():
                    continue
                event = _json(line)
                if not isinstance(event, dict) or completed:
                    raise ValueError("Invalid event or output after turn completion")
                event_type = event.get("type")
                if event_type in ("error", "turn.failed"):
                    raise SessionError("runner_provider", "Codex reported a failed turn.")
                if event_type == "thread.started":
                    if session_id is not None:
                        raise ValueError("More than one provider session ID")
                    session_id = _session_id(event.get("thread_id"))
                elif event_type == "turn.started":
                    continue
                elif event_type == "turn.completed":
                    completed = True
                elif event_type in ("item.started", "item.updated", "item.completed"):
                    item = event.get("item")
                    if not isinstance(item, dict) or item.get("type") not in ("agent_message", "reasoning"):
                        raise SessionError("runner_provider", "Codex returned an unexpected tool request.")
                    if event_type == "item.completed" and item["type"] == "agent_message":
                        response = item.get("text")
                else:
                    raise ValueError("Unknown provider event")
            if not completed or session_id is None or not isinstance(response, str):
                raise ValueError("Missing session ID, final response, or completed turn")
            return session_id, _response(_json(response))
        except (ValueError, TypeError, AttributeError, RecursionError, UnicodeError) as error:
            raise SessionError("runner_response", "Provider output is incomplete or invalid; inspect the saved turn logs.") from error
