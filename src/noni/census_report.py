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

from ._safe_text import safe_path

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

# The one wording of the note that ``ordering-closed`` was not evaluated, declared
# above the table that quotes it: the human-readable branch prints it as a
# ``note:`` line, the NDJSON branch carries the same sentence on the summary
# record's ``not_evaluated`` field, and the fix hint of the class repeats it, so
# one run cannot say one thing in one mode and its opposite in the other. The
# docs that quote the literal are scraped from this constant, so a rename reddens
# the pages rather than leaving them quoting a line nothing prints.
# The class id the note above is about, declared beside it rather than read out
# of its prose: the no-rows headline names this id, and the note's wording is the
# docs' property (three tests scrape the sentence). A headline that derived the
# class from the sentence's leading clause would be silently rewritten the next
# time somebody reworded that sentence, which is the drift this constant closes.
ORDERING_CLOSED_CHECK = "ordering-closed"
ORDERING_CLOSED_NOT_EVALUATED = (
    "ordering-closed was not evaluated: no --issue-state FILE was given, so whether "
    "an ordered issue is closed is not asked (the census never contacts a tracker)")

# The one sentence a run prints when the tree --repo names holds no ``noni/`` at all:
# the shape a caller reaches by pointing the census at a code repository instead of a
# state root. Carried on the same channel as the ordering-closed note (one ``note:``
# line in human mode, the summary row's ``not_evaluated`` list in ``--json`` mode) so
# no new check class and no third NDJSON row kind are needed, and so the exit code of
# a no-``noni/`` tree stays exactly what it was: ledger-empty remains the warn row it
# already was (0, or 42 under ``--strict``). Keyed on the ledger probe's ``absent``
# state, which the probe answers only when ``noni/`` itself is missing -- a
# ``noni/`` that is a file or a symlink is already worded by its own row and is not
# collapsed into this sentence. The path is --repo as the caller spelled it, never a
# resolved absolute path (see the machine-local-path rule in ``census.py``).
NO_STATE_ROOT_NOTE = ("no noni/ directory was found under --repo {repo}: this tree "
                      "holds no noni state, so the ledger, sessions, ordering and "
                      "intent groups had nothing to read (pass --repo naming the "
                      "state root, the directory that holds noni/)")


def no_state_root_note(repo: str) -> str:
    """The no-``noni/`` sentence for one ``--repo`` as the caller spelled it.

    A function rather than a constant because the path varies per run, and the path
    is the caller's spelling rather than the resolved tree: a census row never carries
    a machine-local absolute path the operator did not type. The path is a value from
    argv, so it is rendered here, once, through :func:`noni._safe_text.safe_path`: a
    name carrying a newline would otherwise split this note across two stdout lines and
    break the contract that it opens the report as one line and the verdict closes it.
    """
    return NO_STATE_ROOT_NOTE.format(repo=safe_path(repo))


# The opening words of the note above, which is how the human branch recognises it:
# the sentence it prints first, and the only note kept out of the trailing ``note:``
# block. Derived from the template rather than restated, so a reworded note cannot
# leave the two halves disagreeing about which sentence opens the report.
NO_STATE_ROOT_PREFIX = NO_STATE_ROOT_NOTE.split(" {repo}", 1)[0]

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


def _warn_count(findings: list[dict]) -> int:
    """How many rows of this run are warnings, read off the rows themselves.

    Counted off the rendered ``severity`` of each row and nowhere else: the
    headline, the verdict word and the ``WARN``/``FAIL`` tag beside every row all
    read the same field, so one run cannot answer "was this a warning?" two ways.
    Asking the class table instead is what used to go wrong here — a row whose
    *class* is a fail class but whose own severity is ``warn`` (the cannot-verify
    and cannot-tell rows of probe honesty, escalated only under ``--strict``)
    printed ``WARN`` above a headline that counted it as neither a warning nor
    clean (issue #117).

    ``--strict`` is what a class-table count was there for, and it does not need
    one: a promotion is a no-op for the report, because it moves the row's tag
    and its count together. A promoted row reads ``FAIL`` and leaves the warn
    count, and the exit code it earns is what the summary line says instead of a
    warn count — so the strict run is not double-reported as a warning, and the
    run that merely could not read its input is not quietly un-counted.

    Derived from the run's own rows and never handed in beside them: a number a
    caller passed could disagree with the rows printed above it.
    """
    return sum(1 for f in findings if f["severity"] == "warn")


def _not_evaluated_headline(notes: tuple[str, ...]) -> str:
    """The clause of a no-rows headline that says which checks went unasked.

    A note is a sentence the product wrote for a reader, and this clause is a
    class id, so the two are not derived from each other: a note whose class this
    module knows about is named by that id (``ORDERING_CLOSED_CHECK`` beside the
    sentence itself), and the sentence may be reworded without rewriting the
    headline. A note this module does not know names nothing, so the clause falls
    back to a count rather than print a sentence as a class name — and because
    the known note is counted before that test, a known note can never be
    swallowed by the fallback. Several notes read as a list.
    """
    named = [ORDERING_CLOSED_CHECK for note in notes
             if note == ORDERING_CLOSED_NOT_EVALUATED]
    unknown = sum(1 for note in notes
                  if note != ORDERING_CLOSED_NOT_EVALUATED and not note.strip())
    if not named:
        return f"{unknown or len(notes)} check(s) did not run"
    if unknown:
        return f"{', '.join(named)}, {unknown} other check(s) did not run"
    return f"{', '.join(named)} did not run"


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


