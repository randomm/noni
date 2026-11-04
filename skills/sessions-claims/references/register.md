# The session register

One committed Markdown file per session under `noni/sessions/`, named
`<session-id>.md`. The session-id is the filename without the extension.

## The session-id

The session-id is **random per working copy**: `YYYY-MM-DD-<6 hex chars>`,
allocated once when a session registers (by `scripts/register.py`). Ids are
collision-free by construction (16^6 ≈ 16.7M slots per day), so each register
file has exactly one writer. The id is stable across pulls, pushes, and
clones: once committed, the file's name and the session-id it encodes do not
change.

The id is **not** the identity. A session's identity (the `identity` field)
is a stable, human-readable role name that can be shared across multiple
working copies (e.g. two clones of the same logical session both record
`identity: developer`). The census keys the double-claim check on identity,
not on the session-id or the hostname.

## The register file format

```
- identity: <role name>
- host/worktree: <host> (<worktree path>)
- started: <UTC ISO-8601>
- status: <active|closed|...>
- claims:

  - claim: <task reference>
  - claim: <task reference>
```

All five fields are required. A file missing any required field is flagged
by the census (exit 32 if registered, exit 31 if it has claims but no
identity). An empty claims list is not malformed: a session with no claims
is clean (exit 0).

## The field semantics

- **identity** (permanent): the stable role name. Two sessions in different
  clones of the same logical session can share an identity without creating a
  double-claim.
- **host/worktree** (ephemeral): the host name and worktree path of this
  working copy. The same logical session can legitimately appear from two
  clones; the census keys on identity, not on this field. The `register.py`
  defaults never publish machine-local values: `--host` defaults to the
  allocated session-id (never the machine hostname) and `--worktree` defaults
  to the repo directory's basename (never an absolute path). An explicit
  `--host` / `--worktree` value is written as given; keep it generic in a
  public repo (no absolute paths or hostnames).
- **started** (ephemeral): the UTC ISO-8601 timestamp of registration.
- **status** (permanent): `active` while the session is working; a terminal
  state (`closed`, `done`, `superseded`, or `ended`) excludes the session's
  claims from the double-claim check.
- **claims** (ephemeral): a list of `- claim: <task>` rows. The task
  reference is an issue number (e.g. `#42`) or a noni row id. A claim row
  without a task reference is malformed (exit 32).

## The one-writer invariant

The session-id is allocated by the register writer and is collision-free by
construction. The writer allocates the path and then refuses to write any
path it did not allocate:

- `register.py --file <path>` where `<path>` is neither the path this run
  allocated nor the marked session's file → exit 2 (refused). One rule, both
  pages: `--file` is admitted only for this run's allocation, or for the marked
  name on the route that reuses it. The allocated id is minted once per run, so
  `--file` is only meaningful within the same run as the allocation — pass the
  freshly-allocated path as printed in the `registered session <id>` output, or
  the path of the session this working copy is marked for. A run that allocates —
  `--no-commit`, or one whose marked session has ended, whose file is gone, or
  whose file has no readable `- status:` value — admits only the name it
  allocated: the marked file is the target of the reuse route alone. A path
  belonging to some other session is refused, not written.
- A file that already exists with a different identity → exit 1 (refused).
- A file that already exists with the same identity → exit 0 (idempotent no-op).
- A session file that is a symlink, or a directory on the way to it — `noni/sessions/`
  or the `noni/` above it — that is not a directory (a link, a plain file, a
  socket or a device) → exit 2 (refused). `is_file()` follows a link, so a
  symlinked file would read as present and the atomic replace would land on the
  link's target; the check is `lstat` instead, and it runs before the `mkdir`,
  before the write and before the marker, so a refusal creates no directory, writes
  no file and leaves HEAD where it was. `lstat` reads only the last component, which
  is why the same question is asked of every directory above the file and not of the
  two it happens to write into: a link at `noni/` would otherwise read as the
  ordinary directory and file beneath it and send the write outside the tree. A
  dangling link is refused on this code rather than reported as "no such session
  file". A project reached *through* a linked ancestor is not this state: only the
  session file and the paths beneath the state root are examined.

Two sessions that register concurrently get distinct session-ids and distinct
files. The protocol does not mediate writes to one shared path; it allocates
separate paths by construction.

## The working-copy marker

After a successful allocation the writer records the id in a marker file, and
the marker — not the file name — is what makes a second registration in the
same working copy recognise the session it already owns.

- **Where it lives.** `<git-dir>/noni-session`, where `<git-dir>` is this tree's
  own git directory: `<repo>/.git` for a plain clone, or the directory named by
  the `gitdir:` line of a linked worktree's `.git` file. Each worktree marks
  itself, so two worktrees of one repository never share a session. The path is
  built from `--repo` and never through `git rev-parse`, `GIT_DIR` or
  `GIT_WORK_TREE`, so the marker belongs to the tree the operator named.
