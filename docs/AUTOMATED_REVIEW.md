# Automated local review

`run` coordinates Codex and Claude Code through their installed CLIs. It reviews
the supplied UTF-8 text and produces `artifacts/result.md`. It requires Python
3.11 or later, a local POSIX filesystem, and recent CLIs already signed in.
The Python implementation uses only the standard library.

Automated turns use the static policy in `review_session/prompt_policy.py`
through Codex's developer instructions and Claude Code's appended system
prompt. The goal, source snapshots, peer messages, and report remain separate
user prompt data. The Markdown role prompts in `prompts/` and the repository's
`AGENTS.md` guide manual sessions and contributors; `run` does not load them.

Model turns consume your providers' quota. The task and input snapshots are sent
to both providers through those CLIs. Choose inputs you are authorized to share.
The coordinator runs in the foreground; keep the computer awake and the process
running until it closes. No open agent chat windows are required.

## Start a review

Run from the repository root with a new session path:

```sh
python3 -m review_session run ./sessions/automated-001 \
  --goal "Review the supplied synthetic design brief and write a recommendation with remaining objections." \
  --input examples/automated-task.synthetic.md \
  --minutes 30 --max-rounds 3 --turn-timeout 180
```

This example's brief is synthetic. Running it with real CLIs invokes models;
the [mechanical walkthrough](../examples/mechanical-walkthrough.md) exercises
the manual store without any model calls.

Repeat `--input` for several files. Inputs must be regular UTF-8 files;
symlinks are rejected and their total size may not exceed 128 KiB. They are
snapshotted at creation; later changes to the source files do not change the
review. Include any required evidence in those files:
agents receive the snapshots, goal, peer responses, and current report as prompt
data. The coordinator starts the CLIs in an empty private working directory
with tool and customization flags disabled. This mode is scoped to reviewing
the supplied evidence and proposing a report; repository reads, browsing,
tests, and application edits require a separately authorized workflow. Verify
claims about checks against the evidence supplied.
Reports must attribute evidence of prior tests to its source and mark proposed
runtime checks as unrun. The agents can inspect text during a turn; they cannot
execute tests or independently verify supplied claims about prior test runs.

| Option | Meaning |
| --- | --- |
| `--goal TEXT` | Required task and scope for a new review. |
| `--input FILE` | Required text input; repeat for additional files. |
| `--minutes 30` | Total wall clock budget, including all model turns. |
| `--max-rounds 3` | Maximum draft or revision cycles, from 1 to 10; the initial proposals are separate. |
| `--turn-timeout 180` | Maximum seconds for one CLI turn, also bounded by the session deadline. |
| `--codex-command codex` | Codex executable name or path. |
| `--claude-command claude` | Claude Code executable name or path. |
| `--codex-model NAME` | Optional Codex model selection; otherwise use the CLI default. |
| `--claude-model NAME` | Optional Claude model selection; otherwise use the CLI default. |
| `--resume` | Resume recorded work in an existing automated session without configuration overrides. |

Executable options identify a program, not a shell command with extra flags.
The coordinator launches it directly. Use the installed CLIs' supported model
names for optional model selection.

## CLI integration

