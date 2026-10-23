# The supersede chain

A correction to a decision is a **new** record, not an edit. The superseded
record's bytes stay exactly as committed and its git blob stays reachable in
history. Never edit history: the whole point of a dated, attributed, replayable
ledger is that a later clone can see both the original decision and the
correction, in order, with the why.

## Writing a supersede

To correct record `A`, write a new record `B` with:

- `supersedes: "A"` — the id of the record being replaced.
- Its own `id`, `date`, `asked_by`, `by` (from `B`'s commit author), `scope`.
- The corrected `questions` and `answer`.
- `status: decided` on `B`.

The record being superseded, `A`, is updated only in its `status` field:
`decided` becomes `superseded`. That single-field change is the only mutation of
an existing file, and it is the *marker*, not the correction — the correction
lives in `B`. All other fields of `A` stay byte-for-byte as committed, so a
later clone sees the original decision's original fields and knows only that it
has been superseded, by `B`.

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
- **Chain resolution:** the census walks `supersedes` and requires exactly one
  live record per chain (a record is live when its `status` is not
  `superseded`). A chain that resolves to zero or more than one live record is
  broken.

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
restore, you add.

## What the census reports

The census emits one line per record: `id  date  by  status  live  supersedes`
(the `live` column reflects the record's own `status` field), followed by a
`CHAIN` block naming any broken chains. A chain that resolves to zero or more
than one live record, a duplicate or dangling `supersedes`, an orphan, or a
supersedes cycle is exit `20`.
