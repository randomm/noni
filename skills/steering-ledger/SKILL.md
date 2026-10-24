---
name: steering-ledger
description: Record, attribute and replay operator product-direction decisions as dated, git-committed ledger files under noni/decisions/. Use when an operator steers the direction of an attached project (answers a multiple-choice question or confirms a free-chat candidate record), when a later session or fresh clone needs to replay prior decisions, or when validating the ledger's schema and provenance via the unified census (skills/census/scripts/census.py; the per-epic script census.sh remains a compatible shim). Do NOT use for general code work, CI, or task tracking — this skill owns only the decision-record format, the two steer modes, the supersede chain, and the census that holds the invariants.
---

# steering-ledger

**Mission:** every operator product-direction decision becomes a dated, attributed,
git-committed record that any later session or fresh clone can replay — the same
question, the same answer, and the same why.

Two input modes, one record. An operator steers by **answering a bounded
multiple-choice question** (1-4 questions, 2-4 options each, with a free-text
escape hatch) or by **confirming a free-chat candidate** the agent distils. The
agent never answers for the operator: a decline or cancel leaves the question
open, records nothing, and commits nothing.

The record is the commit. A ping, a comment, or a chat message is a hint; the
committed file is the truth. The census (`scripts/census.sh`) is the enforcement
mechanism for what git and the files can prove: every invariant it enforces is
a script with an honest exit code or a census check that catches the
violation. Prose states the protocol; the census holds the line where git
gives it the evidence. What git cannot prove — that an answer was the
operator's, not an agent's — is a protocol rule agents follow, not a census
check (see Anti-fabrication below).

Read `references/decisions.md` before writing a record. Read
`references/modes.md` before steering. Read `references/supersede.md` before
correcting a record. Read `references/census.md` before reporting on the ledger
state.

## The record

One JSON file per record under `noni/decisions/`, named `<id>.json`. The eight
fields (in order), plus one optional field (`source`):

| field | type | meaning |
|---|---|---|
| `id` | string | stable identifier, `YYYY-MM-DD-<slug>` |
| `date` | string | UTC ISO-8601, from commit metadata at write time |
| `asked_by` | string | the agent role or session that asked |
| `questions` | array | 1-4 question objects, each `{id, text, options[], answer}` |
| `by` | string | git author of the record's commit (forgeable; see below) |
| `scope` | string | the direction area the decision covers |
| `status` | string | `decided`, `open`, or `superseded` |
| `supersedes` | string | id of the record this one replaces, or `null` |
| `source` | object, or `null` (optional) | tracker provenance: `{"issue_number": <int>, "comment_id": <int>}` when the record was produced from a tracker-sourced answer; `null` or absent otherwise (a record without it stays valid) |

A `question` object is `{id, text, options, answer}`. `options` is an array of
2-4 strings. `answer` is either the chosen option's string (or a free-text
escape string) and must name the question it answers by id pairing, or is absent
when the question was left open. The full shape, validation rules, and the
declined/open state are in `references/decisions.md`.

The `answer` names its question by id: in multiple-choice mode each question
carries its own `id` and its own `answer`, so a three-question record is
unambiguous. A `many` or `stranger` tick-parse persists as `status: open` with
the question's `answer` absent — never as an answer. A decline or cancel
persists `status: open` with every `answer` absent; that is the only state
"records nothing" can mean.

## Attribution

`by` is the **git author of the record's commit** — read with
`git log -1 --format=%an -- <record path>`, not from the file body. This is
forgeable locally; the default posture is signed commits, and stranger-detection
is advisory until forge-verified pushes. The census reports `by` from git so a
forged file body cannot claim a different author. The full attribution rule is
in `references/decisions.md`.

## Supersede

A correction writes a **new** file; the superseded record's bytes stay unchanged
and its blob stays reachable in history. Never edit history. Each supersede
chain must resolve to exactly one live record, and a duplicate, dangling, or
cyclic supersedes is refused by the census. The protocol is in
`references/supersede.md`.

## Modes

The two steer modes, the multiple-choice bounds, the free-text escape hatch, and
the anti-fabrication rule (the agent never answers for the operator) are in
`references/modes.md`.

## Census

`scripts/census.sh` is read-only, jq-based, and exits with an honest code:

| code | meaning |
|---|---|
| `0` | clean — every record valid, chain intact |
| `3` | jq not found on the reading machine |
| `10` | a record is missing or malformed, or the ledger is unusable (missing/empty dir, bad filename, unreadable git tree) |
| `12` | a record was edited after commit (supersede instead) |
| `20` | the supersede chain is broken (dangling, duplicate, orphan, cycle, or a chain resolving to zero or more than one live record) |

When several invariant classes fail at once, the lowest code wins
(`10 < 12 < 20`); the stderr message says whether the higher-numbered checks
were skipped. The census does not check operator confirmation: it cannot see
whether the operator confirmed an answer, so it never claims to (below).

The exit-code contract and how to read the report are in `references/census.md`.

The census also dispatches the sessions check (E2): `census.sh --sessions
[SESSIONS_DIR]` reaches into the sibling `sessions-claims` skill via the
relative path `../../sessions-claims/scripts/census-sessions.sh`. That is a
documented dependency: with no override, `sessions-claims` must be installed at
the expected relative path. Set `NONI_SESSIONS_CENSUS` to an absolute path to
point the dispatch at a separately installed copy or an adapter.

## Rules

- **Never answer for the operator.** This is a protocol rule agents follow, not
  something the census enforces: git cannot distinguish an operator answer from
  an agent-written one (agents commit under the operator's identity), so the
  census does not check confirmation and does not claim to. Signed operator
  confirmation, where git can see it, is a follow-up.
- **The answer is confirmed, not written.** A record with an `answer` is a
  confirmed record; an unconfirmed candidate commits nothing.
- **One file per record; the directory is the aggregate.** The census tolerates a
  half-written or malformed record without blinding itself to the rest.
- **Supersede, never edit.** A corrected record is a new file; the old one stays
  byte-for-byte as committed.
- **No project content in the skill.** Core skills carry neither project
  content nor driver-tool vocabulary; integrations are clearly-marked adapters.
  The purity rule is itself a test.
