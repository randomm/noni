# The decision record

One JSON file per record under `noni/decisions/`, named `<id>.json`. The record
is the commit: a file in the working tree that is not committed is not a record,
and a committed record is replayable by any later session or fresh clone because
it reads nothing but git.

## The eight fields

```json
{
  "id": "2026-10-22-steer-order",
  "date": "2026-10-22T14:03:00Z",
  "asked_by": "developer",
  "questions": [
    {
      "id": "q1",
      "text": "Which release should carry the new scheduler?",
      "options": ["next train", "after that", "drop it"],
      "answer": "next train"
    }
  ],
  "by": "Operator Name",
  "scope": "release ordering",
  "status": "decided",
  "supersedes": null
}
```

The field list is fixed and the census validates it. A record with a missing or
malformed field fails the census with exit `10`.

| field | type | rules |
|---|---|---|
| `id` | string | `YYYY-MM-DD-<slug>`; unique across the ledger; equals the filename stem |
| `date` | string | UTC ISO-8601; generated from commit metadata at write time |
| `asked_by` | string | the agent role or session that asked |
| `questions` | array | 1-4 question objects (see below) |
| `by` | string | git author of the record's commit (see Attribution) |
| `scope` | string | the direction area the decision covers |
| `status` | string | `decided` \| `open` \| `superseded` |
| `supersedes` | string \| null | id of the replaced record, or `null` for a root record |

## The question object

Each question in `questions` is an object with four keys. The `answer` names its
question by id pairing: in multiple-choice mode a record can carry up to four
questions, and each question's answer is paired to it by the question's own `id`,
so a multi-question record is unambiguous.

| key | type | rules |
|---|---|---|
| `id` | string | short identifier unique within the record (`q1`, `q2`, ...) |
| `text` | string | the question as asked |
| `options` | array | 2-4 strings; the free-text escape hatch is always available, so a reply may name an option not in the list |
| `answer` | string \| absent | the chosen option's string (or a free-text string), or absent when the question is open |

## The open / declined state

A declined or cancelled steer leaves the question open and records nothing
committable: the agent commits no file. When a record *is* committed to capture
that an answer was not given (e.g. a session that stopped after asking), the
record is persisted with `status: open` and every question's `answer` absent.
`answer` absent + `status: open` is the only state "records nothing" can mean.

A `many` or `stranger` tick-parse is persisted the same way — `status: open`,
`answer` absent, never as an `answer` — because an ambiguous or foreign tick is
not a legitimate operator decision.

## Attribution

`by` is the **git author of the record's commit**, read as

```
git log -1 --format=%an -- noni/decisions/<id>.json
```

not from the file body. A forged `by` in the file body does not change what the
census reports: it reads the author from git, so the body and the commit must
agree or the record is flagged. The default posture is signed commits;
stranger-detection is advisory until forge-verified pushes. This mirrors the
precedent that a reply edited by a non-allowed account voids the reply — the
author is the legitimacy check, and it is the commit author, not the body.

## Ordering and the supersede chain

Replay order is **supersede-chain order first, `date` only as a tie-break.** The
supersede chain is the primary ordering: a record's chain position is defined by
what it supersedes, independent of the timestamp. A record that supersedes
nothing is a chain root. The tie-break exists because two records with no
supersede relationship between them have no chain order and fall back to their
UTC date. See `supersede.md` for the chain-resolution rules.
