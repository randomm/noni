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
| `--strict` | off | treat every warn class as a failure: `session-stalled`, `probe`, `ledger-empty`, `session-same-identity`, `session-deleted`, `hygiene` |
| `--json` | off | emit NDJSON records on stdout (`noni.census/1`) |
| `--only CHECK` | all | run only the named check (repeatable) |
| `--skip CHECK` | none | skip the named check (repeatable) |
| `--list` | — | print the check ids and exit 0 |

## The checks

| check id | code | meaning |
|---|---|---|
| `ledger-record` | 10 | a decision record is malformed (schema violation, bad filename, unreadable/unparseable record) |
| `ledger-empty` | 42 | there is no steering ledger to arbitrate — exactly one row per run, whose message carries the state word `absent` (no `noni/`), `not a directory` (`noni/` is not a directory), `symlink` (refused, never followed), or `empty` (no record to census: `noni/` present with no `decisions/` directory, or a `decisions/` directory that holds no `*.json` record). It only ADDS rows and never weakens a malformed-record `ledger-record` failure (warn by default; fail under `--strict`) |
| `ledger-edited` | 12 | a record was edited after commit (supersede, never edit); a committed record deleted or renamed from the working tree is also reported here, with the "deleted" reason |
| `ledger-chain` | 20 | the supersede chain is broken (dangling, duplicate, orphan, cycle, zero-live, multi-live) |
| `session-double` | 30 | two active claims on the same task from different identities (the arbiter) |
| `session-claim` | 31 | a claim row committed without a register file |
| `session-malformed` | 32 | a session file is malformed (missing field, bad claim row) |
| `session-stalled` | 40 | an active session with no commit for `--stale-after` (warn by default; fail under `--strict`) |
| `session-same-identity` | 43 | two or more non-terminal session files carry the same `identity` — one row per identity, naming every file (warn by default; fail under `--strict`) |
| `session-deleted` | 44 | a `<YYYY-MM-DD>-<6 hex>.md` register file that git history shows was added is gone from the working tree (warn by default; fail under `--strict`) |
| `probe` | 41 | a probe could not read its input (unreadable file, symlink, git failure) — never reported as clean |
| `hygiene` | 50 | a tracked file fails the public-repo hygiene scan (machine-local home path, secret shape, active deny-list entry), or the scan/deny-list did not run (warn by default; fail under `--strict`) |

The `warn` classes are reported either way and never move the exit code on
their own: a run whose only findings are warnings exits 0, and `--strict`
promotes them to failures at their own codes. `ledger-empty` adds rows in the
states where no decision record can be read — no `noni/`, `noni/` not a
directory, a symlink, `noni/` present without a `decisions/` directory, or a
`decisions/` directory holding no `*.json` record. It never weakens a
malformed-record failure: a record that is bad JSON or violates the schema
keeps its `ledger-record` exit 10. A freshly attached project whose
`noni/decisions/` has no records yet therefore censuses clean at exit 0
(operator decision on issue #33; the legacy `census.sh` shim is a different
entry point and keeps its own exit 10 for an empty ledger directory).

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
42  ledger-empty (warn by default; failure under --strict)
43  session-same-identity (warn by default; failure under --strict)
44  session-deleted (warn by default; failure under --strict)
50  hygiene (warn by default; failure under --strict)
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

### The hygiene artifact namespace

`hygiene` rows live in two artifact namespaces, and which one applies is
decided by `subject`, which is therefore the machine-readable discriminator —
consumers should branch on it rather than matching message prose:

| `subject` | meaning | `artifact` |
|---|---|---|
| `path:line` of a tracked file | a built-in or active deny-list violation | that file, root-relative |
| `hygiene scan` | the scan itself did not run (no git tree, `git ls-files` failed or hung, `public_safety` not importable) | the checker, named from the skill directory (`../../../scripts/public_safety.py`) |
| `deny-list` | the deny-list half of the scan did not run; the state word (`absent`, `corrupt`, `present but empty`) is in the message | the checker, as above |

A violating file's artifact is rooted in the tree being audited; the two
probe-failure rows name the census's own checker, which lives outside that
tree, so they are rooted in the installed skill instead — the census never
prints a machine-local absolute path either way. A tracked path may contain a
colon, so the census splits public_safety's `path:line: label` on its known
label set rather than on the first colon, and a violation of an unexpected
shape is reported verbatim instead of split.

