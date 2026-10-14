"""Synthetic provider output; these tests never start a model CLI."""

import json
from pathlib import Path
import unittest

from review_session.adapters import Adapter, RESPONSE_SCHEMA
from review_session.core import SessionError


SESSION_ID = "11111111-2222-4333-8444-555555555555"
RESPONSE = {"message": "Synthetic review.", "artifact": "", "verdict": "comment", "reviewed_sha256": ""}


def codex_output(response=None, extra_events=(), ensure_ascii=True):
    events = [
        {"type": "thread.started", "thread_id": SESSION_ID},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "reasoning", "text": "Synthetic thought."}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(response or RESPONSE, ensure_ascii=ensure_ascii)}},
        *extra_events,
        {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
    ]
    return "\n".join(json.dumps(event, ensure_ascii=ensure_ascii) for event in events)


def claude_output(response=None, **fields):
    return json.dumps({"type": "result", "subtype": "success", "is_error": False,
                       "session_id": SESSION_ID, "structured_output": response or RESPONSE,
                       "permission_denials": [], **fields})


class AdapterTests(unittest.TestCase):
    def assert_error(self, adapter, output, code="runner_response"):
        with self.assertRaises(SessionError) as caught:
            adapter.decode(output)
        self.assertEqual(caught.exception.code, code)

    def test_schema_requires_exact_response_fields(self):
        self.assertEqual(set(RESPONSE_SCHEMA["required"]), set(RESPONSE))
        self.assertFalse(RESPONSE_SCHEMA["additionalProperties"])
        for field in RESPONSE_SCHEMA["properties"].values():
            self.assertEqual(field["type"], "string")

    def test_codex_commands_restrict_initial_and_explicit_resume(self):
        adapter = Adapter("codex", "/synthetic path/codex", model="synthetic-model")
        for session_id in (None, SESSION_ID):
            with self.subTest(session_id=session_id):
                command = adapter.command(Path("/isolated path"), Path("/schema.json"), session_id)
                self.assertEqual(command[0], "/synthetic path/codex")
                self.assertEqual(command[command.index("--cd") + 1], "/isolated path")
                self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
                self.assertEqual(command[command.index("--ask-for-approval") + 1], "never")
                self.assertLess(command.index("--sandbox"), command.index("exec"))
                for flag in ("--json", "--ignore-user-config", "--ignore-rules", "--no-daemon"):
                    self.assertIn(flag, command)
                disabled = {command[index + 1] for index, flag in enumerate(command) if flag == "--disable"}
                self.assertTrue({"shell_tool", "hooks", "plugins", "apps", "multi_agent", "browser_use",
                                 "computer_use", "image_generation", "goals"} <= disabled)
                self.assertIn('web_search="disabled"', command)
                self.assertIn("mcp_servers={}", command)
                self.assertIn("project_doc_max_bytes=0", command)
                self.assertEqual(command[command.index("--output-schema") + 1], "/schema.json")
                self.assertEqual(command[command.index("--model") + 1], "synthetic-model")
                self.assertNotIn("--last", command)
                self.assertNotIn("--ephemeral", command)
                self.assertEqual(command[-1], "-")
                if session_id:
                    self.assertEqual(command[command.index("exec") + 1], "resume")
                    self.assertEqual(command[-2], session_id)
                else:
                    self.assertNotIn("resume", command)

    def test_claude_commands_disable_tools_and_customizations(self):
        adapter = Adapter("claude", "claude", model="synthetic-model")
        for session_id in (None, SESSION_ID):
            with self.subTest(session_id=session_id):
                command = adapter.command(Path("/isolated"), Path("/schema.json"), session_id)
                self.assertEqual(command[command.index("--tools") + 1], "")
                self.assertEqual(command[command.index("--setting-sources") + 1], "")
                self.assertEqual(json.loads(command[command.index("--mcp-config") + 1]), {"mcpServers": {}})
                self.assertEqual(command[command.index("--disallowedTools") + 1], "mcp__*")
                self.assertEqual(json.loads(command[command.index("--settings") + 1]), {"disableAllHooks": True})
                self.assertEqual(json.loads(command[command.index("--json-schema") + 1]), RESPONSE_SCHEMA)
                for flag in ("-p", "--safe-mode", "--restricted", "--strict-mcp-config", "--disable-slash-commands", "--no-chrome"):
                    self.assertIn(flag, command)
                self.assertEqual(command[command.index("--permission-prompts") + 1], "none")
                self.assertNotIn("--bare", command)  # Subscription authentication remains usable.
                self.assertNotIn("--continue", command)
                self.assertNotIn("--no-session-persistence", command)
                if session_id:
                    self.assertEqual(command[command.index("--resume") + 1], session_id)
                else:
                    self.assertNotIn("--resume", command)

    def test_invalid_configuration_and_saved_ids_fail_before_launch(self):
        for arguments in (("other", "cli"), ("codex", ""), ("claude", "cli", "")):
            with self.subTest(arguments=arguments), self.assertRaises(SessionError):
                Adapter(*arguments)
        for kind in ("codex", "claude"):
            for session_id in ("--last", "name", "", 3):
                with self.subTest(kind=kind, session_id=session_id), self.assertRaises(SessionError):
                    Adapter(kind, kind).command(Path("/isolated"), Path("/schema"), session_id)

    def test_successful_outputs_return_exact_session_and_response(self):
        self.assertEqual(Adapter("codex", "codex").decode(codex_output()), (SESSION_ID, RESPONSE))
        self.assertEqual(Adapter("claude", "claude").decode(claude_output()), (SESSION_ID, RESPONSE))
        approval = {**RESPONSE, "verdict": "approve", "reviewed_sha256": "a" * 64}
        self.assertEqual(Adapter("codex", "codex").decode(codex_output(approval))[1], approval)

    def test_codex_uses_last_completed_agent_message(self):
        output = codex_output(extra_events=[{"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({**RESPONSE, "message": "Final synthetic reply."})}}])
        self.assertEqual(Adapter("codex", "codex").decode(output)[1]["message"], "Final synthetic reply.")

    def test_codex_jsonl_preserves_literal_unicode_line_separators_inside_strings(self):
        for separator in ('\u0085', '\u2028', '\u2029'):
            with self.subTest(separator=repr(separator)):
                response = {**RESPONSE, 'message': 'Before' + separator + 'after'}
                output = codex_output(response, ensure_ascii=False)
                self.assertIn(separator, output)
                self.assertEqual(Adapter('codex', 'codex').decode(output), (SESSION_ID, response))

    def test_codex_rejects_failures_and_tool_requests(self):
        adapter = Adapter("codex", "codex")
        for event in ({"type": "turn.failed"}, {"type": "error"}):
            with self.subTest(event=event):
                self.assert_error(adapter, codex_output(extra_events=[event]), "runner_provider")
        for item_type in ("command_execution", "file_change", "mcp_tool_call", "web_search", "future_tool"):
            for event_type in ("item.started", "item.completed"):
                with self.subTest(item_type=item_type, event_type=event_type):
                    self.assert_error(adapter, codex_output(extra_events=[{"type": event_type, "item": {"type": item_type}}]), "runner_provider")

    def test_codex_requires_unambiguous_completed_turn(self):
        adapter = Adapter("codex", "codex")
        lines = codex_output().splitlines()
        invalid_outputs = ["\n".join(lines[:-1]), "\n".join(lines[1:]), "\n".join(lines[:3] + lines[4:]),
                           codex_output() + '\n{"type":"turn.started"}',
                           codex_output(extra_events=[{"type": "thread.started", "thread_id": SESSION_ID}]),
                           codex_output().replace(SESSION_ID, "name"),
                           codex_output(extra_events=[{"type": "future.event"}])]
        for output in invalid_outputs:
            with self.subTest(output=output):
                self.assert_error(adapter, output)

    def test_claude_rejects_failed_results_and_tool_requests(self):
        adapter = Adapter("claude", "claude")
        for fields in ({"is_error": True}, {"is_error": "false"}, {"subtype": "error_max_turns"},
                       {"type": "assistant"}, {"permission_denials": [{"tool_name": "Bash"}]},
                       {"tool_calls": [{"name": "Bash"}]}, {"tool_use": [{"name": "Read"}]}):
            with self.subTest(fields=fields):
                self.assert_error(adapter, claude_output(**fields), "runner_provider")
        self.assert_error(adapter, claude_output(session_id="name"))
        self.assert_error(adapter, claude_output(structured_output="text"))

    def test_invalid_response_fields_are_rejected_for_both_providers(self):
        invalid_responses = [{**RESPONSE, "extra": "bad"}, {key: value for key, value in RESPONSE.items() if key != "artifact"},
                             {**RESPONSE, "message": None}, {**RESPONSE, "message": " "},
                             {**RESPONSE, "message": "\ud800"}, {**RESPONSE, "verdict": "AGREED"},
                             {**RESPONSE, "verdict": "approve"}, {**RESPONSE, "reviewed_sha256": "bad"}]
        for response in invalid_responses:
            for kind, output in (("codex", codex_output(response)), ("claude", claude_output(response))):
                with self.subTest(kind=kind, response=repr(response)):
                    self.assert_error(Adapter(kind, kind), output)

    def test_arbitrary_invalid_json_never_escapes_as_a_traceback(self):
        for kind in ("codex", "claude"):
            for output in (None, "", "   ", "not JSON", "[]", "null", "1", "{}", '{"x":1,"x":2}', '{"x":NaN}', '[' * 2000):
                with self.subTest(kind=kind, output=repr(output)[:80]):
                    self.assert_error(Adapter(kind, kind), output, "runner_provider" if kind == "claude" and output == "{}" else "runner_response")


if __name__ == "__main__":
    unittest.main()
