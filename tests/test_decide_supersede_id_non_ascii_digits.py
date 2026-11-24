"""A ``--supersedes`` written with non-ASCII digits is refused before anything is written.

``ID_RE`` is the record-id shape ``decide.py`` hands ``_decide_flags.build_record_flags``
for ``--supersedes``, and it spelled its digits as ``\\d``. ``\\d`` matches Unicode
decimal digits, so ``--supersedes ٢٠٢٦-10-01-baseline`` passed the shape, and the run
went on looking for a file named after it -- the same defect issue #184 closed for
``--date``, on the other half of the record id.

The refusal is the shape refusal the flag already has ("is not a record id", exit 2),
not a missing-target refusal: a name this writer can never produce is bad usage, and
the run must stop before the ledger is read. The forms driven here are the three the
``--date`` module drives -- an all-Unicode decimal form, a mixed ASCII/Unicode form,
and a superscript form that ``str.isdigit`` calls a digit -- because the rule is a
character rule, not a list of scripts.

The pattern is pinned on the live constant and on the shipped source, as the ``--date``
shape is, so the two halves of the same rule cannot start disagreeing again.
"""

from __future__ import annotations

from decide_fixtures import (
    ANSWERED,
    BASE,
    BASELINE_ID,
    NEW_DATE,
    OPTIONS,
    QUESTION,
    _assert_both_censuses_clean,
    _baseline_repo,
    _porcelain,
    _record_path,
    _run,
)

# Each form is the baseline's id with its date spelled in another script: the one
# value that would have answered for a real record had the shape let it through.
UNICODE_SUPERSEDES = (
    "\u0662\u0660\u0662\u0666-10-01-baseline",  # Arabic-Indic 2026-10-01
    "202\u0666-10-01-baseline",                # one mixed ASCII/Unicode year
    "\u00b2\u00b2\u00b2\u00b2-10-01-baseline",  # superscript digits, a digit to isdigit()
)


def test_a_supersedes_written_in_non_ascii_digits_exits_two_and_writes_nothing(
        tmp_path):
    """AC1: every Unicode-digit id is refused as usage, with the tree untouched.

    The refusal is printed, not raised, and it comes before the ledger is read: no
    record at the new path, nothing staged, and the census still clean over the
    baseline the refused run did not touch.
    """
    repo = _baseline_repo(tmp_path)
    for superseded in UNICODE_SUPERSEDES:
        proc = _run(repo, "--slug", "scheduler", "--date", NEW_DATE,
                    *BASE, *QUESTION, *OPTIONS, *ANSWERED,
                    "--supersedes", superseded)
        assert proc.returncode == 2, f"{superseded!r}: {proc.returncode} {proc.stderr}"
        assert f"--supersedes {superseded!r} is not a record id" in proc.stderr, (
            proc.stderr)
        assert "Traceback" not in proc.stderr, proc.stderr
        assert not _record_path(repo, f"{NEW_DATE}-scheduler").exists(), superseded
    assert _porcelain(repo) == ""
    _assert_both_censuses_clean(repo, "the runs that refused a Unicode id")


def test_a_valid_ascii_supersedes_still_supersedes(tmp_path):
    """AC3: the tightened shape is a tightening, not a change of accepted ids.

    The id the baseline really holds is accepted exactly as before, so a writer that
    refuses Unicode digits has not drifted on the ids it does write.
    """
    repo = _baseline_repo(tmp_path)
    proc = _run(repo, "--slug", "supersedes-baseline", "--date", NEW_DATE,
                *BASE, *QUESTION, *OPTIONS, *ANSWERED,
                "--supersedes", BASELINE_ID)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    assert _record_path(repo, f"{NEW_DATE}-supersedes-baseline").is_file()


def test_the_record_id_shape_is_ascii_digits_stated_once():
    """The id shape is pinned by its literal text, in the module that owns it.

    Read off the live constant and off the shipped source, scoped to ``decide.py``:
    the census keeps deliberate copies of this shape, and those are pinned in the
    census suites that drive them.
    """
    from _harness import REPO

    from noni import decide

    shape = decide.ID_RE
    assert shape.pattern == r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]+", shape.pattern
    for superseded in UNICODE_SUPERSEDES:
        assert not shape.fullmatch(superseded), f"the shape matches {superseded!r}"
    assert shape.fullmatch(BASELINE_ID), "the shape refused the id the writer writes"

    source = (REPO / "src" / "noni" / "decide.py").read_text(encoding="utf-8")
    assert source.count('r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]+"') == 1, (
        "the id shape is spelled more than once in the module that owns it")
    assert 'r"\\d{4}-\\d{2}-\\d{2}-[a-z0-9-]+"' not in source, (
        "the id shape still matches Unicode digits")
