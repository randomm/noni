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
committed files at read time and flags two active claims on the same task from
different identities (exit 30). "No-steal" is an aspiration, not a promise.

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
| `status` | permanent | `active`, `closed`, or another terminal state |
| `claims` | ephemeral | list of `- claim: <task>` rows |

The identity is permanent: it survives across commits, pulls, and clones. The
host/worktree, started, and claims are ephemeral: they describe this working
copy and this session's current work.

Read `references/register.md` before writing a register file. Read
`references/claim.md` before making a claim. Read `references/census.md`
before reporting on the session state.

## Registering a session

```
scripts/register.py --repo REPO --identity IDENTITY [--status STATUS]
                    [--host HOST] [--worktree WORKTREE]
```

The register writer allocates a session-id, creates the file at
`noni/sessions/<session-id>.md`, and refuses to write a path it did not
allocate (exit 2). A re-registration with the same identity on the same file
is an idempotent no-op (exit 0). A registration that would overwrite another
session's file is refused (exit 1).

The `--host` and `--worktree` defaults never publish machine-local values:
`--host` defaults to the allocated session-id and `--worktree` to the repo
directory's basename. Neither default includes an absolute path or a
hostname, because the register file is committed to a public repo. Explicit
`--host` / `--worktree` values are written as given.

## Claiming a task

```
scripts/claim.py --repo REPO --session-id SID --task TASK [--branch BRANCH] [--push]
```

The claim writer appends a `- claim: <task>` row to the session's register
file, commits it, and (with `--push`) pushes with fetch-rebase-push (at most
3 attempts). The task reference is the issue number (e.g. `#42`) or a noni row
id. A claim row without a task reference is malformed (the census flags it,
exit 32).

## The sessions census

```
scripts/census-sessions.sh [SESSIONS_DIR]

# equivalent entry point (the steering-ledger census dispatches here)
census.sh --sessions [SESSIONS_DIR]
```

Read-only, NDJSON on stdout, honest exit code:

| code | meaning |
|---|---|
| `0` | clean — every session file valid, no double-claims |
| `3` | python3 not found on the reading machine |
| `30` | double-claim: two active claims on the same task from different identities |
| `31` | a claim row was committed without a register file (work is not blocked — report only) |
| `32` | a session file is malformed (missing required field, or a claim row with no task reference) |

When several classes fire at once, the lowest code wins (`30 < 31 < 32`);
every check runs in a single pass and all findings are always in the NDJSON
output (the priority only selects the returned code). Each non-zero exit
prints NDJSON rows naming the offending task or file.

The census is the deterministic arbiter. It does not block the session's work:
an unregistered claim (exit 31) is reported, not refused — there is no
pre-commit or pre-push hook, no write-path refusal.

One golden fixture per code lives under `tests/fixtures/sessions-exit-<code>.json`.

## Rules

- **One writer per file.** The session-id is allocated by the register writer
  and is collision-free by construction. A session that tries to write to a
  file it did not allocate is refused (exit 2).
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
