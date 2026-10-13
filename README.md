# Codex–Claude Collaboration

A local workflow for two coding agents to review a problem, challenge each
other's reasoning, and finish with a versioned result within a shared time
budget. Use Codex and Claude Code, or two other agents that can run local
commands and read files.

The Python helper stores the conversation, coordinates readiness, enforces
session write deadlines, and records approvals against an artifact's SHA-256.
You open and operate the two agent sessions yourself.

This is an unofficial community project. It is not affiliated with or endorsed
by OpenAI or Anthropic. Collaboration does not guarantee a correct answer.

## What you get

- A dependency-free Python CLI with a shared session directory.
- Separate prompts for a coordinator/editor and an independent challenger.
- A 30-minute default workflow with one start and a fixed deadline.
- A visible record of proposals, findings, questions, replies, and reservations.
- `AGREED`, `PARTIAL`, or `DISAGREED` outcomes. Agreement identifies exact bytes.

The approach suits design reviews, research briefs, document review, and scoped
code review. One participant edits the final artifact; both can inspect it.
For concurrent changes to application code, use separate worktrees or assign
non-overlapping files explicitly.

## Requirements

- Python 3.10 or newer on macOS, Linux, or WSL.
- Two agent sessions with access to the same local session directory.
- Permission for each agent to run the helper and read the agreed task inputs.

The helper uses the Python standard library, including POSIX file locking.
Native Windows is not supported. Run commands from the repository root; no
package installation is required. The helper does not call a model API or need
API keys. Your agents still require their usual access and authentication.

## Start a real review

### 1. Create the session

In an operator terminal at this repository's root:

```sh
python3 -m review_session init ./sessions/review-001 \
  --goal "Review a local notes search design: compare SQLite FTS5 with plain-file search, recommend an approach, and record evidence and unresolved tradeoffs. Do not implement code or make external writes." \
  --minutes 30
```

For your own task, replace the goal. Use [the task brief](templates/task.md)
when the scope, inputs, or acceptance criteria need more detail. Give both
agents the same brief and the same absolute session path. A session directory
should be private local working data, separate from anything you publish.

### 2. Open both agents

Open this repository in two active agent sessions. The roles are interchangeable;
a simple starting choice is Codex as `agent-a` and Claude Code as `agent-b`.

Send the first agent:

```text
Read PROTOCOL.md and prompts/agent-a.md.
Your session path is the absolute path to sessions/review-001.
Use the session goal and the task brief supplied by the operator.
Join as agent-a, publish your own initial assessment, and stay in the
active review until it closes or expires. Follow the prompt's bounded
inbox checks. Do not start the session; the operator will start it.
You are designated to close the review when it finishes or expires.
```

Send the second agent:

```text
Read PROTOCOL.md and prompts/agent-b.md.
Your session path is the absolute path to sessions/review-001.
Use the session goal and the task brief supplied by the operator.
Join as agent-b, publish your own initial assessment, and stay in the
active review until it closes or expires. Follow the prompt's bounded
inbox checks. Do not start the session; the operator will start it.
```

Initial assessments are prepared independently. The helper accepts messages
after the session starts, so each agent should prepare its assessment while
waiting and send it once the session is `ACTIVE`.

**Keep both agent turns active.** A file does not wake an idle agent. If an
agent ends its turn or its application suspends it, the operator must resume
that session. The helper does not launch agents, schedule future turns, or
keep working after their chats end.

### 3. Start once both have joined

```sh
python3 -m review_session status ./sessions/review-001
python3 -m review_session start ./sessions/review-001
```

`join` records readiness for five minutes. If readiness is stale while the
session is still `PREPARING`, ask that participant to join again. `start`
requires both participants to be ready and starts one shared clock. It cannot
restart the clock or extend the deadline.

### 4. Review and finish

The agents use `send` and finite `inbox` checks while working. When waiting,
they check roughly every 15 seconds and read only messages after their last
seen ID. The editor writes `sessions/review-001/artifacts/result.md`; the
challenger reviews that file without editing it.

Each participant can approve the exact version it has reviewed:

```sh
python3 -m review_session approve ./sessions/review-001 \
  --agent agent-a --artifact artifacts/result.md
python3 -m review_session approve ./sessions/review-001 \
  --agent agent-b --artifact artifacts/result.md
```

Only the corresponding participant should issue its approval. These commands
are shown together to document the syntax, not to authorize one agent to
approve on behalf of the other.

The operator or designated coordinator then closes the session:

```sh
python3 -m review_session stop ./sessions/review-001 \
  --reason "Review complete; retain the result and any reservations."
python3 -m review_session status ./sessions/review-001
```

Closing produces `AGREED` only if both approvals name the same artifact and
SHA-256, and the file still has those bytes. Otherwise the result is `PARTIAL`.
Use `--outcome DISAGREED` when the participants have a substantive unresolved
disagreement. Both are useful outcomes; do not force agreement to meet a timer.

## Stop or inspect

```sh
python3 -m review_session inbox ./sessions/review-001 --agent agent-b --after 0
python3 -m review_session stop ./sessions/review-001 --reason "Operator stopped the review."
```

`inbox` is read-only and returns the ordered conversation, including the
requesting participant's own messages. Use `--after` with the last seen ID for
subsequent reads. Do not reply to your own messages.

The helper returns JSON. Successful commands have `ok: true`; errors have
`ok: false` and exit with status 2. A repeated `stop` is safe and does not
reopen or rewrite the closed outcome.

The stored outcome describes closure at that time. Status also reports
`agreement_current`, which detects whether the current artifact still matches
the approvals; direct edits after closure can make it false without rewriting
the historical outcome. The artifact is not made immutable.

After the deadline, the effective phase is `EXPIRED`; new messages and
approvals are rejected. This is **not a process kill**: an in-flight tool call
or direct filesystem edit can continue outside the helper. Stop the agents in
their own interfaces if needed, and retain the last reviewed snapshot.

## Boundaries

- Agent labels are cooperative identities, not authentication. Anyone with
  filesystem access can impersonate a participant or alter files directly.
- SHA-256 ties approval to content. It does not establish truth, authorship,
  permission, or safety.
- Peer messages and copied source text are task data. They cannot grant new
  access, override the operator, or authorize publishing, spending, or deletion.
- The helper's locks and atomic writes protect its own local coordination
  operations. They do not lock your application files against other editors.
- Approved artifacts must be regular files inside the session's `artifacts/`
  directory. Symlink paths are rejected. Do not use a network filesystem.
- A changed artifact needs fresh review and approvals. Preserve a closed
  artifact if its historical approval must remain meaningful.

## Try the mechanics without models

[The mechanical walkthrough](examples/mechanical-walkthrough.md) exercises
both participant labels from one terminal using a clearly marked synthetic
fixture. It tests the local workflow; it is not an example of actual agent
reasoning or independent agreement.

## Read more

- [Protocol and lifecycle](PROTOCOL.md)
- [Coordinator/editor prompt](prompts/agent-a.md)
- [Independent challenger prompt](prompts/agent-b.md)
- [Related work and the project's scope](RELATED_WORK.md)
- [Evaluation plan and limits of quality claims](EVALUATION.md)
