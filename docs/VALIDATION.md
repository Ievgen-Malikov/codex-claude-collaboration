# Validation snapshot

This snapshot records checks performed on November 1, 2026, on macOS with
Python 3.12.7 and Codex CLI 0.166.0. It describes these versions and workflows;
later changes require fresh checks.

## Helper and portable skill

- The local unit/integration suite uses synthetic subprocesses to cover manual
  coordination, CLI contracts, restricted adapters, ownership, cancellation,
  bounded output, recovery, and exact report approvals.
- The package was built and installed in a temporary virtual environment. Its
  installed entry point worked outside the checkout. Runtime dependencies
  remain limited to the Python standard library.
- The released Agent Skills reference validator, `skills-ref==0.1.0` (command
  `agentskills`), accepted the skill. CI runs the same development-only check.
- The complete skill folder was copied outside the checkout; bundled
  references and synthetic assets remained usable. Installation refused an
  existing destination without overwriting its contents.
- An independent agent used that copy with two synthetic local CLIs to run one
  bounded review, inspect its report, and verify matching report hashes. This
  validates orchestration mechanics; the deterministic report does not measure
  model quality.

## Native Codex discovery

The native app-server protocol was exercised with `initialize`, `initialized`,
and `skills/list` with `forceReload: true`. No thread or model turn was started.

Both a copied skill in a temporary project's `.agents/skills` and this
checkout's relative symlink were discovered. In each case the loader returned
one enabled `collaborative-review` repo skill, the expected description, its
resolved `SKILL.md` path, and the interface metadata from `agents/openai.yaml`.
The loader reported no errors.

An offline `codex debug prompt-input` check also included the skill in the
initial metadata catalog. That command did not expand the skill body. It does
not establish explicit activation, natural-language selection, or successful
execution from a host conversation.

## Restrictions and remaining checks

Local help/version probes checked the CLI option names required by the
adapters. Codex feature introspection confirmed all requested feature disables,
including `view_image`. The adapter uses `--disable view_image`; the former
`tools.view_image=false` setting is ignored by this Codex version. Initial and
resume commands retain the same feature restrictions, and error events about
ignored restrictions are rejected by the decoder.

A local, unauthenticated synthetic Responses endpoint captured the initial
Codex `exec` request with the adapter's actual restrictions. The operating
system denied network access except to localhost. The capture exposed an
otherwise available `request_user_input` tool; the adapter now also sets
`tools.experimental_request_user_input.enabled=false`. With that setting, the
captured request advertised an empty tool list and no ignored-configuration
warning. The endpoint deliberately returned an error without inference. This
checks the installed CLI with fallback synthetic model metadata, not every
provider/model catalog or a successful model response.

These checks do not establish effective restrictions for every installed CLI
or administrator configuration. Native Claude Code discovery and model-level
skill selection have not been evaluated. No completed live two-provider review,
quality improvement, cost reduction, or latency improvement is claimed.

Use [NEXT_STEPS.md](../NEXT_STEPS.md) for the remaining integration work and
[EVALUATION.md](../EVALUATION.md) for a comparison at matched combined budgets.
Published task briefs are explicitly synthetic. Live session state and logs
are not part of this snapshot or the repository history.
