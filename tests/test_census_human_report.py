"""What the census's human report says about the run it renders (issue #117).

The human branch has two lines a reader judges the run by: its headline and its
summary line, the last line of stdout. Before this issue the headline claimed
"all checks passed" whenever no row had been printed -- above the very
``note: ordering-closed was not evaluated`` line that says a check did not run --
and the summary line said ``clean`` whenever the exit code was 0, which is every
run whose only findings are warnings. Both now read off what the run actually
held, and these tests pin all three states plus the counter-case that keeps the
fix honest: a run with no rows and no note still reads as all-clear.

The machine half of the contract is pinned here as well, because it is the half a
wording change could damage: ``verdict ok`` / ``verdict fail`` is keyed on the
exit code alone and moves not at all (the CI readers in
``tests/test_quickstart.py``, ``tests/test_quickstart_ci.py`` and
``tests/test_onboarding.py`` key on it), and ``--json`` keeps its NDJSON bytes.

Split out of ``tests/test_census_reporting.py`` for the size limit; the builders
are in ``tests/census_fixtures.py`` and the runners in ``tests/census_run.py``.
"""

from __future__ import annotations

import json

from _harness import _commit_file, _init_repo
from census_fixtures import _ndjson_rows, _valid_record
from census_run import _run_census


class TestHumanVerdict:
    """The human branch says nothing that is not true of the run (issue #117).

    Two lines carry the promise. The first line of a report is its headline, and
    the last is the line a CI step reads; before this issue the first claimed
    "all checks passed" whenever no row had been printed -- above a
    ``note: ordering-closed was not evaluated`` line -- and the last said
    ``summary: clean`` whenever the exit code was 0, which is every run whose
    only findings are warnings. Both are keyed to what the run actually held:
    the banner needs no rows *and* no note, and the verdict word of the summary
    line follows the warn count rather than ``ok`` alone.

    The machine tail of the last line is the other half of the contract and is
    pinned here too: ``verdict ok`` / ``verdict fail`` is keyed on the exit code
    alone, so the wording changes move it not at all (the CI readers in
    ``tests/test_quickstart.py``, ``tests/test_quickstart_ci.py`` and
    ``tests/test_onboarding.py`` all key on it).
    """

    ALL_CLEAR = "census: no findings; all checks passed"

    def _warn_only_tree(self, tmp_path, name="warn-only"):
        """A tree whose only rows are warnings: one committed record (so the
        ledger group is silent), and no deny-list, which is the always-reporting
        hygiene warn. Exit 0, so the old renderer called this ``clean``."""
        repo = _init_repo(tmp_path / name)
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                     json.dumps(_valid_record(), indent=2))
        return repo

    def _first_line(self, out: str) -> str:
        lines = out.splitlines()
        assert lines, "the human report printed nothing"
        return lines[0]

    def test_warn_only_run_does_not_say_all_checks_passed(self, tmp_path):
        """A run whose rows are all warnings names the warn count in both places."""
        repo = self._warn_only_tree(tmp_path)
        rc, out, err = _run_census(repo, "--now", "2026-10-02T00:00:00Z")
        assert rc == 0, f"warn rows alone exit 0, got {rc}\n{out}\n{err}"
        assert "WARN" in out, f"the run must carry a warn row to test this: {out}"
        first = self._first_line(out)
        assert first != self.ALL_CLEAR, (
            f"a warn-bearing run printed the all-clear banner: {first!r}")
        assert "no findings" not in first, (
            f"the headline denied findings the report prints below it: {first!r}")
        assert "all checks passed" not in first, (
            f"the headline claimed every check passed above warn rows: {first!r}")
        assert "1 warning(s)" in first, (
            f"the headline did not name the warn count: {first!r}")
        last = out.splitlines()[-1]
        assert not last.startswith("summary: clean"), (
            f"the summary line called a warn-bearing run clean: {last!r}")
        assert "1 warning(s)" in last, (
            f"the summary line did not name the warn count: {last!r}")
        assert last.endswith("verdict ok"), (
            f"the machine word of the summary line moved: {last!r}")

    def test_not_evaluated_note_suppresses_the_all_checks_passed_line(
        self, tmp_path,
    ):
        """A class that went unasked is said by the report while it has no row.

        The headline clause and the row are not two ways of saying one thing, and this
        case pins the state where only the clause is left: an order that names no issue
        owes the note and no row, so the run prints rows of no class that could name the
        closed one, and the headline's clause is the only thing saying which check did not
        run. That is also the state the bug hid best -- nothing fired, so the banner was
        the truth of the rows and a lie about the run. An emptied order is the tree for it
        (an absent order answers "nothing was ordered" and owes no note at all, and an
        order of blanks is the malformed class's to answer), and the counter-cases are
        pinned below so the clause is not "always say unchecked".

        Issue #148 gave the stricter case -- an order that does hold issues -- a row of its
        own, which is what gives ``--strict`` a code to return; that run's headline is the
        row-bearing one, and its verdict line is pinned in
        :meth:`test_the_verdict_line_names_the_class_whose_row_it_carries`.
        """
        from ordering_fixtures import ORDER_REL, _commit, _entry, _repo, _seed
        from quickstart_page import ordering_note_from_product

        repo = _repo(tmp_path, "note-only")
        _seed(repo, _entry(7, "2026-10-01-baseline"))
        # The rowless half, built by the tree and not the filter: an order that names no
        # issue owes no row of the class, so the run prints a note and rows of no class
        # that could name it, and the headline's clause is the only thing saying which
        # check did not run. An emptied order is the tree for it -- an absent order answers
        # "nothing was ordered" and owes no note at all, and an order of blanks is the
        # malformed class's to answer -- and the counter-cases are pinned below.
        empty = _repo(tmp_path, "note-only-empty")
        _seed(empty, _entry(7, "2026-10-01-baseline"))
        _commit(empty, ORDER_REL, '{"schema": "noni.order/1", "entries": []}')
        rc, out, err = _run_census(empty, "--skip", "hygiene",
                                   "--now", "2026-10-27T12:00:00Z")
        assert rc == 0, f"an order naming no issue asks no closed question: {rc}"
        assert "note: " in out, f"the note line is what this run reports: {out}"
        assert ordering_note_from_product() in out, (
            f"the note is not the product's own sentence: {out}")
        assert "closed state not checked" not in out, (
            f"an order that names no issue owes no row of the class: {out}")
        first = self._first_line(out)
        assert first != self.ALL_CLEAR, (
            f"a run that skipped a check printed the all-clear banner: {first!r}")
        assert "all checks passed" not in first, (
            f"the headline claimed every check passed above a not-evaluated "
            f"note: {first!r}")
        assert "ordering-closed" in first, (
            f"the headline did not name the class that did not run: {first!r}")
        assert out.splitlines()[-1].endswith("verdict ok"), out

        # The rowless run's counter-cases, so the clause is not "always say unchecked".
        # A run given the state map asked its question, and a run whose class was skipped
        # by name is not an unchecked one: neither may carry the clause.
        state = repo.parent / "state-note-only.json"
        state.write_text('{"7": "open"}', encoding="utf-8")
        rc, out, err = _run_census(repo, "--now", "2026-10-27T12:00:00Z",
                                   "--issue-state", str(state))
        assert rc == 0, f"a closed check that was answered: {rc}\n{out}\n{err}"
        assert "not checked" not in out.splitlines()[-1], (
            f"a run that asked its closed question was worded as one that did not: "
            f"{out.splitlines()[-1]!r}")
        rc, out, err = _run_census(repo, "--now", "2026-10-27T12:00:00Z",
                                   "--skip", "ordering-closed")
        assert rc == 0, f"a run that skipped the class: {rc}\n{out}\n{err}"
        assert "not checked" not in out.splitlines()[-1], (
            f"a skipped class is not an unchecked one: {out.splitlines()[-1]!r}")
        assert "ordering-closed was not evaluated" not in out, (
            f"a class the operator asked away must not be reported as unasked: {out}")

        # The other half: the run that carries the row, whose headline must count it and
        # still name the class. Same tree, no filter, so the class reports itself.
        rc, out, err = _run_census(repo, "--now", "2026-10-27T12:00:00Z")
        assert rc == 0, f"an unasked closed check is a warn, not a failure: {rc}\n{out}"
        assert "closed state not checked" in out, (
            f"the tree must carry the class's own row for this half: {out}")
        rowed = self._first_line(out)
        assert rowed != self.ALL_CLEAR, rowed
        assert "all checks passed" not in rowed, rowed
        assert out.splitlines()[-1].endswith("verdict ok"), out

    def test_the_verdict_line_names_the_class_whose_row_it_carries(self, tmp_path):
        """The verdict line says the closed state went unchecked, on the last line.

        A CI step that greps the verdict -- rather than reading rows -- judged this run
        clean for the whole of issue #148's lifetime, because everything it could match
        sat above the rows. The clause names the class by id, so it cannot be a paraphrase
        of the note that drifted from it, and it appears only on a run that really owes the
        row: the counter-cases below are what stop "always say unchecked" from passing.
        """
        from ordering_fixtures import _entry, _repo, _seed

        repo = _repo(tmp_path, "verdict-unchecked")
        _seed(repo, _entry(7, "2026-10-01-baseline"))
        rc, out, err = _run_census(repo, "--now", "2026-10-27T12:00:00Z")
        assert rc == 0, f"an unasked closed check stays a warn: {rc}\n{out}\n{err}"
        last = out.splitlines()[-1]
        assert last.startswith("summary:"), last
        assert "clean" not in last, (
            f"the verdict called a run with a row clean: {last!r}")
        assert "ordering-closed not checked" in last, (
            f"the verdict did not say the closed state went unchecked: {last!r}")
        assert last.endswith("verdict ok"), last

        # Counter-case one: a run given the state map asked its question, so the
        # verdict must read exactly as it did before the clause existed.
        state = repo.parent / "state-verdict.json"
        state.write_text('{"7": "open"}', encoding="utf-8")
        rc, out, err = _run_census(repo, "--now", "2026-10-27T12:00:00Z",
                                   "--issue-state", str(state))
        assert rc == 0, f"a closed check that was answered: {rc}\n{out}\n{err}"
        assert "not checked" not in out.splitlines()[-1], (
            f"a run that asked its closed question was worded as one that did not: "
            f"{out.splitlines()[-1]!r}")

        # Counter-case two: the class skipped outright owes neither row nor clause.
        rc, out, err = _run_census(repo, "--now", "2026-10-27T12:00:00Z",
                                   "--skip", "ordering-closed")
        assert rc == 0, f"a run that skipped the class: {rc}\n{out}\n{err}"
        assert "not checked" not in out.splitlines()[-1], (
            f"a skipped class is not an unchecked one: {out.splitlines()[-1]!r}")

    def test_a_run_with_nothing_to_report_still_reads_all_clear(self, tmp_path):
        """The counter-case, so the fix cannot be "never say all-clear".

        A run with no rows and no note -- the ordering group filtered out, so the
        note is not owed either -- keeps both all-clear lines. Without this half
        the first test would be satisfied by a renderer that had simply stopped
        telling anyone anything.
        """
        repo = self._warn_only_tree(tmp_path, "all-clear")
        rc, out, err = _run_census(
            repo, "--skip", "hygiene", "--skip", "ordering-closed",
            "--now", "2026-10-02T00:00:00Z")
        assert rc == 0, f"a run that evaluated everything and found nothing: {rc}\n{out}\n{err}"
        assert self._first_line(out) == self.ALL_CLEAR, out
        assert out.splitlines()[-1] == (
            "summary: clean; 0 finding(s); verdict ok"), out

    def test_a_fail_row_keeps_the_failing_verdict_word(self, tmp_path):
        """The fail half of the summary line is untouched by the warn wording.

        The row here is the class the warn-only tree reports (hygiene), promoted
        by ``--strict``, so the two runs differ only in how the run was asked to
        read them. The exit code is earned and the verdict word is the code plus
        the classes that fired -- never ``clean``, never a warn count -- and the
        machine tail flips to ``verdict fail``. That the headline still counts
        the row as a warning is deliberate: it is a warn class, and the verdict
        word is what says the run did not get away with it.
        """
        repo = self._warn_only_tree(tmp_path, "strict")
        rc, out, err = _run_census(
            repo, "--only", "hygiene", "--strict",
            "--now", "2026-10-02T00:00:00Z")
        assert rc == 50, f"--strict promotes the hygiene warn to 50, got {rc}\n{out}\n{err}"
        last = out.splitlines()[-1]
        assert last.startswith("summary: 50 ("), (
            f"a strict run must not read as a warn run: {last!r}")
        assert "clean" not in last, last
        assert "warning(s)" not in last, (
            f"a run that earned its exit code must not soften it into a warn "
            f"count: {last!r}")
        assert last.endswith("verdict fail"), last

    def test_a_warn_row_of_a_fail_class_is_counted_as_a_warning(
        self, tmp_path, monkeypatch,
    ):
        """The row tag and the headline answer "was this a warning?" once (issue #117).

        The warn rows most fixtures produce belong to warn classes, where the
        row and its class agree, and that is exactly the case a class-table count
        gets right. The shape that splits them is probe honesty: a committed
        record whose committed bytes are unreachable is a row of the *fail*
        class ``ledger-edited`` that carries ``warn`` severity, because an
        unreadable tree is not a protocol violation. Counting warnings by the
        class table answered 0 for this run and its summary said ``clean`` above
        a printed ``WARN`` row -- the same inversion this issue was filed for.

        ``blob_content_sha1`` is patched to return None (the same seam
        ``tests/test_census_exit_codes.py::test_unreachable_blob_is_warn_not_fail_
        without_strict`` uses) so the row is reached deterministically on a tree
        that does hold the object. Hygiene is filtered out so the row under test
        is the run's only finding, and the deny-list warn cannot stand in for it.
        """
        import census

        repo = self._warn_only_tree(tmp_path, "cannot-verify")
        monkeypatch.setattr(census.Git, "blob_content_sha1",
                            lambda self, commit, relpath: None)
        rc, out, err = _run_census(
            repo, "--skip", "hygiene", "--now", "2026-10-02T00:00:00Z")
        assert rc == 0, f"a cannot-verify row alone exits 0, got {rc}\n{out}\n{err}"
        assert "ledger-edited" in out and "cannot verify" in out, out
        assert "WARN" in out, f"the row must print as a warning to test this: {out}"
        first = self._first_line(out)
        assert "1 warning(s)" in first, (
            f"a run that printed a WARN row counted no warning: {first!r}")
        assert "0 warning(s)" not in first, (
            f"the headline denied the warning it printed below: {first!r}")
        last = out.splitlines()[-1]
        assert not last.startswith("summary: clean"), (
            f"the summary called a WARN-bearing run clean: {last!r}")
        assert "1 warning(s)" in last, (
            f"the summary line did not name the warning: {last!r}")
        assert last.endswith("verdict ok"), (
            f"the machine word of the summary line moved: {last!r}")

    def test_strict_promotion_moves_the_tag_and_the_count_together(
        self, tmp_path, monkeypatch,
    ):
        """The ``--strict`` half of the same row: promoted, it is no longer a warning.

        The count reads the rendered severity, so a promotion cannot leave a
        ``FAIL`` row counted as a warning: this run earned exit 12, so its
        verdict word is the code and the class, and no warn count softens it. The
        pair with the test above is what a class-table count could not express --
        that file answered 0 warnings for both runs.
        """
        import census

        repo = self._warn_only_tree(tmp_path, "cannot-verify-strict")
        monkeypatch.setattr(census.Git, "blob_content_sha1",
                            lambda self, commit, relpath: None)
        rc, out, err = _run_census(
            repo, "--skip", "hygiene", "--strict",
            "--now", "2026-10-02T00:00:00Z")
        assert rc == 12, f"--strict escalates the cannot-verify row to 12: {rc}\n{out}\n{err}"
        assert "FAIL" in out, f"a promoted row must not print as a warning: {out}"
        assert "WARN" not in out, out
        first = self._first_line(out)
        assert "0 warning(s)" in first, (
            f"a promoted row is no longer a warning, whatever its class says: "
            f"{first!r}")
        last = out.splitlines()[-1]
        assert last.startswith("summary: 12 ("), last
        assert "warning(s)" not in last, (
            f"a run that earned its exit code softened it into a warn count: "
            f"{last!r}")
        assert last.endswith("verdict fail"), last

    def test_json_output_is_unchanged_by_the_human_wording(self, tmp_path):
        """``--json`` is a machine contract, and this fix may not touch it.

        The same tree is run in both modes, so the comparison is between two
        renderings of one set of rows rather than two trees. The summary row
        keeps its key set, its ``ok``/``exit`` values, and no human verdict word
        anywhere on the stream: a fix that had "improved" the machine line as
        well would fail here, not in review.
        """
        repo = self._warn_only_tree(tmp_path, "json-unchanged")
        args = ["--now", "2026-10-02T00:00:00Z"]
        rc_json, out_json, _ = _run_census(repo, *args, json_out=True)
        rc_human, out_human, _ = _run_census(repo, *args)
        assert rc_json == rc_human == 0
        rows = _ndjson_rows(out_json)
        summaries = [r for r in rows if r.get("kind") == "summary"]
        assert len(summaries) == 1, rows
        summary = summaries[0]
        # The key set is the closed one plus ``not_evaluated``, which this tree
        # earns (no --issue-state): the field is the run's own fact and this
        # ticket adds no key of its own to carry the human wording.
        assert set(summary) == {"schema", "kind", "ok", "exit", "counts",
                                "not_evaluated"}, summary
        assert summary["ok"] is True and summary["exit"] == 0, summary
        assert summary["counts"] == {"hygiene": 1}, summary
        assert any("ordering-closed was not evaluated" in line
                   for line in summary["not_evaluated"]), summary
        assert [r["kind"] for r in rows] == ["finding", "summary"], rows
        # The human words live in the human branch only. ``clean`` is not tested
        # as a bare substring of the stream: a hygiene row's own message says
        # "not a hygiene-clean guarantee", and that is the row's business, not
        # the verdict word. The verdict facts of a --json run are its ``ok`` and
        # ``exit`` fields, and no human wording rides along on the summary row.
        assert "warning(s)" not in out_json, out_json
        assert "no findings" not in out_json and "all checks passed" not in out_json
        for line in ("no findings", "all checks passed"):
            assert line not in out_human, (
                f"a warn-bearing human run still printed the all-clear {line!r}")
        _, out_json_again, _ = _run_census(repo, *args, json_out=True)
        assert out_json == out_json_again, "two --json runs of one tree differed"


