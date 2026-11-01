# Validation snapshot

The checks below ran on November 1, 2026, on macOS with Python 3.12.7 and Codex
CLI 0.166.0. The results apply to these versions and workflows. Rerun the checks
after later changes.

## Helper and portable skill

- The local unit and integration tests used synthetic subprocesses. They covered
  manual coordination, CLI contracts, restricted adapters, ownership,
  cancellation, output limits, recovery, and approvals of exact report bytes.
- We built and installed the package in a temporary virtual environment. The
  installed command worked outside the checkout. Its runtime dependencies
  remain limited to the Python standard library.
- The released Agent Skills reference validator, `skills-ref==0.1.0` (command
  `agentskills`), accepted the skill. CI runs the same check as a development
  tool; it adds no runtime dependency.
- A complete copy of the skill worked outside the checkout, including its
  references and synthetic assets. A second installation refused the existing
  destination and left its contents unchanged.
- An independent agent used that copy with two synthetic local CLIs. It ran one
  review within the set limits, read the report, and checked matching report
  hashes. The report came from deterministic test programs, so this checks
  coordination without measuring model quality.

## Native Codex discovery

We checked native discovery with the app-server protocol: `initialize`,
`initialized`, and `skills/list` with `forceReload: true`. These calls started
no thread or model turn.

The loader found both a copied skill in a temporary project's `.agents/skills`
and this checkout's relative symlink. In each case it returned one enabled
`collaborative-review` repository skill with the expected description. It also
returned the resolved `SKILL.md` path and interface metadata from
`agents/openai.yaml`. The loader reported no errors.

An offline `codex debug prompt-input` check also listed the skill in the initial
list of available skills. It left the skill body unexpanded. These are discovery
checks only. Explicit activation, natural-language selection, and a successful
review started from a host conversation remain untested.

## Restrictions and remaining checks

Local version and help commands checked the CLI option names that the adapters
require. Codex reported all requested features as disabled, including
`view_image`. The adapter uses `--disable view_image`; this Codex version ignores
the former `tools.view_image=false` setting. Initial and resume commands use the
same feature restrictions. The decoder rejects error events about ignored
restrictions.

A local synthetic Responses endpoint captured the initial Codex `exec` request
with the adapter's actual restrictions. The endpoint required no authentication,
and the operating system blocked network access except to localhost.

The first capture showed an available `request_user_input` tool. The adapter now
also sets `tools.experimental_request_user_input.enabled=false`. With that
setting, the captured request advertised an empty tool list and produced no
warning about ignored configuration. The endpoint deliberately returned an
error without inference.

This check used the installed CLI with fallback synthetic model metadata. It
did not cover every provider or model catalog, or a successful model response.

Restriction behavior can vary with the installed CLI and administrator
settings; those combinations need separate checks. Native Claude Code discovery
and model-level skill selection remain untested. No complete live review with
both providers is recorded. Quality, cost, and latency improvements remain
unmeasured.

See [NEXT_STEPS.md](../NEXT_STEPS.md) for the remaining integration work. Use
[EVALUATION.md](../EVALUATION.md) to compare approaches with the same combined
budget. Published task briefs are labeled synthetic. This snapshot and the
repository history exclude live session state and logs.
