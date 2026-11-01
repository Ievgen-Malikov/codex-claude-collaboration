# Install and use the review skill

The [collaborative-review skill](../skills/collaborative-review/SKILL.md) gives a
local coding agent an entry point to the existing review coordinator. Ask for
an independent Codex and Claude review, provide the evidence, and get the report
with remaining objections. The Python helper owns the process lifecycle,
recovery, limits, and report approvals.

The skill follows the open [Agent Skills specification](https://agentskills.io/specification).
Its concise entry point loads the CLI reference and synthetic recipes only when
needed. It has no tool pre-approvals, auto-executed shell substitutions, or
embedded copy of the coordinator. The Python runtime still uses only the
standard library.

## 1. Install the helper

From a checkout of this repository on macOS, Linux, or WSL, with Python 3.11+:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
. .venv/bin/activate
agent-review-session --help
```

Package installation may download build tooling; the helper has no third-party
runtime dependencies. It does not install or sign in either provider CLI.
Install Codex and Claude Code through their official instructions and sign in
separately. Native Windows is unsupported.

Start the host agent from this activated terminal so it inherits PATH, or give
it the absolute path to `.venv/bin/agent-review-session`. Installing the skill
does not install the helper. The skill folder can be copied independently of
the checkout once the helper is installed.

## 2. Check the environment without a model call

```sh
agent-review-session doctor
```

The command runs bounded local version/help probes and prints a JSON report.
Exit 0 with `local_checks_passed: true` means the local requirements passed;
exit 2 with `local_checks_passed: false` means a required check failed. Read the
per-check messages for the affected executable and a suggested correction.
Invalid arguments use the usual CLI JSON error on stderr.

`authentication` remains `"not_checked"`. No credential files are inspected,
no session is created, and no model request is made. Help flags do not prove
their runtime behavior, provider availability, or live review compatibility.
The installed CLIs and managed settings remain trusted.

Use executable paths when the CLIs are not on PATH:

```sh
agent-review-session doctor \
  --codex-command /absolute/path/to/codex \
  --claude-command /absolute/path/to/claude
```

Pass those same executable options to a new `run`. They accept programs, not
shell command strings. A probe defaults to 5 seconds; `--probe-timeout SECONDS`
allows up to 10 seconds per probe.

## 3. Install the skill for the host agent

Keep [skills/collaborative-review](../skills/collaborative-review) as the source
of truth. This checkout already exposes it to Codex through the tracked
`.agents/skills/collaborative-review` symlink. No additional Codex skill copy is
needed here. Edit the canonical source and keep symlinks enabled when checking
out this POSIX-only project.

To install into a different Codex project, copy the entire folder, including its
references and assets. From this repository's root, replace the destination
below with that project's actual path:

```sh
python3 -c 'from shutil import copytree; copytree("skills/collaborative-review", "/absolute/path/to/target-project/.agents/skills/collaborative-review")'
```

For Claude Code in this checkout:

```sh
python3 -c 'from shutil import copytree; copytree("skills/collaborative-review", ".claude/skills/collaborative-review")'
```

`copytree` refuses an existing destination instead of merging or replacing a
user's skill. If one already exists, inspect it and preserve local changes
before choosing an update. The copied project files may be committed by the
target project's owner; keep live review sessions and inputs private. In this
repository, edit the canonical `skills/` source rather than maintaining a
second copy.

Restart the host agent if it does not discover the new skill. Codex uses the
project `.agents/skills/` location; Claude Code uses `.claude/skills/`. See the
official [Codex skill guide](https://learn.chatgpt.com/docs/build-skills) and
[Claude Code skill guide](https://code.claude.com/docs/en/skills) for discovery
and host-specific settings. Other hosts may support the format but must also
provide local command execution and access to both provider CLIs. Broad host
compatibility has not been established.

## 4. Request a review

After installation, invoke `$collaborative-review` in Codex or
`/collaborative-review` in Claude Code. Natural-language requests matching its
description may also select the skill. For example:

```text
Use collaborative-review to have Codex and Claude review the architecture brief
I supplied. You may send that brief to both providers and use their model quota.
Keep the review to a recommendation. Use 10 minutes and at most 2 revision rounds.
```

The host prepares the goal and evidence, checks the environment, starts the
existing coordinator, and presents the resulting report. Its selected skill
does not become policy for automated child turns: those continue to use
`review_session/prompt_policy.py`, with source material passed separately as
data. Input instructions cannot expand the user's scope or permissions.

For a first fictional run directly from this checkout, the following command
**invokes both providers and uses model quota**:

```sh
agent-review-session run ./sessions/architecture-001 \
  --goal "Review the supplied synthetic job execution design against its constraints. Recommend a first version and preserve unresolved failure cases. Do not implement changes." \
  --input skills/collaborative-review/assets/architecture.synthetic.md \
  --minutes 10 --max-rounds 2 --turn-timeout 180
```

The session path must be fresh. `sessions/` is ignored in this repository;
verify ignored paths in other projects or use a private directory outside
version control. Inputs must be regular UTF-8 files, with no symlinks and at
most 128 KiB combined. They are frozen when the session starts.

The coordinator stays in the foreground. Keep the host turn, process, and
computer active. It reviews supplied text; it cannot read the target repository,
browse, execute tests, or edit application code. The host must prepare any
authorized supporting evidence before starting.

## Synthetic scenarios

These inputs are fictional starting points, not actual run results or evidence
that two-model review improves quality. Each includes its scope and acceptance
criteria; replace its evidence for a real task.

| Scenario | Input | What a useful report should address |
| --- | --- | --- |
| Architecture decision | [Job execution design](../skills/collaborative-review/assets/architecture.synthetic.md) | Timeouts, disconnects, duplicates, recovery, and a justified first design. |
| Specification review | [Note export specification](../skills/collaborative-review/assets/specification.synthetic.md) | Contradictory requirements, missing states, precise corrections, and open decisions. |
| Supplied diff review | [Profile cache change](../skills/collaborative-review/assets/diff.synthetic.md) | Concrete call sequences that violate the supplied contract and proposed regression checks. |

The expected report contains a recommendation or findings, supporting evidence,
proposed corrections, assumptions, verification gaps, and remaining objections.
Proposed runtime checks must be marked unrun. For a real code diff, include its
base, reviewed revision, relevant surrounding contracts, and supplied test
evidence; the approval hash covers the review report, not the code.

## Inspect the result or recover

```sh
agent-review-session status ./sessions/architecture-001
```

Read `sessions/architecture-001/artifacts/result.md` if it exists, including when
a later stage failed. `AGREED` means both providers approved the current report
bytes; `PARTIAL` preserves work without matching approvals; `DISAGREED` records
unresolved disagreement. Agreement does not prove correctness.

Use [the automated review guide](AUTOMATED_REVIEW.md#interruptions-and-recovery)
for stop and resume commands. Do not retry a turn with an unknown outcome or
start a replacement paid run automatically. Existing deadlines and completed
outputs survive supported resume; a closed session is never reopened.

The package and skill can be checked with synthetic local subprocesses without
provider credentials. Native Codex discovery has also been checked; see the
[versioned validation snapshot](VALIDATION.md) for its scope. A completed live
end-to-end review with both providers and measured review quality remain the
next step in [NEXT_STEPS.md](../NEXT_STEPS.md).
