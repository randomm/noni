---
name: sessions-claims
description: Register agent sessions as one committed file each under noni/sessions/, claim tasks by commit, and detect double-claims via the sessions census (exit 30/31/32). Use when an agent session starts work in a git project, when a session needs to signal ownership of a task, or when the operator or a later session needs to know whether a task has two active claimants. Do NOT use for task tracking, CI, or the steering ledger — this skill owns only the session register, the claim protocol, and the sessions census that holds the invariants.
---

# sessions-claims

**Mission:** concurrent agent sessions on one project register themselves as
one committed file each, and signal ownership of tasks by commit. Claims are
signals, not locks: git delays the second claimant, it does not lock them out.
The census double-claim check is the deterministic arbiter.

## The honesty line

Claims are signals, not locks. A claim is a committed record referencing the
task, written to the session's own file so merges never fight over one blob.
Git's push-rejection acts as a compare-and-swap: the second claimant's push is
delayed until it fetches and rebases, but it is not blocked — after the
fetch-rebase-push protocol (at most 3 attempts) both claims land in git. The
**census double-claim check is the deterministic arbiter**: it reads the
session files in the working tree at read time and flags two active claims on
the same task from different identities (exit 30). "No-steal" is an aspiration,
not a promise.

## The session register

One Markdown file per session under `noni/sessions/`, named
`<session-id>.md`. The session-id is random per working copy
(`YYYY-MM-DD-<6 hex>`), allocated once at registration. Ids are collision-free
by construction, so each file has exactly one writer.

Each register file records five fields:

| field | permanent/ephemeral | meaning |
|---|---|---|
| `identity` | permanent | stable role name (e.g. `developer`, `reviewer`) |
| `host/worktree` | ephemeral | host name and worktree path of this working copy (defaults never include an absolute path or hostname) |
| `started` | ephemeral | UTC ISO-8601 timestamp of registration |
| `status` | permanent | `active`, or a terminal state — the four under **status** in `references/register.md` — see `close.py` |
| `claims` | ephemeral | list of `- claim: <task>` rows |

The identity is permanent: it survives across commits, pulls, and clones. The
host/worktree, started, and claims are ephemeral: they describe this working
copy and this session's current work.

Every `noni/` path the four writers and the sessions census take is resolved
from `--repo` — the one flag that names the state root: the attached project's
own repository by default, or a separate directory carrying the same `noni/`
layout when a team keeps its direction in a private state repository. No tool
reads or writes state relative to its own location or the current directory
beyond `--repo`'s default, and a `--repo` naming no directory is refused before
anything is written.

**The path every line names.** Each writer's success line and its
`left uncommitted` line name the session file the same way: `--repo` joined to
`noni/sessions/<session-id>.md`, which is the file's real location as seen from
the directory you ran the command in. Pass `--repo .noni-state` and both lines
say `.noni-state/noni/sessions/<session-id>.md`, never the state-root-relative
tail alone and never a machine-local absolute path — so a private state
repository cannot be read as a stray `noni/` that appeared beside the project.

Read `references/register.md` before writing a register file. Read
`references/claim.md` before making a claim or releasing one. Read
`references/census.md` before reporting on the session state.

## Registering a session

```
scripts/register.py --repo REPO --identity IDENTITY [--status STATUS]
                    [--host HOST] [--worktree WORKTREE] [--file PATH]
                    [--no-commit] [--push]
```

The register writer allocates a session-id, creates the file at
`noni/sessions/<session-id>.md`, commits that one file, and refuses to write any
other path (exit 2): `--file` is admitted only for this run's allocation, or for
the marked name on the route that reuses it. It marks the working copy with the id
it allocated, under that tree's own `.git/`, and the next run in the same working
copy reads that marker:

