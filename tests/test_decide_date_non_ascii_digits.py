"""A ``--date`` written with non-ASCII digits is refused before anything is written.

Split from ``test_decide_slug_date_prefix.py`` for the 500-line source cap, at the
seam that already separates the two rules: that file owns the ``--slug`` that carries
a date prefix, this one owns the ``--date`` whose digits are not ASCII. The two are
the same rule stated twice in one module, and the module says so -- ``SLUG_DATE_PREFIX``
spells its digits as ``[0-9]`` "so a Unicode digit cannot pose as one", and ``DATE_FLAG_RE``
spelled them as ``\\d``.

The defect: ``\\d`` matches Unicode decimal digits, so ``--date ٢٠٢٦-11-15`` matched
the shape, and ``datetime.strptime`` converted the same digits and found a real day.
The run exited 0 with a record named ``٢٠٢٦-11-15-topic.json``, which is what the
census's ``^[A-Za-z0-9._-]+\\.json$`` then reported as "filename is not a plain
<name>.json path segment": the ledger held a record neither census would read, and a
later ``--supersedes`` of that id was accepted too.

Three kinds of digit are refused, because the shape is a character rule and not a
list of scripts: an all-Unicode decimal form, a mixed ASCII/Unicode form (which is
the case a check of the first character alone would miss), and a non-decimal form
that ``str.isdigit`` calls a digit. A valid ASCII date is accepted exactly as before,
and a calendar-impossible ASCII day keeps its own refusal.

The launched runs are the assertion that matters: exit 2 before the state root, the
identity probe and the calendar get a vote, with no file under ``noni/decisions`` and
an empty ``git status --porcelain``.
"""

from __future__ import annotations

import inspect

from decide_fixtures import (
    ANSWERED,
    BASE,
    NEW_DATE,
    OPTIONS,
    QUESTION,
    _baseline_repo,
    _read,
    _record_path,
    _run,
)
from test_decide_slug_date_prefix import (
    UNICODE_DATES,
    UNICODE_IDS,
    _assert_untouched,
)


def test_a_date_written_in_non_ascii_digits_exits_two_and_writes_nothing(tmp_path):
    """AC1: every Unicode-digit form exits 2 and leaves the tree untouched.

    The three forms are refused at the writer's usage code rather than reaching the
    state-root or identity probes, so a run that would have committed a name no census
    reads stops before git is asked anything at all. A refusal is printed, not raised:
    a Unicode digit is bad usage, the same way a non-ASCII issue number is for the
    order writer, so neither stream carries a traceback.
    """
    repo = _baseline_repo(tmp_path)
    for date in UNICODE_DATES:
        proc = _run(repo, "--slug", "scheduler", "--date", date,
                    *BASE, *QUESTION, *OPTIONS, *ANSWERED)
        assert proc.returncode == 2, f"--date {date!r}: {proc.returncode} {proc.stderr}"
        assert "--date" in proc.stderr, f"--date {date!r}: {proc.stderr}"
        assert "Traceback" not in proc.stderr, f"--date {date!r}: {proc.stderr}"
        assert not _record_path(repo, UNICODE_IDS[date]).exists()
        assert not _record_path(repo, f"{NEW_DATE}-scheduler").exists()
    _assert_untouched(repo)


def test_the_refusal_of_a_non_ascii_date_reads_as_a_shape_refusal(tmp_path):
    """AC1/AC2: a Unicode digit is refused as a bad shape, not as a bad calendar day.

    The shape rule runs first, so a value ``strptime`` would have accepted is refused
    with the "not YYYY-MM-DD" sentence rather than the calendar's, and the value is
    quoted back so an operator can see which flag they got wrong. A superscript date
    already took this wording before the fix; the Arabic-Indic and mixed dates take it
    now, which is the whole behaviour change of this rule. Both calendar refusals are
    pinned beside them: a tightened shape must not swallow the wording a day that does
    not exist earns.
    """
    from noni import _decide_flags

    assert "is not YYYY-MM-DD" in inspect.getsource(_decide_flags.parse_date), (
        "parse_date no longer prints the shape refusal")

    calls: list[str] = []

    def fail(code: int, message: str, hint: str | None = None) -> int:
        calls.append(message)
        return code

    for date in UNICODE_DATES:
        assert _decide_flags.parse_date(date, fail=fail,
                                        exit_usage=2) == (None, 2), date
        assert calls[-1] == f"--date {date!r} is not YYYY-MM-DD", calls[-1]

    for calendar_day in ("2026-02-30", "2026-13-45"):
        assert _decide_flags.parse_date(calendar_day, fail=fail,
                                        exit_usage=2) == (None, 2), calendar_day
        assert calls[-1] == f"--date {calendar_day!r} is not a real calendar date", (
            calls[-1])

    repo = _baseline_repo(tmp_path)
    for date in UNICODE_DATES + ("2026-02-30", "2026-13-45"):
        proc = _run(repo, "--slug", "scheduler", "--date", date,
                    *BASE, *QUESTION, *OPTIONS, *ANSWERED)
        assert proc.returncode == 2, f"--date {date!r}: {proc.returncode} {proc.stderr}"
        combined = proc.stdout + proc.stderr
        assert f"--date {date!r} is" in combined, f"--date {date!r}: {combined}"
    _assert_untouched(repo)


def test_a_valid_ascii_date_is_written_exactly_as_before(tmp_path):
    """AC2: the tightened shape is a tightening, not a change of accepted dates.

    The run the bug let through is refused; an ordinary ASCII date is not. The record
    lands at the id and path it always did, with the date field the run was asked for,
    so a writer that refuses Unicode digits has not drifted on the dates it accepts.
    """
    repo = _baseline_repo(tmp_path)
    proc = _run(repo, "--slug", "scheduler", "--date", NEW_DATE,
                *BASE, *QUESTION, *OPTIONS, *ANSWERED)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    assert _record_path(repo, f"{NEW_DATE}-scheduler").is_file()
    assert _read(repo, f"{NEW_DATE}-scheduler")["date"] == f"{NEW_DATE}T00:00:00Z"


def test_the_date_shape_is_ascii_digits_stated_once():
    """The ``--date`` shape is pinned by its literal text, in the module that owns it.

    ``SLUG_DATE_PREFIX``'s own comment states the digit rule; ``DATE_FLAG_RE`` is the
    half of that rule its author did not write down, so the class is asserted rather
    than inferred. The pattern is read off the shipped source as well as off the live
    constant, because a second copy of the shape in the writer's module is how the two
    halves of the rule start disagreeing again.
    """
    from _harness import REPO

    from noni import _decide_flags

    shape = _decide_flags.DATE_FLAG_RE
    assert shape.pattern == r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", shape.pattern
    assert not shape.fullmatch("\u0662\u0660\u0662\u0666-11-15"), (
        "the date shape matches a Unicode digit")
    assert shape.fullmatch("2026-13-45"), "the shape must not consult the calendar"

    # One copy of the shape in the module that owns it, and no ``\d`` date shape left
    # there: the other ``\d`` patterns of the package (the cited-id and stamp rules)
    # are another issue's business, so the assertion is scoped to this file.
    flags = (REPO / "src" / "noni" / "_decide_flags.py").read_text(encoding="utf-8")
    assert flags.count('r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"') == 1, (
        "the date shape is spelled more than once in the module that owns it")
    assert 'r"^\\d{4}-\\d{2}-\\d{2}$"' not in flags, (
        "the date shape still matches Unicode digits")
