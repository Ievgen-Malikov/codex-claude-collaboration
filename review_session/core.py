"""Small POSIX coordination store. It never starts, wakes, or stops model processes.

The lock serializes cooperating helper processes, not arbitrary editor writes.
Artifact hashes describe bytes observed at approval/closure, not immutable files.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import errno
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import time
from typing import Any, Iterator
import uuid


PARTICIPANTS = ("agent-a", "agent-b")
KINDS = ("proposal", "finding", "question", "reply", "status")
STATE_FILE = "session.json"
LOCK_FILE = ".review-session.lock"
LOCK_TIMEOUT_SECONDS = 3.0
READY_SECONDS = 300
MESSAGE_NAME = re.compile(r"([0-9]+)\.json\Z")
OPERATION_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


class SessionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return parsed


def nonempty(value: str, field: str) -> str:
    if not value.strip():
        raise SessionError("invalid_argument", f"{field} must not be empty.")
    return value


def validate_artifact_record(record: Any, dated: bool = False) -> None:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise ValueError("Invalid artifact record")
    if not record["path"] or not isinstance(record.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
        raise ValueError("Invalid artifact path or SHA-256")
    if dated:
        parse_timestamp(record.get("timestamp"))


def validate_state(state: Any) -> None:
    """Reject corrupt persisted data before any command can mutate the session."""
    required = {"schema_version", "session_id", "goal", "participants", "minutes", "phase",
                "readiness", "approvals", "started_at", "deadline", "stopped_at",
                "outcome", "stop_reason", "finalized_artifact", "created_at"}
    if not isinstance(state, dict) or not required <= state.keys():
        raise ValueError("Missing session fields")
    if state["schema_version"] != 1 or state["participants"] != list(PARTICIPANTS):
        raise ValueError("Unsupported schema or invalid participants")
    if not isinstance(state["session_id"], str):
        raise ValueError("Invalid session ID")
    uuid.UUID(state["session_id"])
    if not isinstance(state["goal"], str) or not state["goal"].strip():
        raise ValueError("Invalid goal")
    minutes = state["minutes"]
    if type(minutes) not in (int, float) or not math.isfinite(minutes) or minutes <= 0:
        raise ValueError("Invalid duration")
    created = parse_timestamp(state["created_at"])
    created + timedelta(minutes=minutes)
    if not isinstance(state["readiness"], dict) or not isinstance(state["approvals"], dict):
        raise ValueError("Readiness and approvals must be objects")
    for field in ("readiness", "approvals"):
        if not set(state[field]) <= set(PARTICIPANTS):
            raise ValueError(f"Unknown participant in {field}")
    for value in state["readiness"].values():
        parse_timestamp(value)
    for record in state["approvals"].values():
        validate_artifact_record(record, dated=True)
    if state["phase"] not in ("PREPARING", "ACTIVE", "STOPPED"):
        raise ValueError("Invalid phase")
    if (state["started_at"] is None) != (state["deadline"] is None):
        raise ValueError("Start and deadline must be present together")
    if state["phase"] == "ACTIVE" and state["deadline"] is None:
        raise ValueError("Active session needs a deadline")
    for field in ("started_at", "deadline", "stopped_at"):
        if state[field] is not None:
            parse_timestamp(state[field])
    if state["phase"] == "STOPPED":
        if state["outcome"] not in ("AGREED", "PARTIAL", "DISAGREED") or state["stopped_at"] is None:
            raise ValueError("Stopped session needs an outcome and timestamp")
        if not isinstance(state["stop_reason"], str) or not state["stop_reason"].strip():
            raise ValueError("Stopped session needs a reason")
    elif any(state[field] is not None for field in ("outcome", "stopped_at", "stop_reason", "finalized_artifact")):
        raise ValueError("An open session cannot have closure fields")
    if state["finalized_artifact"] is not None:
        validate_artifact_record(state["finalized_artifact"])


def atomic_json(path: Path, value: Any) -> None:
    """Replace one file atomically; callers hold the session lock."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def exclusive_lock(descriptor: int) -> Iterator[None]:
    limit = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            if time.monotonic() >= limit:
                raise SessionError("lock_timeout", "Session is busy; retry after the other helper finishes.")
            time.sleep(0.025)
    try:
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


