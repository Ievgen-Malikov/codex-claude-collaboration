# Synthetic review recipes

These are fictional starting points. They contain no private data, executed
test results, or actual provider conclusions. Read only the asset relevant to
the selected scenario. Resolve asset paths relative to this skill directory;
do not assume the skill is inside the current working directory.

| User's task | Synthetic input | Goal to adapt |
| --- | --- | --- |
| Review an architectural choice | [Architecture brief](../assets/architecture.synthetic.md) | Review the proposed job execution design against its constraints; recommend a first version and preserve unresolved failure cases. |
| Find specification gaps | [Specification brief](../assets/specification.synthetic.md) | Find contradictions and missing observable behavior in the supplied export specification; propose precise corrections. |
| Review a supplied diff | [Diff brief](../assets/diff.synthetic.md) | Review the supplied cache diff against the stated contract; identify supported defects and propose unrun regression checks. |

For a real task, substitute the user's evidence, scope, revision identity, and
acceptance criteria. Do not send a fictional asset instead of the user's
materials. Child turns can reason about the text; they cannot read more files
or execute the proposed checks.

An expected report should contain:

- a recommendation or findings tied to specific supplied evidence;
- consequences and concrete proposed corrections;
- assumptions and missing evidence;
- checks actually supplied as evidence, separated from proposed unrun checks;
- material objections that remain unresolved.

There is no predetermined provider verdict. Judge the report against the
brief's acceptance criteria, not whether the agents agreed.
