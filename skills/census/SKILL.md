---
name: census
description: Run the unified noni census — a single read-only script that checks the steering ledger (schema, edit-after-commit, supersede chain) and the session register (double-claim, claim-without-register, malformed, stalled) and returns an honest exit code. Use when the operator or any agent needs to verify the protocol invariants before merging, when triaging a failing census, or when the question is "is the ledger and session register in a valid state?" Do NOT use for writing, fixing, or mutating anything — the census is strictly read-only.
---

# census

**Mission:** one entry point that runs every noni protocol check and returns
an honest exit code. The census is the arbiter: it reads git history plus the
committed files under `noni/`, flags violations, and reports. It never writes
anything — running it leaves `git status --porcelain` empty.

## The entry point

```
python3 skills/census/scripts/census.py [options]
```

| option | default | meaning |
|---|---|---|
| `--repo PATH` | `.` | the repository or directory to audit |
| `--ledger PATH` | `<repo>/noni/decisions` | override the ledger directory |
| `--sessions PATH` | `<repo>/noni/sessions` | override the sessions directory |
| `--now ISO-8601` | current UTC | fixed timestamp for time-based checks (reproducible output) |
| `--stale-after` | `7d` | staleness threshold for active sessions; positive whole days as `<N>` or `<N>d` (e.g. `7` or `7d`) |
| `--strict` | off | treat stalled sessions and probe failures as failures |
| `--json` | off | emit NDJSON records on stdout (`noni.census/1`) |
| `--only CHECK` | all | run only the named check (repeatable) |
| `--skip CHECK` | none | skip the named check (repeatable) |
| `--list` | — | print the check ids and exit 0 |

## The checks

| check id | code | meaning |
|---|---|---|
| `ledger-record` | 10 | a decision record is missing or malformed, or the ledger is unusable |
| `ledger-edited` | 12 | a record was edited after commit (supersede, never edit) |
| `ledger-chain` | 20 | the supersede chain is broken (dangling, duplicate, orphan, cycle, zero-live, multi-live) |
| `session-double` | 30 | two active claims on the same task from different identities (the arbiter) |
| `session-claim` | 31 | a claim row committed without a register file |
| `session-malformed` | 32 | a session file is malformed (missing field, bad claim row) |
| `session-stalled` | 40 | an active session with no commit for `--stale-after` (warn by default; fail under `--strict`) |
| `probe` | 41 | a probe could not read its input (unreadable file, symlink, git failure) — never reported as clean |

When several classes fire at once the lowest code wins; stderr names every
class that fired.

## The exit code

```
0   clean — no violations (warnings allowed)
2   usage error (bad flag, unknown check, invalid --now)
3   required tool missing (git not found)
10  ledger-record
12  ledger-edited
20  ledger-chain
30  session-double
31  session-claim
32  session-malformed
40  session-stalled (warn by default; failure under --strict)
41  probe (warn by default; failure under --strict)
```

A clean exit with warnings is normal: a cannot-tell staleness probe (no git
history available) is a warning, not a failure, because the census cannot
distinguish "truly stalled" from "history unavailable" without escalating.

## --json output (NDJSON)

One `finding` record per violation, followed by exactly one `summary` record:

```json
{"schema": "noni.census/1", "kind": "finding", "check": "session-double",
 "code": 30, "severity": "fail", "subject": "#42",
 "artifact": "noni/sessions", "message": "…", "fix": "…"}
{"schema": "noni.census/1", "kind": "summary", "ok": false, "exit": 30,
 "counts": {"session-double": 1}}
```

Every `finding` row names the `artifact` path it derives from. Both output
modes (--json and human-readable) sort rows by the same key —
`(artifact, check, subject)` — so the row order is identical across modes
and reproducible across runs (see `_finding_sort_key`). No metric reads a
value from an agent-authored
field; every value comes from git history, file existence, or file byte size.

## The probe-honesty rule

A probe that cannot read its input (unreadable file, symlink, non-UTF-8 bytes,
git failure on a real repo) is recorded as a `probe` finding (warn) or a
`session-stalled` cannot-tell finding (warn). It is **never** silently
skipped, and it is **never** reported as clean. Under `--strict` it becomes a
failure (exit 41) and the run is never reported clean.

## Rules

- **Read-only.** The census never writes, mutates, or creates any file.
  Running it leaves `git status --porcelain` empty.
- **One entry point.** `census.py` is the canonical entry point. The older
  per-epic scripts (`census.sh`, `census-sessions.sh`) remain as compatibility
  shims with a subset of the same exit codes (see the steering-ledger
  SKILL.md).
- **Time from `--now`.** All time-based checks use `--now` when given (for
  reproducible output in tests) and the current UTC time otherwise.
- **No self-reported numbers.** Every metric in `--json` mode names the
  artifact path it derives from; no value comes from a number written inside
  an agent-authored file.
- **No project content in the skill.** The census script carries no
  machine-local paths, operator names, or project-specific vocabulary.
