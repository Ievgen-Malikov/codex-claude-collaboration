# Related work

Checked 13 October 2026. These are primary sources for existing projects and
research, not endorsements or a claim to have audited every implementation.
This project's code and prompts are an independent implementation.

File-based agent collaboration, cross-provider review, timed sessions, and
approval signals all have existing examples. The contribution here is a small
local helper and reproducible workflow for a bounded review, including explicit
partial outcomes and approvals tied to the current artifact's bytes.

## Closest practical approaches

| Source | Existing approach | Relationship to this project |
| --- | --- | --- |
| [OpenMOSS/claude-codex-handoff](https://github.com/OpenMOSS/claude-codex-handoff) | Claude Code and Codex share file streams, leases, cursors, and scheduled wake mechanisms. Its examples also include document and fact review. | Direct prior art for file-based cross-agent collaboration; our helper manages one actively attended review with a fixed deadline and matching artifact approvals. |
| [tap: A File-Based Protocol for Heterogeneous LLM Agent Collaboration](https://arxiv.org/abs/2606.14445) | The June 2026 paper describes preserved message files, notification paths, and separate worktrees for Claude/Codex development and review. | Direct prior art for heterogeneous agents using files. Its observational self-development results are not a causal benchmark for this workflow. |
| [inter-agent-deaddrop](https://github.com/laulpogan/inter-agent-deaddrop) | Two Claude Code agents coordinate over a shared filesystem with append-only JSONL, correlation IDs, and heartbeat tiers. | Shows that a local filesystem mailbox and independent sessions are established patterns. |
| [ExaDev/agent-comms](https://github.com/ExaDev/agent-comms) | A cross-harness communication mesh with rooms, direct messages, presence, and visibility. | A broader communication solution; this repository concentrates on the review procedure and exact-version closure. |
| [Claude Code cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging) | Official messaging between Claude Code sessions. | A native option for Claude-only sessions. Our cooperative file protocol can also connect different locally running tools. |

These comparisons describe scope. They do not establish unique features or
superior quality. A user who needs unattended scheduling, native integration,
or more participants should evaluate those tools directly.

## Broader orchestration

[AutoGen's termination tutorial](https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/tutorial/termination.html)
already demonstrates a primary agent and a critic that replies `APPROVE`, plus
time, message, token, and external termination conditions. Its
[current repository](https://github.com/microsoft/autogen) directs new work
toward Microsoft Agent Framework and describes AutoGen as community-managed.

[OpenHands Agent Canvas](https://www.openhands.dev/product/canvas) supports
multiple coding harnesses and parallel worktrees. Its
[repository](https://github.com/OpenHands/OpenHands) warns that conversations
using the same host workspace share files and may conflict.

[ChatDev](https://github.com/OpenBMB/ChatDev) has long used communicative roles
for development and now offers a broader multi-agent orchestration platform.
[A2A](https://a2a-protocol.org/latest/topics/life-of-a-task/) defines stateful
tasks, messages, artifacts, and task lifecycles across agent systems. This local
workflow does not implement A2A or replace those runtimes.

## Why agreement needs independent checks

- [Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/abs/2503.13657)
  (2025) studies failures in system design, inter-agent alignment, and task
  verification. Adding participants does not by itself resolve those failures.
- [Peacemaker or Troublemaker](https://arxiv.org/abs/2509.23055) (September
  2025, preprint) examines how inter-agent sycophancy can produce premature
  consensus in the settings studied.
- [The Consistency Illusion](https://arxiv.org/abs/2606.08457) (June 2026,
  preprint) finds that agreement on answers can hide reasoning misalignment on
  medical question-answering benchmarks. Its findings do not quantify our
  workflow, but motivate explicit evidence and reservations.
- [Google Research's scaling study](https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/)
  (January 2026) describes controlled comparisons across agent architectures,
  tools, and budgets. Benefits depend on the task; communication can also hurt
  performance. We do not infer a performance gain for this repository from it.
- [Can CaMeLs Talk?](https://arxiv.org/abs/2610.05640) (October 2026, preprint)
  demonstrates how untrusted data can become trusted instructions across agent
  boundaries. Our labels and hashes are not a prompt-injection defense.

See [EVALUATION.md](EVALUATION.md) for the comparisons and failure cases needed
before making claims about quality, reliability, or cost savings.