| the marked session | what the next register does |
|---|---|
| active, same identity | continues it: exit 0, nothing written, no commit (`<id>.md already registered (identity=X)`) |
| active, different identity | refused: exit 1, both identities named, the other session's bytes untouched |
| terminal (`closed`, `done`, `superseded`, `ended`), or its file gone | allocates a new session and re-marks the working copy for it |
| a `- status:` line with no readable value | refused: exit 2, the file and the marker named, nothing written |
A marker this run cannot read is no evidence of a session, and a marker whose
text is not a session id counts as no marker at all: the run says so on stderr,
allocates afresh, and never builds a path from marker text. A marked file it
cannot read is a refusal (exit 2) rather than an overwrite: the writer never
replaces bytes it has not seen. `--no-commit` opts out of both the commit and
the marker, which is how a caller that plants more than one session file in one
working copy (or commits them itself) asks for a fresh allocation.

The `--host` and `--worktree` defaults never publish machine-local values:
`--host` defaults to the allocated session-id and `--worktree` to the repo
directory's basename. Neither default includes an absolute path or a
hostname, because the register file is committed to a public repo. Explicit
`--host` / `--worktree` values are written as given.

Exit codes: `0` registered, or the marked active session continued; `1` the
marked file belongs to another identity; `2` a path this run did not allocate, or
a marked file that cannot be read or carries no readable `- status:` value, or
`--repo` naming no directory or being a symlink (refused, never followed), or the
session file this run would write, or any directory from the state root down to it
(its `noni/sessions/` directory and the `noni/` above it), not being a plain path
this writer may follow (a symlink is never followed, and nothing is
created before the refusal); `3` git
could not commit; `4` a `--identity`/`--status` that is not one token, the
session name this run allocated is not one file under `noni/sessions/` (a name
the writer derived itself, so the hint names `--identity` and does not blame
`--repo` or a symlink), or `--no-commit` with `--push`.

A commit that git refuses (exit 3) is the same shape for all four writers: the
file stays on disk with the bytes this run wrote, the one line on stderr names
the cause in noni's words and quotes git after it, and the writer's headline
names the path it left uncommitted. The four causes are written out once, under
"Committing a session file" in `references/register.md`; nothing here restates
them. `register.py` adds one promise the other three do not: it puts the
working-copy marker back to the bytes it held before this run, including no
marker at all when this run created one, so a working copy is never left marked
for a session git never received.

## Releasing a claim

```
scripts/release.py --repo REPO --session-id SID --task TASK [--no-commit] [--push]
```

Removes exactly one `- claim: <task>` row from the session's own file and
commits that file. The row is matched on the stripped line, so an indented row
under `- claims:` and a bare row at EOF (where `claim.py` appends) are both
released. When the session holds no such row, or holds two identical ones, the
run is refused (exit 2) rather than guessing: two identical rows mean the file
was edited outside the writers, and removing one would report a release the
census does not agree with. The register file itself is never deleted.

Releasing is not a lock either: the row is a record this session wrote, and
removing it is what makes the census's double-claim report for that task go
away.

A refusal (exit 1, 2 or 4) writes nothing: the register file keeps the bytes it
had and `git status --porcelain` stays empty for it. A commit git refuses (exit
3) leaves the row removed in the work tree, with the cause named in noni's words
and the path named as written but uncommitted (see "Commit refused by git"
under "Committing a session file" in `references/register.md`).

Exit codes: `0` the row is gone and committed (and pushed with `--push`, or
left uncommitted with `--no-commit`); `1` no such session file; `2` the session
does not hold the task, or the file is unreadable or carries no `- claims:`
marker, or `--repo` names no directory or is a symlink (refused, never
followed), or the session file, or any directory from the state root down to it
(its `noni/sessions/` directory and the `noni/` above it), is not a plain path
this writer may follow (a symlink is never followed, and nothing is written
before the refusal); `3` git could not commit; `4` a `--task`/`--session-id` that is not one
token with no leading dot (the id is also the name of one file under
`noni/sessions/`), or `--no-commit`
with `--push`; `5` the `--push` rebase started and stopped on a session-file
conflict (this run aborts it); `6` the rebase never started (the hint names
committing or stashing) or its state could not be read. `5` and `6` are
`claim.py`'s codes, and mean the same thing here.

## Closing a session

