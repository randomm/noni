"""The census's check contract: the class table and the group sets beside it.

Split from ``census.py`` so each file stays the size one responsibility is worth,
and split again from ``census_render.py``, which owns what the tool *prints* from
this table (the severity rules, the thresholds, the two notes and the renderers):
``census.py`` owns the CLI, the probe seams, the row factory and the group wiring,
and this module owns the one declaration of the check contract (id -> code, default
severity, fix hint), the derived views of that table, and the frozensets that name
its groups.

The table is the single owner: the exit-code choice, ``--list``, the ``--strict``
help string and every row's code, severity and fix hint are derived from it, so
adding a class is one row here rather than five edits that can drift. ``census.py``
re-exports these names so a caller that already imports the census still names them
through it.
"""

from __future__ import annotations

from .census_items import ITEM_CHECKS, ITEM_ROWS  # noqa: F401  (the items group)

SCHEMA_VERSION = "noni.census/1"


# The ledger checks run as one group: any of the three triggers all three, so
# --only/--skip must be applied at group granularity. ledger-empty (42) is
# reported by the same group and adds rows only in the states where no record
# can be read (including a recordless decisions/ directory, which is a warn,
# not the ledger-record failure — operator decision on issue #33); it never
# weakens a malformed-record failure.
LEDGER_CHECKS = frozenset({"ledger-record", "ledger-edited", "ledger-chain"})
WHOLE_ARTIFACT_KEY = "_whole_artifact"

# The ordering group: the three checks share one read of the order artifact, so
# the group runs when any of them was asked for and the row filter keeps what
# the caller named. The fourth row of the group, the `cannot-tell` a run adds
# when --issue-state did not answer an entry's state, is a row of
# `ordering-closed` rather than a class of its own — it answers the closed
# question, so it carries that class's code (46) and, like every cannot-tell row,
# a warn by default that --strict promotes (see _append_cannot_tell).
# A missing order file is not a finding: the ordering layer is optional, so this
# group adds no row at all when the artifact is absent. The code itself lives in
# census_ordering.py beside this file (see the loader under 'Ordering checks').
ORDERING_CHECKS = frozenset({"ordering-malformed", "ordering-stale", "ordering-closed"})

# The intent group is one check over one file, so it needs no group set beside it
# the way the ledger and ordering groups do: the run's one --only rule
# (a group runs when any class of its reporting set was asked for) is decided for
# it by the name itself. The fourth subject of the class, `cannot-tell`, is a row
# of `intent` rather than a class of its own — it answers the citation question —
# and, like every cannot-tell row, it is a warn whatever --strict does not say
# (see the severity override in census_intent.check_intent). A missing
# noni/direction/intent.md is not a finding: standing intent is optional, so the
# group adds no row at all when the artifact is absent.
INTENT_CHECKS = frozenset({"intent"})

# The items group: the six checks share one readdir of ``noni/items/`` and one read
# of each file under it, so the group runs when any of them was asked for and the
# row filter keeps what the caller named. Their ids, codes, severities and fix hints
# are declared by the module that runs the group (``census_items.ITEM_ROWS``, beside
# the classes they describe) and merged into ``CHECKS`` below, so a class cannot
# exist in one place and not the other: the group set and the table rows are the two
# halves of one declaration, written in the same file, and a name missing from
# either is a KeyError at import rather than a class nobody can run or document.
# Like the ordering and intent groups, a missing store is not a finding: an idea
# nobody filed earns no row. Only a store that exists and cannot be listed earns
# ``item-unlistable``, and only then for the path the caller named with ``--items``
# (the ruling on the flag: the default path being absent is the state of a project
# that has never filed an idea, not a fault).

# --- Exit-code table ----------------------------------------------------------
# The class codes live in CHECKS below; 0 | 2 | 3 are reserved for non-class
# outcomes (clean, usage error, required tool missing).
EXIT_CLEAN = 0
EXIT_USAGE = 2
EXIT_TOOL_MISSING = 3

