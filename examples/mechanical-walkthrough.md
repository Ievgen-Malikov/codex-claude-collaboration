# Mechanical walkthrough: no models required

This is a synthetic local exercise. One human uses both participant labels to
test commands; no two agents are running and no independent review takes place.
Run from the repository root with a fresh session path. The helper writes only
the local session; it does not contact model providers.

```sh
python3 -m review_session init ./sessions/mechanical-001 \
  --goal "Exercise the helper using a synthetic fixture; no agent review is claimed." \
  --minutes 30

python3 -m review_session join ./sessions/mechanical-001 --agent agent-a
python3 -m review_session join ./sessions/mechanical-001 --agent agent-b
python3 -m review_session start ./sessions/mechanical-001

python3 -m review_session send ./sessions/mechanical-001 --agent agent-a \
  --kind proposal --text "Synthetic message: review the mechanics fixture."
python3 -m review_session send ./sessions/mechanical-001 --agent agent-b \
  --kind finding --text "Synthetic message: the fixture must say no application tests were run."
python3 -m review_session inbox ./sessions/mechanical-001 --agent agent-a --after 0

cp examples/result.synthetic.md ./sessions/mechanical-001/artifacts/result.md

python3 -m review_session approve ./sessions/mechanical-001 \
  --agent agent-a --artifact artifacts/result.md
python3 -m review_session approve ./sessions/mechanical-001 \
  --agent agent-b --artifact artifacts/result.md
python3 -m review_session stop ./sessions/mechanical-001 \
  --reason "Synthetic mechanical exercise complete."
python3 -m review_session status ./sessions/mechanical-001
```

Both approvals refer to the same copied fixture, so closure should report
`AGREED`. That outcome demonstrates the helper's matching-approval rule. It
does not establish real model participation, independent judgment, or quality.

To inspect the hash rule, create a second session with a new path and repeat the
steps through both approvals. Change the artifact before `stop`, then close it.
Without fresh matching approvals, closure should be `PARTIAL`.

To run an actual two-agent review, use the two prompts and operator steps in
[the README](../README.md). Do not reuse this synthetic transcript as a claimed
real collaboration example.
