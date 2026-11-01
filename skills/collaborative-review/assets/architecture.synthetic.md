# Synthetic architecture review brief

This fictional task demonstrates text review. It is not an actual application
design, benchmark, or record of a provider run.

## Goal

Recommend a first implementation for generating PDF invoices in a small web
application. Review the execution design; do not implement or deploy it.

## Supplied facts and proposal

- A user requests an invoice for a completed order. Generation usually takes
  8 seconds and occasionally 45 seconds.
- The HTTP gateway closes requests after 30 seconds.
- Users sometimes double-click and may retry after losing their connection.
- An order may have only one final invoice number. A successful invoice must
  remain available if the client disconnects.
- The application already has a relational database; it has no job broker.
- The proposal is to generate inside the HTTP handler, insert the final invoice
  record after generation, and tell the client to retry on timeout.
- The proposal claims that disabling the button prevents duplicate generation.
  No implementation or executed test results support that claim.

## Scope

Reason only from these supplied facts. Compare the proposal with a persisted
job handled by an application worker. Recommend only infrastructure justified
by the stated constraints. No repository access, network research, code edits,
or external writes are requested.

## Acceptance criteria

Explain timeout and disconnect behavior, authoritative duplicate protection,
job ownership, recovery after worker interruption, and the user-visible state.
Identify assumptions about invoice-number allocation and failed generation.
Propose concrete acceptance checks, mark them unrun, and preserve objections
that cannot be resolved from the brief.
