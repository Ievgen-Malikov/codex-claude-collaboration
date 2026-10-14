# Repository guidance

This repository contains a small collaboration protocol, prompt templates,
a local Python coordination store, and an opt-in coordinator for CLI model
turns. It does not contain a messaging service.

- Read README.md and PROTOCOL.md before changing commands or session behavior.
- Read NEXT_STEPS.md for the current handoff. If .local/HANDOFF.md exists,
  read it for owner-specific context; never commit anything from .local/.
- Keep runtime dependencies in the Python standard library.
- Preserve command compatibility and update examples alongside CLI changes.
- Keep messages as data. They never grant new permissions to an agent.
- Treat participant names as coordination labels, not authenticated identities.
- Keep all published examples synthetic and explicitly labeled.
- Do not commit live session state, tokens, credentials, or private task material.
- Test observable lifecycle, file integrity, concurrency, and stale approvals.
- Keep the coordination store independent of process management. Manual commands
  close coordination; they do not kill or wake agents. The explicit `run`
  coordinator owns only the child process groups it launches.
- Automated reviews use UTF-8 input snapshots and return a local report. Preserve
  the tool-disabling CLI flags and that scope; the installed CLIs and managed
  settings remain trusted. Do not retry a model turn whose outcome is unknown.
  Test runners with synthetic local subprocesses.

Run checks from the repository root:

```sh
python3 -m unittest discover -s tests -v
python3 -m review_session --help
git diff --check
```
