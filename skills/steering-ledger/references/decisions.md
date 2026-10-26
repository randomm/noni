# The decision record

One JSON file per record under `noni/decisions/`, named `<id>.json`. The record
is the commit: a file in the working tree that is not committed is not a record,
and a committed record is replayable by any later session or fresh clone because
it reads nothing but git.

## The eight fields (plus one optional)

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
  "supersedes": null,
  "source": { "issue_number": 42, "comment_id": 9102 }
}
```

The field list is fixed and the census validates it. A record with a missing or
malformed field fails the census with exit `10`. One field, `source`, is
optional: a record that did not come from a tracker may omit it (or set it to
`null`), but when it is present it must carry exactly the tracker's issue number
and comment id as integers — it is how a ledger record produced from a tracker
answer references where that answer came from.

| field | type | rules |
|---|---|---|
| `id` | string | `YYYY-MM-DD-<slug>`; unique across the ledger; equals the filename stem. `decide.py` builds it from `--date` and `--slug`, and the slug is held to `[a-z0-9-]+` so the name stays a plain path segment (census.sh rejects anything else as `10:bad-name`) |
| `date` | string | UTC ISO-8601. `decide.py` writes `<--date or today, UTC>T00:00:00Z`; a supersede carries the date of the record it replaces, so the chain, the filename stem and replay order stay in step |
| `asked_by` | string | the agent role or session that asked |
| `questions` | array | 1-4 question objects (see below) |
| `by` | string | git author of the record's commit (see Attribution) |
| `scope` | string | the direction area the decision covers |
| `status` | string | `decided` \| `open` \| `superseded` |
| `supersedes` | string \| null | id of the replaced record, or `null` for a root record |
| `source` | object \| null (optional) | tracker provenance: `{"issue_number": <int>, "comment_id": <int>}` when the record was produced from a tracker-sourced answer (an adapter's question-legitimacy verdict); `null` or absent for a record that did not come from a tracker. A record without it stays valid. |

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
| `answer` | string \| null | the chosen option's string (or a free-text string), or `null` when the question is open |

## Writing a record

`scripts/decide.py` is the writer: one command writes the file and commits it,
and `--supersedes` is its flag for a correction rather than a separate script.
Nothing here is hand-written. What the writer decides for you, and what it
never does:

- **Supplied by flags, named after the field:** `id` (from `--date` and
  `--slug`), `asked_by`, `scope`, each question's `id`/`text`/`options`, and
  each answer (`--answer ID=<answer>`). `by` comes from `git config user.name`
  of the tree, so it is not a flag either.
- **Derived, never supplied:** `status`. All questions answered is `decided`;
  any unanswered question is `open` and its `answer` is written as `null`; the
  target of a supersede becomes `superseded`. There is no `--status` flag.
- **Never chosen:** an answer. The writer records what the operator decided;
  a question with no `--answer` is written open, not guessed into a decision.

## The open / declined state

A declined or cancelled steer leaves the question open, and the record that
captures it (a session that stopped after asking, an operator who declined every
option) is written as an **open chain-root record**: `supersedes: null`,
`status: open`, and every question's `answer` written as `null`. A decline is
never a supersede — a supersede whose chain holds no answered record would
resolve to zero live records, which the census reports as exit 20.

`answer` null + `status: open` is the only state "records nothing" can mean.

A `many` or `stranger` tick-parse is persisted the same way — `status: open`,
`answer` null, never as an `answer` — because an ambiguous or foreign tick is
not a legitimate operator decision.

## Attribution

`by` is the **git author of the record's commit**, read as

```
git log -1 --format=%an -- noni/decisions/<id>.json
```

not from the file body. A forged `by` in the file body never reaches the
census report: it reports `by` from git, so a body value the commit does not
carry is simply not what appears in the report — the census does not flag a
mismatch between body and commit. The default posture is signed commits;
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
