# Current status and remaining validation

This workflow grew out of a practical question during a personal project: how
can Codex and Claude Code review the same task, challenge each other's reasoning,
and leave a clear result? The repository packages that idea as a local Python
helper, a protocol, and prompts for two active agent sessions. An opt-in local
coordinator now launches bounded Codex and Claude Code turns to review supplied
text without keeping chat windows active.

A repository-distributed `collaborative-review` skill now provides a thin entry
point to that coordinator. The `doctor` command checks local requirements and
provider version/help interfaces without a model request. The
[skill guide](docs/SKILLS.md) covers package installation, project-local skill
discovery, and three fictional review recipes. These additions do not change
the automated child policy or establish live provider compatibility.

The checkout exposes the skill to Codex through a relative symlink to its
canonical source. Native Codex discovery recognizes the skill and its interface
metadata without loader errors. The [validation snapshot](docs/VALIDATION.md)
records the checked versions and distinguishes discovery from model activation.

Automated tests use synthetic local subprocesses to exercise coordination and
recovery without paid model calls. These checks establish the behavior tested,
not the quality of a two-agent answer. No completed live Codex + Claude Code
review or measured quality gain has been established. Rerun the repository
checks after later changes.

## Next step

Run the first real Codex + Claude Code review with this published helper on a
small, non-sensitive task. Follow the [automated guide](docs/AUTOMATED_REVIEW.md)
with recent, authenticated CLIs and a fresh session directory, or use the
[manual quickstart](README.md#manual-quickstart) and give both active sessions
the same [task brief](templates/task.md). Manual participants still require
operator intervention if their turns end.

Record what happened: whether both agents prepared independent first passes,
which objections changed the result, whether the editor preserved unresolved
concerns, model usage, CLI and model versions, and how much operator intervention
was needed. Check the actual final artifact and record the outcome, including
`PARTIAL` or `DISAGREED` if warranted.
Measure token usage, cost, and latency against the evaluation baselines; no
efficiency gain has been established. Use those observations before expanding
the workflow or changing how conversation context is supplied.
For a code review, name the reviewed commit or diff in `artifacts/result.md`:
the approval hash covers that report, not the application code.

Use the [evaluation plan](EVALUATION.md) before claiming a quality or cost gain.
Keep live session transcripts and private task material out of the public Git
history. Publish an anonymized account of a trial only after checking it with
the operator.
