"""JSON CLI for manual coordination and an opt-in automated review."""

from __future__ import annotations

import argparse
import json
import sys

from .core import KINDS, Session, SessionError, initialize


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise SessionError("invalid_argument", message + "; run with --help for usage.")


def parser() -> argparse.ArgumentParser:
    result = Parser(description="Coordinate a local review, manually or with an opt-in CLI runner.")
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a fresh session without overwriting existing files")
    init.add_argument("path")
    init.add_argument("--goal", required=True)
    init.add_argument("--minutes", type=float, default=30)
    for name in ("join", "send", "inbox", "approve"):
        command = commands.add_parser(name)
        command.add_argument("path")
        command.add_argument("--agent", required=True)
        if name == "send":
            command.add_argument("--kind", choices=KINDS, required=True)
            command.add_argument("--text", required=True)
            command.add_argument("--operation-id", help="Optional ID for idempotent replay of this exact message")
        elif name == "inbox":
            command.add_argument("--after", type=int, default=0)
        elif name == "approve":
            command.add_argument("--artifact", required=True)
            command.add_argument("--expected-sha256", help="Reject approval if the current bytes differ from this reviewed hash")
    for name in ("start", "stop", "status"):
        command = commands.add_parser(name)
        command.add_argument("path")
        if name == "stop":
            command.add_argument("--reason", required=True)
            command.add_argument("--outcome", choices=("DISAGREED",))
    run = commands.add_parser("run", help="Run a bounded text review using installed Codex and Claude CLIs")
    run.add_argument("path", help="Fresh session directory, or an existing automated session with --resume")
    run.add_argument("--resume", action="store_true", help="Reuse frozen inputs and completed outputs; never retry an unknown invocation")
    run.add_argument("--goal", help="Task and scope; required for a new review")
    run.add_argument("--input", action="append", dest="inputs", help="UTF-8 file to snapshot; repeatable, at most 128 KiB combined")
    run.add_argument("--minutes", type=float, help="Total wall clock budget including initial turns (default: 30)")
    run.add_argument("--max-rounds", type=int, help="Draft/revision cycles, from 1 to 10 (default: 3)")
    run.add_argument("--turn-timeout", type=float, help="Maximum seconds per agent turn (default: 180)")
    run.add_argument("--codex-command", help="Codex executable name or path (default: codex)")
    run.add_argument("--claude-command", help="Claude Code executable name or path (default: claude)")
    run.add_argument("--codex-model", help="Optional Codex model selection")
    run.add_argument("--claude-model", help="Optional Claude model selection")
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        if args.command == "init":
            output = initialize(args.path, args.goal, args.minutes)
        elif args.command == "run":
            from .runner import run
            output = run(args.path, resume=args.resume, goal=args.goal, inputs=args.inputs,
                         minutes=args.minutes, max_rounds=args.max_rounds, turn_timeout=args.turn_timeout,
                         codex_command=args.codex_command, claude_command=args.claude_command,
                         codex_model=args.codex_model, claude_model=args.claude_model)
        else:
            session = Session(args.path)
            if args.command in ("start", "status"):
                output = getattr(session, args.command)()
                if args.command == "status":
                    from .runner_store import summary
                    runner = summary(session.root)
                    if runner is not None:
                        output["runner"] = runner
            elif args.command == "join":
                output = session.join(args.agent)
            elif args.command == "send":
                output = session.send(args.agent, args.kind, args.text, args.operation_id)
            elif args.command == "inbox":
                output = session.inbox(args.agent, args.after)
            elif args.command == "approve":
                output = session.approve(args.agent, args.artifact, args.expected_sha256)
            else:
                output = session.stop(args.reason, args.outcome)
        print(json.dumps(output, ensure_ascii=False, allow_nan=False))
        return 0
    except (SessionError, OSError) as error:
        code = error.code if isinstance(error, SessionError) else "io_error"
        print(json.dumps({"ok": False, "error": {"code": code, "message": str(error)}},
                         ensure_ascii=False), file=sys.stderr)
        return 2
