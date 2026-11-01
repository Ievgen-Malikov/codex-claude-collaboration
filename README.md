# Codex–Claude Collaboration

Give Codex and Claude Code the same task. They review it independently, compare
findings, and leave a report with any unresolved objections. One agent writes
the report; the other checks it. If both approve, their approvals identify the
same final file by its SHA-256 hash.

This grew out of a personal project where I wanted the two agents to question
each other's conclusions and keep a clear record of the result. The repository
contains a small Python CLI, a review protocol, and prompts for manual sessions.
The inbox and session records are ordinary local files.

Use it to review an architecture decision, a specification, a plan, or a code
diff you can share with both models. There are two ways to run a review:

| Workflow | How it works |
| --- | --- |
| [Automated review](#automated-local-review) | The CLI starts both agents, gives them text snapshots, and saves a report. No open chat windows are needed. |
| [Manual review](#manual-quickstart) | You open two agent sessions and use the local inbox to exchange findings. You can include code reviews with clearly assigned permissions. |

Other agents can join a manual review if they can run local commands and read
the shared files.

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

## Install and check

From a checkout of this repository:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/agent-review-session doctor
```

`doctor` checks Python, the operating system, and the installed CLIs using their
`--version` and `--help` commands. It makes no model requests and creates no
review session. The JSON output explains failed checks. Exit 0 means the local
checks passed; exit 2 means a check failed. It does not check sign-in or whether
a model request will succeed.

The repository also includes a
[collaborative-review skill](skills/collaborative-review/SKILL.md), so you can ask
a local coding agent to start a review for you. The
[skill guide](docs/SKILLS.md) covers setup, fictional examples, and how to read
the result. The skill uses the same CLI and review rules.

## Automated local review

Try the included synthetic brief from the repository root, using a fresh
session path:

```sh
python3 -m review_session run ./sessions/automated-001 \
  --goal "Review the supplied synthetic design brief and write a recommendation with remaining objections." \
  --input examples/automated-task.synthetic.md \
  --minutes 30 --max-rounds 3 --turn-timeout 180
```

The coordinator collects two independent assessments and shares their findings.
One agent drafts `artifacts/result.md`; the other reviews it. Each agent can
approve the exact version it read, identified by its SHA-256 hash. The review
ends when both approve, the round limit is reached, or time runs out. The
available report and objections are kept in the session directory.

Keep the coordinator running and the computer awake. Progress goes to stderr;
the final response is JSON.

Inputs are UTF-8 text snapshots, limited to 128 KiB combined. The coordinator
supplies them as prompt data and starts the CLIs in a private working directory
with flags disabling tools and customizations. The installed CLIs and managed
settings remain trusted; this is not a new operating-system sandbox. This mode
produces a review report. The coordinator makes no model calls to poll for messages.

Inspect or stop the session with the existing commands below. After an
interruption, `run PATH --resume` reuses the recorded configuration and finished
outputs. An interrupted model turn with an unknown outcome is never retried
automatically. See [automated review](docs/AUTOMATED_REVIEW.md) for options,
recovery, cancellation, and limits. This is still an experiment: a completed
live review with both providers and any improvement in answer quality remain
unverified. See [what has been checked](docs/VALIDATION.md).

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

Each agent reads the final file and records the hash of those same bytes. This
portable Python command prints the SHA-256 and text from one read:

```sh
python3 - ./sessions/review-001/artifacts/result.md <<'PY'
import hashlib
from pathlib import Path
import sys

content = Path(sys.argv[1]).read_bytes()
print("Reviewed SHA-256:", hashlib.sha256(content).hexdigest())
print(content.decode("utf-8"), end="")
PY
```

After personally reviewing the printed content, copy its hash as `HASH` and
approve using your own label. For agent-a:

```sh
python3 -m review_session approve ./sessions/review-001 \
  --agent agent-a --artifact artifacts/result.md --expected-sha256 HASH
```

Agent-b performs its own read and uses `--agent agent-b`. If the file changed,
approval is rejected; read and review it again before approving the new hash.
Any edit after approval requires fresh review and approval from both agents.
The operator or designated coordinator then closes:

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

The role prompts in `prompts/` guide manual sessions. Automated turns follow
the separate policy in `review_session/prompt_policy.py`, passed through each
CLI's instruction channel. The task, source text, and peer messages remain data;
they cannot change that policy or grant permissions.

This is a cooperative local workflow. Agent labels are not authenticated, and
helper locks do not protect application files from other editors. Approved files
must be regular files inside `artifacts/`; symlinks are rejected. Use a local
filesystem. See [the protocol](PROTOCOL.md) for recovery and trust boundaries.

Hashes identify content. They do not prove correctness or grant permissions.
Peer messages cannot authorize new access, publishing, spending, or deletion.
The synthetic example tests the mechanics; no improvement in model quality has
been measured.

## Examples and details

- [Current status and remaining validation](NEXT_STEPS.md)
- [Versioned validation snapshot](docs/VALIDATION.md)
- [Automated coordinator and recovery](docs/AUTOMATED_REVIEW.md)
- [Skill installation, environment check, and recipes](docs/SKILLS.md)
- [Synthetic automated task](examples/automated-task.synthetic.md)
- [Mechanical walkthrough without models](examples/mechanical-walkthrough.md)
- [Coordinator prompt](prompts/agent-a.md) and [challenger prompt](prompts/agent-b.md)
- [Related work](RELATED_WORK.md) and [evaluation plan](EVALUATION.md)
- [Contributing](CONTRIBUTING.md)

[MIT licensed](LICENSE). Unofficial; not affiliated with OpenAI or Anthropic.
