# The claim protocol

A claim is a committed record referencing the task, written to the session's
own register file so merges never fight over one blob.

## The claim row grammar

```
  - claim: <task reference>
```

The task reference is an issue number (e.g. `#42`) or a noni row id. A claim
row without a task reference (e.g. `  - claim:` with nothing after the
colon) is malformed; the census flags it (exit 32).

## Making a claim

```
scripts/claim.py --repo REPO --session-id SID --task TASK [--branch BRANCH]
                 [--push] [--no-commit]
```

The claim writer:
1. Appends `- claim: <task>` to the session's register file.
2. Commits the change (unless `--no-commit`).
3. (With `--push`) pushes with the fetch-rebase-push protocol.

The session must be registered first (the register file must exist); a claim
on an unregistered session exits 1.

A session that has ended claims nothing further. When the file's own
`- status:` field reads a terminal state — the four listed under **status** in
`references/register.md`, the same set the census treats as inactive — the run is
refused with exit 2, the status is named in the message, and nothing is
written. The check runs after the file has been read as UTF-8 (so a file no
parser can read is still reported as malformed, not as terminal) and before the
duplicate-row check (so a terminal session reads as terminal whichever task is
named). It is a write-time refusal on the file this run was pointed at: rows an
earlier session left in a file that has since gone terminal are not touched and
are not a new reportable state — the census keeps ignoring terminal sessions.

### Without the commit: `--no-commit`

For a caller that stages and commits itself, `--no-commit` appends the row and
stops there: it runs no `git add` and no `git commit`, and prints
`claim.py: appended <task> to <file>; left uncommitted`. The row stays in the
working tree for the caller to commit.

The validation chain is the same one the committing path runs, in the same
order, and nothing is written before it passes: the register file must exist
(exit 1), the session file must carry the `- claims:` marker and must not
already claim the task (exit 2, including when an earlier row was itself left
uncommitted), and `--task` must be a single token (exit 4). `--session-id` is
validated the same way by all four writers: it must be one token with no leading
dot, so a value that would name a file outside `noni/sessions/` (a `..` that
walks out of the state root, a path separator, embedded whitespace) is refused
with exit 4 and nothing is written.

`--branch` is validated under `--no-commit` and otherwise ignored: an unsafe
value exits 4, a valid one changes nothing, because there is no push to
target. When `--branch` was given the success line says so in as many words —
`(--branch <X> was validated but nothing was committed or pushed)` — so the
line cannot be mistaken for proof of a targeted write. With no `--branch` the
line is the plain one above. `--no-commit`
with `--push` is refused before anything is written
(exit 4): there would be no commit to push.

