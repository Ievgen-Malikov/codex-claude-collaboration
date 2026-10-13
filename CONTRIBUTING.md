# Contributing

Small improvements to the protocol, examples, recovery behavior, and tests
are welcome. Explain the problem and a concrete way to reproduce it.

## Development

Use Python 3.10 or later on macOS or Linux. Windows users can use WSL.
The helper has no third-party runtime dependencies.

```sh
python3 -m unittest discover -s tests -v
python3 -m review_session --help
git diff --check
```

Add regression coverage for behavioral changes. In particular, check expired
sessions, late messages, interrupted writes, simultaneous senders, and files
changed after approval. Update the CLI instructions when commands change.

## Examples and evaluation

Label simulated conversations as synthetic. Do not publish private logs or
claim that an example measures model quality. See EVALUATION.md for a proposed
comparison of collaboration methods.

## Commits

Use concise Conventional Commit messages, such as
`fix(session): reject stale artifact approvals`. Describe the resulting
behavior and include relevant verification in the pull request.
