"""The README's census wording has to be true of the run it shows (issue #117).

The try-it block promises a reader a census result, and for a long time the page
promised ``summary: clean`` above a run whose only rows were warnings, while the
report's own headline said ``all checks passed`` above a ``note:`` line about a
check that had not run. Docs and renderer were each internally consistent and
both misled. This module is where the two are pinned to each other on that point:
the page is read as data, the documented run is executed, and its lines are
compared to the page's -- the human verdict word, the warn count it names, and
the headline that must not claim every check passed.

What it does not duplicate: the try-it block's *mechanics* (the commands run, the
record is committed, the tree stays clean, the failing case fails honestly) stay
with ``tests/test_readme.py`` and the shared reading layer in
``tests/readme_support.py``. Only the wording assertion lives here, in its own
file, because the size gate caps the promises module and this is a distinct
promise: not "the page's commands work" but "the page's words describe the run".
"""

from __future__ import annotations

from pathlib import Path

from census_report_line import (
    _ALL_CLEAR_BANNER,
    _ALL_CLEAR_VERDICT,
    _WARN_VERDICT_SHAPE,
    _documented_summary_shape,
    _summary_parts,
    _summary_verdict_word,
)
from harness_git import _git
from readme_support import (
    _CLEAN_RUN_WARN_ROWS,
    NONI_DIR,
    _argv_for_run,
    _materialise_clone,
    _reader_env,
    _reader_repository,
    _run_documented,
    _script_name,
)
from readme_tryit import _try_it_commands

from noni import census_render

# The fixed head of the rowless headline, the part of it that is not the verdict
# clause; see ``_assert_clean_summary``.
_HEADLINE_PREFIX = "census: no findings"

# The one line of the report this module exists to police, and the two states it
# must not be in when the run carried rows: see ``_assert_warn_aware_summary``.


def _assert_warn_aware_summary(lines: list[str], warn_count_is_open: bool) -> int:
    """Hold the report's two headline lines to a warn-bearing run.

    Returns the finding count the summary line reported, so the caller can tie it
    to the rows above it. Three assertions, each the failure mode issue #117
    actually had:

    - the human word of the summary line is not the all-clear word, because the
      run printed rows (before the fix it was ``clean`` on any exit-0 run);
    - that word *is* a warn count, so the report says how many rather than
      merely not saying "clean";
    - the first line is not the all-clear banner, which is what a reader scans
      first and what the note line contradicted.

    ``warn_count_is_open`` is the page's own choice: when the page holds the
    number open as a placeholder it cannot pin the count, so the run is held to
    naming one, and to naming no more than the rows the page says a first tree
    carries. When the page pinned a number, ``_documented_summary_shape`` has
    already compared it.
    """
    assert lines, "the census printed nothing"
    verdict = _summary_verdict_word(lines[-1])
    assert verdict != _ALL_CLEAR_VERDICT, (
        f"a run that printed rows called itself {_ALL_CLEAR_VERDICT!r}: "
        f"{lines[-1]!r}"
    )
    assert _WARN_VERDICT_SHAPE.match(verdict), (
        f"the summary line's human word is neither the all-clear word nor a warn "
        f"count: {lines[-1]!r}"
    )
    counted = int(verdict.split(" ", 1)[0])
    if warn_count_is_open:
        assert 0 < counted <= len(_CLEAN_RUN_WARN_ROWS), (
            f"the summary line counted {verdict!r} on a run the page says carries "
            f"at most {len(_CLEAN_RUN_WARN_ROWS)} warn row(s): {lines[-1]!r}"
        )
    assert lines[0] != _ALL_CLEAR_BANNER, (
        f"the first line claimed every check passed above the rows this report "
        f"prints: {lines[0]!r}"
    )
    return counted


def _assert_reader_tree_has_no_ledger(repo: Path) -> None:
    """The precondition the warn-aware wording test plants, checked on disk.

    The test below commits an empty ``noni/decisions/`` so the documented run is
    warn-bearing without a deny-list (see its docstring). A census that stops
    counting that state as a warn row -- or a fixture that quietly stopped
    planting it -- would leave the run saying ``clean``, and the wording
    assertions below would then be vacuous: they would hold the page against a
    run that carries nothing to be wrong about. Reading the tree, not the run's
    own report, is what makes this independent of the thing under test.
    """
    assert (repo / "noni" / "decisions").is_dir(), (
        "the fixture tree no longer holds a noni/ directory: the warn row this "
        "test pins the page against is gone")
    tracked = _git(repo, "ls-files", "noni/decisions").stdout.split()
    assert tracked, "the empty ledger is not committed, so the census reads no ledger"
    assert not list((repo / "noni" / "decisions").glob("*.json")), (
        "the fixture ledger holds a record, so the run owes no warn row and the "
        "wording assertions below prove nothing")


def _ledger_holds_a_record(repo: Path) -> bool:
    """Whether the reader's ledger holds a *.json record right now.

    The switch between the two runs the block performs, read off the filesystem
    rather than off the report: the census's own verdict is what this module
    tests, so it cannot also be the thing that decides which verdict is expected
    of it.
    """
    decisions = repo / "noni" / "decisions"
    return decisions.is_dir() and any(decisions.glob("*.json"))


