# Synthetic specification review brief

This fictional task demonstrates text review. No tests have been executed and
no actual provider result is included.

## Goal

Find contradictions and missing behavior in this note export specification.
Propose precise corrections without implementing the feature.

## Supplied specification

1. Export the selected note as UTF-8 Markdown to a user-selected destination.
2. Export must never overwrite an existing file.
3. If the destination exists, replace it silently so the operation remains
   one click.
4. Display "Export complete" immediately when the user confirms the picker.
5. Preserve the original note if saving fails.
6. If the destination becomes unavailable, allow the user to retry.
7. The user can switch notes while the save is in progress. Completion feedback
   is displayed on whichever note is currently open.

## Scope and missing evidence

The input is the entire specification. No code, platform API guarantees,
accessibility checks, or test results were supplied. Review only this text;
do not write files, browse, or infer an existing implementation.

## Acceptance criteria

Identify conflicting requirements and distinguish contradictions from missing
decisions. Address save confirmation, destination collisions, interruption,
retry, and which note owns an operation's result. Give replacement wording and
propose observable checks, clearly marked unrun. Record any decisions requiring
operator input.
