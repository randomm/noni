"""A ``--decision`` written with non-ASCII digits is refused as the shape it is.

``DECISION_ID_RE`` is the record-id shape ``orderstate.decision_problems`` and
``_successor`` ask, and it spelled its digits as ``\\d``. ``\\d`` matches Unicode decimal
digits, so ``--decision ٢٠٢٦-10-01-baseline`` passed the shape, and the run went on to
build ``noni/decisions/<that>.json`` and look it up -- the arm behind the same exit 4
as an absent record, reached with a name this writer can never produce.

The two arms behind that exit 4 have to stay distinguishable: a malformed id is refused
for its shape and never asks the ledger anything, while a well-formed id for a record
the ledger does not hold is the missing-record answer. Both are asserted here beside
the accepted control, so the tightening is a tightening and not a second refusal word.

``is_index_text`` already gates issue numbers and positions on ``isascii()`` and
``isdecimal()``; this is the same rule for the half of the artifact that names a record.
"""

from __future__ import annotations

from order_fixtures import (
    BASELINE_ID,
    NOW,
    _order,
    _order_path,
    _repo,
)
from orderstate_hint_support import RECORD_FIRST, fix_lines

# Each form is the baseline's id with its date spelled in another script: the one
# value that would have asked the ledger for a real record had the shape let it
# through. A digit to ``\d``, to ``str.isdigit``, and to neither.
UNICODE_DECISIONS = (
    "\u0662\u0660\u0662\u0666-10-01-baseline",  # Arabic-Indic 2026-10-01
    "202\u0666-10-01-baseline",                # one mixed ASCII/Unicode year
    "\u00b2\u00b2\u00b2\u00b2-10-01-baseline",  # superscript digits
)


def test_a_decision_written_in_non_ascii_digits_is_refused_by_the_shape(tmp_path):
    """AC1: a Unicode-digit id earns exit 4, the shape refusal, with no artifact.

    Refused before the ledger is consulted, so the sentence is the writer's own and
    no stream carries a traceback; the fix line is the one every citation refusal
    ends with, and a refused ``add`` writes no artifact.
    """
    repo = _repo(tmp_path)
    for decision in UNICODE_DECISIONS:
        proc = _order(repo, "add", "7", "--decision", decision, "--now", NOW)
        assert proc.returncode == 4, f"{decision!r}: {proc.returncode} {proc.stderr}"
        assert "matches no record" in proc.stderr, proc.stderr
        assert "Traceback" not in proc.stderr, proc.stderr
        assert len(fix_lines(proc.stderr)) == 1, proc.stderr
        assert fix_lines(proc.stderr)[0].endswith(RECORD_FIRST), proc.stderr
    assert not _order_path(repo).exists()


def test_the_three_arms_of_a_refused_citation_stay_three(tmp_path):
    """A Unicode digit is refused as a shape, not as a missing record.

    Three runs, three sentences: a name the writer never produces, a well-formed name
    the ledger does not hold, and the accepted control that writes. If the tightened
    shape had instead fallen through to the file lookup, the first and second would
    print the same words and the distinction this module exists for would be gone.
    """
    repo = _repo(tmp_path, "malformed")
    malformed = _order(repo, "add", "7", "--decision", UNICODE_DECISIONS[0],
                       "--now", NOW)
    ghost = _order(repo, "add", "7", "--decision", "2026-01-01-ghost", "--now", NOW)
    assert malformed.returncode == ghost.returncode == 4
    assert "matches no record" in malformed.stderr, malformed.stderr
    assert "is in the ledger" in ghost.stderr, ghost.stderr
    assert malformed.stderr != ghost.stderr, "the two arms print one sentence"

    ok = _repo(tmp_path, "accepted")
    written = _order(ok, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert written.returncode == 0, written.stderr
    assert _order_path(ok).is_file()


def test_the_decision_id_shape_is_ascii_digits_stated_once():
    """The id shape is pinned by its literal text, in the module that owns it.

    Scoped to ``orderstate.py``: the census keeps deliberate copies of the same
    shape and pins them in its own suites.
    """
    from _harness import REPO

    from noni import orderstate

    shape = orderstate.DECISION_ID_RE
    assert shape.pattern == r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9][a-z0-9-]*", (
        shape.pattern)
    for decision in UNICODE_DECISIONS:
        assert not shape.fullmatch(decision), f"the shape matches {decision!r}"
    assert shape.fullmatch(BASELINE_ID), "the shape refused the id the writer writes"

    source = (REPO / "src" / "noni" / "orderstate.py").read_text(encoding="utf-8")
    assert source.count('r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9][a-z0-9-]*"') == 1, (
        "the id shape is spelled more than once in the module that owns it")
    assert 'r"\\d{4}-\\d{2}-\\d{2}-[a-z0-9][a-z0-9-]*"' not in source, (
        "the id shape still matches Unicode digits")