- **What it holds.** One session id: the id this command allocated, and nothing
  else. The id is read back as an input, not a fact — it passes the same gate a
  `--session-id` on the command line passes (one token, no path separator, no
  leading dot). Text that is not a session id is not a marker for a session: the
  run says so on stderr, treats the working copy as unmarked, allocates a new
  session and re-marks the tree for it. No path is ever built from marker text.
- **What the next register does with it.** An active marked session is
  continued (exit 0, nothing written, no commit) when the identity matches, and
  refused (exit 1, both identities named) when it does not. A marked session in
  a terminal state, or one whose file is gone, is not a session to continue: the
  run allocates a new id and re-marks the working copy for it.
- **When there is no marker.** No `.git` directory, a `gitdir:` line that is
  blank, malformed, or names no existing directory: the run allocates, writes no
  marker, and says so on stderr (`no noni-session was written under <path>`) —
  the session is registered but the next run in this working copy will not find
  it. A marked file that cannot be read is a refusal (exit 2), never an
  overwrite, and a `- status:` line with no readable value is refused the same
  way: register allocates afresh rather than continue a session it cannot tell is
  active.
- **`--no-commit` does not mark.** Asking for the file to be left in the work
  tree is a caller that intends to write more than one session here and commit
  them itself, so it gets a fresh allocation and the existing marker stays where
  it was — an opted-out run cannot steal the working copy's session.
- **A commit that fails puts the marker back.** When the file was written, the
  marker written, and git refused the commit (exit 3), the marker is restored to
  the bytes it held before this run — including no marker at all when this run
  created one. The session file stays on disk and is named in the message; the
  working copy is never left marked for a session git never received, so the
  next run does not continue a session that exists only locally.

## Committing a session file

All four writers (`register.py`, `claim.py`, `release.py`, `close.py`) commit
exactly one path — the session's own file — with the same three steps: reset
that path's index entry, add it, then `git commit --only -- <path>`. Every other
staged entry is left staged and uncommitted, so a writer never sweeps an
unrelated change into its commit and never unstages somebody else's.

The path git is handed is a path *inside* the state root — `noni/sessions/
<session-id>.md` — never a path read against the caller's working directory, and
carrying no component of a relative `--repo`. The writer derives that one name and
uses it for the file it writes (`<repo>/<name>`), for the pathspec and for every
message, so `--repo` alone decides which repository is written and the process
directory has no say in it. The id is minted once per `register.py` run and that
single string names the file, the pathspec, the marker, the commit subject and the
printed line. A name that is absolute, that leaves the root with `..`, that is not
a `.md` file under `noni/sessions/`, or that carries a control character, is
refused before anything is written: an absolute pathspec is what `git add` accepts
from outside the `-C` tree, exiting 0 and staging nothing, so a writer that
admitted one would report a commit that carried no file, and a name carrying a
control character would make the git call itself raise rather than report. Every
git call is bounded by a timeout, makes no signing promise, runs no repository
hooks, and refuses the external transports a remote could name.

### Commit refused by git

When git refuses the commit the writer already wrote its file (exit 3 for all
four writers), the one line on stderr names the cause in noni's own words —
this branch has no upstream configured, the upstream branch no longer exists on
origin, the file already holds the bytes this run wrote so git found nothing to
commit, or git refused for some other reason — and quotes what git said after
it, sanitised and bounded. This is the one place those four states are written
out; the other pages point here. The writer's headline names the path it left
written but uncommitted, so an operator aborting the run knows what to restore:
the file for all four writers, and for `register.py` the marker as well, which
the run restores itself. When the marker cannot be put back, that line says so
and names the marker, because a marker still naming a session git never
received is the state the restore exists to prevent.

`--push` pushes the branch `git rev-parse --abbrev-ref HEAD` names, with
fetch-rebase-push in at most 3 attempts; a detached HEAD is refused rather than
pushed to a branch literally named `HEAD`. A working copy with no git directory
cannot commit, so the writer behaves as `--no-commit` and prints the same line
instead of claiming a commit that could not happen.

## Lifecycle

A session's `status` is the whole of its lifecycle, and two verbs move it:

- `release.py --repo REPO --session-id SID --task TASK` removes one `- claim:`
  row (matched on the stripped line, so an indented row and a bare EOF row are
  both released) and commits the file. No such row, or two identical rows, is
  refused (exit 2). See `references/claim.md`.
- `close.py --repo REPO --session-id SID` sets `- status: closed` and commits
  the file. A session already in a terminal state is a no-op (exit 0, no commit).
  The file is never deleted: it is the session's record, and the census reads
  history for its deleted-file check.

A claim on a session whose status is terminal is refused by `claim.py` (exit 2,
the status named) before anything is written; see `references/claim.md`.

Both take `--no-commit` and `--push`, and both share `claim.py`'s push contract:
fetch-rebase-push in at most 3 attempts, exit 3 when the attempts run out or a
fetch fails, exit 5 when the rebase started and stopped on a session-file
conflict (the run aborts it, so the clone stays on its branch with the commit it
made), and exit 6 when git never started the rebase or its state could not be
read (no abort is run). The full table is in `references/claim.md`.
