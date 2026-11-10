"""The --help text of the shell census entry point, as a package constant.

The entry point prints the constant verbatim, so the bytes a reader
sees have exactly one owner and no hard-coded line range drifts when the text
grows. ``tests/fixtures/census-sh/usage.txt`` holds the
lines the tests both routes are compared against must keep.

The text states the wrapper's shape and nothing else. It names the group the
entry point runs, the one argument it takes, and how to read its exit codes —
and then it points at ``skills/census/SKILL.md``, the single exit-code reference.
A wrapper owns no exit-code table of its own, so a page here would be a second
table to keep in step with the census's, which is what this file used to be.
"""

from __future__ import annotations

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

Beyond the one directory this entry point takes `--json`, `--strict` and
`--now` (in the `--now VALUE` or `--now=VALUE` form) and nothing else.
`--strict` promotes the warn classes the ledger group reports (`ledger-empty`
among them), which is the flag this wrapper used to have no route to. Every
other option, prefix or stray token is refused with the usage error (2) and the
census is not run: `noni census` is the tool that takes `--only` / `--skip`,
the state-path flags and the rest.

Requires the `noni` package importable to the interpreter the wrapper runs
(``NONI_PYTHON``, ``python3`` by default: a program name, resolved on ``PATH``).
The wrapper names that fault on one plain line and exits 3 rather than letting a
traceback stand as the diagnostic. The census is read-only: running it leaves
`git status --porcelain` empty."""

def _constant(label: str) -> str:
    """The help constant an entry point prints, chosen by the label it runs under.

    One entry point remains, so the label is checked rather than looked up: a
    wrapper that names another label is a caller bug, and the refusal says so.
    """
    if label != "census.sh":
        raise KeyError(f"no help text for the entry point {label!r}")
    return CENSUS_SH_HELP


def print_help(label: str) -> int:
    """Print one entry point's help and return the census's clean code.

    Returns rather than exits: the caller is a ``main`` whose return value is the
    process's exit status, so the clean verdict has one owner in the census.
    """
    print(_constant(label))
    return EXIT_CLEAN
