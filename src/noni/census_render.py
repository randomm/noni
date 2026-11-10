"""The check contract's renderings: the report, the thresholds, and the filters.

Split from ``census_report.py`` the way the census split its own body out: that
module owns the one declaration of the check contract (the ``CHECKS`` table and its
group sets), and this module owns everything the tool *renders* from it — the two
severity rules every row and the ``--strict`` help string read, the threshold and
filter helpers the CLI asks before it runs a group, the two sentences a run says
about a state it could not evaluate, and the two renderers that print the report.

Nothing here declares a class, a code or a severity: the names below read the table
through ``census_report``, so the contract keeps one owner and this file is a
rendering of it. ``census.py`` re-exports these names beside the table's own so a
caller that already imports the census still names them through it.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import timedelta

from ._safe_text import safe_path
from .census_report import (
    CLASS_FIX,
    CLASS_SEVERITY,
    SCHEMA_VERSION,
)

STALE_AFTER_RE = re.compile(r"^\d+d?$")

# One threshold flag and one threshold: --stale-after pins the class to the number the
# caller named, and without it the class gets the default that belongs to it (see the
# threshold block in the run's body for why the flag's presence decides, and
# :func:`_threshold` for how a default is parsed).
ORDERING_STALE_AFTER_DEFAULT = "30d"

# The one wording of the note that ``ordering-closed`` was not evaluated, declared
# beside the class whose fix hint repeats it: the human-readable branch prints it as
# a ``note:`` line, the NDJSON branch carries the same sentence on the summary
# record's ``not_evaluated`` field, so one run cannot say one thing in one mode and
# its opposite in the other. The docs that quote the literal are scraped from this
# constant, so a rename reddens the pages rather than leaving them quoting a line
# nothing prints.
#
# The class id the note is about is declared beside it rather than read out of its
# prose: the no-rows headline names that id, and the note's wording is the docs'
# property (three tests scrape the sentence). A headline that derived the class from
# the sentence's leading clause would be silently rewritten the next time somebody
# reworded that sentence, which is the drift this constant closes.
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
                      "holds no noni state, so the ledger, ordering and "
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


def _promote(severity: str, strict: bool) -> str:
    """The run-mode half of severity: a warn row is a failure under --strict.
    The one place that rule lives — both derivations below call it, so there is
    no second copy to drift."""
    return "fail" if strict and severity == "warn" else severity


def _severity(check: str, strict: bool) -> str:
    """The severity a row of ``check`` carries in this run: warn classes become
    failures under --strict, fail classes are unaffected."""
    return _promote(CLASS_SEVERITY[check], strict)


def _threshold(raw: str) -> timedelta:
    """The timedelta a `--stale-after`-shaped value names.

    The module's own defaults go through the same parse the flag's value does,
    so a default that stopped parsing would fail here rather than at the one
    caller that uses it. All three defaults are written in this file, so a bad
    value here is a bug, never hostile input; the ValueError is the assertion.
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


# The opening words of the row ``census_ordering.closed_state_unasked_row`` raises for
# an order whose closed state went unasked. The verdict line recognises that row by this
# prefix rather than by a second copy of the sentence: the row's wording is the product's
# and lives with the class that raises it, and a clause matched on a literal typed here
# would go quietly stale the next time that sentence was reworded.
CLOSED_STATE_UNASKED_PREFIX = "closed state not checked:"


def closed_state_verdict(notes: tuple[str, ...],
                         findings: list[dict] | tuple[dict, ...] = ()) -> str:
    """The clause of the verdict line saying the closed question went unasked, or "".

    A run over an order holding issues with no ``--issue-state`` leaves the whole closed
    question unasked, and a reader who judges the run by its last line (a CI step
    grepping the verdict, a person scanning a terminal) must not have to reach past the
    rows to a ``note:`` line to learn it. So the verdict carries the id of the class that
    went unasked.

    It is keyed on the closed row of this run's own rows, not on the note alone: the note
    says only that no state map came in, which is true of a tree that ordered nothing at
    all, and a verdict that called such a tree unchecked would say something the run did
    not observe. ``census_ordering.closed_state_unasked_row`` raises that row for exactly
    the orders whose closed state really was left unstated, so the clause and the row
    cannot disagree about which run was asked to check a closed order.

    Returns ``""`` rather than folding into the caller's sentence: the caller's all-clear
    branch is shared by every run that has nothing to report, and an empty string is what
    keeps every run that asked its closed question -- an empty order, an absent order, a
    run that skipped the class, or any run given ``--issue-state`` -- worded exactly as it
    was before this clause existed. The caller appends it to the all-clear word rather
    than replacing it: a run with no rows whose closed check went unasked still has no
    findings to count, so it says "clean" and then says what it did not check.
    """
    if ORDERING_CLOSED_NOT_EVALUATED not in notes:
        return ""
    owed = any(f["check"] == ORDERING_CLOSED_CHECK
               and f["message"].startswith(CLOSED_STATE_UNASKED_PREFIX) for f in findings)
    return f" {ORDERING_CLOSED_CHECK} not checked" if owed else ""


