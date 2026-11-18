"""What the census headline counts, rendered in-process (issue #191).

The headline used to print the warn count and the row count side by side
(``census: 2 warning(s), 2 finding(s)``). A run of two warnings read as four
problems, because the finding total already held the two warnings. The line now
states the row total once and splits it in parentheses,
``census: 2 finding(s) (0 fail, 2 warn)``, so the two numbers that are one fact
are printed as one fact.

The whole-line pins live here rather than in ``tests/test_census_human_report.py``
(a size split of that file, not a new suite): each test builds its own findings
list and asks the renderer to print it, with no git tree and no subprocess
between the assertion and the string. That seam is the one the separator
regressions below already used, and it is what makes the states a real tree
cannot be coaxed into -- a fail row beside warn rows -- reachable.

Everything the tests do not name is pinned where it already was: the rowless
lines, the ``note:`` lines, the summary line and ``--json`` are the business of
``tests/test_census_human_report.py`` and the pinned-bytes fixture.
"""

from __future__ import annotations


def _warn_row(check: str = "hygiene", subject: str = "deny-list") -> dict:
    """One warn row of a hand-built run, carrying the fields the renderer reads."""
    return {"check": check, "severity": "warn", "subject": subject,
            "artifact": subject, "message": "not a hygiene-clean guarantee"}


def _fail_row(check: str = "ledger-record",
              subject: str = "2026-10-01-alpha.json") -> dict:
    """One fail row of a hand-built run, same fields as its warn twin."""
    return {"check": check, "severity": "fail", "subject": subject,
            "artifact": "noni/decisions", "message": "malformed: bad field"}


def _unasked_closed_row() -> dict:
    """The row the closed class raises when an order got no ``--issue-state``.

    The headline recognises the clause's own row by the class id and these opening
    words, so a test that wants the "not checked" wording has to carry the row, not
    only the note.
    """
    return {"check": "ordering-closed", "severity": "warn",
            "subject": "noni/direction/order.json",
            "artifact": "noni/direction/order.json",
            "message": "closed state not checked: no --issue-state FILE was given"}


def _counted(findings: list[dict]) -> dict[str, int]:
    """The counts dict of one hand-built findings list, keyed by check.

    The renderer receives the per-class row counts beside the rows, so an
    in-process test has to hand over something consistent with them. Built here
    rather than typed per test so a test cannot pin a headline against a counts
    dict that disagrees with its own rows.
    """
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding["check"]] = counts.get(finding["check"], 0) + 1
    return counts


def _report_of(findings: list[dict],
               notes: tuple[str, ...] = ()) -> list[str]:
    """The lines of one hand-built human report, rendered in this interpreter.

    ``_render`` is asked to print a report the caller built row by row: the exit
    code and ``ok`` follow from the rows, since a fail row is what makes a run
    fail, and the caller names no exception to that.
    """
    import io
    import sys as _sys

    from noni.census_render import _render

    buf = io.StringIO()
    saved = _sys.stdout
    _sys.stdout = buf
    try:
        _render(list(findings), _counted(findings),
                not any(f["severity"] == "fail" for f in findings), 0, False, notes)
    finally:
        _sys.stdout = saved
    return buf.getvalue().splitlines()


def _headline_of(findings: list[dict],
                 notes: tuple[str, ...] = ()) -> str:
    """The headline of one hand-built run, selected by its ``census: `` prefix.

    Selected rather than taken by position because a report can open with a
    ``note: `` line (the no-state-root note precedes the headline), and the
    renderer also prints a ``census: exit`` sentence on stderr for a failing run,
    which this capture never sees.
    """
    lines = _report_of(findings, notes)
    headline = [line for line in lines if line.startswith("census:")]
    assert headline, lines
    return headline[0]


def test_a_warn_only_run_headlines_every_finding_as_warn():
    """The finding total is stated once and split by severity (issue #191).

    The old line read ``census: 2 warning(s), 2 finding(s)`` above the same two
    rows, which readers took as four problems. This is the descriptor's own
    example, and the whole-line pin the ticket asks for: warn rows alone.
    """
    findings = [_warn_row("hygiene"), _warn_row("ordering-stale", "#7")]
    assert _headline_of(findings) == "census: 2 finding(s) (0 fail, 2 warn)"


def test_a_fail_only_run_headlines_every_finding_as_fail():
    """The zero half of the split is spelled out, not hidden.

    A run of two fail rows used to open ``census: 0 warning(s), 2 finding(s)``;
    the new line keeps saying zero, because a reader who is told "2 finding(s)"
    and nothing else cannot tell whether any of them failed.
    """
    findings = [_fail_row(subject="a.json"), _fail_row(subject="b.json")]
    assert _headline_of(findings) == "census: 2 finding(s) (2 fail, 0 warn)"


