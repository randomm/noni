---
name: census
description: Run the unified noni census — a single read-only script that checks the steering ledger (schema, edit-after-commit, supersede chain), the session register (double-claim, claim-without-register, malformed, stalled) the ordering artifact (malformed order, stale entries, ordered-but-closed issues) and the standing intent file (missing or repeated sections, a file past its cap, an intent whose last commit cites no record) and returns an honest exit code. Use when the operator or any agent needs to verify the protocol invariants before merging, when triaging a failing census, or when the question is "are the ledger, the session register, the order and the intent in a valid state?" Do NOT use for writing, fixing, or mutating anything — the census is strictly read-only.
---

# census

**Mission:** one entry point that runs every noni protocol check and returns an honest
exit code. The census is the arbiter: it reads git history plus the committed files
under `noni/`, flags violations, and reports. It writes no file.

## The entry point

The census is a wrapper that imports the `noni` package, so it must be installed or
importable to run (`noni census` is the same code); [Install
noni](../../docs/QUICKSTART.md#install-noni) owns the install commands.

```
python3 skills/census/scripts/census.py [options]
```

Every noni path the census reads resolves from `--repo` — the one flag that
names the state root — and never from the script's own location or the current
directory beyond `--repo`'s default. A `--repo` that is missing, or is not a
directory, is a usage error (exit 2) before any check runs.

| option | default | meaning |
|---|---|---|
| `--repo PATH` | `.` | the repository or directory to audit |
| `--ledger PATH` | `<repo>/noni/decisions` | override the ledger directory |
| `--sessions PATH` | `<repo>/noni/sessions` | override the sessions directory |
| `--ordering PATH` | `<repo>/noni/direction/order.json` | override the ordering artifact |
| `--intent PATH` | `<repo>/noni/direction/intent.md` | override the standing intent file (its citation is still answered against the run's `--ledger`) |
| `--issue-state FILE` | — | JSON map `{"<issue>": "open"\|"closed"}` produced by an adapter or the operator; the only route by which closed state reaches the census, which never contacts a tracker |
| `--now ISO-8601` | current UTC | fixed timestamp for time-based checks (reproducible output) |
| `--stale-after` | `7d` for `session-stalled`, `30d` for `ordering-stale` | staleness threshold; positive whole days as `<N>` or `<N>d` (e.g. `7` or `7d`). Given explicitly, it is the one threshold both classes use; omitted, each class keeps its own default |
| `--strict` | off | treat every warn class as a failure: `session-stalled`, `probe`, `ledger-empty`, `session-same-identity`, `session-deleted`, `ordering-stale`, `ordering-closed`, `hygiene` |
| `--json` | off | emit NDJSON records on stdout (`noni.census/1`) |
| `--only CHECK` | all | run only the named check (repeatable). Rows of a class it does not name are dropped; a row about the file a group was asked to read is reported whatever the filter names, because a group that could not read its input must say so |
| `--skip CHECK` | none | skip the named check (repeatable) |
| `--list` | — | print the check ids and exit 0 |

## The checks

| check id | code | meaning |
|---|---|---|
| `ledger-record` | 10 | a decision record is malformed (schema violation, bad filename, unreadable/unparseable record) |
| `ledger-empty` | 42 | there is no steering ledger to arbitrate — exactly one row per run, whose message carries the state word `absent` (no `noni/`), `not a directory` (`noni/` is not a directory), `symlink` (refused, never followed), or `empty` (no record to census: `noni/` present with no `decisions/` directory, or a `decisions/` directory that holds no `*.json` record). It only ADDS rows and never weakens a malformed-record `ledger-record` failure (warn by default; fail under `--strict`) |
| `ledger-edited` | 12 | a record was edited after commit (supersede, never edit); a committed record deleted or renamed from the working tree is also reported here, with the "deleted" reason — including the case where the whole `decisions/` directory was deleted and the deletion committed; also the `cannot-tell` row for a `decisions/` directory that exists but could not be listed (warn by default; fail under `--strict`) |
| `ledger-chain` | 20 | the supersede chain is broken (dangling, duplicate, orphan, cycle, zero-live, multi-live) |
| `session-double` | 30 | two active claims on the same task from different identities (the arbiter) |
| `session-claim` | 31 | a claim row committed without a register file |
| `session-malformed` | 32 | a session file is malformed (missing field, bad claim row) |
| `session-stalled` | 40 | an active session with no commit for `--stale-after` (warn by default; fail under `--strict`) |
| `session-same-identity` | 43 | two or more non-terminal session files carry the same `identity` — one row per identity, naming every file (warn by default; fail under `--strict`) |
| `session-deleted` | 44 | a `<YYYY-MM-DD>-<6 hex>.md` register file that git history shows was added is gone from the working tree (warn by default; fail under `--strict`) |
| `probe` | 41 | a probe could not read its input (unreadable file, symlink, git failure) — never reported as clean |
| `ordering-malformed` | 15 | the ordering artifact is there and is not the artifact: unparseable bytes, a non-finite number, a key stated twice, wrong `schema`, a duplicate or non-positive `issue`, a `confirmed` that is not a UTC timestamp (one with no offset included), a `decision` matching no file in the ledger, an `--issue-state` file that does not parse or whose keys are not plain positive issue numbers, or a decision ledger whose listing faulted |
| `ordering-stale` | 45 | an order entry whose `confirmed` is older than the `--stale-after` threshold relative to `--now` (warn by default; fail under `--strict`) |
| `ordering-closed` | 46 | an ordered issue the `--issue-state` file says is closed; also the `cannot-tell` row for an entry the file does not mention (warn by default; fail under `--strict`) |
| `intent` | 51 | `noni/direction/intent.md` is there and is not the artifact: a `## Purpose` / `## Principles` / `## Never` / `## Ask first` heading missing, repeated or out of order, the `Last-confirmed:` line absent or repeated, or the file past its line cap; or the last commit that touched it is not an `intent: <decision-id>` headline naming a record the ledger holds (`uncited`). The `cannot-tell` row for a file this run could not read, for a cited decision record that is a symlink or any other non-regular path, for a ledger directory reached through a symlink, or for a file no commit touched, is a warn (fail under `--strict`); an absent file adds no row at all |
| `hygiene` | 50 | a tracked file fails the public-repo hygiene scan (machine-local home path, secret shape, active deny-list entry), a committed allowlist entry matches nothing, or the scan/deny-list did not run (warn by default; fail under `--strict`) |

The `warn` classes are reported either way and never move the exit code on
their own: a run whose only findings are warnings exits 0, and `--strict`
promotes them to failures at their own codes. `ledger-empty` adds rows in the
states where no decision record can be read — no `noni/`, `noni/` not a
directory, a symlink, `noni/` present without a `decisions/` directory, or a
`decisions/` directory holding no `*.json` record. It never weakens a
malformed-record failure: a record that is bad JSON or violates the schema
keeps its `ledger-record` exit 10. A recordless ledger is a state, not a fault:
a freshly attached project whose `noni/decisions/` has no records yet censuses
clean at exit 0, because nothing has been steered yet and there is nothing to
contradict. The ledger wrapper runs this census over that directory, so a
freshly attached tree reads the same way to either entry point.

When several classes fire at once the lowest code wins; stderr names every
class that fired.

## The exit code

```
0   clean — no violations (warnings allowed)
2   usage error (bad flag, unknown check, invalid --now)
3   required tool missing (git not found)
10  ledger-record
12  ledger-edited
15  ordering-malformed
20  ledger-chain
30  session-double
31  session-claim
32  session-malformed
40  session-stalled (warn by default; failure under --strict)
41  probe (warn by default; failure under --strict)
42  ledger-empty (warn by default; failure under --strict)
43  session-same-identity (warn by default; failure under --strict)
44  session-deleted (warn by default; failure under --strict)
45  ordering-stale (warn by default; failure under --strict)
46  ordering-closed (warn by default; failure under --strict)
50  hygiene (warn by default; failure under --strict)
51  intent
```

A clean exit with warnings is normal: a cannot-tell staleness probe (no git
history available) is a warning, not a failure, because the census cannot
distinguish "truly stalled" from "history unavailable" without escalating.

## The human report

Human mode prints one line per finding (`check`, its `WARN`/`FAIL` tag, its
subject and message, then the fix hint), then any `note:` line, then the summary
line. One note is printed first of all, ahead of the headline and every row: on a
`--repo` holding no `noni/` directory — what a caller gets by pointing `--repo` at
a code repository instead of a state root — the run says `note: no noni/ directory
was found under --repo <path>` before rows that would otherwise read as a project
that has not steered yet (a no-`noni/` tree is just a `ledger-empty` warn beside an
inactive `deny-list`). It is a note, not a row: no check class, no row kind and no
exit code is added, and under `--json` it rides the summary row's `not_evaluated`
like any other note. It is not printed when `--ledger`, `--sessions`, `--ordering`
or `--intent` replaces the path under the state root. The first and last lines are
keyed to what the run found:

| state of the run | first line | verdict word of the summary line |
|---|---|---|
| no rows, no note | `census: no findings; all checks passed` | `clean` |
| rows counted | `census: W warning(s), N finding(s)` | `W warning(s)` |
| no rows, a note | `census: no findings; <class> did not run` | `clean` |

So the all-clear banner and the word `clean` are reserved for a report that
carried nothing at all: a run whose only findings are warnings names how many it
counted instead of calling itself `clean`, and a run that skipped a check names
that class instead of claiming every check passed. The warn count is the number
of rows whose own severity is `warn`, read off the same field as the `WARN` tag
beside each row, so a cannot-verify or cannot-tell row of a fail class (warn by
default, escalated by `--strict`) is counted as the warning it prints as; under
`--strict` a promoted row reads `FAIL` and leaves that count, and the exit code
it earns is what the summary line says instead. The summary line's tail,
`verdict ok` / `verdict fail`, is the machine-readable half and is keyed on the
exit code alone: it stays the last line of stdout for a CI step that reads the
report's ending, whatever the human word before it says. `--json` mode is
unaffected by all of this (see below).

## --json output (NDJSON)

One `finding` record per violation, followed by exactly one `summary` record:

```json
{"schema": "noni.census/1", "kind": "finding", "check": "session-double",
 "code": 30, "severity": "fail", "subject": "#42",
 "artifact": "noni/sessions", "message": "…", "fix": "…"}
{"schema": "noni.census/1", "kind": "summary", "ok": false, "exit": 30,
 "counts": {"session-double": 1}}
```

Every `finding` row names the `artifact` path it derives from. Both output modes
(--json and human-readable) sort rows by the same key — `(artifact, check,
subject)` — so the row order is identical across modes and reproducible across runs
(see `_finding_sort_key`). No metric reads a value from an agent-authored field;
every value comes from git history, file existence, or file byte size.

### The hygiene artifact namespace

`hygiene` rows live in two artifact namespaces, and which one applies is
decided by `subject`, which is therefore the machine-readable discriminator —
consumers should branch on it rather than matching message prose:

| `subject` | meaning | `artifact` |
|---|---|---|
| `path:line` of a tracked file | a built-in or active deny-list violation, or an allowlist finding (stale, refused) at line 0 | that file, root-relative |
| `hygiene scan` | the scan itself did not run (no git tree, `git ls-files` failed or hung, `public_safety` not importable, or the committed allowlist unreadable or refused) | the checker, in the hygiene artifact namespace (`noni/public_safety.py`) |
| `deny-list` | the deny-list half of the scan did not run; the state word (`absent`, `corrupt`, `present but empty`) is in the message | the checker, as above |

A violating file's artifact is rooted in the tree being audited; the two
probe-failure rows name the census's own checker, which ships inside the
package rather than beside the tree, so they are rooted in the hygiene artifact
namespace instead — the census never prints a machine-local absolute path either
way. A tracked path may contain a
colon, so the census splits public_safety's `path:line: label` on its known
label set rather than on the first colon, and a violation of an unexpected
shape is reported verbatim instead of split; an allowlist finding is reported at line 0.

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
  relative to the repo root. Nor does the class gate the integrity checks: a
  record that history shows was added and is now gone stays a `ledger-edited`
  failure (12), so an emptied ledger reports the deletion that emptied it — the
  git-backed integrity checks run whatever the empty probe found, and they ask
  git even when the `decisions/` directory itself is gone, so a whole-directory
  deletion committed to history is one `deleted` row per record at exit 12
  rather than a bare no-ledger warning. "History never held a record" is a
  different answer from "git could not answer": the first is the lone
  `ledger-empty` warn at exit 0, the second the cannot-tell row below. When the
  deletion check cannot put its question to git at all (no git tree, or a
  history read that could not answer) and the ledger reads as `empty`, the run
  adds a `ledger-edited` `cannot-tell` row saying the check could not run: the
  deletion check is the only signal that committed records were deleted. It is
  a warn by default (exit 0) and a failure at 12 under `--strict`.
- **An unreadable ledger is never `empty`.** The census lists `decisions/` with
  an explicit `iterdir`, through one listing helper that the probe, the record
  pass and the ordering group all use, because `glob` swallows the `OSError` a
  readdir raises and yields nothing — which would let a directory the run could
  not read report the same exit 0 warn as a project that has never steered
  anything. The ledger is classified once per run: the run decides from that one
  probe whether the group reports at all, and the same probe answers the rows.
  Because the listing is
  shared, a faulted listing is reported by both groups that read it — the ledger
  group's row below, and the ordering group's row that names the citation check
  it could not perform.

  When the listing faults, no state word of the class is rendered (those four
  name states of the tree, and "unlistable" is a fault of this run's read): the
  run adds one `ledger-edited` `cannot-tell` row whose `subject` and `artifact`
  both carry the ledger's name and whose message carries the `OSError` text,
  bounded and stripped of machine-local paths. It is a warn at exit 0 and a
  failure at 12 under `--strict`.
- **An unreadable `noni/sessions/` is never clean.** A `noni/sessions/` that
  stats as a directory and cannot be listed earns exactly one `session-deleted`
  `cannot-tell` row — the class the deletion check already uses for its
  cannot-tells — marked whole-artifact, with the register's name in `subject`,
  `artifact` and its message, under the same naming rule the ledger bullet
  above states (root-relative `noni/sessions` when the census could root it,
  the last segment for an out-of-tree `--sessions` override, and the path as
  given in the identifier fields for a relative override it could not root),
  and the `OSError` text in the message, bounded and stripped of machine-local
  paths. It is a warn at exit 0 and a failure at 44 under `--strict`, and the
  group adds no other row: the read answered nothing, so no file was seen, no
  claim was compared, and the git-backed deletion question is not put either.
  The register is listed with an explicit `iterdir`, never `glob`, which
  swallows the readdir `OSError`. The register is read once per run, whatever
  the filter names, so the gate that opens the group and the rows it reports
  are the answer of that one readdir. A `noni/sessions/` that is simply absent
  stays what it always was: clean, because no sessions registered is a real
  state and not a failed read.
- **`hygiene` (50)** always reports under `noni census`, a clean tree included
  (the per-artifact wrappers run one group each and report no hygiene row). When the
  deny-list class is not active (its file is `absent`, `corrupt`, or present
  with no entries) the run emits one `hygiene` row naming that state; a scan
  that cannot run at all (`--repo` is not a git repo, `git ls-files` fails or
  hangs, `public_safety` is not importable, or the scanner raises
  for any reason) emits one row saying the scan did not run. Neither is ever
  reported as hygiene-clean, and no scanner failure can take the census down:
  every finding the run already collected is still reported. The scan runs
  in-process over the census's own git tree — the `--ledger` / `--sessions`
  overrides never re-target it.

  The file that switches the deny-list half on is `.noni-scrub-denylist`, one
  entry per line, kept at the root of the tree being audited (so
  `<project>/.noni-scrub-denylist`, or `.noni-scrub-denylist` at the state root
  `--repo` names), and `NONI_SCRUB_DENYLIST` names another file when the tree
  carries no default of its own. Blank lines and `#` comments are not entries,
  so a file holding only those reads as `present but empty` and leaves the class
  inactive: it needs at least one usable entry. It stays untracked by design —
  the names it guards must not be committed — which is why `--strict` fails on a
  freshly attached tree and why `docs/PUBLISHING.md` step 1 runs
  `scripts/public_safety.py` rather than trusting a clean census.
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
- **`ordering-closed` (46) reports the state it was not given.** Closed issue
  state reaches the census only through `--issue-state FILE`, a JSON map
  `{"<issue>": "open"|"closed"}` an adapter or the operator produces: the census
  never contacts a tracker, and there is no third adapter seam for it. Two
  states follow from that. An entry whose issue the map does not mention gets a
  `cannot-tell` row of the same class rather than silence, so a partial map
  cannot read as "every ordered issue is open"; it is a warn by default and
  `--strict` promotes it to 46. And when `--issue-state` was not given at all,
  the class is not evaluated: the run names the class and the reason in both
  modes. Human-readable mode prints one `note:` line saying so; `--json` mode
  prints no `note:` line at all and carries the same sentence on the one summary
  record's `not_evaluated` list, so a machine consumer is not left with `"counts":
  {}` and no way to tell "nothing closed" from "the question was not asked". A
  recipe that produces the file with a tracker command line and `jq` is in
  `docs/QUICKSTART.md`.
  A missing `noni/direction/order.json` is not a finding at all — the ordering
  layer is optional — so an attached project that has never ordered anything
  adds no ordering rows to its census.
- **`intent` (51) reports the file, and the commit that wrote it.** The class
  reads `noni/direction/intent.md` once and asks two questions of it: is it the
  artifact its writer writes (four sections in order, one stamp line, under the
  cap), and did the last commit that touched it cite a decision the ledger holds.
  A missing file adds no row: standing intent is optional, exactly as the
  ordering layer is, and a project that has never written one censuses clean.
  The severity split is the ordinary one — a shape or citation the census could
  read and disapprove of is a failure, and anything it could not read (a symlink,
  unreadable bytes, a record it could not open, the decision record the citation
  names standing as a symlink, a directory or any other non-regular path, the
  ledger directory or the directory above it being a symlink, or a file no commit
  ever touched) is a `cannot-tell` warn that `--strict` promotes to 51. A cited
  record is classified before it is opened and then opened with `O_NOFOLLOW`, so a
  link is refused rather than followed and no byte of an outside file decides the
  verdict. The row is marked whole-artifact, so a `--only` filter that named no
  intent class still shows it: a run that could not read the intent never reports
  itself clean.
- **A read the group could not make is reported, never skipped.** An
  `--issue-state` file that does not parse, and a decision ledger whose listing
  faults while an entry cites a decision, each add one row marked whole-artifact:
  the row is about the file the group was asked to read, not one entry inside it,
  so the group's `--only` filter cannot drop it and a run that checked nothing
  cannot report itself clean. A ledger that is simply absent or not a directory
  is different — no listing was attempted, and `ledger-empty` owns that report.
- **A map key must be the issue number itself.** `"07"` or `"-7"` can never match
  an entry's issue, so such a key is reported as malformed rather than becoming a
  silent `cannot-tell` row for an issue the file does name.

### Every ledger row names the ledger the same way

Every row of the ledger group that names the ledger names it by one identifier,
so the rows cannot disagree about which directory they are talking about: the
root-relative path when the census could root it (`noni/decisions`, the form the
census wrote and the one a caller joins on), and the path's **last segment** for
any `--ledger` it could not root — an absolute path, a `~`-rooted one, or a
relative walk out of the tree (`../x/decisions` is `decisions`). A path a caller
spelled out of its own working directory or home is a machine-local location, and
the report promises never to print one; a scrubber's `<path>` marker is not an
answer either, because a marker is not a name anyone can act on.

The rows it applies to, in the fields they render it in:

| row | where the ledger's name appears |
|---|---|
| `ledger-edited` `cannot-tell` for a faulted listing | `subject`, `artifact`, and the parenthesised ledger in its message |
| `ledger-empty` | `subject` and `artifact` |
| `ledger-record` | `artifact`, as the ledger's name with the record's name after it (`decisions/<name>.json`) |
| `ledger-chain` (duplicate, dangling, orphan, cycle, zero-live, multi-live) | `artifact`, on every row of the class |
| `ledger-edited` `cannot-tell` for an override outside the audited git tree | the parenthesised ledger in its message |

The in-tree case is unchanged by the rule and is what a normal run prints: those
fields carry `noni/decisions`, and the record row carries
`noni/decisions/<name>.json`. The `deleted` row of `ledger-edited` is not in the
table because it reports a record's path inside the audited tree, which the
append-only question can only reach for a ledger that is inside it.

### census exit 50 is not the public_safety gate

`scripts/public_safety.py` run as a script is the stricter gate: it refuses to
report clean when the deny-list class is inactive and exits 2. The census
reports the same condition as a `hygiene` warn that leaves the process at exit
0. Both read the deny-list through `public_safety.load_denylist` and its one
precedence (the untracked default file inside the tree being audited, which is
gitignored, then `NONI_SCRUB_DENYLIST`), so the two entry points never disagree
about whether the deny-list half ran — but a clean census exit 50 is not a
substitute for running `scripts/public_safety.py` before publishing.

## Rules

- **Read-only.** The census never writes, mutates, or creates any file. Running it
  leaves `git status --porcelain` empty.
- **One arbiter.** `noni census` (``census.py``) is the only entry point that
  enforces, and the page you are reading is the only exit-code reference. The
  two per-artifact shell entry points (`skills/steering-ledger/scripts/census.sh`
  and `skills/sessions-claims/scripts/census-sessions.sh`) are thin wrappers: each
  takes the one directory its caller names, accepts `--json`, `--strict` and
  `--now` and refuses every other option without running the census, and runs
  this census restricted to its group — the ledger
  shim (`census.sh`) to `ledger-record`, `ledger-edited` and `ledger-chain`, the
  sessions shim (`census-sessions.sh`) to the session group. Neither carries a
  schema, a rule or an exit-code table of
  its own, so neither can disagree with this one, and `jq` is not a prerequisite
  of either. They are reached through `bash` or their own executable bit, never
  under `python3`: the interpreter a wrapper needs is the one it execs itself
  (`NONI_PYTHON`, `python3` by default), and running the script under an
  interpreter hands the reader a syntax error before any check runs. A wrapper
  whose interpreter is missing or whose package will not import says so on one
  plain line and exits 3, the census's own code for a tool the reading machine
  does not have.
- **Time from `--now`.** All time-based checks use `--now` when given (for
  reproducible output in tests) and the current UTC time otherwise.
- **No project content in the skill.** The census script carries no
  machine-local paths, operator names, or project-specific vocabulary. A row
  built from someone else's exception text is bounded and stripped of absolute
  paths for the same reason.
- **Read-only git.** Every git call the census makes pins the host's git
  config away (`GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` to the null device,
  `-c protocol.ext.allow=never -c core.hooksPath=/dev/null` on the command
  line), so a repository being audited cannot turn a read into execution
  through `core.hooksPath` or an external protocol helper.
