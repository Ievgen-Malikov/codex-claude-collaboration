# Install and use the review skill

Use the [collaborative-review skill](../skills/collaborative-review/SKILL.md) to
ask a local coding agent for an independent Codex and Claude review. Supply the
decision and its evidence. The agent runs the Python helper and returns a report
with any remaining objections. The helper sets the deadline, handles recovery,
and records which report each reviewer approved.

The skill follows the open [Agent Skills specification](https://agentskills.io/specification).
It links to CLI instructions and synthetic examples that the agent reads only
when needed. It calls the existing coordinator rather than including another
copy. Loading the skill runs no shell commands and grants no tool permissions.
The Python helper uses only the standard library.

## 1. Install the helper

From a checkout of this repository on macOS, Linux, or WSL, with Python 3.11+:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
. .venv/bin/activate
agent-review-session --help
```

Package installation may download build tools. The helper has no third-party
runtime dependencies. Install Codex and Claude Code using their official
instructions, then sign in to each CLI separately. Installing the Python package
does not install either CLI or sign you in. Native Windows is unsupported.

Start your coding agent from this activated terminal so it can find the helper
on PATH. Otherwise, give it the absolute path to
`.venv/bin/agent-review-session`. Install the helper before using the skill;
copying the skill folder does not install the Python package. Once the helper
is installed, you can use a skill copy outside this checkout.

## 2. Check the environment without a model call

```sh
agent-review-session doctor
```

`doctor` runs each CLI's version and help commands with a timeout. It prints a
JSON report:

| Result | Meaning |
| --- | --- |
| Exit 0 with `local_checks_passed: true` | The required local checks passed. |
| Exit 2 with `local_checks_passed: false` | A required check failed. Read its message for the affected program and a suggested correction. |

Invalid arguments produce the usual CLI JSON error on stderr.

The report shows `authentication: "not_checked"`. `doctor` neither reads
credential files nor starts a session or model request. It checks that the
required CLI options are present. Sign-in, provider availability, and whether
the CLIs apply those options correctly require separate checks. The helper
still trusts the installed CLIs and their administrator settings.

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

Edit the skill in [skills/collaborative-review](../skills/collaborative-review).
This checkout already makes it available to Codex through the tracked
`.agents/skills/collaborative-review` symlink, so no additional copy is needed
here. Keep symlinks enabled when checking out this POSIX-only project.

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

`copytree` stops if the destination already exists. Before updating an installed
skill, inspect it and preserve local changes. You can commit the copied skill
in the target project, but keep live review sessions and inputs private. In this
repository, maintain the source in `skills/` rather than editing a second copy.

Restart your coding agent if it does not find the new skill. Codex uses the
project `.agents/skills/` location; Claude Code uses `.claude/skills/`. See the
official [Codex skill guide](https://learn.chatgpt.com/docs/build-skills) and
[Claude Code skill guide](https://code.claude.com/docs/en/skills) for discovery
and settings for each agent. Other agents need support for the format, local
command execution, and access to both provider CLIs. Their compatibility remains
untested.

## 4. Request a review

After installation, invoke `$collaborative-review` in Codex or
`/collaborative-review` in Claude Code. Natural-language requests matching its
description may also select the skill. For example:

```text
Use collaborative-review to have Codex and Claude review the architecture brief
I supplied. You may send that brief to both providers and use their model quota.
Keep the review to a recommendation. Use 10 minutes and at most 2 revision rounds.
```

Your coding agent prepares the goal and evidence, checks the environment, and
starts the coordinator. It then presents the report. The automated reviewers
use `review_session/prompt_policy.py` as their policy and receive source material
separately as data. They do not inherit the host's skill as policy. Instructions
inside the inputs cannot change the scope or permissions you granted.

To try a fictional review from this checkout, the following command
**invokes both providers and uses model quota**:

```sh
agent-review-session run ./sessions/architecture-001 \
  --goal "Review the supplied synthetic job execution design against its constraints. Recommend a first version and preserve unresolved failure cases. Do not implement changes." \
  --input skills/collaborative-review/assets/architecture.synthetic.md \
  --minutes 10 --max-rounds 2 --turn-timeout 180
```

Choose a fresh session path. This repository ignores `sessions/`; check ignored
paths in other projects, or use a private directory outside version control.
Inputs must be regular UTF-8 files, with no symlinks and at most 128 KiB combined.
The coordinator saves a snapshot of each input when it creates the session.

Keep the coordinator in the foreground, your coding agent's turn active, and
the computer awake. The reviewers can analyze only the supplied text. They
cannot read the target repository, browse, execute tests, or edit application
code. Prepare any authorized supporting evidence before starting the review.

## Synthetic scenarios

Start with one of these fictional briefs. Each includes a scope and acceptance
criteria. Replace its evidence for a real task. These are sample inputs, not
results from actual runs or evidence that two-model review improves quality.

| Scenario | Input | What a useful report should address |
| --- | --- | --- |
| Architecture decision | [Job execution design](../skills/collaborative-review/assets/architecture.synthetic.md) | Timeouts, disconnects, duplicates, recovery, and a justified first design. |
| Specification review | [Note export specification](../skills/collaborative-review/assets/specification.synthetic.md) | Contradictory requirements, missing states, precise corrections, and open decisions. |
| Supplied diff review | [Profile cache change](../skills/collaborative-review/assets/diff.synthetic.md) | Concrete call sequences that violate the supplied contract and proposed regression checks. |

The report should contain a recommendation or findings, supporting evidence,
proposed corrections, assumptions, verification gaps, and remaining objections.
Proposed runtime checks must be marked unrun. For a real code diff, include its
base, reviewed revision, relevant surrounding contracts, and supplied test
evidence; the approval hash covers the review report, not the code.

## Inspect the result or recover

```sh
agent-review-session status ./sessions/architecture-001
```

Read `sessions/architecture-001/artifacts/result.md` if it exists, even when a
later stage failed. The recorded outcome tells you how the review ended:

| Outcome | Meaning |
| --- | --- |
| `AGREED` | Both providers approved the exact current report bytes. |
| `PARTIAL` | The review ended without matching current approvals. Any completed work is kept. |
| `DISAGREED` | Unresolved disagreement remains. |

Agreement does not prove correctness.

Use [the automated review guide](AUTOMATED_REVIEW.md#interruptions-and-recovery)
for stop and resume commands. Do not retry a turn with an unknown outcome or
start a replacement paid run automatically. Existing deadlines and completed
outputs survive supported resume. A closed session is never reopened.

You can check the package and skill with synthetic local subprocesses, without
provider credentials. Native Codex discovery has also been checked. The
[validation snapshot](VALIDATION.md) records the versions and scope of those
checks. The next step is a complete live review with both providers and a
measurement of review quality; see [NEXT_STEPS.md](../NEXT_STEPS.md).