def _assert_clean_summary(lines: list[str]) -> int:
    """The tour's end state: a run with no row says so, and counts no row.

    The all-clear word belongs to exactly this run (issue #117), so the clean
    half of the page's promise is pinned here too: a report that went back to
    counting warnings it never printed, or that hid a row behind ``clean``, is
    caught by the count check the caller runs on the returned number.
    """
    assert lines, "the census printed nothing"
    assert _summary_verdict_word(lines[-1]) == _ALL_CLEAR_VERDICT, (
        f"a run whose tree holds a record called itself a warn count: {lines[-1]!r}"
    )
    # The banner is the all-clear only when nothing was skipped. This tree gets no
    # --issue-state map, so the headline carries that class's own clause instead of
    # "all checks passed" (issue #148); the deny-list note, by contrast, must not
    # reach the headline at all, which is the half that keeps this assertion from
    # passing on any headline that merely starts with the counts.
    unasked = census_render._not_evaluated_headline(
        [census_render.ORDERING_CLOSED_NOT_EVALUATED])
    expected = [_ALL_CLEAR_BANNER, f"{_HEADLINE_PREFIX}{unasked}"]
    assert lines[0] in expected, (
        f"a clean run opened with neither the all-clear banner nor the clause "
        f"naming the class that did not run: {lines[0]!r}, expected one of {expected}"
    )
    assert "deny-list" not in lines[0], (
        f"the deny-list note reached the headline, where a reader would take it for "
        f"a check that ran: {lines[0]!r}"
    )
    return int(_summary_parts(lines[-1])[2])


def test_the_readme_shows_a_warn_aware_summary_line(tmp_path: Path) -> None:
    """The documented run's own lines are the page's lines, warn and all.

    Runs the try-it block verbatim against a materialised clone and a scratch
    reader repository -- the topology the page sells -- and then holds the
    census's report to the page on the wording, not merely on the verdict word a
    CI step reads. A page that reverted to ``clean`` here, or a renderer that
    went back to printing it above warn rows, fails this test; the two cases
    that used to pass anyway (a substring check on ``verdict ok``, a shape check
    on the page's line alone) could not tell the two states apart.

    The warn-bearing run is the first census the block's reader can run, and it
    is the run the page's wording is compared to. Before issue #194 the deny-list
    row made every such run warn-bearing by itself; a tree with no deny-list
    configured now says so in a `note:` line and emits no row. So the reader tree
    is built as the page's reader builds it -- their own file committed, plus
    `noni/decisions/` present and holding no record, the state that still warns --
    and the census is read there, before the block's `decide.py` step. Then
    `decide.py` runs and the census runs a second time, as the clean run the tour
    ends on. Both runs are the page's own command, verbatim, in the page's own
    topology; neither is steered by hand.
    """
    clone = tmp_path / NONI_DIR
    _materialise_clone(clone)
    repo = _reader_repository(tmp_path)
    # The reader's own file, and the empty ledger, both committed. The census
    # reads tracked state, so a ``noni/`` that exists only on disk is a ``noni/``
    # it does not see, and the page's reader has committed their project before
    # the first census run.
    (repo / "README.md").write_text("project\n", encoding="utf-8")
    (repo / "noni" / "decisions").mkdir(parents=True)
    (repo / "noni" / "decisions" / ".gitkeep").write_text("", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "state")
    _assert_reader_tree_has_no_ledger(repo)
    _line, shown_word, warn_count_is_open = _documented_summary_shape()
    env = _reader_env()
    ran_census = False

    for argv in _try_it_commands():
        cmd = _argv_for_run(argv, clone, repo)
        proc = _run_documented(cmd, repo, env)
        assert proc.returncode == 0, (
            f"documented command failed ({proc.returncode}): {argv}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
        if _script_name(argv) != "census.py":
            continue
        ran_census = True
        lines = proc.stdout.splitlines()
        if not _ledger_holds_a_record(repo):
            # The census of the unsteered tree: the run the page's warn-aware
            # wording is about, and the only one that can carry a row here now
            # that an unconfigured deny-list is a note (issue #194).
            _assert_reader_tree_has_no_ledger(repo)
            reported = _assert_warn_aware_summary(lines, warn_count_is_open)
        else:
            # The tour's own end state: decide.py has written, so the run owes no
            # row and must say so rather than counting one it did not print.
            reported = _assert_clean_summary(lines)
        # Every row the summary counted must appear above it, by class word: a
        # count that did not come from the rows would be a number the report
        # made up, and it is the half of the summary the page cannot see.
        for row_class in _CLEAN_RUN_WARN_ROWS[:reported]:
            assert any(row_class in line for line in lines[:-1]), (
                f"the summary counted {reported} finding(s) but no row names "
                f"{row_class!r}:\n{proc.stdout}"
            )
        # The page's shape and the run's line are one shape: head, human word,
        # count, machine tail. Only the count is left open by the page, and the
        # run has filled it in.
        assert lines[-1].startswith("summary: "), lines[-1]
        assert lines[-1].endswith("verdict ok"), lines[-1]
        assert f"{reported} finding(s);" in lines[-1], lines[-1]
        if shown_word is not None:
            assert shown_word in lines[-1], (
                f"the page shows the verdict word {shown_word!r} where the run "
                f"printed {lines[-1]!r}"
            )

    assert ran_census, "the try-it block no longer runs the census"
