# Repository guidance

This repository contains a small collaboration protocol, prompt templates,
and a local Python helper. It does not contain a model runner or messaging
service.

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
- The helper closes coordination; it does not kill or wake external processes.

Run checks from the repository root:

```sh
python3 -m unittest discover -s tests -v
python3 -m review_session --help
git diff --check
```