# The one wording of the human and NDJSON note lives above CHECKS, beside the
# class whose fix hint repeats it (``ORDERING_CLOSED_NOT_EVALUATED``).
def _render(
    findings: list[dict], counts: dict[str, int], ok: bool, exit_code: int, json_out: bool,
    notes: tuple[str, ...] = (),
) -> None:
    """Emit the results in either NDJSON (--json) or human-readable form.

    ``notes`` is what a run observed about a class it did not evaluate (the
    ordering-closed note today). Human mode prints each as its own ``note:`` line
    beside the report; the NDJSON branch prints none of them on stdout and puts
    them on the one summary row instead, under ``not_evaluated``, so a machine
    consumer loses nothing to the mode it picked and the closed set of row kinds
    (``finding``, ``summary``) stays closed. The field is omitted when there is
    nothing to say, so a run that evaluated everything keeps the byte stream it
    had before the field existed.

    The human branch says nothing that is not true of the run it renders. The
    all-clear banner needs both halves of "nothing to report" — no rows *and*
    no note — and the verdict word of the summary line follows the number of
    rows tagged ``WARN``, not ``ok`` alone, so a run that counted warnings does
    not read ``clean`` and a run that skipped a check does not read ``all checks
    passed`` (issue #117). The count is the same field the ``WARN`` tag beside
    each row is read from, so a row that prints ``WARN`` is a warning in the
    headline too, whatever its class's default severity says. A headline about
    skipped checks names the classes the notes name, so the report says *which*
    question went unasked rather than only that one did. The machine word of the summary line, ``verdict ok`` /
    ``verdict fail``, is keyed on ``ok`` alone and never moves: it is what the
    CI steps and the docs tests of this repository read, and ``--json`` carries
    the same fact as its own ``ok`` field.

    ``census notes must be a tuple`` is the field's contract, and ``tuple`` is
    part of it, not just the elements: the producer in ``census_run`` hands over
    a tuple, and a one-note caller that passed a bare ``str`` would otherwise
    sail through the element check and then have its sentence split character by
    character into ``note: o``, ``note: r``, ... lines (and a string spread into
    ``not_evaluated``), which is the per-mode-diverging shape this field exists
    to prevent. A dict or a pair would print as a ``note: {...}`` line in one
    mode and an object inside a list in the other, so a producer is refused here
    rather than a consumer surprised later.
    """
    if not isinstance(notes, tuple):
        raise TypeError(
            f"census notes must be a tuple of sentences, "
            f"got {type(notes).__name__}: {notes!r}")
    for note in notes:
        if not isinstance(note, str):
            raise TypeError(
                f"a census note must be a sentence, got {type(note).__name__}: {note!r}")
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
        summary = {"schema": SCHEMA_VERSION, "kind": "summary", "ok": ok,
                   "exit": exit_code, "counts": counts_row}
        if notes:
            summary["not_evaluated"] = list(notes)
        print(json.dumps(summary, sort_keys=True))
    else:
        fired = {f["check"] for f in findings}
        warns = _warn_count(findings)
        # The no-state-root note is the one sentence a caller needs BEFORE anything
        # else: on a tree with no ``noni/``, the rows that follow all describe
        # artifacts that are absent because the whole state root is missing, and a
        # reader who meets them first reads a wrong --repo as a project that merely
        # has not steered yet. So it opens the human report, ahead of the headline and
        # every row. It is excluded from ``notes`` below because it has already been
        # said, which also keeps the all-clear banner honest (see its condition). The
        # note selected here and the note suppressed below the rows are the same object
        # compared by identity, so the two halves cannot disagree about which sentence
        # has already been said: a second relation (a prefix here, an equality there)
        # would let a note that merely opens the same way print twice in one report.
        state_note = next((n for n in notes if n.startswith(NO_STATE_ROOT_PREFIX)), None)
        if state_note is not None:
            print(f"note: {state_note}")
        if not findings and not notes:
            print("census: no findings; all checks passed")
        elif not findings:
            # "Nothing to report" is two facts, and the headline says the one
            # that is true of this run: no rows, and these checks unasked.
            print(f"census: no findings; {_not_evaluated_headline(notes)}")
        else:
            print(f"census: {warns} warning(s), {len(findings)} finding(s)")
            for f in sorted(findings, key=_finding_sort_key):
                tag = {"fail": "FAIL", "warn": "WARN"}.get(f["severity"], "?")
                print(f"{f['check']:<16} {tag:<4} {f['subject']}: {f['message']}")
                print(f"{'':<16} fix: {CLASS_FIX[f['check']]}")
        for note in notes:
            # Reprinting the state-root note would say the same sentence twice in one
            # report; the ordering-closed note and any other still print here, below
            # the rows they qualify.
            if note is not state_note:
                print(f"note: {note}")
        if ok:
            verdict_text = (f"{warns} warning(s)" if warns else "clean")
        else:
            verdict_text = f"{exit_code} ({', '.join(sorted(fired))})"
        # The verdict line stays the last line of stdout: a CI step that reads the
        # report's ending (tests/test_quickstart.py) must still find it there, so
        # the notes sit above it, beside the findings they qualify.
        print(f"summary: {verdict_text}; {sum(counts.values())} finding(s); verdict {'ok' if ok else 'fail'}")
        if not ok:
            print(
                f"census: exit {exit_code}; the lowest class code wins — every check ran and "
                "every finding is reported above",
                file=sys.stderr,
            )
