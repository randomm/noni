# The supersede chain

A correction to a decision is a **new** record, not an edit. The superseded
record's bytes stay exactly as committed and its git blob stays reachable in
history. Never edit history: the whole point of a dated, attributed, replayable
ledger is that a later clone can see both the original decision and the
correction, in order, with the why.

## Writing a supersede

Records are written with `scripts/decide.py`. It is the only writer: it derives
the fields it can derive, refuses the shapes the census would reject, and lands
both files in one commit. Read `SKILL.md` for the flags and the exit codes.

To correct record `A`, run the writer with `--supersedes "A"`:

```
scripts/decide.py --repo REPO --slug SLUG --scope SCOPE --asked-by ROLE \
  --question ID=TEXT [--option ID=OPTION]... --answer ID=ANSWER... \
  --date <A's date> --supersedes A
```

The writer produces `B`, a new record with:

- `supersedes: "A"` — the id of the record being replaced.
- Its own `id` (`<date>-<slug>`), `date`, `asked_by`, `by` (from `git config
  user.name` of the tree) and `scope`.
- The corrected `questions` and `answer`, from the `--question`, `--option` and
  `--answer` flags.
- `status: decided`, which the writer derives from the answers it was given.

Every question of `B` must be answered, or the run is refused: an open supersede
would leave the chain with no live answer.

The record being superseded, `A`, is updated only in its `status` field:
`decided` becomes `superseded`. The writer makes that single-field change in the
same commit as `B`, and it is the *marker*, not the correction — the correction
lives in `B`. All other fields of `A` stay byte-for-byte as committed, so a
later clone sees the original decision's original fields and knows only that it
has been superseded, by `B`. To keep that promise the writer demands a target it
can describe completely: a committed regular file, byte-identical to its last
commit, in the form the writer itself writes. Anything else is refused rather
than rewritten.

```
A: { id: "2026-10-01-x", status: "decided", supersedes: null, ... }
B: { id: "2026-10-22-x", status: "decided", supersedes: "2026-10-01-x", ... }
A (after B commits): { ..., status: "superseded", ... }   # only status changed
```

## Chain resolution

The census walks `supersedes` to resolve each chain. For each chain, exactly one
record is **live** (the one whose `status` is not `superseded`). A chain that
resolves to zero or more than one live record is broken.

- **Root:** `supersedes: null`. A chain root with `status: superseded` but no
  later record pointing at it is broken — something marked it superseded
  without writing the replacement.
- **Duplicate supersedes** (two different records both `supersedes: "A"`) is
  refused: a record is replaced by at most one later record.
- **Dangling supersedes** (`B.supersedes` names an id that does not exist in the
  ledger) is broken.

A record with an earlier `date` than the record it supersedes is **not** a
violation: the supersede chain is the authoritative ordering; the date is a
tie-break for records with no supersede relationship.

## The `status` lifecycle

| transition | how |
|---|---|
| `open` -> `decided` | operator confirms an answer (or a multi-option parse is unambiguous) |
| `decided` -> `superseded` | a later record `supersedes` this id; only the `status` field of this record changes |

`superseded` is terminal: a superseded record is never un-superseded. To
reverse a supersede, write yet another record that supersedes the superseder.
The chain is append-only in the same sense the ledger is: you do not delete or
restore, you add. `decide.py` holds that line: there is no flag that edits a
committed record, and the only field of an existing file it will touch is
`status`.

## What the census reports

The census emits one line per record: `id  date  by  status  live  supersedes`
(the `live` column reflects the record's own `status` field), followed by a
`CHAIN` block naming any broken chains. A chain that resolves to zero or more
than one live record, a duplicate or dangling `supersedes`, an orphan, or a
supersedes cycle is exit `20`.
