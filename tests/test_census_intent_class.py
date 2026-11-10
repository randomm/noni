"""The ``intent`` census class: the artifact's shape and its citation.

The class is optional by contract -- an absent ``noni/direction/intent.md``
contributes no row at all -- so the absent case is asserted first. Every refusal
the writer makes is asserted here as a row too (``tests/intent_shapes.py`` is the
single list both suites read), which is what keeps the artifact and the arbiter
from drifting apart. The rows this run raises when it could not make a read are in
``tests/test_census_intent_cannot_tell.py``.
"""

from __future__ import annotations

import json

import pytest
from intent_fixtures import (
    INTENT_REL,
    RECORD_ID,
    _commit,
    _human,
    _rows,
    _run,
    commit_intent,
    install_intent,
    record,
    repo_with_record,
    subjects,
    write_intent,
)
from intent_shapes import (
    FENCED_EXAMPLES,
    FENCED_HEADING,
    INDENTED_STAMP,
    INTENT_REFUSAL_SHAPES,
    _unclosed_fence,
)


def test_absent_intent_contributes_no_row(tmp_path):
    repo = repo_with_record(tmp_path)
    code, rows, _, stderr = _run(repo)
    assert rows == []
    assert code == 0
    assert stderr == ""


def test_cited_four_section_intent_is_clean(tmp_path):
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo)
    code, rows, _, _ = _run(repo)
    assert rows == []
    assert code == 0


@pytest.mark.parametrize("name, text, subject", INTENT_REFUSAL_SHAPES)
def test_every_writer_refusal_has_its_row(tmp_path, name, text, subject):
    repo = repo_with_record(tmp_path)
    write_intent(repo, text)
    commit_intent(repo)
    code, rows, _, _ = _run(repo)
    assert subjects(rows) == [subject]
    row = rows[0]
    assert row["check"] == "intent"
    assert row["code"] == 51
    assert row["severity"] == "fail"
    assert row["artifact"] == INTENT_REL
    assert code == 51


def test_a_fenced_heading_is_not_a_section(tmp_path):
    repo = repo_with_record(tmp_path)
    write_intent(repo, FENCED_HEADING)
    commit_intent(repo)
    code, rows, _, _ = _run(repo)
    assert rows == []
    assert code == 0


def test_an_indented_stamp_line_is_not_the_stamp(tmp_path):
    repo = repo_with_record(tmp_path)
    write_intent(repo, INDENTED_STAMP)
    commit_intent(repo)
    code, rows, _, _ = _run(repo)
    assert rows == []
    assert code == 0


def test_a_closed_block_may_hold_an_example_heading_and_stamp(tmp_path):
    """The control for the unclosed-fence refusal: balance is what matters.

    The same second `## Principles` and second stamp line the unclosed shape hides
    away, written inside a block the file closes again, is a file the writer writes
    and the class passes. Without this row the two shapes cannot be told apart: a
    rule that refused every fenced example would keep every other name green here.
    """
    repo = repo_with_record(tmp_path)
    write_intent(repo, FENCED_EXAMPLES)
    commit_intent(repo)
    code, rows, _, _ = _run(repo)
    assert rows == []
    assert code == 0


def test_the_unclosed_fence_row_says_what_the_opener_costs(tmp_path):
    """The row names the rule it applied, and never quotes the hidden lines.

    A row that echoed the concealed content would print whatever a draft put after
    the opener, so the sentence is the census's own -- and it has to say the fence
    was unclosed rather than leave `section-missing` to read as a plain missing
    heading, which is the wrong repair for a file that carries a fence too many.
    """
    repo = repo_with_record(tmp_path)
    write_intent(repo, _unclosed_fence())
    commit_intent(repo)
    code, rows, _, _ = _run(repo)
    assert subjects(rows) == ["section-missing"]
    assert rows[0]["code"] == 51
    assert "unclosed code fence" in rows[0]["message"], rows[0]
    assert "Prefer the boring technology" not in rows[0]["message"]
    assert "2030-01-01" not in rows[0]["message"]
    assert code == 51