# The one declaration of the check contract: id -> (code, default severity,
# fix hint). Everything a caller can read about a class — its exit code, its
# severity with and without --strict, the fix hint on every row, the --list
# output and the --strict help string — is derived from this table, so adding
# a class means one row here rather than five edits that can drift.
CHECKS: dict[str, tuple[int, str, str]] = {
    "ledger-record": (
        10, "fail",
        "repair or remove the offending record, or pass the ledger directory of the right clone",
    ),
    "ledger-edited": (
        12, "fail",
        "supersede the record with a new file; never edit a committed record",
    ),
    "ledger-chain": (
        20, "fail",
        "repair the supersede chain so it resolves to exactly one live record per chain",
    ),
    "probe": (
        41, "warn",
        "fix the unreadable file or the git tree; a census that cannot read its input reports "
        "the probe failure, never clean",
    ),
    "ledger-empty": (
        42, "warn",
        "record at least one dated decision under the ledger directory (steer a question and "
        "commit the record), or pass the ledger directory of the clone that holds the decisions",
    ),
    "hygiene": (
        50, "warn",
        "remove the personal path, secret shape or deny-list name from the tracked file (rewrite "
        "history if it was ever committed), and keep the local deny-list present so the deny-list "
        "class stays active",
    ),
    "intent": (
        51, "fail",
        "repair noni/direction/intent.md to the four sections the direction skill documents "
        "(## Purpose, ## Principles, ## Never, ## Ask first, in that order, each once, with one "
        "'Last-confirmed: YYYY-MM-DD' line, within 200 lines) and write it with "
        "skills/direction/scripts/intent.py, which commits it as 'intent: <decision-id>' naming a "
        "record the ledger holds; an unreadable file is reported by this class and never as clean",
    ),
    "ordering-malformed": (
        15, "fail",
        "repair noni/direction/order.json to the noni.order/1 shape (schema, a unique positive "
        "issue, a live record id in `decision` and a UTC confirmed stamp per entry), or write "
        "it with skills/direction/scripts/order.py, which refuses the shapes this class reports",
    ),
    "ordering-stale": (
        45, "warn",
        "confirm the entry again (order.py confirm ISSUE, or confirm with no issue for the whole "
        "order); an entry nobody has confirmed since --stale-after is the operator's last word "
        "on the order only as far back as that",
    ),
    "ordering-closed": (
        46, "warn",
        # The note itself is the constant above this table, not prose here, and
        # its sentence is not restated below either: the human ``note:`` line and
        # the summary row's not_evaluated field carry one wording, three doc
        # tests scrape it from the constant, and tests/test_census_report_mode.py
        # refuses any fix hint containing it. A hint that spoke the note's words
        # would put "not evaluated" into a row of the class that did run, where
        # the class was evaluated and found nothing closed; the note belongs to
        # the note, the fix belongs to the fix.
        "remove the closed issue from the order (order.py remove ISSUE), or reopen it; the "
        "order is what to work on next, so an issue the tracker has closed does not "
        "belong in it. When --issue-state was not given the class adds no row at "
        "all, and the run prints its own note rather than leaving a rowless class "
        "to read as every ordered issue being open",
    ),
}

# Derived views of CHECKS — never edited by hand.
# The items group's six rows are declared by the module that runs them (see
# ``ITEM_ROWS`` above) and merged in here, so the table stays the one place a code,
# a severity or a fix hint is read from while the class itself keeps its own file.
CHECKS.update(ITEM_ROWS)

CLASS_CODE = {name: code for name, (code, _sev, _fix) in CHECKS.items()}
CLASS_SEVERITY = {name: sev for name, (_code, sev, _fix) in CHECKS.items()}
CLASS_FIX = {name: fix for name, (_code, _sev, fix) in CHECKS.items()}


def _known_checks(only: list[str] | None, skip: list[str] | None) -> list[str] | tuple[str, str]:
    """The ids this run reports: ``CHECKS`` narrowed by --only and --skip.

    A list of ids when both flags named classes the table knows, and a
    ``(kind, message)`` pair naming every unknown one when they did not: the run
    prints the message and returns its usage code, so the refusal is asked here,
    beside the table the names are checked against, and no filter can name a class
    that has no code, no severity and no fix hint to render.
    """
    known = list(CLASS_CODE)
    bad_only = [c for c in (only or []) if c not in known]
    bad_skip = [c for c in (skip or []) if c not in known]
    if bad_only:
        return ("error", f"unknown check: {', '.join(sorted(bad_only))} (known: {', '.join(known)})")
    if bad_skip:
        return ("error", f"unknown check: {', '.join(sorted(bad_skip))} (known: {', '.join(known)})")
    excluded = set(skip or [])
    if only:
        return [c for c in known if c in set(only) - excluded]
    return [c for c in known if c not in excluded]
