# Current status and remaining validation

The project supports both manual sessions and automated text reviews. The
`run` command starts Codex and Claude Code, manages the review, and saves the
report. You do not need to keep chat windows open.

The `collaborative-review` skill starts reviews through the same CLI. `doctor`
checks the local tools without making a model request. The
[skill guide](docs/SKILLS.md) explains installation and includes three fictional
review examples. Automated reviewers still follow the separate policy in
`review_session/prompt_policy.py`.

Codex finds the skill through this checkout's symlink to `skills/`. It reads the
description and interface metadata without errors. That confirms discovery,
not whether a model will select and follow the skill. The
[validation record](docs/VALIDATION.md) lists the versions and checks.

Tests use synthetic local subprocesses to check coordination and recovery
without paid model calls. A completed live review with both providers and any
improvement in answer quality remain unverified. Rerun the repository checks
after changes.

## Next step

Complete a live Codex + Claude Code review with the published helper on a
small, non-sensitive task. Follow the [automated guide](docs/AUTOMATED_REVIEW.md)
with recent, authenticated CLIs and a fresh session directory, or use the
[manual quickstart](README.md#manual-quickstart) and give both active sessions
the same [task brief](templates/task.md). Manual participants still require
operator intervention if their turns end.

Record what happened:

- Did both agents prepare an independent first assessment?
- Which objections changed the report? Which concerns remained unresolved?
- How much time, model usage, and manual intervention did the review need?
- Which CLI and model versions were used, and what was the final outcome?

Read the final report and record its actual outcome, including `PARTIAL` or
`DISAGREED` when appropriate. Compare token usage, cost, and elapsed time with
the evaluation baselines before claiming an efficiency gain. Use the results
before expanding the workflow or changing how conversation context is supplied.
For a code review, name the reviewed commit or diff in `artifacts/result.md`:
the approval hash covers that report, not the application code.

Use the [evaluation plan](EVALUATION.md) before claiming a quality or cost gain.
Keep live session transcripts and private task material out of the public Git
history. Publish an anonymized account of a trial only after checking it with
the operator.
