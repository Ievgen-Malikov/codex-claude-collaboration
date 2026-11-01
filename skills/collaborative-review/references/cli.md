# Coordinator CLI

Use the installed `agent-review-session` executable, or its user-supplied
absolute path. An activated virtual environment makes the installed command
available on PATH. The copied skill does not include the Python package.

If the helper is missing, explain that it must be installed. From an existing
checkout, use `python3 -m venv .venv`, followed by
`.venv/bin/python -m pip install .` from that checkout; use
`.venv/bin/agent-review-session` as the helper. Do not guess a checkout path or
silently install software into the user's agent configuration.

## Check the local environment

```sh
agent-review-session doctor
```

`doctor` runs bounded version/help probes without invoking a model, reading
credential files, or creating a review session. It prints JSON to stdout:

- Exit 0 and `local_checks_passed: true`: the required local checks passed.
- Exit 2 and `local_checks_passed: false`: inspect the failed checks and their
  messages before starting a review.
- `authentication: "not_checked"`: the command does not check sign-in or model
  access. Help output alone cannot confirm how flags behave during a real run.
  Passing these checks does not prove that a complete review will succeed.

Invalid command arguments produce the CLI's usual JSON error on stderr.
For custom installations, pass the same `--codex-command PROGRAM` and
`--claude-command PROGRAM` to both `doctor` and a new `run`. These identify
executables, not shell commands with arguments. Each diagnostic probe defaults
to 5 seconds; `--probe-timeout SECONDS` allows up to 10 seconds per probe.

## Start one review

Choose an absolute session path with no existing session state inside a
private parent directory. The placeholders below must be replaced with actual
paths and the user's goal:

```sh
agent-review-session run /absolute/private/review-001 \
  --goal "Review the supplied decision and report evidence, corrections, and unresolved objections. Do not implement changes." \
  --input /absolute/private/brief.md \
  --minutes 30 --max-rounds 3 --turn-timeout 180
```

Repeat `--input FILE` for multiple regular UTF-8 files, at most 128 KiB combined.
Inputs are snapshotted when the session is created. Later source edits do not
change the submitted evidence. The coordinator creates its fresh session; an
empty pre-existing directory is also accepted. A private parent created with
`mktemp -d` may contain a new session path.

Progress is on stderr; the final command response is JSON. On failure, stdout
is empty and stderr contains a JSON error record, possibly alongside progress
lines. Read the report and status even when a later stage fails: completed work
can survive. No new model call is needed to inspect the local session.

## Inspect, stop, and recover

Use the actual session path in these commands:

```sh
agent-review-session status /absolute/private/review-001
agent-review-session inbox /absolute/private/review-001 --agent agent-b --after 0
agent-review-session stop /absolute/private/review-001 --reason "Operator requested stop."
```

Reading the inbox does not consume messages. `stop` records closure; a running
coordinator observes it and attempts to terminate only its own local process
groups. Local termination cannot retract a provider request or guarantee its
billing stopped. Do not signal unrelated processes or old recorded PIDs.

After inspecting an interruption, resume only when the coordinator permits it
and the original authorization remains applicable:

```sh
agent-review-session run /absolute/private/review-001 --resume
```

Resume uses the original options, input snapshots, completed outputs, and
deadline. You cannot override its configuration, extend its deadline, or reopen
a closed review. A turn whose outcome is unknown must not be repeated
automatically; report the blocker and preserve the session for inspection.

| Recorded outcome | Report to the user |
| --- | --- |
| `AGREED` | Both providers approved the same current report bytes. |
| `PARTIAL` | The review ended without matching current approvals. Any completed work is kept. |
| `DISAGREED` | The review closed with recorded unresolved disagreement. |

The report is `SESSION/artifacts/result.md`. `status` supplies the recorded
outcome, runner diagnostics, and `agreement_current`. Preserve a closed report
before editing it; historical approval does not cover later edits.
