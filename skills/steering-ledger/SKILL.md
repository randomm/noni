---
name: steering-ledger
description: Record, attribute and replay operator product-direction decisions as dated, git-committed ledger files under noni/decisions/. Use when an operator steers the direction of an attached project (answers a multiple-choice question or confirms a free-chat candidate record), when a later session or fresh clone needs to replay prior decisions, or when validating the ledger's schema and provenance via the unified census (skills/census/scripts/census.py; the ledger shim census.sh is a thin wrapper over it). Do NOT use for general code work, CI, or task tracking — this skill owns only the decision-record format, the two steer modes, the supersede chain, and the census that holds the invariants.
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
committed file is the truth. `noni census` (the unified census,
`skills/census/scripts/census.py`) is the enforcement mechanism for what git and
the files can prove; `scripts/census.sh` beside it is the ledger shim — a thin
wrapper that runs that same census over the ledger group and returns its exit
code, kept so the path older pages print still runs. Every invariant it enforces is
a script with an honest exit code or a census check that catches the
violation. Prose states the protocol; the census holds the line where git
gives it the evidence. What git cannot prove — that an answer was the
operator's, not an agent's — is a protocol rule agents follow, not a census
check (see Anti-fabrication below).

Read `references/decisions.md` before writing a record. Read
`references/modes.md` before steering. Read `references/supersede.md` before
correcting a record. Read `references/census.md` before reporting on the ledger
state. Write records with `scripts/decide.py` (below): it is the only writer,
and it refuses the shapes the census would reject.

Every `noni/` path these commands read or write resolves from `--repo`, the one
flag that names the state root: the attached project's own repository by
default, or a separate directory carrying the same `noni/` layout when a team
keeps its direction in a private state repository. The script's own location
never decides where state is read from or written to, and a `--repo` naming no
directory is refused before anything is written.

**The path every line names.** The `wrote` line names the record's real location
from the directory the command ran in: `--repo` joined to
`noni/decisions/<id>.json`. It is spelled the same with and without `--no-commit`,
and a `--supersedes` line names both paths that way, so a private state
repository never reads as a stray `noni/` beside the project.

## Writing a record

