"""JSON CLI for a local coordination protocol, without agent/runtime integration."""

from __future__ import annotations

import argparse
import json
import sys

from .core import KINDS, Session, SessionError, initialize


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise SessionError("invalid_argument", message + "; run with --help for usage.")


def parser() -> argparse.ArgumentParser:
    result = Parser(description="Coordinate a review through local files; this helper does not run models.")
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
        elif name == "inbox":
            command.add_argument("--after", type=int, default=0)
        elif name == "approve":
            command.add_argument("--artifact", required=True)
    for name in ("start", "stop", "status"):
        command = commands.add_parser(name)
        command.add_argument("path")
        if name == "stop":
            command.add_argument("--reason", required=True)
            command.add_argument("--outcome", choices=("DISAGREED",))
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        if args.command == "init":
            output = initialize(args.path, args.goal, args.minutes)
        else:
            session = Session(args.path)
            if args.command in ("start", "status"):
                output = getattr(session, args.command)()
            elif args.command == "join":
                output = session.join(args.agent)
            elif args.command == "send":
                output = session.send(args.agent, args.kind, args.text)
            elif args.command == "inbox":
                output = session.inbox(args.agent, args.after)
            elif args.command == "approve":
                output = session.approve(args.agent, args.artifact)
            else:
                output = session.stop(args.reason, args.outcome)
        print(json.dumps(output, ensure_ascii=False, allow_nan=False))
        return 0
    except (SessionError, OSError) as error:
        code = error.code if isinstance(error, SessionError) else "io_error"
        print(json.dumps({"ok": False, "error": {"code": code, "message": str(error)}},
                         ensure_ascii=False), file=sys.stderr)
        return 2