## The probe-honesty rule

A probe that cannot read its input (unreadable file, symlink, non-UTF-8 bytes,
git failure on a real repo) is recorded as a `probe` finding (warn) or a
`session-stalled` cannot-tell finding (warn). It is **never** silently
skipped, and it is **never** reported as clean. Under `--strict` it becomes a
failure (exit 41) and the run is never reported clean.

The same rule extends to the classes that report their own absence:

- **`ledger-empty` (42)** reports the ledger that has no record to arbitrate.
  "No `noni/` at all" is exactly one row carrying the state word `absent` — not
  the silent clean it used to be, because a census that says nothing here cannot
  tell "nothing to census" apart from "the ledger went missing". `empty` names
  the other no-record trees: `noni/` present with no `decisions/` directory, and
  a `decisions/` directory that holds no `*.json` record — a freshly attached
  project is a warning, not a failure, and the row names the ledger path
  relative to the repo root. A record that exists and is malformed is still a
  `ledger-record` failure (10). Nor does the class gate the integrity checks: a
  record that history shows was added and is now gone stays a `ledger-edited`
  failure (12), so an emptied ledger reports the deletion that emptied it — the
  git-backed integrity checks run whatever the empty probe found. When the
  deletion check cannot put its question to git at all (no git tree, or a
  history read that could not answer) and the ledger reads as `empty`, the run
  adds a `ledger-edited` `cannot-tell` row saying the check could not run: the
  deletion check is the only signal that committed records were deleted, so a
  silent one would let a gutted ledger read as a plain no-ledger warning. It is
  a warn by default (exit 0) and a failure at 12 under `--strict`.
- **`hygiene` (50)** always reports, a clean tree included. When the
  deny-list class is not active (its file is `absent`, `corrupt`, or present
  with no entries) the run emits one `hygiene` row naming that state; a scan
  that cannot run at all (`--repo` is not a git repo, `git ls-files` fails or
  hangs, `scripts/public_safety.py` is not importable, or the scanner raises
  for any reason) emits one row saying the scan did not run. Neither is ever
  reported as hygiene-clean, and no scanner failure can take the census down:
  every finding the run already collected is still reported. The scan runs
  in-process over the census's own git tree — the `--ledger` / `--sessions`
  overrides never re-target it.
- **The deletion classes report what they could not check.** A
  `--sessions`/`--ledger` override that points outside the audited git tree
  switches off the append-only question for that group; both say so in a
  `cannot-tell` row rather than letting a filtered or `--strict` run read "no
  rows" as "nothing was deleted". A cannot-tell row is a warn by default and
  is promoted by `--strict`, whatever its class's own severity: not being able
  to read the tree is not itself a protocol violation. The edit check's
  `cannot verify` row — a committed blob that is unreachable in a shallow or
  pruned tree — follows the same rule: it is a `ledger-edited` row that stays a
  warn at exit 0 and becomes a failure only under `--strict`, unlike the
  genuine `record was edited after commit` row of the same class, which fails
  either way.

### census exit 50 is not the public_safety gate

`scripts/public_safety.py` run as a script is the stricter gate: it refuses to
report clean when the deny-list class is inactive and exits 2. The census
reports the same condition as a `hygiene` warn that leaves the process at exit
0. Both read the deny-list through `public_safety.load_denylist` and its one
precedence (the default file next to the checker, which is gitignored, then
`NONI_SCRUB_DENYLIST`), so the two entry points never disagree about whether
the deny-list half ran — but a clean census exit 50 is not a substitute for
running `scripts/public_safety.py` before publishing.

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
  machine-local paths, operator names, or project-specific vocabulary. A row
  built from someone else's exception text is bounded and stripped of absolute
  paths for the same reason.
- **Read-only git.** Every git call the census makes pins the host's git
  config away (`GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` to the null device,
  `-c protocol.ext.allow=never -c core.hooksPath=/dev/null` on the command
  line), so a repository being audited cannot turn a read into execution
  through `core.hooksPath` or an external protocol helper.
