# The sessions census

`scripts/census-sessions.sh` is the session register's own entry point, and a
thin one: it takes the one directory its caller names and runs `noni census`
(`skills/census/scripts/census.py`, documented in `skills/census/SKILL.md`) over
the session group — `session-double`, `session-claim`, `session-malformed`,
`session-stalled`, `session-same-identity`, `session-deleted` and `probe` — and
exits with the census's own code. It carries no parser, no rules and no
exit-code table of its own, so there is nothing here for it to disagree with the
census about: **the census's check table and exit-code list in
`skills/census/SKILL.md` are the reference for this entry point too.** It runs
the session group and nothing else, so it reports no `hygiene`, `ordering-*` or
`intent` row — `noni census` is the whole picture. Where an
older page listed a narrower set of codes and its own row shapes, that list is
gone; the census is the single arbiter because this wrapper now runs it.

It is a bash script, so it runs under `bash` or through its own executable bit,
never under `python3` — the interpreter it needs is the one it execs itself
(`NONI_PYTHON`, `python3` by default), and running the script under an
interpreter hands the reader a syntax error before any check runs. A missing
interpreter or an unimportable package is named on one plain line and exits 3,
the census's own code for a tool the reading machine does not have.

It never writes; it reads `noni/sessions/*.md` and the git history and reports an
honest exit code. Output goes to stdout only (no writes under `noni/census/`).

## Usage

```
bash scripts/census-sessions.sh <state-root>/noni/sessions   the sessions census
bash scripts/census-sessions.sh --help        the wrapper's own help
```

The one argument is the sessions directory of the state root — the directory
`--repo` names for the writers, with `noni/sessions` under it. Pass the sessions
directory of the clone you want to audit. There is no current-directory default:
a run with no argument is a usage error (`2`), so the census never reads whatever
`noni/sessions` happened to sit next to the caller. One run audits one register,
so a second directory is that error too, and so is a directory handed over as a
symlink: the census does not read through links. The state-path flags — `--repo`,
`--ledger`, `--sessions` — are this entry point's to set from the directory it is
given, so typing one of them (or a prefix of one) is the same refusal too: the
census would otherwise read the path you named and call it clean.

Every other argument goes to the census untouched, so its options are this entry
point's options: `--json` for the machine-readable rows, `--strict` to promote
the warn classes to failures at their own codes, `--now` for a fixed timestamp
(reproducible output), `--only` / `--skip` to filter rows.

## What the census reports

The claim protocol's arbiter check is `session-double` (30): two active claims on
the same task from different identities. The census keys on the `identity`
field, not the file path or the hostname, and the same identity claiming one
task from two files is not a double-claim. `session-claim` (31) is a claim row
committed with no register file — reported, never blocked: there is no pre-commit
or pre-push hook and no write-path refusal. `session-malformed` (32) is a
register file missing a required field or carrying a claim row with no task
reference, and a file whose name is not the allocated `<YYYY-MM-DD>-<6 hex>.md`
shape.

The classes this entry point used to lack are here now, because it runs the
census that has them: `session-stalled` (40), `probe` (41),
`session-same-identity` (43) and `session-deleted` (44), each warn by default
and a failure under `--strict`. What each reads, and the rule that a register
this run could not list is reported rather than read as clean, are on the check
table of `skills/census/SKILL.md`.

When several classes fire at once the lowest code wins and stderr names every
class that fired; every check runs whatever the exit, so no finding is lost to
the code that was returned. In `--json` mode every finding is one row with its
`check`, `code`, `severity`, `subject`, `artifact`, `message` and `fix`, followed
by exactly one `summary` row.

## The census is the arbiter

Git delays the second claimant (push-rejection acts as compare-and-swap), it does
not lock them out. After the fetch-rebase-push protocol both claims land, and the
census is the check that detects the double-claim at read time. It does not block
the session's work: an unregistered claim is reported, not refused.

One golden fixture per code lives under `tests/fixtures/sessions-exit-<code>.json`.