The caller's obligation is part of the flag: the commit is what makes the claim
visible outside this working copy. The census reads the session files in the
working tree, so a census run in the same clone does see an uncommitted row and
fires its normal codes for it: `30` when it makes two active claims on one task
from different identities, `32` when the row carries no task reference, `31`
when the file has claim rows but no register. What an uncommitted row does not
reach is any other clone, until it is committed and pushed: the exit-code
meanings that name a commit (exit 31's "a claim row was committed without a
register file") describe the register once git has the row. Commit the row, or
revert it.

## The push protocol

The push protocol is **fetch-rebase-push with at most 3 attempts**. The
losing pusher ends rebased-and-pushed: both claims land in git. The census
then flags the double-claim (exit 30) if the two claims are on the same task
from different identities.

This is the "compare-and-swap" behaviour of git: the second claimant's push
is rejected when the first claimant's push lands first. The second claimant
fetches, rebases onto the latest branch tip, and pushes again. After at most
3 attempts the push succeeds (or the script exits 3 with the last error).

The expected post-condition is: **both claims land** (the losing pusher is
rebased-and-pushed), and the census then flags the double-claim.

### When the rebase does not land

A rebase failure is never reported as a push failure. On a failed
`git rebase origin/<branch>` the script probes both `rebase-merge` and
`rebase-apply` (via `git rev-parse --git-path`) and requires positive
evidence that a rebase is genuinely stopped in one of them: its `head-name`
and `onto` files both read back non-empty. That is what a live stopped rebase
always leaves, and what a directory an earlier crashed run left behind does
not.

| code | case | what the script does |
|---|---|---|
| `5` | **rebase conflict**: the rebase started and stopped | runs `git rebase --abort`, echoes git's own output, and prints a hint naming the cause (another writer changed the same session file) and the remedy (fetch, resolve, re-run claim) |
| `6` | **rebase refused**: the rebase never started | runs no abort, and its hint names committing or stashing the local change |
| `6` | **state unreadable**: the probe could not run or a state file could not be read | runs no abort and asserts nothing about the clone: the message says the state could not be read and names running `git status` and `git rebase --abort` by hand |
| `3` | **killed by the timeout**: the rebase was stopped by the timeout rather than answered by git | reported as a timeout, not a conflict; if a rebase was found stopped it is aborted first (and the message says so), if none was stopped nothing is aborted |

A state directory this run did not stop in front of is not automatically the
refusal case. A directory with no readable `head-name` and `onto` is (an empty
or unreadable leftover): no abort runs. But a rebase left by an abandoned run
(`git rebase --quit`, a run that was killed, or one a person ran by hand)
still carries both files non-empty, so the probe reads it as a stopped rebase
and claim.py aborts it — and `git rebase --abort` resets the worktree and the
index, so any unstaged change to a tracked file is reset. Before a `--push`
run, clear any leftover rebase yourself (`git rebase --abort`, or
`git rebase --quit` to drop the state without touching files) and commit or
stash local work.

The exit-5 post-condition is that the clone is left where it was before the
rebase: `.git/rebase-merge` and `.git/rebase-apply` are both absent,
`git rev-parse --abbrev-ref HEAD` still prints the branch the run was invoked
on, and HEAD is that branch's tip before the rebase, sha for sha. That commit
is the claim commit this run made, so `git show HEAD:<session file>` still
carries the claim row. The abort itself resets index and worktree, so on this
path any unstaged change to a tracked file is reset to that commit: commit or
stash local work before a `--push` run. `claim.py` itself never invokes
`git reset`; the resets described above are what `git rebase --abort` does.
When `git rebase --abort` itself fails the script still exits 5, says the abort
failed and that the clone is still mid-rebase, echoes git's own
rebase output, and leaves cleanup to be done by hand — that one path is the
exception to the post-condition above.

A refused rebase is the dirty-worktree case: an unstaged modification of a
tracked file other than the session file (staged changes are not this case).
The claim commit is already made by then, so the caller's own commit or stash
resolves it and the push can be retried.

Everything else in the retry loop stays in the exit-3 class: a failed fetch,
a detached HEAD, an unresolvable branch, a push that is still rejected after
3 attempts, a `git add` or `git commit` that git refused (the row is left in
the worktree or the index, and the message says which), and a git call that
times out. A rebase killed by the timeout is reported in that class too, after
the state probe has had its say: if it had entered and stopped before being
killed, the abort still runs (exit 3, said to be a timeout that stopped in a
conflict); if nothing was stopped, nothing is aborted.

## Exit codes

The claim exit codes are the contract `scripts/claim.py` publishes as its
`Exit codes:` block; this is that table for the operator (codes 0-6), and
`skills/sessions-claims/SKILL.md` repeats it verbatim so the skill reads on its
own. A test asserts both copies against the `EXIT_*` constants. The census exit
tables are in `references/census.md`.

| code | meaning |
|---|---|
| `0` | claim committed (and pushed, with `--push`), or appended and left uncommitted with `--no-commit` |
| `1` | the register file for `--session-id` does not exist (register first) |
| `2` | the session file is malformed (no `- claims:` marker, not readable as UTF-8), the session already claims the same task, or the session's status is terminal; see the terminal-status paragraph above for what each refusal writes |
| `3` | push failed after 3 fetch-rebase-push attempts; also a failed fetch, a detached HEAD, an unresolvable branch, a git call that timed out, or a `git add`/`git commit` that git refused (the row is left in the worktree or the index, unstaged or staged as the failure says) |
| `4` | usage error: bad `--task`, `--session-id` or `--branch` value (`--session-id` must name one file under `noni/sessions/`, so whitespace, a path separator, a `..` walk out of the state root or a leading dot is refused), `--no-commit` with `--push`, a `--repo` that is not a directory, or a `--repo` that is a symlink (refused, never followed — the message names the real path) |
| `5` | rebase conflict; see the abort post-condition above |
| `6` | rebase refused, or its state could not be read; see the hints above |

Every failure prints a message and a fix hint on stderr, never a Python
traceback; the success lines go to stdout. What git printed is echoed
sanitised (control characters stripped) and bounded to `GIT_OUTPUT_LIMIT`
characters, because that text can originate with the remote. The codes are
published as `EXIT_*` module constants in
`src/noni/claim.py`, and a test asserts that docstring table against the code.

## Releasing a claim

`release.py --repo REPO --session-id SID --task TASK [--no-commit] [--push]`
removes one `- claim: <task>` row from the session's own file and commits it.
The row is matched on the **stripped line**, so the indented row under
`- claims:` that `register.py` writes and the bare row at EOF that `claim.py`
appends are both released, and neither shape is privileged. Every other row,
and every field line, stays byte-identical.

Two shapes are refused rather than guessed, both exit 2:

- **the session holds no such row** — the message names both the task and the
  session, so the operator can see which of the two was wrong;
- **the session holds two identical rows** — `claim.py` refuses a duplicate, so
  a pair means the file was edited outside the writers, and removing one of them
  silently would report a release the census does not agree with.

A file that carries no `- claims:` marker is refused the same way: without it
the writer cannot tell a claim row from a field line, and guessing which lines
are rows is exactly what this writer does not do.

The register file itself is never deleted, even when the released row was the
last one: the file is the session's record, and the census reads history for its
deleted-file check. A session that has finished its work is `close.py`'s
business, not this command's.

Releasing is not a lock either. The row is a record this session wrote; the
census is what reports a double-claim, and removing the row is what makes that
report for the task go away.

| code | meaning |
|---|---|
| `0` | the row is removed and committed (and pushed with `--push`), or removed and left uncommitted with `--no-commit` |
| `1` | the register file for `--session-id` does not exist (register first) |
| `2` | the session does not hold that task, or the file is unreadable, not UTF-8, carries no `- claims:` marker, holds the row twice, `--repo` names no directory, or `--repo` is a symlink (refused, never followed) |
| `3` | git could not commit the change, or `--push` failed after 3 fetch-rebase-push attempts (also a fetch failure, a detached HEAD, or an unresolvable branch) |
| `4` | `--task` or `--session-id` is not a single token (`--session-id` is also the name of one file under `noni/sessions/`, so a path separator or a `..` walk out of the state root is refused), or `--no-commit` was combined with `--push` |

`--no-commit` runs no git at all and prints `release.py: <path> left
uncommitted`; a working copy with no git directory answers the same line, since
there is nothing to commit into. The census reads the working tree, so the
removal is visible in this clone and invisible to every other one until it is
committed and pushed.

A refusal (exit 1, 2 or 4) removes no row: the file keeps the bytes it had.
When git refuses the commit (exit 3) the row is already gone from the work
tree, and the one line on stderr names the cause in noni's words — the four
states are under "Committing a session file" in `references/register.md` —
followed by the path this run left written but uncommitted and, after it, what
git said, sanitised.

## Closing a session

`close.py --repo REPO --session-id SID [--no-commit] [--push]` sets the
session's own `- status:` line to `closed` and commits that one file. That is
the whole of it, and it is how a session stops counting toward the double-claim
check: the census ignores a terminal status.

Only the status line moves — the identity, the claims, the timestamps and every
other byte stay as they were. The file is never deleted. Closing is idempotent:
a session already in a terminal state (`closed`, `done`, `superseded`, `ended`)
needs no commit, so a second close exits 0, leaves HEAD unmoved, and prints
`<id>.md was already closed (status=X); nothing to do`. That no-op is not a
refusal — it writes nothing and keeps the exit 0 it always had.

A refusal (exit 1, 2 or 4) moves no line. When git refuses the commit (exit 3)
the status line is already written, and the one line on stderr names the cause
in noni's words — the four states are under "Committing a session file" in
`references/register.md` — followed by the path this run left written but
uncommitted and, after it, what git said, sanitised.

| code | meaning |
|---|---|
| `0` | the status line was written and committed (and pushed with `--push`), or the session was already closed, or the change was left uncommitted with `--no-commit` |
| `1` | the register file for `--session-id` does not exist (register first) |
| `2` | the file is unreadable, not UTF-8, carries no `- status:` field line, `--repo` names no directory, or `--repo` is a symlink (refused, never followed) |
| `3` | git could not commit the change, or `--push` failed after 3 fetch-rebase-push attempts |
| `4` | `--session-id` is not a single token with no leading dot (the name of one file under `noni/sessions/`, so a path separator or a `..` walk out of the state root is refused), or `--no-commit` was combined with `--push` |

## What "claim" does not mean

A claim is an honest signal of ownership, not an authorization scope. It does
not prevent another session from working on the same task; it does not grant
permission; it does not create a lock. The census is the only mechanism that
detects the situation where two sessions claim the same task, and it is
report-only: it flags the double-claim, it does not block the second session's
work.

"No-steal" is an aspiration, not a promise: git delays the second claimant,
it does not lock them out.