def test_the_filter_cannot_drop_the_intent_class_can_never_read(tmp_path):
    """The probe-honesty rule, pinned for this group: one uncommitted intent, then
    the same tree under a filter that named no intent class.

    Every ``cannot-tell`` this class raises comes from a read of the file itself,
    and ``keep`` only spares a row the group actually appended. Gating the group on
    its own class names alone therefore let ``--only ordering-stale`` report
    ``verdict ok`` on a tree whose intent it never opened -- the same inversion
    ``skills/census/SKILL.md`` promises against, and the one the ordering group
    pins in ``tests/test_census_ordering_malformed.py``. The row must arrive at its
    class and warn severity, and the filter must still filter: a widened gate that
    ran the group for an absent file would fail the assertion below it.
    """
    repo = repo_with_record(tmp_path)
    write_intent(repo)
    _commit(repo, "README.md", "hello\n")
    # hygiene always reports on an isolated fixture repo (its deny-list row), and
    # is not the row under test: every assertion here is about the intent class.
    intent_rows = [(r["check"], r["subject"])
                   for r in _rows(repo) if r["check"] == "intent"]
    assert intent_rows == [("intent", "cannot-tell")], intent_rows
    warns = [r for r in _rows(repo) if r["check"] == "intent"]
    assert warns[0]["severity"] == "warn"

    filtered = [(r["check"], r["subject"])
                for r in _rows(repo, "--only", "ordering-stale")
                if r["check"] == "intent"]
    assert filtered == [("intent", "cannot-tell")], filtered
    assert _run(repo, "--only", "ordering-stale")[0] == 0

    # The filter is still a filter, and so is the gate. An absent intent earns no
    # row for any run, filtered or not: the group is entered on a path that holds
    # something, not always.
    quiet = repo_with_record(tmp_path, subdir="quiet")
    _commit(quiet, "README.md", "hello\n")
    assert [r for r in _rows(quiet) if r["check"] == "intent"] == []
    assert [r for r in _rows(quiet, "--only", "ordering-stale")
            if r["check"] == "intent"] == []

    # And a well-formed intent the filter never named still yields only its own
    # rows, not a second copy of them: the gate opens the group, it does not widen
    # what the group is permitted to report.
    cited = repo_with_record(tmp_path, subdir="cited")
    install_intent(cited)
    commit_intent(cited)
    assert [r for r in _rows(cited, "--only", "ordering-stale")
            if r["check"] == "intent"] == []


def test_a_headline_that_does_not_cite_is_uncited(tmp_path):
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo, subject="docs: restate the intent")
    code, rows, _, _ = _run(repo)
    assert subjects(rows) == ["uncited"]
    assert rows[0]["artifact"] == INTENT_REL
    assert code == 51


def test_a_headline_that_cites_no_nameable_id_is_uncited(tmp_path):
    """The word alone is not a citation: an empty or malformed id cites nothing."""
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo, subject="intent: ")
    code, rows, _, _ = _run(repo)
    assert subjects(rows) == ["uncited"]
    assert code == 51


def test_a_cited_record_the_ledger_does_not_hold_is_uncited(tmp_path):
    repo = repo_with_record(tmp_path, records=())
    install_intent(repo)
    commit_intent(repo)
    code, rows, _, _ = _run(repo)
    assert subjects(rows) == ["uncited"]
    assert RECORD_ID in rows[0]["message"]
    assert code == 51


def test_a_superseded_record_is_uncited(tmp_path):
    """The writer refuses to install one; history records what was installed."""
    repo = repo_with_record(tmp_path, records=(
        record(), record(status="superseded", supersedes=RECORD_ID),
    ))
    install_intent(repo)
    commit_intent(repo)
    code, rows, _, _ = _run(repo)
    assert subjects(rows) == ["uncited"]
    assert "superseded" in rows[0]["message"]
    assert code == 51


def test_a_headline_commit_touching_another_path_does_not_count(tmp_path):
    """The citation is read from the last commit that touched *this* path."""
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo)
    _commit(repo, "README.md", "hello\n")
    code, rows, _, _ = _run(repo)
    assert rows == []
    assert code == 0


