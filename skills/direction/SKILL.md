---
name: direction
description: Set and correct the order the operator wants issues worked next -- one committed artifact, noni/direction/order.json, written only by scripts/order.py (add, move, remove, confirm) -- and keep the standing intent the agents read first at session start, noni/direction/intent.md, written only by scripts/intent.py (set). Use when the operator says what to work on first, when a release train reorders the queue, when an ordered issue needs re-confirming, when the project's purpose or principles must be recorded or corrected, or when the census reported an ordering-malformed / ordering-stale / ordering-closed / intent row and the artifact must be repaired with its writer. Do NOT use for the steering ledger (that is the steering-ledger skill), for the session register (sessions-claims), or for reading the state (the census skill is the arbiter) -- this skill owns the ordered list, the standing intent, and the two writers that produce them.
---

# direction

**Mission:** the direction layer holds two committed files: one ordered list of
the issues the operator wants worked next, and one small statement of what the
project is for and what it will not do. Position in the list *is* the order, an
issue appears at most once, and every entry carries the time the operator last
confirmed it. The intent file is the first thing a session reads. Each file has
one writer, so a correction is simply another run of the command.

## The two files, and which question each answers

| file | what it holds | who writes it | who reads it |
|---|---|---|---|
| `noni/direction/intent.md` | purpose, principles, never-do, ask-first | `scripts/intent.py` | every session, first |
| `noni/direction/order.json` | the issues to work next, in order | `scripts/order.py` | whoever plans next |

Both are optional and both resolve from `--repo`, the one flag that names the
state root. This skill owns both files and both writers, and nothing else.

## The precedence rule

When a question comes up, its answer comes from exactly one of three places, in
this order:

1. **The most recent applicable ledger decision wins.** Look in
   `noni/decisions/` for a record that speaks to this question; the newest live
   one (the end of its supersede chain) is the answer, even where the intent file
   says otherwise. An operator who overrode a principle made a dated record of
   it, and that record is the current word.
2. **Otherwise `noni/direction/intent.md`.** Its four sections settle what the
   project is for, how a close call goes, what is prohibited, and what must be
   asked.
3. **If neither settles it, wait and ask.** Do not guess, do not infer the
   operator's preference from nearby code, and do not record your own answer as a
   decision to make the question go away.

Items listed under `## Ask first` are **never** decided autonomously, whatever
the other two files appear to imply: the agent stops, states what it found and
what it would do, and waits for the operator.

**The per-session protocol.** At session start, read `noni/direction/intent.md`
first when it is present -- before registering a session and before claiming a
task. A project that has written none has no intent file and nothing to read:
absence is a state, not a failure, and the census says nothing about it.

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

## The standing intent

One file, one writer, four sections:

```
noni/direction/intent.md
```

| section | what belongs there |
|---|---|
| `## Purpose` | what the project exists to be, and for whom -- the reason the queue exists |
| `## Principles` | the rules that decide a close call, written so two readers apply them alike |
| `## Never` | prohibitions an agent can be held to, each one checkable |
| `## Ask first` | the questions an agent must stop and ask about, never decide |

The rules the writer enforces and the census reports as the `intent` class:
the four level-2 headings, in that order, each exactly once; exactly one
`Last-confirmed: YYYY-MM-DD` line; at most 200 lines; and no code fence left
unclosed. A heading inside a fenced code block is not a heading, so a worked
example inside a section is safe, as long as the block is closed again.

An absent file is not an error, and the census adds no row for it: standing
intent is optional, and a project that has never written one censuses clean.

A template ships at `references/intent-template.md`. Copy it, fill the four
sections, and hand the draft to the writer -- the template itself validates, so
a project can install it as-is and edit it afterwards.

## Writing the intent

```
scripts/intent.py --repo REPO set --from FILE --decision ID [--no-commit]
```

`--from` names the Markdown file holding the draft; `--decision` names the
steering-ledger record that set this direction, and the run is refused unless a
file under `noni/decisions/` carries that id and its status is not
`superseded`. Standing direction always traces to a record the ledger holds,
which is what makes the precedence rule above answerable.

The writer restamps the `Last-confirmed:` line to this run's UTC day (the day
the operator set the intent is the writer's to record, not the draft's to
claim), writes the file through a temp file and `os.replace`, and commits it
alone with the subject `intent: <decision-id>` (`git add -- <path>`, then
`git commit --only -- <path>`, so a file somebody else had staged is neither
committed nor unstaged). A run that changes no byte says the file is unchanged
and commits nothing. `--no-commit` writes through the same validation chain and
stops before git, with one line saying the file is left uncommitted and naming it
by the same path the committed route names.

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
steering-ledger record that set the entry's position, and it is never empty: an
entry whose `decision` is `null`, blank or absent is not an order this writer
writes (exit 4, naming the entry) and the census reports it as
`ordering-malformed` (15) -- a position nobody can look up is a position nobody
decided. `confirmed` is the UTC timestamp the writer stamped when the operator
last confirmed the entry.

