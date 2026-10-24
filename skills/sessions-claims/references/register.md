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

- `register.py --file <path>` where `<path>` does not match the allocated
  path → exit 2 (refused). The allocated id is minted once per run, so
  `--file` is only meaningful within the same run as the allocation — pass
  the freshly-allocated path as printed in the `registered session <id>`
  output. A re-run that reuses a previously-allocated file is rejected
  (exit 2), not re-registered.
- A file that already exists with a different identity → exit 1 (refused).
- A file that already exists with the same identity → exit 0 (idempotent no-op).

Two sessions that register concurrently get distinct session-ids and distinct
files. The protocol does not mediate writes to one shared path; it allocates
separate paths by construction.
