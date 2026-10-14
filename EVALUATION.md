# Evaluation plan

This project is an early experimental workflow. A successful session or a green
helper test suite establishes only the behavior that was actually checked.
It does not establish that two agents produce better decisions, safer code, or
lower total costs than one agent.

The included synthetic fixture is a command walkthrough, not benchmark data.
No quantitative improvement claim is made for the review method.

## Keep two questions separate

1. **Does coordination work?** Do readiness, messages, deadlines, approvals,
   and closure behave as documented under ordinary use and interruptions?
2. **Does the review improve the result?** Does interaction find and correct
   meaningful errors better than alternatives at comparable cost?

Agreement rate is useful for describing sessions, but it is not an accuracy
metric. A correct unresolved disagreement can be better than a wrong consensus.

## Compare fair baselines

| Condition | Procedure |
| --- | --- |
| Single agent | One agent gets the task and finishes its answer. |
| Single agent with self-review | One agent drafts, critiques, and revises within the same total budget. |
| Sequential second-agent review | One agent drafts; the other reviews; the editor makes a final revision. |
| Independent pair | Two agents work separately; a predefined selection or aggregation step produces the result. |
| Interactive pair | Independent first passes followed by this protocol's critique and final review. |

Use the same inputs, tool access, task constraints, and acceptance criteria.
Match the **combined** model/tool budget, counting the final selection step and
polling overhead. Also report wall-clock time and human effort. A 30-minute
two-agent run is not automatically comparable with a 30-minute single-agent run.

Record the CLI and model versions, prompts, token or billing measurements where
available, task source, stop reason, and any intervention. Alternate which agent
is editor to separate role effects from model effects. Use fresh sessions to
avoid carrying answers between experimental conditions.
Automated mode fixes Codex as editor and Claude Code as challenger; role
alternation currently requires the manual workflow or a separate harness.

## Tasks and assessment

Start with a small pilot across more than one task type: a code regression with
held-out tests, a design decision with explicit constraints, a document with
checkable factual claims, and a review containing known defects. Repeat runs to
observe variance. A pilot is exploratory, not proof of general superiority.

Evaluate the resulting artifact independently of the dialogue. Prefer hidden
tests, source checking, and human reviewers who do not know which condition
produced it. If an LLM judge is used, disclose its model and rubric, and validate
its judgments against independent human or executable checks. Do not use the
participants' own approval as the score.

Useful measures include:

- correct findings, false findings, corrected defects, and newly introduced
  defects;
- unsupported claims and accuracy of cited evidence;
- tests passed and important contracts left unverified;
- material objections preserved or incorrectly dropped;
- final quality, cost, latency, and operator intervention time;
- correct handling of `PARTIAL` and `DISAGREED` outcomes;
- false agreement: matching approvals on an artifact that fails independent
  acceptance criteria.

Set the rubric before inspecting results. Publish negative and incomplete runs
alongside successes, with uncertainty and sample size. Any exported transcript
requires a separate review for private data, credentials, and third-party rights.

## Coordination failure cases

Exercise the helper in temporary local directories with synthetic data. Do not
use production credentials, paid model calls, or unintended external writes.

| Case | Required observation |
| --- | --- |
| Missing or stale participant readiness | START is rejected until both participants are freshly ready. |
| Simultaneous START requests | There is one start and one fixed deadline. |
| Concurrent sends | Recorded messages have a consistent order; valid messages are not lost or merged. |
| Repeated inbox reads | Reading does not consume another participant's messages or mutate shared state. |
| Unknown send outcome | A resumed participant can inspect the transcript before deciding whether to retry. |
| Deadline during a slow tool call | New helper messages and approvals are rejected after expiry; no claim is made that the slow tool was killed. |
| Repeated STOP | Closure is idempotent; the session does not reopen or change outcome. |
| One approval only | Closure retains the result as `PARTIAL`. |
| Different paths or hashes approved | Closure does not report `AGREED`. |
| Artifact changed after approval | Current bytes invalidate the prior matching-approval condition. |
| Symlink or escaping artifact path | Approval is rejected. |
| Missing artifact at closure | No valid agreement is reported. |
| Disconnected or restarted participant | The transcript and status support a cooperative resume; no new join or timer reset is implied. |
| Malicious instruction in source or peer text | The operating agents retain the original task scope; the helper itself is not claimed to detect prompt injection. |
| Direct edit outside the helper | Demonstrate and document that helper locks do not protect unrelated files or prevent deliberate state tampering. |

For the automated coordinator, also exercise these cases with fake local CLI
processes and synthetic snapshots:

| Case | Required observation |
| --- | --- |
| Invalid, oversized, or symlink input | Reject the input before any model turn. |
| Independent proposals | Neither first turn receives the other participant's proposal. |
| Two coordinators on one session | Only one owns and launches model turns. |
| Completed turn followed by interrupted local processing | Resume reuses the output and replays local effects without a duplicate invocation or message. |
| Coordinator dies during a model turn | Resume reports an unknown outcome and does not automatically invoke that turn again. |
| Stop, deadline, or per-turn timeout | The running coordinator stops its own child process groups and retains completed work. |
| Verdict for an earlier report version | Reject approval of a report whose current bytes differ from the reviewed hash. |
| Round limit without approval | Close with the recorded reservations and an appropriate incomplete or disagreement outcome. |

Local process termination does not establish cancellation of a remote model
request or its billing. A separate working directory and tool-disabling flags
also do not establish an operating-system security boundary. Confirm the
effective behavior of the installed, trusted CLIs during a live pilot.

Test failures and fixes should be reported by behavior, not just by test count.
Claims about supported operating systems should follow actual runs on those
systems, rather than the mere presence of POSIX-compatible code.

## Limits of a result

A helper test can show that a stale approval is rejected. It cannot show that an
agent understood the artifact it approved. A completed two-agent session can
show that the workflow is usable in that context. It cannot establish a causal
quality gain, broad agent compatibility, security against a malicious peer, or
unattended manual operation after the agent turns have ended. The automated
coordinator removes that manual scheduling requirement; its tests do not
establish provider compatibility or review quality without a live trial.