The file is written in one canonical form: keys in the order above, two-space
indent, one trailing newline. A file that is not in that form is refused, never
quietly reformatted -- an order the operator committed is not this run's to
rewrite.

An absent file is not an error. Nothing ordered yet is a state, and the first
`add` creates the file.

The path is resolved from `--repo` — the one flag that names the state root: the
attached project's own repository by default, or a separate directory carrying
the same `noni/` layout when a team keeps its direction in a private state
repository. The script's own location never decides where the artifact is read
from or written to, and a `--repo` naming no directory is refused before
anything is written.

## Writing the order

The verb comes first, after `--repo`: what you are doing to the order, then the
issue, then the flags that qualify it. `order.py --help` prints the same order.

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

**The path every line names.** The `wrote`, `committed` and `left uncommitted`
lines of both writers name the artifact's real location from the directory the
command ran in: `--repo` joined to `noni/direction/order.json` (or
`noni/direction/intent.md`). On Route B that is `.noni-state/noni/direction/order.json`,
and it is spelled identically with and without `--no-commit`, so a private state
repository never reads as a stray `noni/` beside the project.

The commit stages only the path this command wrote (`git add -- <path>`, then
`git commit --only -- <path>`), so a file somebody else had staged is neither
committed nor unstaged. A run that changes no byte -- confirming an entry already
stamped at the time it was given -- prints the order it read, says the file is
unchanged, and commits nothing.

## The exit codes

| code | meaning |
|---|---|
| `0` | the order was written (and committed unless `--no-commit`), or no byte of it needed changing |
| `2` | invalid input: an argparse failure, a subcommand outside `add`/`move`/`remove`/`confirm`, an issue that is not a positive integer, a missing `--decision` on `add`, a `--to`/`--at` that is not a 1-based position of the resulting list, a flag passed to the verb that does not own it, a `--now` that is not a valid UTC timestamp, a `--repo` that is not a directory, or a `noni/`, `noni/direction/` or `noni/decisions/` that is not a directory this writer may read or write through (a symlink, a plain file, a socket or a device: every directory from the state root down to it is asked of `lstat` before any read, write or `mkdir`, so nothing is followed and nothing is written, and an absent directory is admitted because the first `add` creates it) |
| `3` | a path this writer needs could not be read or written, or a git call failed or timed out: the order file is not a regular file at its path, a decision record it must read is unreadable, the artifact could not be written, or the commit step failed (the file is left written and named, never claimed as committed) |
| `4` | what the order itself refuses: the issue is already listed (`add`), absent from the order (`move`, `remove`, `confirm`), no file under `noni/decisions/` carries the given `--decision` id, that record is superseded (the hint names its successor), or the existing file is not the artifact this writer writes |

`intent.py` publishes the same four codes for its one verb: `2` for an argparse
failure, a subcommand outside `set`, a missing `--from` or `--decision`, a
`--from` that is not a readable regular file or is not UTF-8, a `--repo` that
is not a directory, or a `noni/`, `noni/direction/` or `noni/decisions/` that
is not a directory this writer may read or write through (the same `lstat`
guard the order writer runs, refused before any read, write or `mkdir`, an
absent directory admitted because the first `set` creates it); `3` for an
unreadable or unwritable path or a git call that
failed or timed out; `4` for a draft that is not an intent file (a section
missing, repeated or out of order, the stamp line absent or repeated, the file
past the line cap) or a `--decision` the ledger does not hold or has superseded.

Every refusal (2, 3 or 4) leaves the tracked files byte-identical: reads and
checks happen before any write, the write goes to a temp file in its own
directory and moves into place with `os.replace`, so a crash mid-write leaves
the old bytes and never a truncated file.

## Repairing what the census reports

