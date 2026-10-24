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
scripts/claim.py --repo REPO --session-id SID --task TASK [--branch BRANCH] [--push]
```

The claim writer:
1. Appends `- claim: <task>` to the session's register file.
2. Commits the change.
3. (With `--push`) pushes with the fetch-rebase-push protocol.

The session must be registered first (the register file must exist); a claim
on an unregistered session exits 1.

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

## What "claim" does not mean

A claim is an honest signal of ownership, not an authorization scope. It does
not prevent another session from working on the same task; it does not grant
permission; it does not create a lock. The census is the only mechanism that
detects the situation where two sessions claim the same task, and it is
report-only: it flags the double-claim, it does not block the second session's
work.

"No-steal" is an aspiration, not a promise: git delays the second claimant,
it does not lock them out.