```
scripts/close.py --repo REPO --session-id SID [--no-commit] [--push]
```

Sets the session's own `- status:` line to `closed` and commits that one file.
This is how a session stops counting toward the double-claim check. The file is
never deleted — it is the session's record, and the census reads history for
its deleted-file check — and no line but the status line moves.

Closing is idempotent: a session already in a terminal state needs no commit,
so a second close exits 0, moves no HEAD, and says the session `was already
closed (status=X)`. That no-op is not a refusal: it writes nothing, exits 0, and
leaves the tree byte-identical.

A refusal (exit 1, 2 or 4) writes nothing. A commit git refuses (exit 3) leaves
the status line written in the work tree, with the cause named in noni's words
and the path named as written but uncommitted (see "Commit refused by git"
under "Committing a session file" in `references/register.md`).

Exit codes: `0` closed and committed (and pushed with `--push`, or left
uncommitted with `--no-commit`), or already closed; `1` no such session file;
`2` the file is unreadable or carries no `- status:` line, or `--repo` names no
directory or is a symlink (refused, never followed), or the session file, or any
directory from the state root down to it (its `noni/sessions/` directory and the
`noni/` above it), is not a plain path this writer may follow (a symlink
is never followed, and nothing is written before the refusal); `3` git could not commit, or
`--push` failed; `4` a `--session-id`
that is not one token with no leading dot (the id is also the name of one file
under `noni/sessions/`), or `--no-commit` with `--push`; `5` the `--push` rebase
started and stopped on a session-file conflict (this run aborts it); `6` the
rebase never started (the hint names committing or stashing) or its state could
not be read. `5` and `6` are `claim.py`'s codes, and mean the same thing here.

`--no-commit` on the three writers above (and on `claim.py`) writes through the
same validation chain, runs no git at all, and prints `<tool>.py: <path> left
uncommitted`. Committing the change is then the caller's obligation: the census
reads the working tree, so an uncommitted change is visible in that clone and
invisible to every other one.

## Claiming a task

```
scripts/claim.py --repo REPO --session-id SID --task TASK [--branch BRANCH]
                 [--push] [--no-commit]
```

The claim writer appends a `- claim: <task>` row to the session's register
file, commits it, and (with `--push`) pushes with fetch-rebase-push (at most
3 attempts). The task reference is the issue number (e.g. `#42`) or a noni row
id. A claim row without a task reference is malformed (the census flags it,
exit 32).

A session whose own `- status:` is terminal cannot claim a new task: the run is
refused with exit 2, the status is named, and nothing is written. The four
terminal statuses are the ones listed under "The field semantics" in
`references/register.md`
and the same set the census treats as inactive. The refusal is a write-time check
on the file this run was pointed at — claim rows an earlier session left in a
file that has since gone terminal are left untouched and are not a new
reportable state; the census keeps ignoring terminal sessions, exactly as it did
before.

`--no-commit` appends the row through the same validation chain and stops
before git: no `git add`, no `git commit`, and one line on stdout saying the
change is left uncommitted for the caller to commit. The census reads the
session files in the working tree, so a row left uncommitted is visible to a
census run in that same working copy, but invisible to every other clone until
it is committed and pushed. Committing it is the caller's obligation.
`--branch` is
validated under `--no-commit` and otherwise ignored, and when it was given the
success line says plainly that it had no effect (`--branch <X> was validated
but nothing was committed or pushed`) so it cannot be mistaken for a targeted
write;
`--no-commit` with `--push` is refused as a usage error (exit 4) before anything
is written.

A claim command aborts a rebase it started and never aborts one it cannot see
is stopped. Exit codes (the full table, with the abort post-condition, is in
`references/claim.md`):