def test_not_evaluated_note_without_a_named_class_glues_nothing():
    """A not-evaluated note naming no class contributes no headline clause.

    Regression: the counts branch used to append ``{n} check(s) did not run``
    flush against the counts (``1 finding(s)1 check(s) did not run``). With no
    named class the headline carries no extra clause at all: the first line is
    exactly the counts, and the note line below the rows says what was not
    evaluated.
    """
    import io
    import sys as _sys

    from noni.census_render import (
        NO_STATE_ROOT_NOTE,
        _render,
    )

    findings = [{"check": "hygiene", "severity": "warn",
                 "subject": "noni/direction/order.json",
                 "artifact": "noni/direction/order.json",
                 "message": "not a hygiene-clean guarantee"}]
    note = NO_STATE_ROOT_NOTE.format(repo="state/repo")
    buf = io.StringIO()
    saved = _sys.stdout
    _sys.stdout = buf
    try:
        _render(findings, {"hygiene": 1}, True, 0, False, (note,))
    finally:
        _sys.stdout = saved
    lines = buf.getvalue().splitlines()
    headline = [line for line in lines if line.startswith("census:")][0]
    assert headline == "census: 1 warning(s), 1 finding(s)", lines[:3]
    assert "did not run" not in headline, headline
    assert f"note: {note}" in lines, lines


