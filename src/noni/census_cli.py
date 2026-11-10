"""The census's flag surface: the one argument parser the tool builds.

Split from ``census.py`` so each file stays the size one responsibility is
worth: ``census.py`` keeps the check contract's re-exports, the probe seams, the
row factory and the group entry points, and this module owns the flags. The body
of the run they configure — the validation, the per-group gating and the
exit-code choice — is in ``census_run.py`` beside this file, and ``census.py``
re-exports both ``main`` and ``_build_parser`` so the census stays the module its
wrappers, ``python -m noni census``, ``noni census`` and its tests import.

The parser builds its own help from the check contract: ``--strict`` names the
warn classes through ``_warn_class_names()`` and ``--stale-after`` quotes the two
defaults declared in ``census_render.py``, so neither line is a copy that can drift
from the table. The store's own path override is declared here beside the other two
so one parser remains the whole flag surface. ``prog`` is the label from ``labels``, never a name derived
from ``__file__``, which is what lets the in-place wrapper and the console route
print the same bytes.

Nothing here decides anything about a repository: the parser only turns argv
into the namespace the run reads.
"""

from __future__ import annotations

import argparse

from . import labels
from .census_render import (
    ITEM_STALE_AFTER_DEFAULT,
    ORDERING_CLOSED_NOT_EVALUATED,  # noqa: F401  (doc scraper)
    ORDERING_STALE_AFTER_DEFAULT,
    _warn_class_names,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=labels.CENSUS,
        description="The unified noni census: read-only checks over the steering "
        "ledger, the ordering artifact and the item store, with an honest "
        "exit code.",
    )
    parser.add_argument("--repo", default=".", help="the repository (or directory) to audit (default: current directory)")
    parser.add_argument("--ledger", default=None, help="ledger directory (default: <repo>/noni/decisions)")
    parser.add_argument("--ordering", default=None,
                        help="ordering artifact (default: "
                             "<repo>/noni/direction/order.json)")
    parser.add_argument("--intent", default=None, metavar="FILE",
                        help="standing intent file (default: "
                             "<repo>/noni/direction/intent.md); its citation is "
                             "answered against the --ledger of this run, so the "
                             "override moves the file and not the ledger")
    parser.add_argument("--items", default=None, metavar="DIR",
                        help="item store (default: <repo>/noni/items); absent is "
                             "not a finding, since an idea nobody filed earns no "
                             "row, but a store named here that cannot be listed is "
                             "reported by item-unlistable rather than reading as an "
                             "empty store")
    parser.add_argument("--issue-state", default=None, metavar="FILE",
                        help='JSON map {"<issue>": "open"|"closed"} produced by an adapter '
                             "or the operator; without it the ordering-closed check is not "
                             "evaluated (the census never contacts a tracker)")
    parser.add_argument("--now", default=None, metavar="ISO-8601", help="fixed timestamp for time-based checks (reproducible output)")
    parser.add_argument("--stale-after", default=ORDERING_STALE_AFTER_DEFAULT,
                        metavar="DAYS",
                        help=f"staleness threshold in positive whole days as `<N>` or `<N>d` "
                             f"(e.g. `7` or `7d`); the class keeps its own default "
                             f"({ORDERING_STALE_AFTER_DEFAULT} for order entries), and a "
                             "given value applies to every stale class")
    parser.add_argument("--strict", action="store_true",
                        help=f"treat warn classes ({_warn_class_names()}) as failures")
    parser.add_argument("--json", action="store_true", dest="json_out", help="emit NDJSON records on stdout (noni.census/1)")
    parser.add_argument("--only", action="append", default=None, metavar="CHECK", help="run only the named check(s); repeatable")
    parser.add_argument("--skip", action="append", default=None, metavar="CHECK", help="skip the named check(s); repeatable")
    parser.add_argument("--list", action="store_true", dest="list_checks", help="print the check ids and exit")
    return parser