| census row | what to do with this skill |
|---|---|
| `ordering-malformed` (15) | the file is not the artifact: unparseable, a number that is not finite, a key stated twice, wrong `schema`, a duplicate or non-positive `issue`, a `confirmed` that is not a UTC timestamp (including one with no offset), a `decision` that is blank, `null`, absent, or not a string, a `decision` matching no record, an `--issue-state` file that does not parse or whose keys are not plain issue numbers, or a decision ledger whose listing faulted. The writer refuses to overwrite such a file (exit 4): repair it to the documented shape and commit it in the canonical form, or remove it and rebuild the queue with `order.py add` |
| `ordering-stale` (45) | an entry nobody confirmed within the threshold. `confirm` it if the position still stands, `remove` it if it does not |
| `ordering-closed` (46) | the issue is closed in the `--issue-state` map, so it is not work to do next: `remove` it. A `cannot-tell` row of the same class says the map does not mention the issue -- the fix belongs to whoever produced the map, not to this file |
| `intent` (51), subject `section-missing` | the file is missing a heading, repeats one, has the four out of order, its `Last-confirmed:` line is absent or repeated, or a code fence was left unclosed. Edit the draft and re-run `intent.py set`, which refuses a draft it would not have written |
| `intent` (51), subject `over-cap` | the file is past 200 lines. Move the material that belongs in a dated call into a ledger record and re-run `intent.py set` |
| `intent` (51), subject `uncited` | the last commit that touched the file is not an `intent: <decision-id>` commit naming a record the ledger holds, so the intent rests on nothing. Re-run `intent.py set --decision ID` with a live record's id rather than editing the commit by hand |
| `intent` (51), subject `cannot-tell` | the file could not be read (a symlink, a device, unreadable bytes), the decision record it cites is not an ordinary file (a symlink, dangling or not, a directory, a device), the ledger directory or the directory above it is a symlink, or no commit touching the file was found, so nothing was checked. Fix the path, restore the record, or commit the file; the row is a warn and never a silent clean. The census classifies the cited record before opening it and opens it with `O_NOFOLLOW`, so a link is refused rather than followed and no verdict comes from bytes outside the repo. A hardlink is the limit of that: `lstat` cannot tell one from an ordinary file, so a record hardlinked to an outside file still yields an `uncited` verdict, reported beside the `ledger-edited` failure that compares the working tree to the committed blob |

## The intent edge cases that matter

- **A section heading inside a code fence is not a section.** `## Never` written
  as an example inside a fenced block does not count as the `Never` section and
  does not make the file a repeat of it. Both readers track the fences.
- **A code fence that never closes is refused.** An unclosed opener puts every
  line after it inside the block, which hides them from the section and stamp
  rules at once, so a file whose fences do not balance is refused (exit 4) and
  reported `section-missing` rather than read as well-shaped. Balanced fences are
  always fine, however many there are.
- **A `Last-confirmed:` line indented, or inside a code fence, is not the stamp
  line.** The line must start at column 0 with no leading space, and the writer
  restamps only a line it recognised as the stamp, so a draft that hides it in a
  block is refused rather than silently given a second line.
- **The stamp is the writer's.** Whatever date the draft carries, the run stamps
  today's UTC day, because the confirmation being recorded is this run's. A
  project that wants a dated confirmation of its own writes a ledger record.
- **A symlink or a directory at the intent path is refused, never followed** --
  exit 3 for the writer, a `cannot-tell` row for the census. A path that is not
  an ordinary file has no sections to check and no citation to read, and calling
  it clean would be the worst possible answer. The same holds for the record a
  citation names, and for the ledger directory holding it: a symlink, a dangling
  link, a directory or a device at `noni/decisions/<id>.json` is a `cannot-tell`
  row, never an `uncited` verdict built from whatever the link points at. The
  refusal is at the open (`O_NOFOLLOW` plus a check of the descriptor), so a link
  cannot be swapped in between the classification and the read.
- **A commit that touched the file without naming a live record is `uncited`,
  not `cannot-tell`.** The history answered; the answer was the wrong subject.
  Only a history that could not be read at all, or a file that could not be
  read, is a `cannot-tell`.
- **The two writers share nothing but their shape.** `order.py` stamps
  timestamps and `intent.py` stamps a date; `order.py` refuses a duplicate
  issue and `intent.py` refuses a duplicate section. Nothing is factored between
  them, so neither file's rules leak into the other.
- **The writers are not the arbiters.** They validate what they write; they do
  not decide whether the ledger, the session register, the order or the intent
  are sound. Run the census for that.

## The order edge cases that matter

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
  refusals to what it reads, so a file the writer will not write is never a
  file the census calls clean.
- **A key stated twice is not a document.** json keeps the last of a repeated key
  and drops the rest, which invents a file: an entry that writes `"decision":
  "a", "decision": null` does not cite nothing. Both readers refuse the document
  outright -- the writer as a refusal, the census as one whole-artifact
  `ordering-malformed` row -- rather than answering it twice over.
- **A `confirmed` with no UTC offset is not a timestamp.** `2026-10-26T00:00:00`
  names no instant, so the writer refuses it and the census reports it malformed
  too, instead of reading it as UTC and judging staleness against a minute nobody
  chose.
- **The census accepts nothing the writer would refuse.** Its rules are the
  writer's, applied to the bytes on disk: a blank `decision` is malformed there
  too, not just here, even though a blank string is a string, and so is a
  `decision` of `null` -- every entry cites the record that set its position, so
  an entry that cites nothing is an ordering nobody can replay. Repair the file
  to what this writer emits, not merely to something that parses -- a
  hand-repaired file the census accepts and the writer still refuses can never
  be corrected with `order.py`, because every verb refuses to open it.
- **The writer is not the arbiter.** It validates what it writes; it does not
  decide whether the ledger, the session register or the order are sound. Run
  the census for that.
