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


def test_a_note_container_that_is_not_a_tuple_is_refused_at_the_renderer():
    """The container is part of the contract, not only its elements.

    The element guard alone let a bare ``str`` through: ``for note in "abc"``
    yields ``"a"``, ``"b"``, ``"c"``, each of them a ``str``, so a caller that
    handed the renderer one sentence instead of a tuple of them got three
    ``note: <one letter>`` lines in human mode and a three-letter list in
    ``--json``. A ``list`` of sentences prints the right bytes today, so an
    element-only check would certify it, and the next producer to pass a
    one-element ``str`` would arrive through the same door. ``census_run`` builds
    a ``tuple``, so refusing every other container costs nothing at the call site
    and closes the split-a-string shape outright.
    """
    import pytest

    from noni.census_render import _render

    for bad in (NOTE, [NOTE], {NOTE}, {"note": NOTE}, 7, None):
        for json_out in (True, False):
            with pytest.raises(TypeError, match="must be a tuple"):
                _render([], {}, True, 0, json_out, bad)


def test_no_fix_hint_repeats_the_not_evaluated_note():
    """The comment beside the ``ordering-closed`` hint forbids quoting the note;
    the hint used to state that rule and then paraphrase it.

    ``ORDERING_CLOSED_NOT_EVALUATED`` is one sentence with three doc scrapers, and
    the comment above the class's fix hint says a hint must not carry it, because
    the hint of the class that *did* run would then read as a row of the class that
    did not. The hint is derived into ``CLASS_FIX`` and printed on every
    ``ordering-closed`` row, so the paraphrase was a second home for the sentence
    -- one that no scraper watched. This asserts the rule the comment claims, over
    every class, so the comment and the table cannot drift apart again.
    """
    from noni.census_render import CLASS_FIX, ORDERING_CLOSED_NOT_EVALUATED

    assert CLASS_FIX, "the derived view of the class table is empty"
    quoted = [check for check, hint in CLASS_FIX.items()
              if ORDERING_CLOSED_NOT_EVALUATED in hint]
    assert not quoted, (
        f"these fix hints quote the note verbatim: {quoted}")
    # The paraphrase this class used to carry: neither half of the sentence may
    # reappear in a hint under other words.
    for check, hint in CLASS_FIX.items():
        assert "was not evaluated" not in hint, (
            f"{check}: the hint restates the not-evaluated note: {hint}")


def test_a_note_that_is_not_a_sentence_is_refused_at_the_renderer(tmp_path):
    """``not_evaluated`` is a ``list[str]`` by contract, not by accident.

    The doc names the field a list of the classes a run did not evaluate and
    why, and a consumer is entitled to read each element as a sentence. A note
    that arrived as a dict or a pair would have printed as ``note: {...}`` in
    human mode and an object inside a list in ``--json``: two shapes for one
    field, which is the divergence the field exists to remove. So the renderer
    refuses a non-string note rather than emitting a stream whose element type
    varies per run.
    """
    import pytest

    from noni.census_render import _render

    for bad in ({"class": "ordering-closed", "why": "no flag"}, ("a", "pair"), 7, None):
        with pytest.raises(TypeError, match="must be a sentence"):
            _render([], {}, True, 0, True, (bad,))
        with pytest.raises(TypeError, match="must be a sentence"):
            _render([], {}, True, 0, False, (bad,))

    # The shape the contract does allow, in both modes: strings inside a tuple.
    _render([], {}, True, 0, True, (NOTE,))
    _render([], {}, True, 0, False, (NOTE,))