def test_a_record_that_will_not_parse_is_uncited(tmp_path):
    """The census read the record in full: what it holds is not a record."""
    repo = repo_with_record(tmp_path, records=(),
                            raw={f"noni/decisions/{RECORD_ID}.json": "{ not json"})
    install_intent(repo)
    commit_intent(repo)
    code, rows, _, _ = _run(repo)
    assert subjects(rows) == ["uncited"]
    assert "not readable JSON" in rows[0]["message"]
    assert code == 51


def test_a_record_whose_status_is_no_word_at_all_is_uncited(tmp_path):
    """A hand-edited status answers nothing about the chain, and the census says
    which word it found unacceptable without quoting the record's contents."""
    repo = repo_with_record(tmp_path, records=(),
                            raw={f"noni/decisions/{RECORD_ID}.json":
                                 json.dumps(dict(record(), status="maybe"), indent=2)})
    install_intent(repo)
    commit_intent(repo)
    code, rows, _, _ = _run(repo)
    assert subjects(rows) == ["uncited"]
    assert "maybe" not in rows[0]["message"]
    assert "not decided or open" in rows[0]["message"]
    assert code == 51


def test_a_record_that_is_not_an_object_is_uncited(tmp_path):
    repo = repo_with_record(tmp_path, records=(),
                            raw={f"noni/decisions/{RECORD_ID}.json": "[1, 2]"})
    install_intent(repo)
    commit_intent(repo)
    code, rows, _, _ = _run(repo)
    assert subjects(rows) == ["uncited"]
    assert "not a JSON object" in rows[0]["message"]
    assert code == 51


def test_the_ledger_override_is_the_ledger_the_citation_answers_against(tmp_path):
    """--ledger is honoured, as for every other group that reads the ledger."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / f"{RECORD_ID}.json").write_text(
        json.dumps(record(), indent=2) + "\n", encoding="utf-8")
    repo = repo_with_record(tmp_path, records=())
    install_intent(repo)
    commit_intent(repo)
    _, rows, _, _ = _run(repo, "--ledger", str(elsewhere))
    assert subjects(rows) == []


def test_strict_promotes_the_class_to_its_own_code(tmp_path):
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo, subject="docs: restate the intent")
    code, rows, _, _ = _run(repo, "--strict")
    assert [row["code"] for row in rows] == [51]
    assert code == 51


def test_the_class_reports_only_its_own_rows(tmp_path):
    repo = repo_with_record(tmp_path)
    _commit(repo, "noni/direction/order.json", json.dumps(
        {"schema": "noni.order/1", "entries": []}, indent=2) + "\n")
    install_intent(repo)
    commit_intent(repo, subject="docs: restate the intent")
    code, rows, _, _ = _run(repo)
    assert {row["check"] for row in rows} == {"intent"}
    assert code == 51


def test_human_output_names_the_class_and_its_subject(tmp_path):
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo, subject="docs: restate the intent")
    code, stdout, _ = _human(repo)
    assert code == 51
    assert "intent" in stdout
    assert "uncited" in stdout


def test_the_row_carries_a_fix_that_names_the_writer(tmp_path):
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo, subject="docs: restate the intent")
    _, rows, _, _ = _run(repo)
    assert "skills/direction/scripts/intent.py" in rows[0]["fix"]


def test_the_artifact_of_a_path_that_cannot_be_resolved_is_the_path_itself(tmp_path):
    """Naming the artifact is not allowed to end the run.

    The row's identifier comes from ``resolve()``, which follows the chain a
    symlinked artifact stands at, and ``pathlib`` turns an ``ELOOP`` it cannot
    attach an errno to into ``RuntimeError`` -- not an ``OSError``, and so not a
    fault any of this class's readers was catching. A row that reports a file this
    run could not read still has to name it, and the path it was given is the only
    spelling of it the run has: the report prints paths root-relative by
    convention, not by contract.
    """
    import noni.census as census

    repo = repo_with_record(tmp_path)
    a = repo / "noni" / "direction" / "a.md"
    b = repo / "noni" / "direction" / "b.md"
    a.parent.mkdir(parents=True, exist_ok=True)
    a.symlink_to(b)
    b.symlink_to(a)

    assert census._rel_to_root(repo, a) == str(a)
