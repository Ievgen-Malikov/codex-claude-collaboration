"""Private, durable bookkeeping for the opt-in subprocess runner."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Any, Iterator
import uuid

from .core import PARTICIPANTS, SessionError, atomic_json, parse_timestamp


RUNNER_FILE = "runner.json"
MAX_TEXT_BYTES = 131072
JOB_ID = re.compile(r"(?:proposal-agent-[ab]|draft-[1-9][0-9]*|review-[1-9][0-9]*-agent-[ab])\Z")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_response(job: dict, response: Any) -> None:
    if not isinstance(response, dict) or set(response) != {"message", "artifact", "verdict", "reviewed_sha256"}:
        raise ValueError("Response does not match the review schema")
    if any(not isinstance(value, str) for value in response.values()):
        raise ValueError("Response fields must be strings")
    sizes = {key: len(value.encode("utf-8")) for key, value in response.items()}
    if not response["message"].strip() or sizes["message"] > 65536:
        raise ValueError("Message is empty or exceeds 65536 bytes")
    if response["verdict"] not in ("comment", "approve", "disagree"):
        raise ValueError("Invalid review verdict")
    if job["stage"] == "review":
        if response["artifact"] or not job["artifact_sha256"] or response["reviewed_sha256"] != job["artifact_sha256"]:
            raise ValueError("Review must name the supplied artifact hash and cannot replace it")
    else:
        if response["verdict"] != "comment" or response["reviewed_sha256"]:
            raise ValueError("Only a review can approve or disagree")
        if job["stage"] == "proposal" and response["artifact"]:
            raise ValueError("A proposal cannot replace the report")
        if job["stage"] == "draft" and (not response["artifact"].strip() or sizes["artifact"] > MAX_TEXT_BYTES):
            raise ValueError("Draft is empty or exceeds 131072 bytes")


def read_input(path: str) -> dict[str, str]:
    source = Path(path).expanduser().absolute()
    try:
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise SessionError("invalid_argument", "Inputs must be regular UTF-8 text files.")
            data = handle.read(MAX_TEXT_BYTES + 1)
            after = os.fstat(handle.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise SessionError("invalid_argument", "Input changed while snapshotting; finish edits and retry.")
        if len(data) > MAX_TEXT_BYTES:
            raise SessionError("invalid_argument", "Combined inputs exceed 131072 UTF-8 bytes.")
        text = data.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise SessionError("invalid_argument", f"Cannot snapshot input {source.name}: {error}") from None
    return {"name": source.name, "text": text, "sha256": sha256(text)}


def configuration(inputs: list[str], max_rounds: int, turn_timeout: float,
                  codex_command: str, claude_command: str,
                  codex_model: str | None, claude_model: str | None) -> tuple[dict, list[dict]]:
    if type(max_rounds) is not int or not 1 <= max_rounds <= 10:
        raise SessionError("invalid_argument", "--max-rounds must be between 1 and 10.")
    if not math.isfinite(turn_timeout) or turn_timeout <= 0:
        raise SessionError("invalid_argument", "--turn-timeout must be finite and positive.")
    if not inputs:
        raise SessionError("invalid_argument", "Supply at least one --input UTF-8 text file.")
    snapshots = []
    total = 0
    for path in inputs:
        item = read_input(path)
        total += len(item["text"].encode("utf-8"))
        if total > MAX_TEXT_BYTES:
            raise SessionError("invalid_argument", "Combined inputs exceed 131072 UTF-8 bytes.")
        snapshots.append(item)
    adapters = {}
    for agent, kind, command, model in (("agent-a", "codex", codex_command, codex_model),
                                       ("agent-b", "claude", claude_command, claude_model)):
        if not isinstance(command, str) or not command.strip():
            raise SessionError("invalid_argument", f"{kind} executable must not be empty.")
        executable = shutil.which(command)
        if executable is None:
            raise SessionError("runner_unavailable", f"{kind} executable not found: {command}")
        if model is not None and not model.strip():
            raise SessionError("invalid_argument", "Model names must not be empty.")
        adapters[agent] = {"kind": kind, "executable": str(Path(executable).absolute()), "model": model}
    return {"max_rounds": max_rounds, "turn_timeout": turn_timeout, "adapters": adapters}, snapshots


def validate(data: Any, session_id: str | None = None) -> None:
    """Never turn a corrupt journal into new paid invocations."""
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported runner schema")
    uuid.UUID(data["session_id"])
    if session_id is not None and data["session_id"] != session_id:
        raise ValueError("Runner belongs to another session")
    if data["status"] not in ("running", "complete", "failed", "unknown"):
        raise ValueError("Invalid runner status")
    if data["error"] is not None and not isinstance(data["error"], str):
        raise ValueError("Invalid runner error")
    config = data["config"]
    if type(config["max_rounds"]) is not int or not 1 <= config["max_rounds"] <= 10:
        raise ValueError("Invalid round limit")
    timeout = config["turn_timeout"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Invalid turn timeout")
    if set(config["adapters"]) != set(PARTICIPANTS):
        raise ValueError("Invalid adapter participants")
    for agent, kind in zip(PARTICIPANTS, ("codex", "claude")):
        adapter = config["adapters"][agent]
        if adapter["kind"] != kind or not isinstance(adapter["executable"], str) or not Path(adapter["executable"]).is_absolute():
            raise ValueError("Invalid adapter")
        if adapter["model"] is not None and (not isinstance(adapter["model"], str) or not adapter["model"].strip()):
            raise ValueError("Invalid model")
    if not isinstance(data["inputs"], list) or not data["inputs"]:
        raise ValueError("Missing input snapshots")
    total = 0
    for item in data["inputs"]:
        if not isinstance(item["name"], str) or not isinstance(item["text"], str) or sha256(item["text"]) != item["sha256"]:
            raise ValueError("Invalid input snapshot")
        total += len(item["text"].encode("utf-8"))
    if total > MAX_TEXT_BYTES:
        raise ValueError("Input snapshots exceed limit")
    if not isinstance(data["provider_sessions"], dict) or not set(data["provider_sessions"]) <= set(PARTICIPANTS):
        raise ValueError("Invalid provider sessions")
    for value in data["provider_sessions"].values():
        uuid.UUID(value)
    if not isinstance(data["jobs"], dict):
        raise ValueError("Invalid jobs")
    for identifier, job in data["jobs"].items():
        if not JOB_ID.fullmatch(identifier) or job["agent"] not in PARTICIPANTS:
            raise ValueError("Invalid job identity")
        if job["stage"] not in ("proposal", "draft", "review") or type(job["round"]) is not int:
            raise ValueError("Invalid job stage")
        if job["stage"] == "proposal":
            expected_id = "proposal-" + job["agent"]
            if job["round"] != 0:
                raise ValueError("Invalid proposal round")
        else:
            if not 1 <= job["round"] <= config["max_rounds"]:
                raise ValueError("Invalid review round")
            expected_id = f'draft-{job["round"]}' if job["stage"] == "draft" else f'review-{job["round"]}-{job["agent"]}'
            if job["stage"] == "draft" and job["agent"] != "agent-a":
                raise ValueError("Only agent-a can propose a draft")
        if identifier != expected_id:
            raise ValueError("Job ID does not match its stage, round and participant")
        if job["status"] not in ("running", "completed", "applied", "failed"):
            raise ValueError("Invalid job status")
        if "error" in job and (job["status"] != "failed" or not isinstance(job["error"], str)
                               or not job["error"].strip()):
            raise ValueError("Invalid failed job reason")
        parse_timestamp(job["started_at"])
        for field in ("message_ids", "peer_message_ids"):
            values = job[field]
            if (not isinstance(values, list) or any(type(value) is not int or value <= 0 for value in values)
                    or values != sorted(set(values))):
                raise ValueError("Invalid message IDs")
        if not set(job["peer_message_ids"]) <= set(job["message_ids"]):
            raise ValueError("Peer message IDs do not belong to the input context")
        if job["artifact_sha256"] is not None and not re.fullmatch(r"[0-9a-f]{64}", job["artifact_sha256"]):
            raise ValueError("Invalid artifact hash")
        if job["pid"] is not None and (type(job["pid"]) is not int or job["pid"] <= 0):
            raise ValueError("Invalid process ID")
        if job["status"] in ("completed", "applied"):
            validate_response(job, job["response"])
            provider = job["provider_session_id"]
            uuid.UUID(provider)
            if data["provider_sessions"].get(job["agent"]) != provider:
                raise ValueError("Job provider session differs from participant session")
        elif job["response"] is not None or job["provider_session_id"] is not None:
            raise ValueError("Incomplete job cannot carry a completed response")


def load(root: Path, session_id: str | None = None) -> dict:
    try:
        data = json.loads((root / RUNNER_FILE).read_text(encoding="utf-8"))
        validate(data, session_id)
        return data
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError) as error:
        raise SessionError("invalid_runner", f"Runner journal is missing or invalid: {error}") from None


def save(root: Path, data: dict) -> None:
    validate(data)
    atomic_json(root / RUNNER_FILE, data)


def prepare_job_directory(root: Path, identifier: str) -> Path:
    """Reuse only unjournaled preparation; provider logs make a retry unsafe."""
    if not JOB_ID.fullmatch(identifier):
        raise SessionError("invalid_runner", "Invalid turn directory identifier.")
    parent = root / ".runner"
    parent.mkdir(mode=0o700, exist_ok=True)
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            os.mkdir(identifier, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        directory_fd = os.open(identifier, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                               dir_fd=parent_fd)
        try:
            for name in ("stdout.jsonl", "stderr.log"):
                try:
                    os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise SessionError("runner_outcome_unknown", "Unjournaled turn has provider logs; inspect and preserve them before starting a fresh review. No model call was retried.")
        finally:
            os.close(directory_fd)
    finally:
        os.close(parent_fd)
    return parent / identifier


@contextmanager
def owner_lock(root: Path) -> Iterator[None]:
    """Hold ownership for the whole run, separately from short helper locks."""
    descriptor = os.open(root / ".runner.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "r+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SessionError("runner_busy", "Another coordinator owns this session.") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def summary(root: Path) -> dict | None:
    if not (root / RUNNER_FILE).exists():
        return None
    data = load(root)
    counts = {name: 0 for name in ("running", "completed", "applied", "failed")}
    for job in data["jobs"].values():
        counts[job["status"]] += 1
    return {"status": data["status"], "jobs": counts,
            "provider_sessions": data["provider_sessions"], "error": data["error"],
            "max_rounds": data["config"]["max_rounds"], "turn_timeout": data["config"]["turn_timeout"]}
