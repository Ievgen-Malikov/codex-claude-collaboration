# Current status and first live trial

This workflow grew out of a practical question during a personal project: how
can Codex and Claude Code review the same task, challenge each other's reasoning,
and leave a clear result? The repository packages that idea as a local Python
helper, a protocol, and prompts for two active agent sessions.

The CLI, packaging, and synthetic walkthrough have been checked. The 25 CLI
tests cover readiness, deadlines, concurrent messages, closure, and artifact
approvals. GitHub Actions passed on Linux and macOS at the last code change
(`23852fb`). Two independent reviews found no remaining blocker. These checks
establish the helper's behavior, not the quality of a two-agent answer.

## Next step

Run the first real Codex + Claude Code review with this published helper on a
small, non-sensitive task. Follow the [README](README.md) and give both agents
the same [task brief](templates/task.md). Keep both turns active for the shared
30-minute window; the helper cannot wake an idle agent.

Record what happened: whether both agents prepared independent first passes,
which objections changed the result, whether the editor preserved unresolved
concerns, and how much operator intervention was needed. Check the actual final
artifact and record the outcome, including `PARTIAL` or `DISAGREED` if warranted.
For a code review, name the reviewed commit or diff in `artifacts/result.md`:
the approval hash covers that report, not the application code.

Use the [evaluation plan](EVALUATION.md) before claiming a quality or cost gain.
Keep live session transcripts and private task material out of the public Git
history. Publish an anonymized account of a trial only after checking it with
the operator.
