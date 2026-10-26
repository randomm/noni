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
target. `--no-commit` with `--push` is refused before anything is written
(exit 4): there would be no commit to push.

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

A rebase failure is never reported as a push failure, and never leaves the
clone mid-rebase. On a failed `git rebase origin/<branch>` the script probes
both `rebase-merge` and `rebase-apply` (via `git rev-parse --git-path`) to
tell the two cases apart:

| code | case | what the script does |
|---|---|---|
| `5` | **rebase conflict**: the rebase started and stopped | runs `git rebase --abort`, echoes git's own output, and prints a hint naming the cause (another writer changed the same session file) and the remedy (fetch, resolve, re-run claim) |
| `6` | **rebase refused**: the rebase never started | runs no abort, and its hint names committing or stashing the local change |

The exit-5 post-condition is that the clone is left where it was before the
rebase: `.git/rebase-merge` and `.git/rebase-apply` are both absent,
`git rev-parse --abbrev-ref HEAD` still prints the original branch, and HEAD
is the commit the script recorded before the attempt, sha for sha. That commit
is the claim commit this run made, so `git show HEAD:<session file>` still
carries the claim row. The script never runs `git reset --hard`.

A refused rebase is the dirty-worktree case: an unstaged modification of a
tracked file other than the session file (staged changes are not this case).
The claim commit is already made by then, so the caller's own commit or stash
resolves it and the push can be retried.

Everything else in the retry loop stays in the exit-3 class: a failed fetch,
a detached HEAD, an unresolvable branch, a push that is still rejected after
3 attempts, and a git call that times out.

## Exit codes

| code | meaning |
|---|---|
| `0` | claim committed (and pushed, with `--push`), or appended and left uncommitted with `--no-commit` |
| `1` | the register file for `--session-id` does not exist (register first) |
| `2` | the session file is malformed (no `- claims:` marker, not readable as UTF-8) or the session already claims the same task |
| `3` | push failed after 3 fetch-rebase-push attempts; also a failed fetch, a detached HEAD, an unresolvable branch, or a git call that timed out |
| `4` | usage error: bad `--task` or `--branch` value, or `--no-commit` with `--push` |
| `5` | rebase conflict; see the abort post-condition above |
| `6` | rebase refused; see the hint about committing or stashing |

Every failure prints a message and a fix hint on stderr, never a Python
traceback. The codes are published as `EXIT_*` module constants in
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