def _not_evaluated_headline(notes: tuple[str, ...]) -> str:
    """The clause of a no-rows headline that says which checks went unasked.

    A note is a sentence the product wrote for a reader, and this clause is a
    class id, so the two are not derived from each other: a note whose class this
    module knows about is named by that id (``ORDERING_CLOSED_CHECK`` beside the
    sentence itself), and the sentence may be reworded without rewriting the
    headline. A note this module does not know names nothing, so the clause falls
    back to a count rather than print a sentence as a class name — and because the
    known note is counted before that test, a known note can never be swallowed by
    the fallback. Several notes read as a list.
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
    """The comma-separated ids of every warn class, derived from the table — the
    --strict contract is written once, in the table, and appears here and in
    SKILL.md as a rendering of it rather than a fourth copy that can drift."""
    return ", ".join(name for name, sev in CLASS_SEVERITY.items() if sev == "warn")


# One shared sort key for every finding row, in both the --json (NDJSON) and
# human-readable branches: (artifact, check, subject). Both modes therefore
# emit the same findings in the same order.
def _finding_sort_key(f: dict) -> tuple[str, str, str]:
    """One shared sort key for every finding row, in both the --json (NDJSON)
    and human-readable branches: (artifact, check, subject)."""
    return (f["artifact"], f["check"], f["subject"])


def _render(
    findings: list[dict], counts: dict[str, int], ok: bool, exit_code: int,
    json_out: bool, notes: tuple[str, ...] = (),
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
    question went unasked rather than only that one did. The machine word of the
    summary line, ``verdict ok`` / ``verdict fail``, is keyed on ``ok`` alone and
    never moves: it is what the CI steps and the docs tests of this repository
    read, and ``--json`` carries the same fact as its own ``ok`` field.

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
        _render_json(findings, counts, ok, exit_code, notes)
        return
    _render_human(findings, counts, ok, exit_code, notes)


def _render_json(findings: list[dict], counts: dict[str, int], ok: bool,
                 exit_code: int, notes: tuple[str, ...]) -> None:
    """The NDJSON branch: one ``finding`` row per finding, then one ``summary`` row.

    The row kinds are closed (``finding`` and ``summary``, no more), which is what
    lets a machine consumer read the stream without a schema negotiation, and the
    notes ride the summary rather than becoming a third kind. The field is omitted
    when there is nothing to say, so a run that evaluated everything emits exactly
    the bytes it emitted before the field existed.
    """
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


def _render_human(findings: list[dict], counts: dict[str, int], ok: bool,
                  exit_code: int, notes: tuple[str, ...]) -> None:
    """The human branch: the opening note, the rows, the trailing notes, the verdict.

    The no-state-root note is the one sentence a caller needs BEFORE anything else:
    on a tree with no ``noni/``, the rows that follow all describe artifacts that are
    absent because the whole state root is missing, and a reader who meets them first
    reads a wrong --repo as a project that merely has not steered yet. So it opens the
    report, ahead of the headline and every row, and is excluded from the trailing
    block because it has already been said — which also keeps the all-clear banner
    honest (see its condition). The note selected here and the note suppressed below
    the rows are the same object compared by identity, so the two halves cannot
    disagree about which sentence has already been said: a second relation (a prefix
    here, an equality there) would let a note that merely opens the same way print
    twice in one report.

    The verdict line stays the last line of stdout: a CI step that reads the report's
    ending (tests/test_quickstart.py) must still find it there, so the notes sit above
    it, beside the findings they qualify.
    """
    state_note = next((n for n in notes if n.startswith(NO_STATE_ROOT_PREFIX)), None)
    if state_note is not None:
        print(f"note: {state_note}")
    warns = _warn_count(findings)
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
    fired = {f["check"] for f in findings}
    if ok:
        # ``closed_state_verdict`` returns the empty string for every run that asked
        # its closed question, and the all-clear word survives only when it did.
        verdict_text = (f"{warns} warning(s)" if warns else "clean") \
            + closed_state_verdict(notes, findings)
    else:
        verdict_text = f"{exit_code} ({', '.join(sorted(fired))})"
    print(f"summary: {verdict_text}; {sum(counts.values())} finding(s); "
          f"verdict {'ok' if ok else 'fail'}")
    if not ok:
        print(
            f"census: exit {exit_code}; the lowest class code wins — every check ran and "
            "every finding is reported above",
            file=sys.stderr,
        )


# The table's own derived views, re-exported for the callers that reached them
# through the census before the renderers were split out: one object each, never a
# copy, so the contract keeps its single owner in ``census_report``.
__all__ = [name for name in dir() if name.startswith("_")] + [
    "CLOSED_STATE_UNASKED_PREFIX",
    "NO_STATE_ROOT_NOTE", "NO_STATE_ROOT_PREFIX",
    "ORDERING_CLOSED_CHECK", "ORDERING_CLOSED_NOT_EVALUATED",
    "ORDERING_STALE_AFTER_DEFAULT", "STALE_AFTER_RE",
    "no_state_root_note",
]