`decide.py` is a wrapper: it imports the `noni` package, which must be installed
or importable on `PYTHONPATH` before it runs (the *Install noni* section of
[docs/QUICKSTART.md](../../docs/QUICKSTART.md#install-noni)); `noni decide` is the same
code once it is.

```
scripts/decide.py --repo REPO --slug SLUG --scope SCOPE --asked-by ROLE
                  --question ID=TEXT [--option ID=OPTION]... [--answer ID=ANSWER]...
                  [--date YYYY-MM-DD] [--source-issue N --source-comment N]  # N positive
                  [--decided-by WHO] [--on-behalf-of WHO] [--single-option]
                  [--why REASON] [--supersedes ID] [--no-commit]
```

One command per steering act. The record's `id` is `<date>-<slug>`, its `by`
is `git config user.name` of the tree, and its `status` is **derived, never
supplied**: all questions answered is `decided`, any unanswered question is
`open`, and the target of a supersede becomes `superseded`. There is no
`--status` flag: the writer records what the operator decided and never
chooses an answer, so every question's text, options and answer come from
flags.

| code | meaning |
|---|---|
| `0` | the record was written (and committed unless `--no-commit`) |
| `2` | invalid input: an argparse failure, an empty or malformed `--slug`, a `--slug` that already starts with a date (the writer adds it), a malformed `--date`, a malformed `--question`/`--option`/`--answer`, a `--source-issue`/`--source-comment` that is not a positive integer, a question outside 1-4 or with outside 2-4 options, an empty or multi-line `--decided-by`/`--on-behalf-of`, `--on-behalf-of` without `--decided-by`, an empty, multi-line or over-long `--why`, a question with one option when `--single-option` was not given, or `--supersedes` with an unanswered question |
| `3` | git or identity: `--repo` is not a git work tree, `git config user.name` is not set (the hint names the command), a git probe timed out or failed for a reason that answered nothing, or a `noni/` or `noni/decisions/` that is not a directory this writer may read or write through (a symlink, a plain file, a socket or a device: every directory from the state root down to the ledger is asked of `lstat` before the git probes, the first read or the `mkdir`, so nothing is followed and nothing is written, and an absent ledger is admitted because the first record creates it; a `--repo` that is a directory holding no `noni/` is admitted on the same ground, because `decide` is the ledger's creator and its first record is what brings the tree into being — what makes such a run auditable rather than silent is that it is a real, reported commit that names the state root and the record it wrote, asked before the ledger is read) |
| `4` | a collision or a bad supersede target: the record path exists as anything (a file, a directory or a symlink), or the target is missing, already superseded, untracked, locally modified, not a regular file at its path (a symlink, directory or device), not readable at all, not in the writer's canonical form, or carries a field the census does not type as a string (`id`, `asked_by`, `by`, `scope`, `date`; `supersedes` as a string or null; `decided_by` and `on_behalf_of` as non-empty single-line strings when present), a `status` outside `decided`, `open` or `superseded`, `questions` that are not a non-empty list of objects each with a string `id` and a string-or-null `answer`, or a number JSON cannot hold. A `git show` reporting the path is not in HEAD is this code, not `3` |
| `5` | the commit failed: both paths are rolled back (index reset, target restored, new record removed), and anything the rollback could not do is named — a failed reset with the paths that may still be staged, or a path it could not restore |

Every refusal leaves the target and the ledger untouched: the writes happen
only after every check passes, each file goes to a temp file in its own
directory and is moved into place with `os.replace`, and a failed commit rolls
both paths back so `git status --porcelain` is empty for them again. The commit
stages exactly the paths the command wrote (`git add -- <paths>` then
`git commit --only -- <paths>`), so a file somebody else had staged is neither
committed nor unstaged. `--no-commit` writes through the same validation chain
and stops before git, printing one line that names the paths and says to commit
them before running the census. With `--supersedes` that same line also says the
target's status is now `superseded`: `--no-commit` writes **both** files, so an
operator who aborts the run has two paths to put right — delete the new record
and restore the target — or the chain is left with no live record and the
census reports it (exit 20, `zero-live`).

`--supersedes ID` writes the new record and flips the target's `status` to
`superseded` in **one** commit of exactly those two paths, with the message
`steering: supersede <target> with <id>`. It requires every question in the new
record to be answered (else exit 2), because an open supersede would leave the
chain with no live answer. The target is read from the working tree and must be
tracked, committed and byte-identical to `git show HEAD:<path>`, and in this
writer's own canonical form (its fields, their order and its indent): a target
the writer would render differently is refused with exit 4 rather than
rewritten, because the rewrite could then move bytes beyond the `status` value
that is the only field the writer touches.

## The record

One JSON file per record under `noni/decisions/`, named `<id>.json`. The eight
fields (in order), plus the optional fields (`source`, `decided_by`,
`on_behalf_of`, `single_option`, `why`):

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
| `decided_by` | string (optional) | who made the decision, when that is not the commit author: a login or pseudonym, never a personal-name requirement. Written by `--decided-by`; absent means the commit author decided, which is how every record written before this field stays valid. It never overrides `by` in the report (see Attribution) |
| `on_behalf_of` | string (optional) | the party a delegated decision was made for, written by `--on-behalf-of`, which the writer refuses without `--decided-by` |
| `single_option` | `true` (optional) | the marker `--single-option` writes to say a question was asked with one option on purpose, so nothing had to be invented. It is a per-record marker over a per-question bound: with it set, any question may carry one option, and at least one question of the record must. A one-option record without it is a schema violation, and a marker no question of the record carries one option is one too |
| `why` | string (optional) | the operator's one line of reason for the decision, written by `--why`: a non-empty single line of at most 280 characters, counted in code points. The bound is shared with an order entry's `why` and the item store's reason field, so one number holds the product's rationales. Absent means no reason was recorded, which keeps every record written before the field valid |

A `question` object is `{id, text, options, answer}`. `options` is an array of
2-4 strings, or exactly one string for a question of a record that carries
`single_option` (the marker is read per record and the bound is judged per
question, and at least one question of a marked record must hold one option).
`answer` is either the chosen option's string (or a free-text
escape string) and must name the question it answers by id pairing, or is
`null` when the question was left open. The full shape, validation rules, and
the declined/open state are in `references/decisions.md`.

The `answer` names its question by id: in multiple-choice mode each question
carries its own `id` and its own `answer`, so a three-question record is
unambiguous. A `many` or `stranger` tick-parse persists as `status: open` with
the question's `answer` `null` — never as an answer. A decline or cancel that
is recorded at all persists as `status: open` with every `answer` `null`, as an
open chain-root record; that is the only state "records nothing" can mean.

## Attribution

`by` is the **git author of the record's commit** — read with
`git log -1 --format=%an -- <record path>`, not from the file body. This is
forgeable locally; the default posture is signed commits, and stranger-detection
is advisory until forge-verified pushes. The census reports `by` from git so a
forged file body cannot claim a different author. The full attribution rule is
in `references/decisions.md`.

Because agents commit under the operator's identity, `by` alone cannot say who
*decided*. `--decided-by <who>` records that separately, and `--on-behalf-of
<who>` names the party a delegate acted for. Both are written next to `by`, never
in place of it: the report's `by` column keeps coming from git, and the census
checks only that each value is a non-empty single line — it never verifies an
identity. A record without `decided_by` still means the commit author decided.

`--why <reason>` records the operator's own line of reason beside the attribution.
It says nothing about who decided: it is the answer to why the decision went that way.
The same one-line rule and the same 280-character bound hold for an order entry's
reason. The writer refuses a blank, a multi-line or an over-long value at the flag
(exit 2) and the census reports a hand-edited one at exit 10 naming `why`; a record
with no `why` is not incomplete, it simply records no reason.

## Supersede

A correction writes a **new** file with `scripts/decide.py --supersedes ID`;
the superseded record's bytes stay unchanged apart from its `status`, and its
blob stays reachable in history. Never edit history. Each supersede
chain must resolve to exactly one live record, and a duplicate, dangling, or
cyclic supersedes is refused by the census. The protocol is in
`references/supersede.md`.

## Modes

The two steer modes, the multiple-choice bounds, the free-text escape hatch, and
the anti-fabrication rule (the agent never answers for the operator) are in
`references/modes.md`.

## Census

`scripts/census.sh <state-root>/noni/decisions` is read-only and exits with an
honest code. It is the ledger shim, not the enforcer and not a second arbiter:
it is a thin wrapper that runs `noni census` (the unified census,
`skills/census/scripts/census.py`) over the ledger group — `ledger-record`,
`ledger-edited` and `ledger-chain` — and returns the census's own exit code. It
has no schema, no jq and no exit-code table of its own; the census is the single
arbiter of every rule and `skills/census/SKILL.md` is the single exit-code
reference for it. It runs the ledger group and nothing else, so it reports no
`hygiene`, `ordering-*` or `intent` row — `noni census` is the whole picture. It is a
bash script: run it as `bash
scripts/census.sh <dir>` or, since it carries its executable bit and its bash
shebang, as `scripts/census.sh <dir>`. Why no interpreter may stand in front of
it is in `references/census.md`. Its one argument is the ledger directory of the
state root (`--repo` plus `noni/decisions`): there is no current-directory
default, so a run with no argument is the usage error `2`. Beyond the directory
it takes `--json`, `--strict` and `--now` (the `--now VALUE` and `--now=VALUE`
forms) and nothing else — `--strict` is the route that promotes the ledger
group's warn classes, `ledger-empty` among them. Every other option is refused
with `2` without running the census, so filters and anything else need
`noni census`.

A `decisions/` directory that holds no `*.json` record is not a failure: the
census reports it as the `ledger-empty` warn at exit 0 and promotes it to 42
under `--strict`, so a freshly attached tree censuses clean here exactly as it
does under `noni census`. That is the one answer the entry points were found to
disagree about, and it is settled by running the same census both ways.

When several invariant classes fail at once, the lowest code wins and stderr
names every class that fired; the rules and the codes are the census's, in
`skills/census/SKILL.md`. The census does not check operator confirmation: it
cannot see whether the operator confirmed an answer, so it never claims to
(below).

How to read the report — the rows the ledger group prints and what each check
reads — is in `references/census.md`.

The sessions register has its own entry point in its own skill,
`skills/sessions-claims/scripts/census-sessions.sh`; it is the same kind of
wrapper over the same census, and this script no longer dispatches to it. A
command line that still types the retired form (`census.sh --sessions DIR`) is
refused with this script's own usage code, naming the option and pointing at the
entry point that runs the register.

## Rules

- **Never answer for the operator.** This is a protocol rule agents follow, not
  something the census enforces: git cannot distinguish an operator answer from
  an agent-written one (agents commit under the operator's identity), so the
  census does not check confirmation and does not claim to. Signed operator
  confirmation, where git can see it, is a follow-up.
- **The answer is confirmed, not written.** A record with an `answer` is a
  confirmed record; an unconfirmed candidate commits nothing. A declined steer
  that is recorded at all is an open chain-root record with every `answer`
  `null` — never a supersede.
- **One file per record; the directory is the aggregate.** The census tolerates a
  half-written or malformed record without blinding itself to the rest.
- **Supersede, never edit.** A corrected record is a new file; the old one stays
  byte-for-byte as committed.
- **No project content in the skill.** Core skills carry neither project
  content nor driver-tool vocabulary; integrations are clearly-marked adapters.
  The purity rule is itself a test.
