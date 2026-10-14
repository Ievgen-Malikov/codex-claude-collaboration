"""Observable CLI and filesystem contracts; no models, network, or credentials."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from review_session.cli import main
from review_session.core import Session, SessionError, parse_timestamp, utc_now


class SessionCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "session"

    def command(self, command, *arguments, error=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([command, str(self.path), *arguments])
        self.assertNotIn("Traceback", stderr.getvalue())
        if error:
            self.assertEqual(code, 2, stdout.getvalue())
            self.assertEqual(stdout.getvalue(), "")
            value = json.loads(stderr.getvalue())
            self.assertFalse(value["ok"])
            self.assertEqual(value["error"]["code"], error, value)
        else:
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertEqual(stderr.getvalue(), "")
            value = json.loads(stdout.getvalue())
            self.assertTrue(value["ok"])
        return value

    def initialize(self):
        return self.command("init", "--goal", "Independently review the draft", "--minutes", "30")

    def active(self):
        self.initialize()
        for agent in ("agent-a", "agent-b"):
            self.command("join", "--agent", agent)
        return self.command("start")

    def artifact(self, text="Version one", name="result.md"):
        path = self.path / "artifacts" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return "artifacts/" + name

    def approve_both(self, artifact):
        for agent in ("agent-a", "agent-b"):
            self.command("approve", "--agent", agent, "--artifact", artifact)

    def test_initialization_preserves_unrelated_files_and_refuses_existing_session(self):
        self.path.mkdir()
        unrelated = self.path / "personal-note.txt"
        unrelated.write_text("Preserve me")
        initialized = self.initialize()
        self.assertEqual(initialized["phase"], "PREPARING")
        self.assertEqual(initialized["participants"], ["agent-a", "agent-b"])
        original_state = (self.path / "session.json").read_bytes()
        self.command("init", "--goal", "Replace it", error="already_exists")
        self.assertEqual((self.path / "session.json").read_bytes(), original_state)
        self.assertEqual(unrelated.read_text(), "Preserve me")

    def test_initialization_refuses_reserved_directory_without_overwriting(self):
        (self.path / "artifacts").mkdir(parents=True)
        original = self.path / "artifacts" / "important.txt"
        original.write_text("Keep")
        self.command("init", "--goal", "Review", error="already_exists")
        self.assertEqual(original.read_text(), "Keep")
        self.assertFalse((self.path / "session.json").exists())

    def test_start_requires_both_fresh_participants_and_cannot_reset_deadline(self):
        self.initialize()
        self.command("start", error="not_ready")
        self.command("join", "--agent", "agent-a")
        self.command("start", error="not_ready")
        self.command("join", "--agent", "agent-b")
        started = self.command("start")
        self.assertEqual(started["phase"], "ACTIVE")
        self.assertEqual(parse_timestamp(started["deadline"]) - parse_timestamp(started["started_at"]),
                         timedelta(minutes=30))
        self.command("start", error="already_started")
        self.command("join", "--agent", "agent-a", error="already_started")
        self.assertEqual(self.command("status")["deadline"], started["deadline"])

    def test_stale_readiness_requires_new_join(self):
        self.initialize()
        now = utc_now()
        with patch("review_session.core.utc_now", return_value=now):
            self.command("join", "--agent", "agent-a")
            self.command("join", "--agent", "agent-b")
        with patch("review_session.core.utc_now", return_value=now + timedelta(seconds=301)):
            self.assertFalse(self.command("status")["readiness_fresh"]["agent-a"])
            self.command("start", error="not_ready")
            self.command("join", "--agent", "agent-a")
            self.command("join", "--agent", "agent-b")
            self.assertEqual(self.command("start")["phase"], "ACTIVE")

    def test_cannot_send_or_approve_before_start(self):
        self.initialize()
        artifact = self.artifact()
        self.command("send", "--agent", "agent-a", "--kind", "proposal", "--text", "Draft", error="not_active")
        self.command("approve", "--agent", "agent-a", "--artifact", artifact, error="not_active")

    def test_inbox_is_shared_ordered_read_only_and_after_is_explicit(self):
        self.active()
        literal = "$(touch SHOULD_NOT_EXIST); `echo no`; agent text\nПривет"
        first = self.command("send", "--agent", "agent-a", "--kind", "proposal", "--text", literal)
        self.command("send", "--agent", "agent-b", "--kind", "reply", "--text", "Consider revision")
        before = {str(path.relative_to(self.path)): path.read_bytes()
                  for path in self.path.rglob("*") if path.is_file()}
        inbox = self.command("inbox", "--agent", "agent-b")
        again = self.command("inbox", "--agent", "agent-b")
        self.assertEqual(inbox, again)
        self.assertEqual([item["id"] for item in inbox["messages"]], [1, 2])
        self.assertEqual(inbox["messages"][0]["text"], literal)
        self.assertEqual(first["message"]["session_id"], inbox["session_id"])
        after = self.command("inbox", "--agent", "agent-a", "--after", "1")
        self.assertEqual([item["id"] for item in after["messages"]], [2])
        snapshot = {str(path.relative_to(self.path)): path.read_bytes()
                    for path in self.path.rglob("*") if path.is_file()}
        self.assertEqual(before, snapshot)

    def test_deadline_expires_dynamically_rejects_writes_and_allows_stop(self):
        started = self.active()
        artifact = self.artifact()
        state_before = (self.path / "session.json").read_bytes()
        deadline = parse_timestamp(started["deadline"])
        with patch("review_session.core.utc_now", return_value=deadline):
            self.assertEqual(self.command("status")["phase"], "EXPIRED")
            self.assertEqual((self.path / "session.json").read_bytes(), state_before)
            self.command("send", "--agent", "agent-a", "--kind", "status", "--text", "Late", error="expired")
            self.command("approve", "--agent", "agent-a", "--artifact", artifact, error="expired")
            closed = self.command("stop", "--reason", "Time elapsed")
        self.assertEqual(closed["phase"], "STOPPED")
        self.assertEqual(closed["outcome"], "PARTIAL")

    def test_send_rechecks_admission_if_id_scan_crosses_deadline(self):
        started = self.active()
        deadline = parse_timestamp(started["deadline"])
        before = deadline - timedelta(microseconds=1)
        with patch("review_session.core.utc_now", side_effect=[before, deadline]):
            self.command("send", "--agent", "agent-a", "--kind", "finding", "--text", "Too late after scan", error="expired")
        self.assertEqual(self.command("inbox", "--agent", "agent-b")["messages"], [])

    def test_send_timestamp_uses_the_checked_admission_time(self):
        started = self.active()
        deadline = parse_timestamp(started["deadline"])
        before = deadline - timedelta(seconds=1)
        admitted = deadline - timedelta(microseconds=1)
        with patch("review_session.core.utc_now", side_effect=[before, admitted, deadline]):
            result = self.command("send", "--agent", "agent-a", "--kind", "finding", "--text", "Admitted before deadline")
        self.assertEqual(parse_timestamp(result["message"]["timestamp"]), admitted)
        self.assertLess(parse_timestamp(result["message"]["timestamp"]), deadline)

    def test_operation_id_deduplicates_the_same_send_and_preserves_manual_messages(self):
        self.active()
        manual = self.command("send", "--agent", "agent-a", "--kind", "proposal", "--text", "Manual first pass")
        self.assertNotIn("operation_id", manual["message"])
        session = Session(str(self.path))
        first = session.send("agent-b", "finding", "Exact finding\nПривет", operation_id="run-1:message.2")
        message_path = self.path / "messages" / "00000002.json"
        original_bytes = message_path.read_bytes()
        repeated = session.send("agent-b", "finding", "Exact finding\nПривет", operation_id="run-1:message.2")
        self.assertEqual(repeated, first)
        self.assertEqual(message_path.read_bytes(), original_bytes)
        self.assertEqual(first["message"]["operation_id"], "run-1:message.2")
        following = self.command("send", "--agent", "agent-a", "--kind", "reply", "--text", "Continue review")
        self.assertEqual(following["message"]["id"], 3)
        self.assertNotIn("operation_id", following["message"])
        self.assertEqual([item["id"] for item in self.command("inbox", "--agent", "agent-a")["messages"]], [1, 2, 3])

    def test_reusing_operation_id_for_different_content_is_a_conflict(self):
        self.active()
        session = Session(str(self.path))
        session.send("agent-a", "finding", "Reviewed finding", operation_id="turn-1")
        before = (self.path / "messages" / "00000001.json").read_bytes()
        for agent, kind, text in (("agent-b", "finding", "Reviewed finding"),
                                  ("agent-a", "reply", "Reviewed finding"),
                                  ("agent-a", "finding", "Changed finding")):
            with self.subTest(agent=agent, kind=kind, text=text):
                with self.assertRaises(SessionError) as caught:
                    session.send(agent, kind, text, operation_id="turn-1")
                self.assertEqual(caught.exception.code, "operation_conflict")
        self.assertEqual((self.path / "messages" / "00000001.json").read_bytes(), before)
        self.assertEqual(len(session.inbox("agent-a", 0)["messages"]), 1)

    def test_invalid_operation_ids_are_rejected_without_messages(self):
        self.active()
        session = Session(str(self.path))
        for value in ("", "x" * 129, "has space", "slash/", "Привет", "token\n", 1, b"token"):
            with self.subTest(operation_id=value):
                with self.assertRaises(SessionError) as caught:
                    session.send("agent-a", "status", "Waiting", operation_id=value)
                self.assertEqual(caught.exception.code, "invalid_argument")
        self.assertEqual(session.inbox("agent-a", 0)["messages"], [])

    def test_operation_id_cli_retries_return_the_original_message(self):
        self.active()
        arguments = ("--agent", "agent-a", "--kind", "status", "--text", "Waiting", "--operation-id", "turn_1")
        first = self.command("send", *arguments)
        self.assertEqual(self.command("send", *arguments), first)
        self.command("send", "--agent", "agent-a", "--kind", "status", "--text", "Changed",
                     "--operation-id", "turn_1", error="operation_conflict")
        self.command("send", "--agent", "agent-a", "--kind", "status", "--text", "Invalid",
                     "--operation-id", "with space", error="invalid_argument")

    def test_deduplicated_sends_still_require_an_active_session(self):
        started = self.active()
        session = Session(str(self.path))
        session.send("agent-a", "status", "Waiting", operation_id="turn-1")
        with patch("review_session.core.utc_now", return_value=parse_timestamp(started["deadline"])):
            with self.assertRaises(SessionError) as caught:
                session.send("agent-a", "status", "Waiting", operation_id="turn-1")
            self.assertEqual(caught.exception.code, "expired")
        self.command("stop", "--reason", "Operator stopped")
        with self.assertRaises(SessionError) as caught:
            session.send("agent-a", "status", "Waiting", operation_id="turn-1")
        self.assertEqual(caught.exception.code, "not_active")

    def test_operation_scan_crossing_deadline_does_not_send_or_return_retry(self):
        started = self.active()
        session = Session(str(self.path))
        session.send("agent-a", "status", "Waiting", operation_id="turn-1")
        deadline = parse_timestamp(started["deadline"])
        for operation_id in ("turn-1", "turn-2"):
            with self.subTest(operation_id=operation_id):
                with patch("review_session.core.utc_now", side_effect=[deadline - timedelta(microseconds=1), deadline]):
                    with self.assertRaises(SessionError) as caught:
                        session.send("agent-a", "status", "Waiting", operation_id=operation_id)
                    self.assertEqual(caught.exception.code, "expired")
        self.assertEqual(len(session.inbox("agent-a", 0)["messages"]), 1)

    def test_concurrent_retries_publish_one_message(self):
        self.active()

        def send(_):
            return Session(str(self.path)).send("agent-a", "finding", "One operation", operation_id="shared-operation")

        with ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(send, range(16)))
        self.assertTrue(all(reply == replies[0] for reply in replies))
        self.assertEqual([item["id"] for item in Session(str(self.path)).inbox("agent-b", 0)["messages"]], [1])

    def test_stop_without_approvals_is_partial_and_idempotent(self):
        self.active()
        artifact = self.artifact()
        first = self.command("stop", "--reason", "Human ended review")
        second = self.command("stop", "--reason", "Change reason", "--outcome", "DISAGREED")
        self.assertEqual(first["stopped_at"], second["stopped_at"])
        self.assertEqual(second["stop_reason"], "Human ended review")
        self.assertEqual(second["outcome"], "PARTIAL")
        self.command("send", "--agent", "agent-b", "--kind", "status", "--text", "No", error="not_active")
        self.command("approve", "--agent", "agent-b", "--artifact", artifact, error="not_active")

    def test_both_approve_exact_current_bytes_before_agreed_closure(self):
        self.active()
        artifact = self.artifact("Agreed text\n")
        self.approve_both(artifact)
        expected_hash = hashlib.sha256(b"Agreed text\n").hexdigest()
        status = self.command("status")
        self.assertTrue(status["agreement_current"])
        self.assertEqual(status["actual_artifacts"], [{"path": artifact, "sha256": expected_hash}])
        closed = self.command("stop", "--reason", "Both reviewed this version")
        self.assertEqual(closed["outcome"], "AGREED")
        self.assertEqual(closed["finalized_artifact"], {"path": artifact, "sha256": expected_hash})

    def test_guarded_approval_records_only_the_expected_bytes(self):
        self.active()
        artifact = self.artifact("Reviewed bytes\n")
        expected_hash = hashlib.sha256(b"Reviewed bytes\n").hexdigest()
        approval = Session(str(self.path)).approve("agent-a", artifact, expected_sha256=expected_hash)
        self.assertEqual(approval["approval"]["sha256"], expected_hash)
        self.command("approve", "--agent", "agent-b", "--artifact", artifact, "--expected-sha256", expected_hash)
        self.assertTrue(self.command("status")["agreement_current"])

    def test_guarded_approval_rejects_changed_bytes_and_preserves_previous_approvals(self):
        self.active()
        artifact = self.artifact("Reviewed bytes")
        self.approve_both(artifact)
        expected_hash = hashlib.sha256(b"Reviewed bytes").hexdigest()
        before = (self.path / "session.json").read_bytes()
        self.artifact("An external revision")
        with self.assertRaises(SessionError) as caught:
            Session(str(self.path)).approve("agent-a", artifact, expected_sha256=expected_hash)
        self.assertEqual(caught.exception.code, "artifact_changed")
        self.assertEqual((self.path / "session.json").read_bytes(), before)
        self.command("approve", "--agent", "agent-b", "--artifact", artifact,
                     "--expected-sha256", expected_hash, error="artifact_changed")
        self.assertEqual((self.path / "session.json").read_bytes(), before)
        self.assertFalse(self.command("status")["agreement_current"])

    def test_invalid_expected_hashes_are_rejected_without_approvals(self):
        self.active()
        artifact = self.artifact()
        before = (self.path / "session.json").read_bytes()
        session = Session(str(self.path))
        for value in ("", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n", 1, b"a" * 64):
            with self.subTest(expected_sha256=value):
                with self.assertRaises(SessionError) as caught:
                    session.approve("agent-a", artifact, expected_sha256=value)
                self.assertEqual(caught.exception.code, "invalid_argument")
        self.command("approve", "--agent", "agent-a", "--artifact", artifact,
                     "--expected-sha256", "invalid", error="invalid_argument")
        self.assertEqual((self.path / "session.json").read_bytes(), before)

    def test_approval_hashing_crossing_deadline_preserves_previous_approvals(self):
        started = self.active()
        artifact = self.artifact("Reviewed bytes")
        self.approve_both(artifact)
        expected_hash = hashlib.sha256(b"Reviewed bytes").hexdigest()
        before = (self.path / "session.json").read_bytes()
        deadline = parse_timestamp(started["deadline"])
        now = deadline - timedelta(microseconds=1)
        original_hash = Session._artifact

        def hash_after_deadline(session, name):
            nonlocal now
            observation = original_hash(session, name)
            now = deadline
            return observation

        for guard in (None, expected_hash):
            with self.subTest(expected_sha256=guard):
                now = deadline - timedelta(microseconds=1)
                with patch("review_session.core.utc_now", side_effect=lambda: now), patch.object(Session, "_artifact", new=hash_after_deadline):
                    with self.assertRaises(SessionError) as caught:
                        Session(str(self.path)).approve("agent-a", artifact, expected_sha256=guard)
                self.assertEqual(caught.exception.code, "expired")
                self.assertEqual((self.path / "session.json").read_bytes(), before)

    def test_approval_rejects_changed_peer_context_without_replacing_previous_approval(self):
        self.active()
        session = Session(str(self.path))
        artifact = self.artifact("Reviewed bytes")
        expected_hash = hashlib.sha256(b"Reviewed bytes").hexdigest()
        first = session.send("agent-b", "finding", "Initial observation")["message"]
        session.send("agent-a", "reply", "Editor response")
        session.approve("agent-a", artifact)
        newer = session.send("agent-b", "finding", "New material objection")["message"]
        before = (self.path / "session.json").read_bytes()
        with self.assertRaises(SessionError) as caught:
            session.approve("agent-a", artifact, expected_hash, expected_peer_ids=[first["id"]])
        self.assertEqual(caught.exception.code, "runner_context_changed")
        self.assertEqual((self.path / "session.json").read_bytes(), before)
        approved = session.approve("agent-a", artifact, expected_hash,
                                   expected_peer_ids=[first["id"], newer["id"]])
        self.assertEqual(approved["approval"]["sha256"], expected_hash)

    def test_approval_rejects_invalid_expected_peer_ids_without_writing(self):
        self.active()
        session = Session(str(self.path))
        artifact = self.artifact()
        before = (self.path / "session.json").read_bytes()
        for value in ((), 1, [0], [-1], [True], ["1"], [1, 1], [2, 1]):
            with self.subTest(expected_peer_ids=value):
                with self.assertRaises(SessionError) as caught:
                    session.approve("agent-a", artifact, expected_peer_ids=value)
                self.assertEqual(caught.exception.code, "invalid_argument")
        self.assertEqual((self.path / "session.json").read_bytes(), before)

    def test_peer_message_cannot_arrive_between_context_check_and_approval(self):
        self.active()
        session = Session(str(self.path))
        artifact = self.artifact("Reviewed bytes")
        expected_hash = hashlib.sha256(b"Reviewed bytes").hexdigest()
        attempted = Event()
        original_hash = Session._artifact
        pending = None

        def send_peer():
            attempted.set()
            return Session(str(self.path)).send("agent-b", "finding", "A concurrent peer message")["message"]

        def hash_with_concurrent_peer(locked_session, name):
            nonlocal pending
            pending = pool.submit(send_peer)
            self.assertTrue(attempted.wait(timeout=1))
            self.assertFalse(pending.done())
            return original_hash(locked_session, name)

        with ThreadPoolExecutor(max_workers=1) as pool:
            with patch.object(Session, "_artifact", new=hash_with_concurrent_peer):
                approved = session.approve("agent-a", artifact, expected_hash, expected_peer_ids=[])
            message = pending.result(timeout=5)
        self.assertLessEqual(parse_timestamp(approved["approval"]["timestamp"]), parse_timestamp(message["timestamp"]))
        with self.assertRaises(SessionError) as caught:
            session.approve("agent-a", artifact, expected_hash, expected_peer_ids=[])
        self.assertEqual(caught.exception.code, "runner_context_changed")

    def test_changed_artifact_invalidates_old_approvals(self):
        self.active()
        artifact = self.artifact()
        self.approve_both(artifact)
        self.artifact("Version two")
        self.assertFalse(self.command("status")["agreement_current"])
        self.assertEqual(self.command("stop", "--reason", "Changed since review")["outcome"], "PARTIAL")

    def test_status_agreement_uses_the_same_observed_hash_as_artifact_listing(self):
        self.active()
        artifact = self.artifact("Reviewed bytes")
        self.approve_both(artifact)
        expected_hash = hashlib.sha256(b"Reviewed bytes").hexdigest()
        original_hash = Session._artifact
        observations = []

        def hash_then_edit(session, name):
            observation = original_hash(session, name)
            observations.append(observation)
            if len(observations) == 1:
                self.artifact("Externally edited after the observation")
            return observation

        with patch.object(Session, "_artifact", new=hash_then_edit):
            snapshot = self.command("status")
        self.assertEqual(snapshot["actual_artifacts"], [{"path": artifact, "sha256": expected_hash}])
        self.assertTrue(snapshot["agreement_current"])
        self.assertEqual(len(observations), 1)
        # A later status observes the edit; the first status remains a coherent
        # report of the bytes it read, rather than mixing two different reads.
        later = self.command("status")
        self.assertFalse(later["agreement_current"])
        self.assertNotEqual(later["actual_artifacts"][0]["sha256"], expected_hash)

    def test_reapproval_is_needed_for_each_participant_after_revision(self):
        self.active()
        artifact = self.artifact()
        self.approve_both(artifact)
        self.artifact("Revised")
        self.command("approve", "--agent", "agent-a", "--artifact", artifact)
        self.assertFalse(self.command("status")["agreement_current"])
        self.command("approve", "--agent", "agent-b", "--artifact", artifact)
        self.assertEqual(self.command("stop", "--reason", "Reapproved")["outcome"], "AGREED")

    def test_equal_hashes_at_different_paths_do_not_agree(self):
        self.active()
        self.command("approve", "--agent", "agent-a", "--artifact", self.artifact(name="a.md"))
        self.command("approve", "--agent", "agent-b", "--artifact", self.artifact(name="b.md"))
        self.assertEqual(self.command("stop", "--reason", "Different files")["outcome"], "PARTIAL")

    def test_one_approval_or_missing_artifact_cannot_be_agreed(self):
        self.active()
        artifact = self.artifact()
        self.command("approve", "--agent", "agent-a", "--artifact", artifact)
        self.assertFalse(self.command("status")["agreement_current"])
        self.command("approve", "--agent", "agent-b", "--artifact", artifact)
        (self.path / artifact).unlink()
        status = self.command("status")
        self.assertIsNone(status["actual_artifacts"][0]["sha256"])
        self.assertEqual(self.command("stop", "--reason", "Artifact removed")["outcome"], "PARTIAL")

    def test_explicit_disagreement_overrides_matching_approvals(self):
        self.active()
        self.approve_both(self.artifact())
        closed = self.command("stop", "--reason", "Substantive question unresolved", "--outcome", "DISAGREED")
        self.assertEqual(closed["outcome"], "DISAGREED")
        self.assertIsNone(closed["finalized_artifact"])

    def test_later_external_edits_do_not_rewrite_historical_closure(self):
        self.active()
        self.approve_both(self.artifact())
        self.command("stop", "--reason", "Complete")
        self.artifact("An external change after closure")
        status = self.command("status")
        self.assertEqual(status["outcome"], "AGREED")
        self.assertFalse(status["agreement_current"])
        self.assertNotEqual(status["finalized_artifact"]["sha256"], status["actual_artifacts"][0]["sha256"])

    def test_artifact_traversal_absolute_paths_and_symlinks_are_rejected(self):
        self.active()
        outside = Path(self.temporary.name) / "outside.txt"
        outside.write_text("Must not approve")
        self.artifact()
        (self.path / "artifacts" / "escape.txt").symlink_to(outside)
        (self.path / "artifacts" / "outside").symlink_to(outside.parent, target_is_directory=True)
        for name in ("../outside.txt", "artifacts/../../outside.txt", str(outside),
                     "artifacts/escape.txt", "artifacts/outside/outside.txt", "artifacts"):
            with self.subTest(name=name):
                self.command("approve", "--agent", "agent-a", "--artifact", name, error="invalid_artifact")
        self.assertEqual(self.command("status")["approvals"], {})

    def test_nested_regular_artifact_works_and_fifo_does_not_block(self):
        self.active()
        artifact = self.artifact(name="drafts/final.md")
        self.approve_both(artifact)
        os.mkfifo(self.path / "artifacts" / "pipe")
        self.command("approve", "--agent", "agent-a", "--artifact", "artifacts/pipe", error="invalid_artifact")
        self.assertTrue(self.command("status")["agreement_current"])

    def test_expected_validation_errors_are_json_without_tracebacks(self):
        self.command("status", error="not_initialized")
        for minutes in ("0", "-1", "nan", "inf", "10000000000"):
            self.command("init", "--goal", "Review", "--minutes", minutes, error="invalid_argument")
        self.command("init", "--goal", " ", error="invalid_argument")
        self.initialize()
        self.command("join", "--agent", "someone-else", error="unknown_agent")
        self.command("inbox", "--agent", "agent-a", "--after", "-1", error="invalid_argument")
        self.command("send", "--agent", "agent-a", "--kind", "execute", "--text", "No", error="invalid_argument")
        self.command("stop", "--reason", "", error="invalid_argument")

    def test_corrupt_session_types_fail_without_repair_or_traceback(self):
        self.active()
        state_path = self.path / "session.json"
        valid = json.loads(state_path.read_text())
        invalid = [
            ("participants", "agent-a"),
            ("participants", ["agent-a"]),
            ("readiness", []),
            ("readiness", {"agent-a": None}),
            ("approvals", []),
            ("approvals", {"agent-a": "approved"}),
            ("approvals", {"agent-a": {"path": 42, "sha256": "no", "timestamp": "bad"}}),
            ("minutes", "30"),
            ("deadline", None),
        ]
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                state_path.write_text(json.dumps({**valid, field: value}))
                before = state_path.read_bytes()
                self.command("status", error="invalid_session")
                self.command("stop", "--reason", "Do not repair silently", error="invalid_session")
                self.assertEqual(state_path.read_bytes(), before)
        state_path.write_text(json.dumps(valid))
        self.assertEqual(self.command("status")["phase"], "ACTIVE")

    def test_corrupt_message_is_reported_without_hidden_cursor_or_repair(self):
        self.active()
        self.command("send", "--agent", "agent-a", "--kind", "finding", "--text", "Preserve me")
        path = self.path / "messages" / "00000001.json"
        valid = json.loads(path.read_text())
        for value in ([], {"id": "one"}, {**valid, "id": 2},
                      {**valid, "session_id": "00000000-0000-0000-0000-000000000000"},
                      {**valid, "operation_id": None}, {**valid, "operation_id": "with space"}):
            with self.subTest(value=value):
                path.write_text(json.dumps(value))
                before = path.read_bytes()
                self.command("inbox", "--agent", "agent-a", error="invalid_messages")
                self.assertEqual(path.read_bytes(), before)

    def test_concurrent_cli_sends_never_lose_or_duplicate_messages(self):
        self.active()
        project = Path(__file__).resolve().parents[1]
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

        def send(index):
            result = subprocess.run([sys.executable, "-m", "review_session", "send", str(self.path),
                                     "--agent", "agent-a" if index % 2 else "agent-b",
                                     "--kind", "finding", "--text", f"Independent finding {index}"],
                                    cwd=project, env=environment, text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)["message"]["id"]

        with ThreadPoolExecutor(max_workers=8) as pool:
            identifiers = list(pool.map(send, range(24)))
        self.assertEqual(sorted(identifiers), list(range(1, 25)))
        messages = self.command("inbox", "--agent", "agent-a")["messages"]
        self.assertEqual([message["id"] for message in messages], list(range(1, 25)))
        self.assertEqual({message["text"] for message in messages},
                         {f"Independent finding {index}" for index in range(24)})

    def test_lock_wait_is_bounded_and_reports_retry(self):
        self.initialize()
        with open(self.path / ".review-session.lock", "r+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            with patch("review_session.core.LOCK_TIMEOUT_SECONDS", 0.05):
                self.command("status", error="lock_timeout")
            fcntl.flock(handle, fcntl.LOCK_UN)
        self.assertEqual(self.command("status")["phase"], "PREPARING")


if __name__ == "__main__":
    unittest.main()
