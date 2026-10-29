"""The ordering artifact is optional: a project that never ordered anything.

No ordering rows at all and no exit code of its own, and ``--strict`` does not
invent a finding where there is nothing to report. Contrast the ledger, whose
absence is the ledger-empty warn.

Split out of ``tests/test_census_ordering.py``; the builders are in
``tests/ordering_fixtures.py``.
"""

from __future__ import annotations

from ordering_fixtures import _repo, _run

# --- the absent artifact ------------------------------------------------------


def test_no_order_file_adds_no_ordering_row(tmp_path):
    """The ordering layer is optional: a project that has never ordered anything
    censuses with no ordering rows at all, and no exit code of its own. Contrast
    the ledger, whose absence is the ledger-empty warn."""
    repo = _repo(tmp_path)
    code, rows, out, err = _run(repo)
    assert code == 0, (code, out, err)
    assert rows == [], rows


def test_a_missing_file_is_not_reported_even_under_strict(tmp_path):
    """--strict promotes warnings, it does not invent findings: a run with
    nothing to report stays clean whatever the flag does to severities."""
    repo = _repo(tmp_path)
    code, rows, out, err = _run(repo, "--strict")
    assert code == 0, (code, out, err)
    assert rows == [], rows
