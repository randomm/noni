# Standing intent -- template

Copy this file, fill the four sections in, and install it with the writer (the
noni package must be installed or importable for the writer to run -- see the
*Install noni* section of
[docs/QUICKSTART.md](../../../docs/QUICKSTART.md#install-noni)):

```
scripts/intent.py --repo REPO set --from ./intent-draft.md --decision <record-id>
```

The writer validates the text, restamps the `Last-confirmed:` line to this run's
UTC day, and commits the file alone with the subject
`intent: <record-id>`. `<record-id>` is the `<date>-<slug>` of a record under
`noni/decisions/` that is not superseded -- the decision that set this direction.
Run the `decide` line first and read the id off the line it prints.

Keep this file small. It is the first thing an agent session reads, so it holds
what never changes without a decision, not the running commentary of the project:
the ordering artifact holds the queue, the ledger holds the dated calls, the
session register holds who is doing what. Everything the four headings below say
must survive a long run of ordinary work; anything that can change inside one
belongs in one of those three.

The rules the writer enforces, and the census (`intent`, code 51) reports:

- four level-2 headings, `## Purpose`, `## Principles`, `## Never`, `## Ask first`,
  in that order, each exactly once;
- exactly one `Last-confirmed: YYYY-MM-DD` line;
- at most 200 lines.

A heading inside a fenced code block does not count, so an example inside one of
the sections is safe -- and every block you open has to be closed again. An
opener with no closer puts the rest of the file inside the block, hiding it from
the heading and stamp rules, so a file whose fences do not balance is refused.

---

Last-confirmed: 2026-01-01

## Purpose

One or two sentences: what this project exists to be, and for whom. Not the
roadmap -- the reason the roadmap exists. An agent should be able to settle
"does this change serve the project" from this paragraph.

## Principles

The rules that decide a close call, written so two readers apply them the same
way. Each line is a tie-breaker, not a value: "prefer the boring technology",
"never trade an operator-visible failure for a quiet one", "a compatibility
shim lives one release and then it goes".

A principle that nobody has ever had to invoke is a slogan; delete it. A
principle an operator has overridden once belongs in the ledger as a dated
record, because from that moment the file and the ledger disagree and the
precedence rule below decides which one the agent follows.

## Never

The things this project does not do, stated as prohibitions an agent can be held
to. Where `## Principles` guides a choice, this section closes one: "never edit a
committed record", "never add a dependency to dodge a bug", "never push to the
default branch".

Keep each line checkable. If the census, the CI or a script already enforces it,
say which, so an agent knows the rule has teeth rather than only prose.

## Ask first

The questions an agent must stop and ask about, never decide on its own. Money,
legal and licensing calls, anything that deletes data or rewrites published
history, anything that changes what a user sees as their own decision, and
anything the operator has named here.

An item in this section is never answered autonomously: no inference, no
"obviously they would want", no default. The agent asks, states what it found and
what it would do, and waits.