def test_rowless_run_naming_a_class_keeps_the_semicolon():
    """A rowless run that names a class separates the clause with a semicolon.

    `census: no findings; ordering-closed did not run` -- the rowless site keeps
    the semicolon it had before issue #166's PR glued the clause onto the counts
    with a comma. The counts site keeps its comma. Fails on the PR's current
    comma output until the renderer restores the semicolon for the rowless case.
    """
    import io
    import sys as _sys

    from noni.census_render import (
        ORDERING_CLOSED_NOT_EVALUATED,
        _render,
    )

    buf = io.StringIO()
    saved = _sys.stdout
    _sys.stdout = buf
    try:
        _render([], {}, True, 0, False, (ORDERING_CLOSED_NOT_EVALUATED,))
    finally:
        _sys.stdout = saved
    lines = buf.getvalue().splitlines()
    headline = [line for line in lines if line.startswith("census:")][0]
    assert headline == "census: no findings; ordering-closed did not run", lines


def test_rowless_run_whose_note_names_no_class_prints_only_no_findings():
    """A rowless run whose note names no class prints exactly `census: no findings`.

    No trailing semicolon, and never the all-clear banner: a note exists, so the
    run is not all-clear. The note itself still prints below the rows.
    """
    import io
    import sys as _sys

    from noni.census_render import (
        NO_STATE_ROOT_NOTE,
        _render,
    )

    note = NO_STATE_ROOT_NOTE.format(repo="state/repo")
    buf = io.StringIO()
    saved = _sys.stdout
    _sys.stdout = buf
    try:
        _render([], {}, True, 0, False, (note,))
    finally:
        _sys.stdout = saved
    lines = buf.getvalue().splitlines()
    headline = [line for line in lines if line.startswith("census:")][0]
    assert headline == "census: no findings", lines