| code | meaning |
|---|---|
| `0` | claim committed (and pushed, with `--push`), or appended and left uncommitted with `--no-commit` |
| `1` | the register file for `--session-id` does not exist (register first) |
| `2` | the session file is malformed (no `- claims:` marker, not readable as UTF-8), the session already claims the same task, or the session's status is terminal; see the paragraph above for what each refusal writes |
| `3` | push failed after 3 fetch-rebase-push attempts; also a failed fetch, a detached HEAD, an unresolvable branch, a git call that timed out, or a `git add`/`git commit` that git refused |
| `4` | usage error: bad `--task`, `--session-id` or `--branch` value (`--session-id` must name one file under `noni/sessions/`, so whitespace, a path separator, a `..` walk out of the state root or a leading dot is refused), `--no-commit` with `--push`, a `--repo` that is not a directory, or a `--repo` that is a symlink (refused, never followed — the message names the real path) |
| `5` | rebase conflict: the rebase started and stopped; the script aborts it, which leaves the clone on the branch it was invoked on at the claim commit it made (if the abort itself fails, the message says the clone needs manual cleanup) |
| `6` | rebase refused: the rebase never started (the hint names committing or stashing), or its state could not be read (no abort run, and the message says so) |

Read `references/claim.md` for the push protocol, the exit-5 abort
post-condition and its one exception.

## The sessions census

```
bash scripts/census-sessions.sh <state-root>/noni/sessions

# equivalent entry point (the steering-ledger census dispatches here)
bash scripts/census.sh --sessions <state-root>/noni/sessions
```

Both are bash wrappers, so `bash <path>` always runs them whatever the file mode
a checkout landed at; the direct form works where the executable bit is set.
Neither runs under `python3`: the interpreter they need is the one they exec
themselves, and `references/census.md` is the page that states that rule.

The one argument is the sessions directory of the state root (`--repo` plus
`noni/sessions`); there is no current-directory default, so a run with no
argument is the usage error `2`, and a second directory is that error too — one
run audits one register.

Read-only, NDJSON on stdout, honest exit code:

| code | meaning |
|---|---|
| `0` | clean — every session file valid, no double-claims |
| `2` | usage: no sessions directory was given, more than one was given, or the one given is not a directory |
| `3` | the interpreter the wrapper runs is not found on the reading machine |
| `30` | double-claim: two active claims on the same task from different identities |
| `31` | a claim row was committed without a register file (work is not blocked — report only) |
| `32` | a session file is malformed (missing required field, or a claim row with no task reference) |

The wrapper runs the interpreter named by `NONI_PYTHON` when that variable is
set, and `python3` otherwise. `references/census.md` states the same rule for
the exit-3 row, which is the one a reader misreads as a hint to run the wrapper
under `python3`.

When several classes fire at once, the lowest code wins (`30 < 31 < 32`);
every check runs in a single pass and all findings are always in the NDJSON
output (the priority only selects the returned code). Each non-zero exit
prints NDJSON rows naming the offending task or file.

The census is the deterministic arbiter. It does not block the session's work:
an unregistered claim (exit 31) is reported, not refused — there is no
pre-commit or pre-push hook, no write-path refusal.

Beyond this table, the unified census warns (43) when two or more non-terminal
session files share one `identity`, and (44) when a committed session file is
deleted from the working tree; both are warn by default and fail at their own
code under `--strict` (see `skills/census/SKILL.md`).

One golden fixture per code lives under `tests/fixtures/sessions-exit-<code>.json`.

## Rules

- **One writer per file.** The session-id is allocated by the register writer
  and is collision-free by construction. A session that tries to write to a
  file it did not allocate is refused (exit 2). Each of the four writers commits
  exactly its own session file: a change somebody else had staged is neither
  swept into that commit nor unstaged by it.
- **Claims are signals, not locks.** The census is the arbiter, not the
  write path. An unregistered claim is reported (exit 31), not blocked.
- **Identity, not hostname, is the key.** The census keys the double-claim
  check on the `identity` field, not on the file path or the hostname. Two
  sessions with the same identity claiming the same task are reported as
  "same identity, multiple sessions", not as a double-claim.
- **The census is read-only.** Running it leaves `git status --porcelain`
  empty; output goes to stdout only (no writes under `noni/census/`).
- **No project content in the skill.** Core skills carry neither project
  content nor driver-tool vocabulary; integrations are clearly-marked adapters.
