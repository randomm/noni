# The ledger shim

`scripts/census.sh` is the ledger's own entry point, and a thin one: it takes
the one directory its caller names and runs `noni census`
(`skills/census/scripts/census.py`, documented in `skills/census/SKILL.md`) over
the ledger group — `ledger-record`, `ledger-edited` and `ledger-chain` — and
exits with the census's own code. It carries no schema, no rules and no
exit-code table of its own, so there is nothing here for it to disagree with the
census about and nothing for this page to document separately: **the census's
check table and exit-code list in `skills/census/SKILL.md` are the reference for
this entry point too.** Where an older page listed codes of its own, that list
is gone; where the two entry points once disagreed, the census is the arbiter
because the wrapper now *is* the census.

It is a bash script, so it runs under `bash` or through its own executable bit
and its bash shebang — never under `python3`, which reads its braces as Python
and dies on a syntax error before any check runs. This is the one page that
states that rule for this shim; `SKILL.md` and the sessions shim's reference
point here. The wrapper needs a Python 3 that can import the package
(`NONI_PYTHON`, `python3` by default); a missing interpreter or an unimportable
package is named on one plain line and exits 3. `jq` is not required by anything
in noni: the record rules live in the package, which is what the shim runs.

It never writes; it reads `noni/decisions/*.json` and the git history, and
reports an honest exit code. It enforces the invariants that git and the files
can prove. What git cannot prove — that an answer was the operator's, not an
agent's — the census does not check and does not claim to (see
`references/modes.md`, Anti-fabrication).

## Usage

This shim is bash and parses its own arguments, but it still runs the package:
the census it launches imports the `noni` package, which must be installed or
importable on `PYTHONPATH`, and a run without it names that on one line and exits
3 (the *Install noni* section of
[docs/QUICKSTART.md](../../../docs/QUICKSTART.md#install-noni) owns the commands).

```
bash scripts/census.sh <state-root>/noni/decisions   the decisions census
bash scripts/census.sh --help        the wrapper's own help
```

Each line is one bash script, so `bash <path>` is the form that always runs: it
works whatever the file mode a checkout happened to land at. The direct form
(`scripts/census.sh <dir>`) is the same script where the executable bit is set.

The one argument is the ledger directory of the state root — the directory
`--repo` names for the writers. Pass the absolute path of a clone's ledger to
census a tree other than the one you are in; run with no argument, the run is a
usage error (2) rather than a census of whatever `noni/` happened to sit next to
the caller, and a second directory is the same refusal. A directory handed over
as a symlink is that refusal too: the census does not read through links.

Beyond the directory this entry point takes `--json` for the NDJSON rows,
`--strict` to promote the warn classes, and `--now` for a fixed timestamp, in
either `--now VALUE` or `--now=VALUE` form. Those are the whole allowlist: every
other option, prefix or stray token is refused with `2` and the census is not
run. Filters and everything else need `noni census`, which takes `--only` /
`--skip`, the state-path flags and the rest, and refuses what it does not define.

The sessions register is not this entry point's subject. It has its own wrapper,
`skills/sessions-claims/scripts/census-sessions.sh`, over the same census.

## Reading the report

Human mode prints one finding row per violation, each with its check id, its
severity and a fix line, then a `summary:` line naming the verdict; `--json`
prints one `finding` record per violation and exactly one `summary` record.
Rows are sorted by `(artifact, check, subject)` identically in both modes, so
the same findings come out in the same order whichever way you read them.
A non-zero exit also puts one line on stderr naming the code that won and
saying that every check ran — the lowest code decides the exit, and no higher
check is skipped.

The ledger group's rows, what each means, and the rule that a row whose input
could not be read is never reported as clean are all in the check table of
`skills/census/SKILL.md`. The `by` field is only schema-checked (non-empty
string): the census has no `by` column to disagree with, so a body value the
commit does not carry is simply not what a report prints, and no identity is
verified.

A `decisions/` directory that exists and can be read but holds no `*.json`
record is not a failure: it is the `ledger-empty` warn, at exit 0 and promoted
to 42 under `--strict`. A directory that could not be enumerated is different —
the census says the read faulted rather than reporting the empty ledger an
unreadable directory would otherwise look like. Both states, and the state words
`ledger-empty` carries, are on that same table.
