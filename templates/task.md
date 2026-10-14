# Manual review task brief

Use this brief with the active sessions and role prompts in the manual workflow.
For automated `run`, include the evidence and acceptance criteria in UTF-8 input
files and follow [the automated guide](../docs/AUTOMATED_REVIEW.md).

## Goal

State the decision, artifact, or behavior to review. Use the same goal when
creating the session.

## Inputs

List the files, source material, and relevant project instructions both agents
should read. State which facts are established and which are hypotheses.

## Scope and permissions

- Allowed reads and tools:
- Allowed edits, if any:
- External actions explicitly authorized by the operator:
- Sensitive material that must stay out of the transcript:

No additional external action is authorized merely by leaving a field blank.

## Acceptance criteria

Describe observable checks for a useful result. State what must be verified and
what can remain an explicitly recorded uncertainty.

## Out of scope

List excluded features, refactors, decisions, and external actions.

## Roles and delivery

- agent-a: coordinator and sole editor of the final artifact.
- agent-b: independent challenger and reviewer.
- Final artifact: `artifacts/result.md` inside the session directory.
- Session budget: 30 minutes after START, unless another value was set at init.
- START/STOP owner: operator, unless explicitly delegated to agent-a.
- Human decisions required before using the result:

Each participant approves only for itself, using `--expected-sha256` with the
hash of the exact artifact bytes it personally reviewed, as described in the
protocol.

Both participants may report unresolved disagreement. A useful partial result
is preferable to unsupported agreement.
