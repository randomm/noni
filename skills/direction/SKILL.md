---
name: direction
description: Set and correct the order the operator wants issues worked next -- one committed artifact, noni/direction/order.json, written only by scripts/order.py (add, move, remove, confirm). Use when the operator says what to work on first, when a release train reorders the queue, when an ordered issue needs re-confirming, or when the census reported an ordering-malformed / ordering-stale / ordering-closed row and the artifact must be repaired with its writer. Do NOT use for the steering ledger (that is the steering-ledger skill), for the session register (sessions-claims), or for reading the state (the census skill is the arbiter) -- this skill owns only the ordered list and the one writer that produces it.
---

# direction

**Mission:** the direction layer holds one ordered list of the issues the
operator wants worked next, as one committed file. Position in the list *is*
the order, an issue appears at most once, and every entry carries the time the
operator last confirmed it. The writer is the only writer, so the file has one
owner and a correction of the order is simply another run of the command.

## The honesty line

The order is a signal, not a lock. Writing it says what the operator wants
worked next; it blocks nobody, and nothing in the core reads it to decide
whether work may start. The census is the arbiter of its shape: `order.py`
refuses what the census would report, and the census reports what the writer
would have refused, so the artifact and the arbiter cannot drift apart.

The writer never contacts a tracker. An issue number is checked only for being
a positive integer, so the core stays viable with no adapter installed, and
whether an issue is still open is a question the census answers from an
`--issue-state` file somebody else produced.

## The artifact

One file, one schema, one writer:

```
noni/direction/order.json
```

| field | meaning |
|---|---|
| `schema` | `noni.order/1`, the artifact's version marker |
| `entries` | `[{issue, decision, confirmed}]` in the order the operator wants |

Position is the list index, not a field -- so a reorder moves entries and never
renumbers anything. `issue` is a positive integer. `decision` is the id of the
steering-ledger record that set the entry's position, or `null`. `confirmed` is
the UTC timestamp the writer stamped when the operator last confirmed the entry.

The file is written in one canonical form: keys in the order above, two-space
indent, one trailing newline. A file that is not in that form is refused, never
quietly reformatted -- an order the operator committed is not this run's to
rewrite.

An absent file is not an error. Nothing ordered yet is a state, and the first
`add` creates the file.

## Writing the order

```
scripts/order.py --repo REPO add ISSUE --decision ID [--at N] [--now ISO-8601] [--no-commit]
scripts/order.py --repo REPO move ISSUE --to N [--now ISO-8601] [--no-commit]
scripts/order.py --repo REPO remove ISSUE [--now ISO-8601] [--no-commit]
scripts/order.py --repo REPO confirm [ISSUE] [--now ISO-8601] [--no-commit]
```

Every run prints the resulting order, one line per entry: the 1-based position,
the issue, and the decision (or `-`) and confirmed timestamp it carries.

`add` requires `--decision`: a position someone placed is a decision, and the id
it names must be a file under `noni/decisions/` that is not superseded. `--at N`
inserts at the 1-based position `N` of the list this run produces (the new
length), and appends at the end when omitted. `move` requires `--to N` and
restamps the moved entry, because a reorder is the operator confirming it again.
`confirm` with an issue restamps that entry; without one it restamps every
entry, which is how "the whole queue still stands" is said. `remove` is the only
verb that shortens the list.

`--now` stamps the entry with the timestamp given instead of the clock, which is
what makes a run -- and the census run that judges its staleness -- reproducible
from the command line alone. A `--now` with no UTC offset is refused.

`--no-commit` writes through the same validation chain and stops before git: no
`git add`, no `git commit`, and one line on stdout saying the file is left
uncommitted. The census reads the working tree, so an uncommitted order reads as
far as the next census run in that same working copy and no further. Committing
it is the caller's obligation.

The commit stages only the path this command wrote (`git add -- <path>`, then
`git commit --only -- <path>`), so a file somebody else had staged is neither
committed nor unstaged. A run that changes no byte -- confirming an entry already
stamped at the time it was given -- prints the order it read, says the file is
unchanged, and commits nothing.

