# The decision record

One JSON file per record under `noni/decisions/`, named `<id>.json`. The record
is the commit: a file in the working tree that is not committed is not a record,
and a committed record is replayable by any later session or fresh clone because
it reads nothing but git.

## The eight fields (plus the optional ones)

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
  "source": { "issue_number": 42, "comment_id": 9102 },
  "decided_by": "operator-ann",
  "on_behalf_of": "the platform team",
  "single_option": true
}
```

The field list is fixed and the census validates it. A record with a missing or
malformed field fails the census with exit `10`. Four fields are optional:
`source`, `decided_by`, `on_behalf_of` and `single_option`. A record that carries
none of them is the eight-field shape and stays valid, which is what keeps every
record written before these fields existed censusable. Each optional field is
checked when present.

| field | type | rules |
|---|---|---|
| `id` | string | `YYYY-MM-DD-<slug>`; unique across the ledger; equals the filename stem. `decide.py` builds it from `--date` and `--slug`, and the slug is held to `[a-z0-9-]+` so the name stays a plain path segment (`ledger-record` reports anything else). The writer adds the date, so a slug that already starts with one shaped `YYYY-MM-DD-` (`^[0-9]{4}-[0-9]{2}-[0-9]{2}-`, shape only: `2026-11-08-topic` and `2026-13-45-topic` alike) is refused at exit 2 before anything is written, and the refusal shows the slug without its date prefix (a slug that is only a date and its trailing dash has nothing left to show, so it takes the character rule); `topic-2026` and `v2026-11-08` are accepted, and so is a bare `2026-11-08`, which carries no trailing dash |
| `date` | string | UTC ISO-8601. `decide.py` writes `<--date or today, UTC>T00:00:00Z`, for a supersede as for any other record: the chain, not the date, is what orders the ledger |
| `asked_by` | string | the agent role or session that asked |
| `questions` | array | 1-4 question objects (see below) |
| `by` | string | git author of the record's commit (see Attribution) |
| `scope` | string | the direction area the decision covers |
| `status` | string | `decided` \| `open` \| `superseded` |
| `supersedes` | string \| null | id of the replaced record, or `null` for a root record |
| `source` | object \| null (optional) | tracker provenance: `{"issue_number": <int>, "comment_id": <int>}` when the record was produced from a tracker-sourced answer (an adapter's question-legitimacy verdict); `null` or absent for a record that did not come from a tracker. A record without it stays valid. |
| `decided_by` | string (optional) | who made the decision, when that is not the commit author: a login or pseudonym, never a personal-name requirement. Written by `--decided-by`. Absent means the commit author decided, so records written before this field stay valid. The census types it as a non-empty single-line string and verifies nothing about the identity |
| `on_behalf_of` | string (optional) | the party a delegated decision was made for, written by `--on-behalf-of`. Same census shape as `decided_by`. `decide.py` refuses it without `--decided-by`; a hand-edited record carrying one name and not the other is well formed, because the pairing is the writer's rule and not the census's |
| `single_option` | `true` (optional) | written by `--single-option`: the marker that says a question was asked with one option on purpose. It is the only thing that makes a one-option question valid, so a one-option record without it is a `ledger-record` exit 10. It is a per-record marker over a per-question bound: with it set, any question of that record may hold one option and at least one must, so a marker no question carries one option is a `ledger-record` exit 10 as well. Written as the JSON `true` literal, anything else is a malformed marker |

## The question object

Each question in `questions` is an object with four keys. The `answer` names its
question by id pairing: in multiple-choice mode a record can carry up to four
questions, and each question's answer is paired to it by the question's own `id`,
so a multi-question record is unambiguous.

| key | type | rules |
|---|---|---|
| `id` | string | short identifier unique within the record (`q1`, `q2`, ...) |
| `text` | string | the question as asked |
| `options` | array | 2-4 strings, or exactly one string for a question of a record that carries `single_option` (the marker is read per record, the bound judged per question, and one question of a marked record must hold one option); the free-text escape hatch is always available, so a reply may name an option not in the list |
| `answer` | string \| null | the chosen option's string (or a free-text string), or `null` when the question is open |

## Writing a record

`scripts/decide.py` is the writer: one command writes the file and commits it,
and `--supersedes` is its flag for a correction rather than a separate script.
Nothing here is hand-written. What the writer decides for you, and what it
never does:

- **Supplied by flags, named after the field:** `id` (from `--date` and
  `--slug`), `asked_by`, `scope`, each question's `id`/`text`/`options`, and
  each answer (`--answer ID=<answer>`). `by` comes from `git config user.name`
  of the tree, so it is not a flag either. `--decided-by` and `--on-behalf-of`
  name who decided and, for a delegate, who they decided for; `--single-option`
  records that a question was asked with one option on purpose.
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

### Who decided, when the commit author is not that person

Agents commit under the operator's identity, so `by` names who committed and
not who decided. `decided_by` records the decider separately, and
`on_behalf_of` names the party a delegate acted for (the writer is a wrapper, so
the `noni` package must be installed or importable on `PYTHONPATH` first -- see
the *Install noni* section of
[docs/QUICKSTART.md](../../../docs/QUICKSTART.md#install-noni)):

```
scripts/decide.py --repo . --decided-by operator-ann --on-behalf-of "the platform team" ...
```

The three rules that keep this honest without pretending to verify anyone:

- The record's `by` still comes from git and the report's `by` column still
  reads `git log -1 --format=%an`. `decided_by` never overrides it, so a body
  value cannot buy an author it does not have.
- A record with no `decided_by` means the commit author decided. That is the
  reading for every record written before the field existed, and it is why no
  old record needed rewriting.
- The census checks the shape and nothing else: each name is a non-empty single
  line. It never verifies an identity, and it does not enforce the pairing —
  `decide.py` refuses `--on-behalf-of` without `--decided-by`, and a record
  hand-edited to carry one name alone stays well formed.

## The schema level, and a writer newer than the census

The field list above is one closed set, and the census knows it by number: the
writer declares a **ledger schema level**, and an attached project can commit the
level its census runs at:

```json
// noni/direction/census-level.json
{ "schema_level": 1 }
```

The file is a sibling of `decisions/`, never inside it, so the census never reads
it as a record. Whoever pins the census for a project commits it, with the number
that census's own code declares. It is the project's statement about its own pin,
so the writer reads it and never creates it.

A `decide.py` run asks one question of that file before it writes anything, and
the question is a single integer comparison: is the writer's level greater than
the declared one? Three answers:

| the tree | what happens |
|---|---|
| no declaration file | the ordinary project. Writes and censuses exactly as it did before the file existed; nothing new is printed and the census reports nothing |
| declared level at or above the writer's | the pair is in step, or the project's census is newer than its writer. The record is written |
| declared level below the writer's | **exit 4** — the run refuses, naming both levels, the file, and the fix in both directions: upgrade the census pin to this noni, or run the writer at the commit that census was pinned at |
| the file is not readable JSON, is not an object, or holds no integer level | **exit 2** — a file the run cannot read says nothing about the census it was meant to describe, so the run refuses rather than writing on the uncertainty. `0` is a readable answer (a census predating the first declared set) and takes exit 4, not exit 2 |

The drift this closes is the one that costs a day: a project pins one noni commit
for its CI census and runs a newer one locally, and on the day the newer writer
emits a field the pinned census does not declare, the record commits cleanly and
the census refuses it hours later in a red run. The refusal moves that moment to
the write.

The census says the same fact from its side. A record carrying a field the census
does not declare is still a `ledger-record` exit 10 naming the field, and its row
now adds why: an unknown field is what a record from a newer writer looks like to
an older census, and the row quotes the level this census runs at and names the
upgrade that clears it.

Bumping the writer's level is part of the change that changes the closed set: a
field added to the optional list without a bump is a record a pinned census refuses
with nothing said at the writer, which is the bug the number exists to close.

## Ordering and the supersede chain

Replay order is **supersede-chain order first, `date` only as a tie-break.** The
supersede chain is the primary ordering: a record's chain position is defined by
what it supersedes, independent of the timestamp. A record that supersedes
nothing is a chain root. The tie-break exists because two records with no
supersede relationship between them have no chain order and fall back to their
UTC date. See `supersede.md` for the chain-resolution rules.
