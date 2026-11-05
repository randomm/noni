"""The ordering-closed note as the ``--json`` stream carries it (issue #97).

The human branch prints ``note: ...`` and the NDJSON branch put nothing, so a
machine consumer of ``--json`` could not tell "the closed class found no closed
issue" from "the closed class was never asked", and the census never contacts a
tracker: the class is asked only when ``--issue-state`` is given. The fix adds a
``not_evaluated`` field to the one summary row rather than a third row kind, so
these tests pin both halves of that decision: the field carries the sentence in
the mode that has no ``note:`` line, and the legal kind set stays closed.

The sentence itself is read from the product's source through the shared scraper
in ``quickstart_page``: three doc tests quote it and a fourth written here would
only add a fourth copy to keep in step.
"""

from __future__ import annotations

import json

from ordering_fixtures import BASELINE_ID, _entry, _repo, _seed
from quickstart_page import ordering_note_from_product
from test_census_report_mode import LEGAL_KINDS, _run_census_json

NOTE = ordering_note_from_product()[len("note: "):]


def _tree(tmp_path, name: str):
    """A repo holding one clean cited entry, so the ordering group has an
    artifact to evaluate and the closed class is the only one left unanswered."""
    repo = _repo(tmp_path, name)
    _seed(repo, _entry(3, BASELINE_ID, "2026-10-26T09:00:00Z"))
    return repo


def test_the_json_summary_row_carries_the_not_evaluated_fact(tmp_path):
    """Without ``--issue-state`` the stream names the unanswered class on the
    summary row, in a machine-readable field, and never as a finding row.

    The finding-row half is the point: a row of the class that was not evaluated
    would be a fabricated verdict (and would fail the run), so the fact belongs on
    the row that already reports what the run *did* decide."""
    repo = _tree(tmp_path, "json-note")
    rc, rows = _run_census_json(repo, "--only", "ordering-closed")
    assert rc == 0, f"a run that evaluated everything else is clean: rc={rc} rows={rows}"
    findings = [r for r in rows if r["kind"] == "finding"]
    assert findings == [], f"the unevaluated class invented a row: {findings}"
    summaries = [r for r in rows if r["kind"] == "summary"]
    assert len(summaries) == 1, f"expected exactly one summary row: {rows}"
    carried = summaries[0]["not_evaluated"]
    assert isinstance(carried, list) and carried, f"summary row: {summaries[0]}"
    assert any(NOTE in line for line in carried), f"summary row: {summaries[0]}"
    assert all("ordering-closed" in line for line in carried), (
        f"a note that does not name its class answers nothing: {carried}")


def test_the_field_is_absent_when_the_class_was_evaluated(tmp_path):
    """Given a state file the class is answered, and the summary row goes back to
    the key set it had before the field existed: no empty list, no null. A field
    that appeared on every run would widen the schema for every consumer to
    handle a case that only one run has."""
    repo = _tree(tmp_path, "json-no-note")
    state = repo.parent / "state.json"
    state.write_text(json.dumps({"issues": {"3": "open"}}), encoding="utf-8")
    _rc, rows = _run_census_json(repo, "--only", "ordering-closed",
                                 "--issue-state", str(state))
    summaries = [r for r in rows if r["kind"] == "summary"]
    assert len(summaries) == 1, f"expected exactly one summary row: {rows}"
    assert "not_evaluated" not in summaries[0], f"summary row: {summaries[0]}"


def test_the_field_never_adds_a_row_kind(tmp_path):
    """The kind set stays the closed pair: the fix is a field on the summary row,
    not a third kind, so a consumer that dispatches on ``kind`` is unaffected."""
    repo = _tree(tmp_path, "json-kinds")
    _rc, rows = _run_census_json(repo)
    kinds = {r["kind"] for r in rows}
    assert kinds <= LEGAL_KINDS, f"a census run emitted an illegal kind: {kinds}"
    assert any("not_evaluated" in r for r in rows), (
        "this run asks nothing that leaves a class unevaluated, so the test would "
        "pass vacuously: pin the ordering note's tree")
