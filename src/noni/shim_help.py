"""The --help text of the two shell census entry points, as package constants.

Both entry points print one of these constants verbatim, so the bytes a reader
sees have exactly one owner and no hard-coded line range drifts when the text
grows. ``tests/fixtures/census-sh/usage.txt`` and ``sessions-usage.txt`` hold the
lines the tests both routes are compared against must keep.

The text states the wrapper's shape and nothing else. It names the group the
entry point runs, the one argument it takes, and how to read its exit codes —
and then it points at ``skills/census/SKILL.md``, the single exit-code reference.
A wrapper owns no exit-code table of its own, so a page here would be a second
table to keep in step with the census's, which is what this file used to be.
"""

from __future__ import annotations

import sys

from .census_report import EXIT_CLEAN

CENSUS_SH_HELP = """The ledger shim: the steering ledger's own entry point.

  census.sh <state-root>/noni/decisions

It is a thin wrapper. It carries no rules and no exit-code table: it runs the
unified noni census (``noni census``, ``skills/census/scripts/census.py``) over
the ledger group alone — `ledger-record`, `ledger-edited` and `ledger-chain` —
and exits with the census's own code. The census itself is the arbiter, and
`skills/census/SKILL.md` is the single reference for its check classes and exit
codes; read that page, not this one, when a run tells you something.

The one argument is the ledger directory of the state root — the directory
`--repo` names for the writers, with `noni/decisions` under it. There is no
current-directory default: run with no argument, the run is a usage error (2)
rather than a census of whatever `noni/` happened to sit next to the caller. Two
directories are the same refusal — one run audits one ledger.

Every census option is accepted and passed through to the census, so the run
keeps the flags the unified census documents rather than a subset: `--json`,
`--strict`, `--now`, `--only`, `--skip` and the rest. `--strict` promotes the
warn classes the ledger group reports (`ledger-empty` among them), which is the
flag this wrapper used to have no route to.

Requires the `noni` package importable to the interpreter the wrapper runs
(``NONI_PYTHON``, ``python3`` by default: a program name, resolved on ``PATH``).
The wrapper names that fault on one plain line and exits 3 rather than letting a
traceback stand as the diagnostic. The census is read-only: running it leaves
`git status --porcelain` empty."""

CENSUS_SESSIONS_SH_HELP = """The sessions census: the session register's own entry point.

  census-sessions.sh <state-root>/noni/sessions

It is a thin wrapper. It carries no rules and no exit-code table: it runs the
unified noni census (``noni census``, ``skills/census/scripts/census.py``) over
the session group alone — `session-double`, `session-claim`, `session-malformed`
and the register's warn classes — and exits with the census's own code. The
census itself is the arbiter, and `skills/census/SKILL.md` is the single
reference for its check classes and exit codes; read that page, not this one,
when a run tells you something.

The census is the deterministic arbiter for the claim protocol. Two active
claims on the same task from different identities are a double-claim: git
delays the second claimant, it does not lock them out, so the census is the
check that catches it at read time. A claim committed without a register file
is reported but the session's work is not blocked — the census is report-only.

The one argument is the sessions directory of the state root — the directory
`--repo` names for the writers, with `noni/sessions` under it. Pass the sessions
directory of the clone you want to audit. There is no current-directory
default: a run with no argument is a usage error (2), because a relative default
would census whatever `noni/sessions` happened to sit next to the caller and
report a clean the caller never pointed at. Two directories are the same
refusal — one run audits one register.

Every census option is accepted and passed through, so the run keeps the flags
the unified census documents rather than a subset: `--json` for the NDJSON rows,
`--strict` to promote the warn classes, `--now` for a fixed timestamp, and the
`--only` / `--skip` filters.

Requires the `noni` package importable to the interpreter the wrapper runs
(``NONI_PYTHON``, ``python3`` by default: a program name, resolved on ``PATH``).
The wrapper names that fault on one plain line and exits 3 rather than letting a
traceback stand as the diagnostic. The census is read-only: running it leaves
`git status --porcelain` empty."""


def _constant(label: str) -> str:
    """The help constant an entry point prints, chosen by the label it runs under.

    One table keyed by the label rather than two near-identical branches: the
    label is what the wrapper passes and what a reader of the refusal sees.
    """
    table = {"census.sh": CENSUS_SH_HELP, "census-sessions.sh": CENSUS_SESSIONS_SH_HELP}
    if label not in table:
        raise KeyError(f"no help text for the entry point {label!r}")
    return table[label]


def print_help(label: str) -> int:
    """Print one entry point's help and return the census's clean code.

    Returns rather than exits: the caller is a ``main`` whose return value is the
    process's exit status, so the clean verdict has one owner in the census.
    """
    print(_constant(label))
    return EXIT_CLEAN


def main(argv: list[str] | None = None) -> int:
    """Print the census's help from the package, for a wrapper that has no args.

    ``python -m noni.shim_help`` is the route the wrappers take: one module-level
    call, no logic in bash, and the same bytes whatever the terminal width.
    """
    label = (list(sys.argv[1:] if argv is None else argv) or ["census.sh"])[0]
    return print_help(label)


if __name__ == "__main__":
    raise SystemExit(main())