def initialize(path: str, goal: str, minutes: float) -> dict[str, Any]:
    nonempty(goal, "Goal")
    if not math.isfinite(minutes) or minutes <= 0:
        raise SessionError("invalid_argument", "--minutes must be a finite positive number.")
    try:
        utc_now() + timedelta(minutes=minutes)
    except OverflowError:
        raise SessionError("invalid_argument", "--minutes is too large.") from None
    root = Path(path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    reserved = [root / name for name in (STATE_FILE, LOCK_FILE, "messages", "artifacts")]
    if any(item.exists() or item.is_symlink() for item in reserved):
        raise SessionError("already_exists", "Session paths already exist; choose a new directory. Existing files were preserved.")
    try:
        descriptor = os.open(root / LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SessionError("already_exists", "Another initializer owns this directory; existing files were preserved.") from None
    with os.fdopen(descriptor, "r+") as handle, exclusive_lock(handle.fileno()):
        if any(item.exists() or item.is_symlink() for item in reserved if item.name != LOCK_FILE):
            raise SessionError("already_exists", "Reserved session paths appeared; existing files were preserved.")
        (root / "messages").mkdir()
        (root / "artifacts").mkdir()
        state = {
            "schema_version": 1,
            "session_id": str(uuid.uuid4()),
            "goal": goal,
            "participants": list(PARTICIPANTS),
            "minutes": minutes,
            "created_at": timestamp(utc_now()),
            "phase": "PREPARING",
            "readiness": {},
            "approvals": {},
            "started_at": None,
            "deadline": None,
            "stopped_at": None,
            "outcome": None,
            "stop_reason": None,
            "finalized_artifact": None,
        }
        atomic_json(root / STATE_FILE, state)
    return {"ok": True, "path": str(root), **state}


class Session:
    def __init__(self, path: str):
        self.root = Path(path).expanduser().resolve()

    @contextmanager
    def locked(self) -> Iterator[dict[str, Any]]:
        try:
            descriptor = os.open(self.root / LOCK_FILE, os.O_RDWR | os.O_NOFOLLOW)
        except FileNotFoundError:
            raise SessionError("not_initialized", "Session not found; run init first.") from None
        with os.fdopen(descriptor, "r+") as handle, exclusive_lock(handle.fileno()):
            try:
                state = json.loads((self.root / STATE_FILE).read_text(encoding="utf-8"))
                validate_state(state)
            except (ValueError, TypeError, AttributeError, OverflowError, FileNotFoundError) as error:
                raise SessionError("invalid_session", f"Session state is missing or invalid: {error}") from None
            yield state

    def _agent(self, state: dict[str, Any], agent: str) -> None:
        if agent not in state["participants"]:
            raise SessionError("unknown_agent", "Use --agent agent-a or --agent agent-b; names are conventions, not authentication.")

    def _active(self, state: dict[str, Any]) -> datetime:
        if state["phase"] != "ACTIVE":
            raise SessionError("not_active", "Session is not active; start it once both agents are ready, or use a new session after stop.")
        admitted_at = utc_now()
        if admitted_at >= parse_timestamp(state["deadline"]):
            raise SessionError("expired", "The coordination deadline has passed; use stop to record the outcome.")
        return admitted_at

    def _save(self, state: dict[str, Any]) -> None:
        atomic_json(self.root / STATE_FILE, state)

    def _artifact(self, artifact: str) -> dict[str, str]:
        """Hash a regular artifact via directory FDs; reject every symlink component."""
        candidate = PurePosixPath(artifact)
        parts = candidate.parts
        if (candidate.is_absolute() or len(parts) < 2 or parts[0] != "artifacts"
                or ".." in parts or "\\" in artifact or "\x00" in artifact):
            raise SessionError("invalid_artifact", "Use a relative file inside artifacts/, without traversal or symlinks.")
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in parts[:-1]:
                next_descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                          dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
            file_descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                      dir_fd=descriptor)
            with os.fdopen(file_descriptor, "rb") as handle:
                before = os.fstat(handle.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise SessionError("invalid_artifact", "The artifact must be a regular file inside artifacts/.")
                digest = hashlib.sha256()
                for block in iter(lambda: handle.read(65536), b""):
                    digest.update(block)
                after = os.fstat(handle.fileno())
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                        after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise SessionError("artifact_changed", "Artifact changed while hashing; finish edits and retry.")
            return {"path": candidate.as_posix(), "sha256": digest.hexdigest()}
        except OSError as error:
            raise SessionError("invalid_artifact", f"Cannot read artifact safely: {error.strerror}. Check its path and remove symlinks.") from None
        finally:
            os.close(descriptor)

    def _agreement(self, state: dict[str, Any]) -> dict[str, str] | None:
        approvals = [state["approvals"].get(agent) for agent in state["participants"]]
        if not all(approvals):
            return None
        first = approvals[0]
        if any((item["path"], item["sha256"]) != (first["path"], first["sha256"])
               for item in approvals[1:]):
            return None
        try:
            current = self._artifact(first["path"])
        except SessionError:
            return None
        return current if current["sha256"] == first["sha256"] else None

    def _view(self, state: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        phase = state["phase"]
        if phase == "ACTIVE" and now >= parse_timestamp(state["deadline"]):
            phase = "EXPIRED"
        actual = []
        for path in sorted({item["path"] for item in state["approvals"].values()}):
            try:
                actual.append(self._artifact(path))
            except SessionError as error:
                actual.append({"path": path, "sha256": None, "error": str(error)})
        # Use the hashes displayed in this view, so an external edit cannot make
        # the artifact listing and agreement flag describe different observations.
        observed_hashes = {item["path"]: item["sha256"] for item in actual}
        approvals = [state["approvals"].get(agent) for agent in state["participants"]]
        agreement_current = False
        if all(approvals):
            first = approvals[0]
            agreement_current = all(
                (item["path"], item["sha256"]) == (first["path"], first["sha256"])
                for item in approvals
            ) and observed_hashes.get(first["path"]) == first["sha256"]
        return {"ok": True, **state, "phase": phase, "now": timestamp(now),
                "readiness_fresh": {agent: agent in state["readiness"] and
                                    0 <= (now - parse_timestamp(state["readiness"][agent])).total_seconds() <= READY_SECONDS
                                    for agent in state["participants"]},
                "actual_artifacts": actual, "agreement_current": agreement_current}

    def status(self) -> dict[str, Any]:
        with self.locked() as state:
            return self._view(state)

    def join(self, agent: str) -> dict[str, Any]:
        with self.locked() as state:
            self._agent(state, agent)
            if state["phase"] != "PREPARING":
                raise SessionError("already_started", "Readiness can only be refreshed before start; use a new session for another round.")
            state["readiness"][agent] = timestamp(utc_now())
            self._save(state)
            return self._view(state)

    def start(self) -> dict[str, Any]:
        with self.locked() as state:
            if state["phase"] != "PREPARING":
                raise SessionError("already_started", "This session has already started; its deadline cannot be reset.")
            now = utc_now()
            missing = [agent for agent in state["participants"] if agent not in state["readiness"]
                       or not 0 <= (now - parse_timestamp(state["readiness"][agent])).total_seconds() <= READY_SECONDS]
            if missing:
                raise SessionError("not_ready", "Fresh readiness required; run join for: " + ", ".join(missing))
            state.update(phase="ACTIVE", started_at=timestamp(now),
                         deadline=timestamp(now + timedelta(minutes=state["minutes"])))
            self._save(state)
            return self._view(state)

    def _messages(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        paths = sorted(((int(match.group(1)), path) for path in (self.root / "messages").iterdir()
                        if (match := MESSAGE_NAME.fullmatch(path.name))), key=lambda item: item[0])
        try:
            messages = []
            for identifier, path in paths:
                item = json.loads(path.read_text(encoding="utf-8"))
                if (not isinstance(item, dict) or type(item.get("id")) is not int
                        or item["id"] != identifier or identifier <= 0
                        or item.get("session_id") != state["session_id"]
                        or item.get("agent") not in PARTICIPANTS or item.get("kind") not in KINDS
                        or not isinstance(item.get("text"), str)):
                    raise ValueError("Invalid message fields")
                if "operation_id" in item and (not isinstance(item["operation_id"], str)
                                                or not OPERATION_ID.fullmatch(item["operation_id"])):
                    raise ValueError("Invalid message operation ID")
                parse_timestamp(item.get("timestamp"))
                messages.append(item)
            return messages
        except (ValueError, TypeError, OSError):
            raise SessionError("invalid_messages", "A message file is unreadable or invalid; preserve the session and inspect messages/.") from None

    def send(self, agent: str, kind: str, text: str, operation_id: str | None = None) -> dict[str, Any]:
        nonempty(text, "Message text")
        if len(text.encode("utf-8")) > 65536:
            raise SessionError("invalid_argument", "Message exceeds 65536 UTF-8 bytes; put long material in artifacts/.")
        if kind not in KINDS:
            raise SessionError("invalid_argument", "Unknown message kind.")
        if operation_id is not None and (not isinstance(operation_id, str) or not OPERATION_ID.fullmatch(operation_id)):
            raise SessionError("invalid_argument", "Operation ID must be 1–128 ASCII letters, digits, or . _ : - characters.")
        with self.locked() as state:
            self._agent(state, agent)
            self._active(state)
            # Derive the next ID from committed files, so an interrupted write
            # cannot make a future send reuse an already published message ID.
            if operation_id is not None:
                messages = self._messages(state)
                for item in messages:
                    if item.get("operation_id") == operation_id:
                        # A retry does not publish again, but is still a send
                        # and must remain inside the active coordination window.
                        self._active(state)
                        if (item["agent"], item["kind"], item["text"]) != (agent, kind, text):
                            raise SessionError("operation_conflict", "Operation ID already belongs to a different message; preserve the original and use a new ID.")
                        return {"ok": True, "message": item}
                names = [item["id"] for item in messages]
            else:
                # Manual sends retain their lightweight filename scan and
                # their original record shape when no operation ID is supplied.
                names = [int(match.group(1)) for path in (self.root / "messages").iterdir()
                         if (match := MESSAGE_NAME.fullmatch(path.name))]
            identifier = max(names, default=0) + 1
            # Directory scanning can cross the deadline. Recheck admission and
            # timestamp that same observation before the filesystem commit.
            admitted_at = self._active(state)
            message = {"id": identifier, "session_id": state["session_id"],
                       "agent": agent, "kind": kind, "text": text, "timestamp": timestamp(admitted_at)}
            if operation_id is not None:
                message["operation_id"] = operation_id
            atomic_json(self.root / "messages" / f"{identifier:08d}.json", message)
            return {"ok": True, "message": message}

    def inbox(self, agent: str, after: int) -> dict[str, Any]:
        if after < 0:
            raise SessionError("invalid_argument", "--after must be zero or a positive message ID.")
        with self.locked() as state:
            self._agent(state, agent)
            messages = [item for item in self._messages(state) if item["id"] > after]
            return {"ok": True, "session_id": state["session_id"], "agent": agent,
                    "after": after, "messages": messages}

    def approve(self, agent: str, artifact: str, expected_sha256: str | None = None,
                expected_peer_ids: list[int] | None = None) -> dict[str, Any]:
        if expected_sha256 is not None and (not isinstance(expected_sha256, str)
                                            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)):
            raise SessionError("invalid_argument", "Expected SHA-256 must contain exactly 64 lowercase hexadecimal characters.")
        if expected_peer_ids is not None and (not isinstance(expected_peer_ids, list)
                or any(type(value) is not int or value <= 0 for value in expected_peer_ids)
                or expected_peer_ids != sorted(set(expected_peer_ids))):
            raise SessionError("invalid_argument", "Expected peer message IDs must be a sorted list of unique positive integers.")
        with self.locked() as state:
            self._agent(state, agent)
            self._active(state)
            if expected_peer_ids is not None:
                peer_ids = [item["id"] for item in self._messages(state) if item["agent"] != agent]
                if peer_ids != expected_peer_ids:
                    raise SessionError("runner_context_changed", "Peer messages changed since the review snapshot; read the current discussion before approving.")
            # The same lock covers peer context, observed bytes and publication
            # of the approval, so cooperating senders cannot race admission.
            observed = self._artifact(artifact)
            if expected_sha256 is not None and observed["sha256"] != expected_sha256:
                raise SessionError("artifact_changed", "Artifact no longer matches the reviewed SHA-256; read the current version before approving.")
            # Hashing a large file may cross the deadline; validate again before writing.
            admitted_at = self._active(state)
            approval = {**observed, "timestamp": timestamp(admitted_at)}
            state["approvals"][agent] = approval
            self._save(state)
            return {"ok": True, "session_id": state["session_id"], "agent": agent, "approval": approval}

    def stop(self, reason: str, outcome: str | None = None) -> dict[str, Any]:
        nonempty(reason, "Stop reason")
        with self.locked() as state:
            if state["phase"] == "STOPPED":
                return self._view(state)
            agreement = self._agreement(state)
            state.update(phase="STOPPED", stopped_at=timestamp(utc_now()), stop_reason=reason,
                         outcome="DISAGREED" if outcome == "DISAGREED" else "AGREED" if agreement else "PARTIAL",
                         finalized_artifact=agreement if outcome != "DISAGREED" else None)
            self._save(state)
            return self._view(state)
