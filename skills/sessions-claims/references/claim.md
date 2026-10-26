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

### Without the commit: `--no-commit`

For a caller that stages and commits itself, `--no-commit` appends the row and
stops there: it runs no `git add` and no `git commit`, and prints
`claim.py: appended <task> to <file>; left uncommitted`. The row stays in the
working tree for the caller to commit.

The validation chain is the same one the committing path runs, in the same
order, and nothing is written before it passes: the register file must exist
(exit 1), the session file must carry the `- claims:` marker and must not
already claim the task (exit 2, including when an earlier row was itself left
uncommitted), and `--task` must be a single token (exit 4).

`--branch` is validated under `--no-commit` and otherwise ignored: an unsafe
value exits 4, a valid one changes nothing, because there is no push to
target. The success line names the target branch when `--branch` was given, so
a caller cannot mistake a dropped `--branch` for a targeted write. `--no-commit`
with `--push` is refused before anything is written
(exit 4): there would be no commit to push.

The caller's obligation is part of the flag: an uncommitted row is visible to
no arbiter. The census reads committed files, so a row nobody commits is
invisible to the double-claim, register and malformed checks, and it also stops
the stall check from answering for that file; and the next `claim.py --push` in
the same clone meets a dirty worktree and exits 6. Commit the row, or revert
it.

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

A stray state directory that is not a stopped rebase (no readable `head-name`
and `onto`) is the refusal case, not the conflict case: `git rebase --abort`
resets the worktree and the index, so aborting a rebase this run did not start
would throw away the caller's unrelated work and report it as a claim conflict.

The exit-5 post-condition is that the clone is left where it was before the
rebase: `.git/rebase-merge` and `.git/rebase-apply` are both absent,
`git rev-parse --abbrev-ref HEAD` still prints the branch the run was invoked
on, and HEAD is that branch's tip before the rebase, sha for sha. That commit
is the claim commit this run made, so `git show HEAD:<session file>` still
carries the claim row. The abort itself resets index and worktree, so on this
path any unstaged change to a tracked file is reset to that commit: commit or
stash local work before a `--push` run. The script never runs `git reset
--hard`. When `git rebase --abort` itself fails the script still exits 5, says
the abort failed and that the clone is still mid-rebase, echoes git's own
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

This is the one table; `SKILL.md` points here rather than repeating it.

| code | meaning |
|---|---|
| `0` | claim committed (and pushed, with `--push`), or appended and left uncommitted with `--no-commit` |
| `1` | the register file for `--session-id` does not exist (register first) |
| `2` | the session file is malformed (no `- claims:` marker, not readable as UTF-8) or the session already claims the same task |
| `3` | push failed after 3 fetch-rebase-push attempts; also a failed fetch, a detached HEAD, an unresolvable branch, a git call that timed out, or a `git add`/`git commit` that git refused (the row is left in the worktree or the index, unstaged or staged as the failure says) |
| `4` | usage error: bad `--task` or `--branch` value, or `--no-commit` with `--push` |
| `5` | rebase conflict; see the abort post-condition above |
| `6` | rebase refused, or its state could not be read; see the hints above |

Every failure prints a message and a fix hint on stderr, never a Python
traceback; the success lines go to stdout. What git printed is echoed
sanitised (control characters stripped) and bounded to `GIT_OUTPUT_LIMIT`
characters, because that text can originate with the remote. The codes are
published as `EXIT_*` module constants in
`scripts/claim.py`, and a test asserts that docstring table against the code.

## What "claim" does not mean

A claim is an honest signal of ownership, not an authorization scope. It does
not prevent another session from working on the same task; it does not grant
permission; it does not create a lock. The census is the only mechanism that
detects the situation where two sessions claim the same task, and it is
report-only: it flags the double-claim, it does not block the second session's
work.

"No-steal" is an aspiration, not a promise: git delays the second claimant,
it does not lock them out.