The Codex adapter uses `codex exec` with JSON events and a response schema, then
continues the saved thread by its explicit ID. These interfaces are described in
[official OpenAI documentation](https://learn.chatgpt.com/docs/non-interactive-mode)
and the [Codex CLI reference](https://learn.chatgpt.com/docs/cli/reference).

The Claude Code adapter uses print mode, JSON structured output, and explicit
session resume. See [programmatic Claude Code](https://code.claude.com/docs/en/headless).
Its tool, MCP, and customization flags are described in the
[Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference).

## Review steps and outcomes

The coordinator creates the session, records readiness, and starts its fixed
deadline before calling either model. It obtains the independent proposals
before sharing either with the peer. Agent-a proposes the report; agent-b
reviews it and can request corrections. Once agent-b approves a draft, agent-a
also reviews that version. Each approval is based on that agent's own verdict
about the exact report bytes and their SHA-256. A report revision
requires fresh verdicts for the revised hash.

The coordinator waits on local processes; it never calls a model merely to
check for messages. Progress goes to stderr and the final command result is
JSON. The existing session commands remain available in another terminal:
On failure, stdout is empty, stderr contains a JSON error record, and the exit
status is 2. Other stderr lines can describe progress or host diagnostics;
consumers should identify the error record rather than assume it is the last line.

```sh
python3 -m review_session status ./sessions/automated-001
python3 -m review_session inbox ./sessions/automated-001 --agent agent-b --after 0
python3 -m review_session stop ./sessions/automated-001 \
  --reason "Operator stopped the automated review."
```

`status` includes the runner's status, counts of jobs by status, provider session
IDs, limits, and any error alongside the session state. The transcript retains
both participants' responses; reading it does not consume
messages. `artifacts/result.md` is the available report, not an approval of
application code or proof of correctness.

| Outcome | Meaning |
| --- | --- |
| `AGREED` | Both agents approved the current report's same path and SHA-256. |
| `PARTIAL` | The run closed without matching approvals, including interrupted or incomplete review. |
| `DISAGREED` | The round limit was reached with an explicit disagreement in the latest review. |

A deadline, per-turn timeout, or round limit bounds the work. At the round limit,
the report receives an explicitly attributed **Coordinator closure record**
with the latest review and stop reason. This addition has not been reviewed by
both agents, so that version cannot close as `AGREED`. A comment without approval
closes as `PARTIAL`; the latest explicit disagreement closes as `DISAGREED`.

Runtime failures preserve finished outputs and the current report, then record
the available outcome. This is ordinarily `PARTIAL`, but a failure after both
guarded approvals can still leave an `AGREED` outcome if the exact approved file
matches at closure. Preserve the closed report before editing it;
`agreement_current` detects whether its bytes still match the historical approvals.

## Interruptions and recovery

Only one coordinator can own a session at a time. The runner keeps its
configuration, CLI session IDs, job records, input snapshots, and outputs in the
private session directory, including `runner.json`. Do not edit those records
by hand or commit them. The default `sessions/` directory is ignored by Git;
choose an ignored private location if using a different path.

To continue after an interruption:

```sh
python3 -m review_session run ./sessions/automated-001 --resume
```

Resume uses the original inputs, options, and deadline. It does not accept a
new goal or other configuration overrides. Completed CLI outputs are reused;
already recorded local messages and report effects are replayed idempotently.
Resume does not extend time or reopen a stopped session.

If the coordinator died during a CLI turn, that turn has an unknown outcome.
It may have reached the provider even if no complete response was saved. The
coordinator refuses to call the model again automatically. Inspect `status`,
the recorded job logs, and local processes; stop the old session and use a new
path for a new review. A nonzero CLI exit is likewise not permission to repeat
the request indefinitely.

Ctrl-C, the session deadline, or an operator `stop` causes a running coordinator
to attempt to terminate the local child process groups it owns. The store's
`stop` command does not itself kill processes, and after a crash the operator must
inspect and stop any surviving children. No local cancellation can retract a
remote request, undo its effects, or guarantee that provider billing stopped.
The coordinator never terminates unrelated agent sessions.

If any owned group cannot be confirmed stopped, `run` reports `runner_cleanup`
with the affected PIDs and original failure, when present. Treat those groups as
potentially still running and inspect the private logs and current processes.
Recorded PIDs remain evidence; they are not safe targets for later automatic
signalling.

## Boundaries and verification

The runner requests disabled tools and customizations through CLI flags and
uses a separate working directory. It trusts the installed CLIs and their
administrator policies, which can override ordinary settings. It does not add
an operating-system sandbox or protect against a compromised CLI or a malicious
local user. Agent labels remain coordination labels. Goal text, source inputs,
peer messages, and generated report text do not authorize new permissions or
external actions.

Keep manual discussion and report edits out of a running automated session.
The coordinator detects independent report changes and preserves the changed
file when it encounters them. Arbitrary editors do not honor its helper lock,
however; report checks and writes do not provide an atomic compare-and-swap
guarantee against simultaneous external edits.

Runner tests use fake local CLI processes and synthetic input. They verify
observable coordination, bounded execution, report hashes, and recovery without
paid model calls. A live trial with both providers has not yet been run. CLI
compatibility and review quality should be measured in that trial before
claiming an improvement; see [the evaluation plan](../EVALUATION.md).
No reduction in tokens, cost, or latency has been measured. The coordinator
resumes provider conversations and supplies complete turn context; measure this
overhead during the pilot before changing context delivery or adding machinery.
