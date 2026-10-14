# Codex–Claude Collaboration

Let Codex and Claude Code review the same task through a local file-based inbox.
One agent writes the result; the other challenges it. Each approves the final
file by SHA-256, within a shared time budget.

This repository provides a Python CLI, a review protocol, and two agent prompts.
The optional `run` command launches Codex and Claude Code turns automatically
to review supplied text and produce a local report. The manual workflow lets
you coordinate two active sessions yourself, including scoped code reviews.
Other agents can participate manually if they can run local commands and read
files.

## Requirements

- Python 3.11 or newer on macOS, Linux, or WSL.
- For automated review: recent Codex and Claude Code CLIs, installed and signed
  in, and permission to submit the supplied task and inputs to both providers.
- For manual review: two active agent sessions with access to the same local
  directory, and permission to run the helper and read the task inputs.

The Python helper has no third-party runtime dependencies. Manual commands do
not call models. `run` uses the CLIs' usual authentication and consumes model
quota. Native Windows is unsupported; the helper uses POSIX file locking and
the coordinator uses POSIX process groups.

## Automated local review

Run from this repository's root with a fresh session path:

```sh
python3 -m review_session run ./sessions/automated-001 \
  --goal "Review the supplied synthetic design brief and write a recommendation with remaining objections." \
  --input examples/automated-task.synthetic.md \
  --minutes 30 --max-rounds 3 --turn-timeout 180
```

The coordinator collects two independent assessments, exchanges their findings,
and writes the editor's proposed report to `artifacts/result.md`. Each agent
reviews and approves the report's exact SHA-256. It closes at agreement, the
round limit, or the deadline, preserving the available report and objections.
No active chat windows are needed; the coordinator and computer must keep
running. Progress is written to stderr; the final response is JSON.

Inputs are UTF-8 text snapshots, limited to 128 KiB combined. The coordinator
supplies them as prompt data and starts the CLIs in a private working directory
with flags disabling tools and customizations. The installed CLIs and managed
settings remain trusted; this is not a new operating-system sandbox. This mode
produces a review report. The coordinator makes no model calls to poll for messages.

Inspect or stop the session with the existing commands below. After an
interruption, `run PATH --resume` reuses the recorded configuration and finished
outputs. An interrupted model turn with an unknown outcome is never retried
automatically. See [automated review](docs/AUTOMATED_REVIEW.md) for options,
recovery, cancellation, and limits. The supplied example is synthetic; no live
model trial or quality gain has been established.

## Manual quickstart

### 1. Create a review

```sh
git clone https://github.com/Ievgen-Malikov/codex-claude-collaboration.git
cd codex-claude-collaboration
python3 -m review_session init ./sessions/review-001 \
  --goal "Review the design in the supplied task brief and recommend a solution. Do not implement code or make external writes." \
  --minutes 30
```

Replace the goal with your task. Give both agents the same inputs and, when
needed, a completed [task brief](templates/task.md). Keep live session data
private; the default `sessions/` directory is ignored by Git.

Copy `path` from the JSON output. Replace `<SESSION_PATH>` in both messages below
with that absolute path. Run all helper commands from this repository's root.

### 2. Open both agents

Open this repository in Codex and Claude Code. Send Codex:

```text
Read PROTOCOL.md and prompts/agent-a.md.
Session path: <SESSION_PATH>
Use the session goal and the task inputs I supplied.
Join as agent-a and prepare your independent first assessment.
Wait for ACTIVE before sending it. I will start the session.
Continue the review with bounded inbox checks until it ends or expires.
You are designated to close the review when it finishes or expires.
```

Send Claude Code:

```text
Read PROTOCOL.md and prompts/agent-b.md.
Session path: <SESSION_PATH>
Use the session goal and the task inputs I supplied.
Join as agent-b and prepare your independent first assessment.
Wait for ACTIVE before sending it. I will start the session.
Continue the review with bounded inbox checks until it ends or expires.
```

The roles are interchangeable. **Keep both agent turns active.** If an agent
ends its turn or the application suspends it, resume that session yourself.
A new message file does not wake an idle agent.

### 3. Start the shared clock

Once both agents have joined:

```sh
python3 -m review_session status ./sessions/review-001
python3 -m review_session start ./sessions/review-001
```

Both readiness records must be less than five minutes old. Ask an agent to join
again if its readiness has expired. The clock starts once and cannot be extended.

### 4. Review and close

The agents exchange messages and check for replies roughly every 15 seconds when
waiting. Agent-a edits `sessions/review-001/artifacts/result.md`; agent-b reviews
it and sends findings. For application code changes, assign separate files or
worktrees in the task brief.

Each agent approves for itself after reading the final file. For agent-a:

```sh
python3 -m review_session approve ./sessions/review-001 \
  --agent agent-a --artifact artifacts/result.md
```

Agent-b uses `--agent agent-b`. Any edit after approval requires fresh review and
approval from both agents. The operator or designated coordinator then closes:

```sh
python3 -m review_session stop ./sessions/review-001 --reason "Review complete."
```

| Outcome | Meaning |
| --- | --- |
| `AGREED` | Both approvals name the same file and hash, and the current file matches. |
| `PARTIAL` | Review closed without matching current approvals. |
| `DISAGREED` | The coordinator closes with `--outcome DISAGREED` because objections remain. |

Agreement is optional. Preserve unresolved objections in the result.

## Inspect or stop

```sh
python3 -m review_session inbox ./sessions/review-001 --agent agent-b --after 0
python3 -m review_session status ./sessions/review-001
python3 -m review_session stop ./sessions/review-001 --reason "Operator stopped the review."
```

The inbox includes both agents' messages. Use the last seen ID with `--after`
for later reads; do not reply to your own messages. Reading does not consume
messages. Commands return JSON; errors have `ok: false` and exit with status 2.

At the deadline, `send` and `approve` are rejected. The designated coordinator
can still call `stop` to record the outcome. Repeated `stop` calls are safe.
The manual helper cannot cancel agent tool calls or prevent direct file edits.
For an automated session, a running coordinator observes the stop and terminates
its own local child process groups. It cannot retract a remote model request.

`status` reports `agreement_current` to detect changes since approval. The
coordination store does not retain artifact versions; preserve a closed result
before editing it.

## Trust and limits

This is a cooperative local workflow. Agent labels are not authenticated, and
helper locks do not protect application files from other editors. Approved files
must be regular files inside `artifacts/`; symlinks are rejected. Use a local
filesystem. See [the protocol](PROTOCOL.md) for recovery and trust boundaries.

Hashes identify content. They do not prove correctness or grant permissions.
Peer messages cannot authorize new access, publishing, spending, or deletion.
The synthetic example tests the mechanics; no improvement in model quality has
been measured.

## Examples and details

- [Current status and first live trial](NEXT_STEPS.md)
- [Automated coordinator and recovery](docs/AUTOMATED_REVIEW.md)
- [Synthetic automated task](examples/automated-task.synthetic.md)
- [Mechanical walkthrough without models](examples/mechanical-walkthrough.md)
- [Coordinator prompt](prompts/agent-a.md) and [challenger prompt](prompts/agent-b.md)
- [Related work](RELATED_WORK.md) and [evaluation plan](EVALUATION.md)
- [Contributing](CONTRIBUTING.md)

[MIT licensed](LICENSE). Unofficial; not affiliated with OpenAI or Anthropic.
