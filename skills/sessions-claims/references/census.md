# The sessions census

`scripts/census-sessions.sh` is the read-only arbiter for the session
register. It never writes; it reads `noni/sessions/*.md` and reports an
honest exit code. Output goes to stdout only (no writes under `noni/census/`).

## Usage

```
scripts/census-sessions.sh <state-root>/noni/sessions

# equivalent entry point (the steering-ledger census dispatches here)
census.sh --sessions <state-root>/noni/sessions
```

The one argument is the sessions directory of the state root — the directory
`--repo` names for the writers, with `noni/sessions` under it. Pass the sessions
directory of the clone you want to audit. There is no current-directory default:
a run with no argument is a usage error (`2`), so the census never reads whatever
`noni/sessions` happened to sit next to the caller. One run audits one register,
so a second directory is a usage error (`2`) too, naming every path given.

## Exit codes

| code | meaning |
|---|---|
| `0` | clean — every session file valid, no double-claims, all claims have a register file |
| `2` | usage: no sessions directory was given, more than one was given, or the one given is not a directory (the state root is named by the caller, never by the cwd) |
| `3` | python3 not found on the reading machine (missing dependency) |
| `30` | double-claim: two active claims on the same task from different identities |
| `31` | a claim row was committed without a register file (work is not blocked — report only) |
| `32` | a session file is malformed (missing required field, or a claim row with no task reference) |

**Legacy shim.** This table is `census-sessions.sh`, the per-epic entry point.
The unified census (`skills/census/scripts/census.py`, documented in
`skills/census/SKILL.md`) is the arbiter and adds three register classes this
shim does not report: `session-same-identity` (43, warn) — two or more
non-terminal register files carrying one `identity`, one row per identity
naming every file; `session-deleted` (44, warn) — a
`<YYYY-MM-DD>-<6 hex>.md` file that HEAD-reachable history shows was added and
is gone from the working tree, because sessions end via their `status` field
and never by deleting the register; and `session-stalled` (40, warn) — an
active file with no commit for `--stale-after`, reported as cannot-tell when
history is unavailable. All three are warn by default and fail at their own
code under `--strict`. `same-identity-multi-session` below is the shim's
narrower claim-overlap view; the unified class of the same name is the
file-level view.

When several classes are violated at once, the **lowest number wins**
(`30 < 31 < 32`). Every check runs in a single pass regardless of the exit
— the priority only selects which code is returned — so all findings are
always in the NDJSON output. The stderr line names the returned code and
notes this.

Each non-zero exit prints NDJSON rows on stdout naming the offending task or
file (filenames below are of the registered shape `<YYYY-MM-DD>-<6 hex>.md`,
allocated by `register.py`):

- `{"type": "double-claim", "task": "#42", "sessions": [{"identity": "developer", "sessions": [...]}, {"identity": "reviewer", "sessions": [...]}]}`
- `{"type": "claim-without-register", "file": "noni/sessions/<session-id>.md", "problems": [...]}`
- `{"type": "malformed", "file": "noni/sessions/<session-id>.md", "problems": [...]}`
- `{"type": "same-identity-multi-session", "task": "#42", "identity": "developer", "sessions": [...]}`

## What each check reads

- **`0` (clean):** every `noni/sessions/*.md` has all five required fields
  (identity, host/worktree, started, status, claims), no claim row has a
  missing task reference, and no task has two active claims from different
  identities. A session file with an empty claims list is clean.
- **`30` (double-claim):** two or more active claims on the same task from
  different identities. The census keys on the `identity` field, not on the
  file path or the hostname. The same identity in multiple sessions for the
  same task is reported as `same-identity-multi-session`, not as a
  double-claim.
- **`31` (claim without register):** a file under `noni/sessions/` that has
  claim rows but no identity field — the session committed claims without
  registering. The work is not blocked: there is no pre-commit or pre-push
  hook, no write-path refusal. The census is report-only.
- **`32` (malformed):** a registered session file is missing a required field
  (other than identity, which maps to exit 31 when claims are present), or a
  claim row has no task reference.

## The census is read-only

The census never writes, never mutates a session file, and never creates a
file. Running it leaves `git status --porcelain` empty. Output goes to stdout
only; no files are written under `noni/census/` in this epic (that is E3's
concern).

## The census is the arbiter

The census is the deterministic arbiter for the claim protocol. Git delays
the second claimant (push-rejection acts as compare-and-swap), it does not
lock them out. After the fetch-rebase-push protocol both claims land, and the
census is the check that detects the double-claim at read time. The census
does not block the session's work: an unregistered claim (exit 31) is
reported, not refused.

One golden fixture per code lives under `tests/fixtures/sessions-exit-<code>.json`.
