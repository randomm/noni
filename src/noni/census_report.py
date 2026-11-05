"""The census's check contract: the class table, its views, and the report.

Split from ``census.py`` so each file stays the size one responsibility is
worth: ``census.py`` owns the CLI, the probe seams, the row factory and the
group wiring, and this module owns the one declaration of the check contract
(id -> code, default severity, fix hint), the derived views of that table, the
two severity rules, the group filters, the threshold and filter helpers the CLI
asks before it runs a group, and the two renderers that print the report.

The table is the single owner: the exit-code choice, ``--list``, the
``--strict`` help string and every row's code, severity and fix hint are derived
from it, so adding a class is one row here rather than five edits that can
drift. ``census.py`` re-exports these names so a caller that already imports the
census still names them through it.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import timedelta

SCHEMA_VERSION = "noni.census/1"



# The ledger checks run as one group: any of the three triggers all three, so
# --only/--skip must be applied at group granularity. ledger-empty (42) is
# reported by the same group and adds rows only in the states where no record
# can be read (including a recordless decisions/ directory, which is a warn,
# not the ledger-record failure — operator decision on issue #33); it never
# weakens a malformed-record failure.
LEDGER_CHECKS = frozenset({"ledger-record", "ledger-edited", "ledger-chain"})
# The session register group, likewise: the checks share one read of the
# register, so the group runs together and the row filter decides what is kept.
SESSION_CHECKS = frozenset({
    "session-double", "session-claim", "session-malformed", "session-stalled",
    "session-same-identity", "session-deleted", "probe",
})
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
# the way the ledger, sessions and ordering groups do: the run's one --only rule
# (a group runs when any class of its reporting set was asked for) is decided for
# it by the name itself. The fourth subject of the class, `cannot-tell`, is a row
# of `intent` rather than a class of its own — it answers the citation question —
# and, like every cannot-tell row, it is a warn whatever --strict does not say
# (see the severity override in census_intent.check_intent). A missing
# noni/direction/intent.md is not a finding: standing intent is optional, so the
# group adds no row at all when the artifact is absent.
INTENT_CHECKS = frozenset({"intent"})

# One threshold flag, two thresholds: --stale-after pins both classes to the
# number the caller named, and without it each class gets the default that
# belongs to it (see the threshold block in main for why the flag's presence
# decides, and _threshold for how a default is parsed).
SESSION_STALE_AFTER_DEFAULT = "7d"
ORDERING_STALE_AFTER_DEFAULT = "30d"
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
    "session-double": (
        30, "fail",
        "release the claim on the task in one session, or record who keeps it as a ledger decision",
    ),
    "session-claim": (
        31, "fail",
        "register the session (add the identity field) or move the orphan claim into a registered session file",
    ),
    "session-malformed": (
        32, "fail",
        "restore the missing field or add the missing task reference to the claim row",
    ),
    "session-stalled": (
        40, "warn",
        "close the session or commit a fresh register update if the work is still in flight",
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
    "session-same-identity": (
        43, "warn",
        "give each session file its own identity, or close the stale session files so only one "
        "non-terminal file carries that identity",
    ),
    "session-deleted": (
        44, "warn",
        "restore the session file (git checkout <commit> -- <path>) — ending a session goes "
        "through its status field, never through deleting the register file",
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
        "issue and a UTC confirmed stamp per entry, decision a live record id or null), or write "
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
        "remove the closed issue from the order (order.py remove ISSUE), or reopen it; the order "
        "is what to work on next, so an issue the tracker has closed does not belong in it",
    ),
}

# Derived views of CHECKS — never edited by hand.
CLASS_CODE = {name: code for name, (code, _sev, _fix) in CHECKS.items()}
CLASS_SEVERITY = {name: sev for name, (_code, sev, _fix) in CHECKS.items()}
CLASS_FIX = {name: fix for name, (_code, _sev, fix) in CHECKS.items()}
def _promote(severity: str, strict: bool) -> str:
    """The run-mode half of severity: a warn row is a failure under --strict.
    The one place that rule lives — both derivations below call it, so there is
    no second copy to drift."""
    return "fail" if strict and severity == "warn" else severity


def _severity(check: str, strict: bool) -> str:
    """The severity a row of ``check`` carries in this run: warn classes become
    failures under --strict, fail classes are unaffected."""
    return _promote(CLASS_SEVERITY[check], strict)


STALE_AFTER_RE = re.compile(r"^\d+d?$")
def _threshold(raw: str) -> timedelta:
    """The timedelta a `--stale-after`-shaped value names.

    The module's own defaults go through the same parse the flag's value does,
    so a default that stopped parsing would fail here rather than at the one
    caller that uses it. Both defaults are written in this file, so a bad value
    here is a bug, never hostile input; the ValueError is the assertion.
    """
    if not STALE_AFTER_RE.fullmatch(raw):
        raise AssertionError(f"census default {raw!r} is not a stale-after threshold")
    return timedelta(days=int(raw.rstrip("dD")))


def _warn_class_names() -> str:
    """The comma-separated ids of every warn class, derived from CHECKS — the
    --strict contract is written once, in the table, and appears here and in
    SKILL.md as a rendering of it rather than a fourth copy that can drift."""
    return ", ".join(name for name, (_code, sev, _fix) in CHECKS.items() if sev == "warn")

def _known_checks(only: list[str] | None, skip: list[str] | None) -> list[str] | tuple[str, str]:
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

# One shared sort key for every finding row, in both the --json (NDJSON) and
# human-readable branches: (artifact, check, subject). Both modes therefore
# emit the same findings in the same order.
def _finding_sort_key(f: dict) -> tuple[str, str, str]:
    """One shared sort key for every finding row, in both the --json (NDJSON)
    and human-readable branches: (artifact, check, subject)."""
    return (f["artifact"], f["check"], f["subject"])


def _render(
    findings: list[dict], counts: dict[str, int], ok: bool, exit_code: int, json_out: bool
) -> None:
    """Emit the results in either NDJSON (--json) or human-readable form."""
    if json_out:
        for f in sorted(findings, key=_finding_sort_key):
            row = {
                "schema": SCHEMA_VERSION,
                "kind": "finding",
                "check": f["check"],
                "code": f["code"],
                "severity": f["severity"],
                "subject": f["subject"],
                "artifact": f["artifact"],
                "message": f["message"],
                "fix": CLASS_FIX[f["check"]],
            }
            print(json.dumps(row, sort_keys=True))
        counts_row = {k: v for k, v in counts.items() if v}
        print(
            json.dumps(
                {"schema": SCHEMA_VERSION, "kind": "summary", "ok": ok, "exit": exit_code, "counts": counts_row},
                sort_keys=True,
            )
        )
    else:
        fired = {f["check"] for f in findings}
        if not findings:
            print("census: no findings; all checks passed")
        else:
            for f in sorted(findings, key=_finding_sort_key):
                tag = {"fail": "FAIL", "warn": "WARN"}.get(f["severity"], "?")
                print(f"{f['check']:<16} {tag:<4} {f['subject']}: {f['message']}")
                print(f"{'':<16} fix: {CLASS_FIX[f['check']]}")
        if ok:
            verdict_text = "clean"
        else:
            verdict_text = f"{exit_code} ({', '.join(sorted(fired))})"
        print(f"summary: {verdict_text}; {sum(counts.values())} finding(s); verdict {'ok' if ok else 'fail'}")
        if not ok:
            print(
                f"census: exit {exit_code}; the lowest class code wins — every check ran and "
                "every finding is reported above",
                file=sys.stderr,
            )
