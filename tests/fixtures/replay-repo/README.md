# replay-repo fixture

A generator script (`generate.sh`) that produces a snapshot git repo whose
`noni/decisions/` tree is a self-contained, replayable steering ledger. The
repo is a full clone (not shallow), so a fresh clone can replay every recorded
decision from the clone alone, with no access to the source repository.

## Layout

```
replay-repo/
  .git/                      # full git history (not shallow)
  noni/decisions/
    2026-10-01-r1.json       # chain root, superseded
    2026-10-22-r2.json       # supersedes r1, superseded by r3
    2026-10-10-r3.json       # supersedes r2, the live record (EARLIER date than r2)
    2026-10-25-r4.json       # detached root, different scope
```

## The planted date reversal

r2 (the superseded record) has a date of **2026-10-22** and r3 (the live
superseder) has a date of **2026-10-10** — r3's date is *earlier* than r2's.
This pins the rule that **supersede-chain order is primary and `date` is only
a tie-break**: a replay that sorts by `date` alone would put r3 before r2,
which is wrong. The replay test asserts the chain order (r1 → r2 → r3) and
that r4 is the only other live record.

## Usage

```
tests/fixtures/replay-repo/generate.sh /tmp/replay-out
# → /tmp/replay-out/replay-repo
```

The test (tests/test_replay.py) calls this generator in a `tmp_path` and then
`git clone`s the result into a fresh `tmp_path` to prove the replay reads
nothing but git.
