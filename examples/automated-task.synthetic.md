# Synthetic automated review brief

This is a fictional task for demonstrating the coordinator. It contains no
private application data and is not a record of an actual agent review.

## Task

Recommend a first version of a local notes application's export feature.
The operator wants to export one selected note as a UTF-8 Markdown file.
The application runs on a user's laptop. No network access is required.

## Constraints

- Show the chosen destination before creating the export.
- Preserve the source note if export fails.
- Avoid overwriting an existing destination without a deliberate user choice.
- Give a clear completion or failure message.
- Keep this review to a recommendation; do not implement code or write an export.

## Questions to resolve

Should the first version use a file picker, a fixed export directory, or another
approach? What should happen when the destination already exists or becomes
unavailable after selection? How should the application distinguish a saved
export from an interrupted operation whose result has not been confirmed?

## Acceptance criteria for the report

Explain the recommendation and its failure behavior. Give concrete checks a
future implementation should pass. Preserve any remaining material objections
or assumptions. The brief includes no application code or executed test results;
the report must identify proposed checks as unrun.
