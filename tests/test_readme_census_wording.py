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
    _summary_verdict_word,
)
from readme_support import (
    _CLEAN_RUN_WARN_COUNT,
    NONI_DIR,
    _argv_for_run,
    _materialise_clone,
    _reader_env,
    _reader_repository,
    _run_documented,
    _script_name,
)
from readme_tryit import _try_it_commands

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
    naming one within the rows the page says a first tree carries. When the page
    pinned a number, ``_documented_summary_shape`` has already compared it.
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
        assert 0 < counted <= _CLEAN_RUN_WARN_COUNT, (
            f"the summary line counted {verdict!r} on a run the page says carries "
            f"at most {_CLEAN_RUN_WARN_COUNT} warn row(s): {lines[-1]!r}"
        )
    assert lines[0] != _ALL_CLEAR_BANNER, (
        f"the first line claimed every check passed above the rows this report "
        f"prints: {lines[0]!r}"
    )
    return counted


def test_the_readme_shows_a_warn_aware_summary_line(tmp_path: Path) -> None:
    """The documented run's own lines are the page's lines, warn and all.

    Runs the try-it block verbatim against a materialised clone and a scratch
    reader repository -- the topology the page sells -- and then holds the
    census's report to the page on the wording, not merely on the verdict word a
    CI step reads. A page that reverted to ``clean`` here, or a renderer that
    went back to printing it above warn rows, fails this test; the two cases
    that used to pass anyway (a substring check on ``verdict ok``, a shape check
    on the page's line alone) could not tell the two states apart.
    """
    clone = tmp_path / NONI_DIR
    _materialise_clone(clone)
    repo = _reader_repository(tmp_path)
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
        reported = _assert_warn_aware_summary(lines, warn_count_is_open)
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
