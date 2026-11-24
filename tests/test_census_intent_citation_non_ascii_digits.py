"""The intent class's citation gate accepts only ASCII digits in the id it names.

``census_intent.RECORD_ID_RE`` is the census's deliberate duplicate of the writer's
record-id shape -- the class does not import the writer -- and it spelled its digits as
``\\d``. A commit subject of ``intent: <Arabic-Indic 2026>-10-01-baseline`` therefore
read as a nameable id, and the class went on to compose a path from it and ask the
ledger for it.

Two things are asserted. First the behaviour, through the class's own seam: a citation
written in non-ASCII digits is not a citation at all, so the run says ``uncited`` about
a commit that names no record, the same row it already gives a subject that carries the
word and no nameable id. Second the shape, on the live constant, on the shipped source,
and against the writer's copy in ``decide.py``: the two spellings are one rule written
twice on purpose, so an id they disagree about is the drift these pins close.
"""

from __future__ import annotations

import json

from intent_class_ast import intent_class_text
from intent_fixtures import (
    RECORD_ID,
    commit_intent,
    install_intent,
    repo_with_record,
    run_census_in_process,
)
from ordering_shapes import non_ascii_record_id

FORGED = non_ascii_record_id()

INTENT = "intent"


def _intent_rows(stdout: str) -> list[dict]:
    """The intent class's finding rows of a JSON run, whole (message included)."""
    return [json.loads(line) for line in stdout.splitlines() if line.strip()
            and json.loads(line).get("kind") == "finding"
            and json.loads(line)["check"] == INTENT]


def test_a_citation_written_in_non_ascii_digits_names_no_record(tmp_path):
    """AC1: a Unicode-digit id is no citation, so the row says the commit cited nothing.

    The alternative is the old behaviour: the shape matched, the class composed
    ``noni/decisions/<forged>.json`` and asked the ledger for it, and the row quoted
    a record no writer can produce back to the operator as the direction the intent
    rests on. Refused at the shape, the run gives the sentence it already has for a
    subject that names nothing, and no forged id reaches a row.
    """
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo, subject=f"intent: {FORGED}")
    _code, out, err = run_census_in_process(repo, "--only", INTENT)
    rows = _intent_rows(out)
    assert [r["subject"] for r in rows] == ["uncited"], (rows, err)
    assert "does not name a decision record" in rows[0]["message"], rows[0]
    combined = out + err
    assert FORGED not in combined, (
        f"a Unicode-digit id reached the report as a cited record: {combined[:400]}")
    assert "Traceback" not in combined, combined[:400]


def test_a_real_citation_still_names_its_record(tmp_path):
    """AC3: the tightening is a tightening. The id the ledger holds is still cited.

    Without the control the uncited row above would be satisfiable by a gate that
    refused every id, which is a class that answers nothing.
    """
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo)
    _code, out, err = run_census_in_process(repo, "--only", INTENT)
    assert _intent_rows(out) == [], (out, err)


def test_the_citation_shape_is_ascii_digits_stated_once():
    """The census's copy of the id shape is pinned, and held to the writer's rule.

    Three assertions, one per way the two copies part company: the live constant's
    pattern, the literal in the module that owns it (scoped to that file, as the
    other id pins are scoped to theirs), and the shared date prefix read off both
    constants -- the census's comment claims it copies the writer's shape, and the
    date half is where the digit rule lives.
    """
    from noni import census_intent, decide

    shape = census_intent.RECORD_ID_RE
    assert shape.pattern == r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9][a-z0-9-]*", (
        shape.pattern)
    assert not shape.fullmatch(FORGED), "the citation shape matches a Unicode digit"
    assert shape.fullmatch(RECORD_ID), "the shape refused a real record id"
    # The digit rule sits in the date half; a tightening that also refused digits
    # inside the slug would change what a valid id is, not which digits count.
    assert shape.fullmatch(f"{RECORD_ID}-2"), "the shape refuses digits inside the slug"

    text = intent_class_text()
    assert text.count('r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9][a-z0-9-]*"') == 1, (
        "the id shape is spelled more than once in the module that owns it")
    assert 'r"\\d{4}-\\d{2}-\\d{2}-[a-z0-9][a-z0-9-]*"' not in text, (
        "the citation shape still matches Unicode digits")

    shared = r"[0-9]{4}-[0-9]{2}-[0-9]{2}-"
    assert shape.pattern.startswith(shared) and decide.ID_RE.pattern.startswith(shared), (
        "the census's copy and the writer's shape no longer spell one date rule: "
        f"{shape.pattern} / {decide.ID_RE.pattern}")