## The exit codes

| code | meaning |
|---|---|
| `0` | the order was written (and committed unless `--no-commit`), or no byte of it needed changing |
| `2` | invalid input: an argparse failure, a subcommand outside `add`/`move`/`remove`/`confirm`, an issue that is not a positive integer, a missing `--decision` on `add`, a `--to`/`--at` that is not a 1-based position of the resulting list, a flag passed to the verb that does not own it, or a `--now` that is not a valid UTC timestamp |
| `3` | a path this writer needs could not be read or written, or a git call failed or timed out: the order file is not a regular file at its path, a decision record it must read is unreadable, the artifact could not be written, or the commit step failed (the file is left written and named, never claimed as committed) |
| `4` | what the order itself refuses: the issue is already listed (`add`), absent from the order (`move`, `remove`, `confirm`), no file under `noni/decisions/` carries the given `--decision` id, that record is superseded (the hint names its successor), or the existing file is not the artifact this writer writes |

Every refusal (2, 3 or 4) leaves the artifact untouched: reads and checks happen
before any write, the write goes to a temp file in its own directory and moves
into place with `os.replace`, so a crash mid-write leaves the old bytes and
never a truncated order.

## Repairing what the census reports

| census row | what to do with this skill |
|---|---|
| `ordering-malformed` (15) | the file is not the artifact: unparseable, a number that is not finite, wrong `schema`, a duplicate or non-positive `issue`, a `confirmed` that is not a UTC timestamp, a blank or absent `decision` where an id or null is required, a `decision` matching no record, or an `--issue-state` file that does not parse. The writer refuses to overwrite such a file (exit 4): repair it to the documented shape and commit it in the canonical form, or remove it and rebuild the queue with `order.py add` |
| `ordering-stale` (45) | an entry nobody confirmed within the threshold. `confirm` it if the position still stands, `remove` it if it does not |
| `ordering-closed` (46) | the issue is closed in the `--issue-state` map, so it is not work to do next: `remove` it. A `cannot-tell` row of the same class says the map does not mention the issue -- the fix belongs to whoever produced the map, not to this file |

## The edge cases that matter

- **A `decision` id is identified by its filename stem.** `add --decision ID`
  looks for `noni/decisions/<ID>.json`, the path `decide.py` names its records
  by. A ledger that is not there at all is the same answer as no file with that
  name: the id matches no record. A record whose body disagrees with its own
  name is the census's `ledger-record` / `ledger-chain` problem, not this
  writer's.
- **A superseded record cannot set a position.** The refusal names the record
  that superseded it and shows the flag to pass. A chain that moved on again is
  superseded by the newest of its links.
- **An unreadable record is exit 3, not exit 4.** "I could not read it" and "it
  is not there" are different answers, and the caller fixes them differently.
- **A non-regular path is refused, never followed.** A symlink, a directory or a
  device at the artifact path is exit 3 with the reason; this writer does not
  read through links or replace them with an order file.
- **`NaN`, `Infinity` and an overflowing literal are not JSON here.** The reader
  refuses the three bare tokens, and a number that overflows to infinity (json
  reads `1e400` into `inf` with no token to stop it) is refused too: a value no
  writer can name is not a value an order can carry. The census applies the same
  two refusals to what it reads, so a file the writer will not write is never a
  file the census calls clean.
- **The census accepts nothing the writer would refuse.** Its rules are the
  writer's, applied to the bytes on disk: a blank `decision` is malformed there
  too, not just here, even though a blank string is a string. Repair the file to
  what this writer emits, not merely to something that parses -- a hand-repaired
  file the census accepts and the writer still refuses can never be corrected
  with `order.py`, because every verb refuses to open it.
- **The writer is not the arbiter.** It validates what it writes; it does not
  decide whether the ledger, the session register or the order are sound. Run
  the census for that.