def test_a_mixed_run_splits_the_findings_between_fail_and_warn():
    """The fail and warn halves add up to the total printed before them.

    One fail row and two warn rows is the shape the old headline read worst: it
    named two warnings and three findings, so the reader had to work out on their
    own which of the three were which.
    """
    findings = [_fail_row(), _warn_row("hygiene"), _warn_row("ordering-stale", "#7")]
    assert _headline_of(findings) == "census: 3 finding(s) (1 fail, 2 warn)"


def test_a_strict_promotion_moves_a_row_to_the_fail_half_of_the_headline():
    """A promoted row is a fail in the headline, counted the way the tag reads it.

    ``--strict`` rewrites the rendered severity of a warn row before the renderer
    sees it, so the split cannot come from the class table: a promoted row prints
    ``FAIL`` and belongs in the fail half, which is what the split reads. Here it
    is the run's only row, the state the ticket names for ``--strict``.
    """
    promoted = dict(_warn_row("ledger-edited", "2026-10-01-alpha"))
    promoted["severity"] = "fail"
    assert _headline_of([promoted]) == "census: 1 finding(s) (1 fail, 0 warn)"


def test_a_warn_row_of_a_fail_class_lands_in_the_warn_half_of_the_headline():
    """The split reads the row's own severity, the same field the ``WARN`` tag reads.

    A row of a fail class that carries ``warn`` severity (the cannot-verify and
    cannot-tell rows of probe honesty) is a warning to the tag beside it, so it
    must be a warning in the headline too: a split taken from the class table
    would print ``(1 fail, 0 warn)`` above a printed ``WARN`` row, which is the
    issue #117 inversion in a new place. Derived from the run's rows and never
    from the counts dict, which counts rows per class and holds no severity.
    """
    findings = [_warn_row("ledger-edited", "2026-10-01-alpha.json"),
                _fail_row()]
    assert _headline_of(findings) == "census: 2 finding(s) (1 fail, 1 warn)"


def test_the_counts_clause_keeps_its_comma_after_the_parenthesis():
    """The not-evaluated clause still opens with its own separator.

    The clause now lands after the closing parenthesis, and issue #166's fix is
    what keeps the comma and space in front of it: glued, the counts and the
    class id rendered as one garbled token. The run carries the closed class's own
    row, which is what makes the clause say "not checked" rather than "did not
    run" (issue #148).
    """
    from noni.census_render import ORDERING_CLOSED_NOT_EVALUATED

    findings = [_warn_row("hygiene"), _warn_row("ordering-stale", "#7"),
                _unasked_closed_row()]
    assert _headline_of(findings, (ORDERING_CLOSED_NOT_EVALUATED,)) == (
        "census: 3 finding(s) (0 fail, 3 warn), ordering-closed not checked")


def test_not_evaluated_note_without_a_named_class_glues_nothing():
    """A not-evaluated note naming no class contributes no headline clause.

    Regression: the counts branch used to append ``{n} check(s) did not run``
    flush against the counts (``1 finding(s)1 check(s) did not run``). With no
    named class the headline carries no extra clause at all: the first line is
    exactly the counts, and the note line below the rows says what was not
    evaluated.
    """
    from noni.census_render import NO_STATE_ROOT_NOTE

    findings = [_warn_row("hygiene", "noni/direction/order.json")]
    note = NO_STATE_ROOT_NOTE.format(repo="state/repo")
    lines = _report_of(findings, (note,))
    headline = [line for line in lines if line.startswith("census:")][0]
    assert headline == "census: 1 finding(s) (0 fail, 1 warn)", lines[:3]
    assert "did not run" not in headline, headline
    assert f"note: {note}" in lines, lines


def test_rowless_run_naming_a_class_keeps_the_semicolon():
    """A rowless run that names a class separates the clause with a semicolon.

    `census: no findings; ordering-closed did not run` -- the rowless site keeps
    the semicolon it had before issue #166's PR glued the clause onto the counts
    with a comma. The counts site keeps its comma.
    """
    from noni.census_render import ORDERING_CLOSED_NOT_EVALUATED

    lines = _report_of([], (ORDERING_CLOSED_NOT_EVALUATED,))
    headline = [line for line in lines if line.startswith("census:")][0]
    assert headline == "census: no findings; ordering-closed did not run", lines


def test_rowless_run_whose_note_names_no_class_prints_only_no_findings():
    """A rowless run whose note names no class prints exactly `census: no findings`.

    No trailing semicolon, and never the all-clear banner: a note exists, so the
    run is not all-clear. The note itself still prints below the rows.
    """
    from noni.census_render import NO_STATE_ROOT_NOTE

    note = NO_STATE_ROOT_NOTE.format(repo="state/repo")
    lines = _report_of([], (note,))
    headline = [line for line in lines if line.startswith("census:")][0]
    assert headline == "census: no findings", lines
