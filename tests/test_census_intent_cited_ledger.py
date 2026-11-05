"""A link above the cited record — in ``noni/decisions`` or ``noni/`` — earns cannot-tell.

The cited record is one path: ``noni/decisions/<id>.json``. Refusing the leaf is
only half the invariant, because a link at either directory above it puts every
record beneath it outside the tree the census was asked to audit while the leaf
still stats as an ordinary file. Those states, and the two halves of the gate that
answers for them — the ledger probe the run already took, and the classifier this
class asks for itself — are asserted here.

The states of the cited path itself are in
``tests/test_census_intent_cited_record.py``; the intent file's own faults in
``tests/test_census_intent_cannot_tell.py``; the builders and runners in
``tests/intent_fixtures.py``.
"""

from __future__ import annotations

import json

import pytest
from intent_class_ast import intent_class_text, intent_module
from intent_fixtures import (
    RECORD_ID,
    _intent_rows,
    _json_rows,
    _run,
    probe_state_answers,
    run_census_in_process,
    subjects,
)

# The planted-path builders, named for what they plant rather than for the fixture.
from intent_fixtures import planted_ledger_link as _planted_ledger_link
from intent_fixtures import planted_record_link as _planted_record_link


@pytest.fixture
def intent_class():
    """The source of the module that owns the intent class; see the helper's doc."""
    return intent_class_text()


@pytest.fixture
def intent_ast(intent_class):
    """The same module parsed, for the pins that are about structure, not spelling."""
    return intent_module(intent_class)


def _assert_cannot_tell(intent_rows, code=0):
    """One ``cannot-tell`` warn from the intent class, at the exit that row decides."""
    assert subjects(intent_rows) == ["cannot-tell"], intent_rows
    assert intent_rows[0]["severity"] == "warn", intent_rows
    assert code == 0, f"a cannot-tell warn must leave the run at 0, not {code}"
    return intent_rows[0]


def _classifier_only_why(module):
    """The gate with its probe half taken away, so only the classifier is left.

    The fallback is the half of ``_ledger_why`` a hand-composed caller relies on, and
    the half a run that always probes would never exercise: with the probe answer
    short-circuiting it, a gate that only read the probe would pass every whole-run
    test and still hand a linked ledger straight to the read.
    """
    def gate(ledger, file_kind, ledger_state=None):
        for path in (ledger, ledger.parent):
            kind, _problem = file_kind(path, kind="dir")
            if kind == "symlink":
                return module.LEDGER_LINKED
            if kind == "nonregular":
                return module.LEDGER_NOT_A_DIR
        return None

    return gate


def test_a_symlinked_ledger_directory_is_cannot_tell(tmp_path):
    """A link above the cited path is the same defect one level up, and is refused.

    With ``noni/decisions`` itself a link to a directory outside the tree, the leaf
    classification calls the record an ordinary file and the read follows the parent
    link, so an outside file decided the verdict. The class classifies the ledger
    and the directory above it, the way ``probe_ledger`` does, before composing a
    path under them.

    The link is planted over the directory the intent cites, not alongside a missing
    one: an intent whose tree the run cannot reach earns no row from any class, and
    the state under test is the link, not an empty tree.
    """
    repo = _planted_ledger_link(tmp_path, "ledger-link")
    code, rows, _, _ = _run(repo)
    row = _assert_cannot_tell(_intent_rows(rows), code)
    # Neither the target's bytes nor the path to it reaches the row.
    row_text = json.dumps(row)
    assert "superseded" not in row_text
    assert "ledger-lives-here" not in row_text
    assert RECORD_ID in row["message"]


def test_a_symlinked_parent_of_the_ledger_is_cannot_tell(tmp_path):
    """``noni/`` itself as a link is refused too — one level up is still outside.

    The state the ledger group calls "symlink" and refuses to list; the intent group
    reads a record under the same path, so it asks the same two questions. The link
    is planted over the directory that holds the committed intent as well, so the run
    owes the read: the group is entered for a file it can reach, and the cited record
    behind the link is the thing it must refuse.
    """
    repo = _planted_ledger_link(tmp_path, "parent-link", parent=True)
    assert (repo / "noni" / "direction" / "intent.md").is_file(), (
        "the fixture lost the intent the run has to be owed a read of"
    )
    code, rows, _, _ = _run(repo)
    _assert_cannot_tell(_intent_rows(rows), code)
    assert "outside-nonni" not in json.dumps(_intent_rows(rows)[0])


def test_the_probe_refuses_a_link_it_saw_and_stays_out_of_the_way_otherwise(
        tmp_path, monkeypatch):
    """The refusal reads the probe the run already took, matched with ``==``.

    ``census_ledger.probe_ledger`` classifies the ledger and ``noni/`` and answers
    the state word ``"symlink"`` for a link at either level — the state the ledger
    group already refuses to list. The intent group reads a record under that same
    directory, so the run hands it that answer: a leaf classification alone calls
    the record an ordinary file and the read follows the parent link into bytes
    outside the audited tree, which is where an ``uncited ... the record is
    superseded`` verdict used to come from (measured with this gate removed).

    Two further states are asked of the same seam because the gate can fail in
    either direction. An unrecognised word must leave the read open, or a project
    whose ledger module gains a state word reports blindness for a tree that is
    fine. And the match is ``==``, not ``in``: a state that merely spells the word
    is not the finding the ledger module reported, and refusing on it would turn a
    clean tree into a cannot-tell.
    """
    import noni.census as census

    repo = _planted_ledger_link(tmp_path, "probe-state")
    monkeypatch.setattr(census, "_ledger_probe", probe_state_answers("symlink"))
    code, rows, _, _ = _run(repo)
    row = _assert_cannot_tell(_intent_rows(rows), code)
    assert RECORD_ID in row["message"], row
    assert "symlink" in row["message"], row
    assert "ledger-lives-here" not in json.dumps(row), row

    clean = _planted_record_link(tmp_path, "probe-passed")
    for state in ("ok-but-new", "not-symlink"):
        monkeypatch.setattr(census, "_ledger_probe", probe_state_answers(state))
        code, rows, _, _ = _run(clean)
        assert _intent_rows(rows) == [], (
            f"a probe that answered {state!r} closed the cited-record read, so the "
            f"gate refused on something other than the ledger module's own "
            f"'symlink': {_intent_rows(rows)}"
        )
        assert code == 0, rows


def test_the_cited_record_row_words_the_ledger_link_without_a_path(tmp_path,
                                                                   monkeypatch):
    """The row built from the probe's state word carries no path and no fault text.

    The probe's own ``problem`` field is ``OSError`` words for the states a fault
    forced, and a row must not carry the path a stat failed on. This row is composed
    from one fixed sentence of this module's, so a probe that arrived with a
    machine-local path in its fault half still reports a path-free row.
    """
    import noni.census as census

    repo = _planted_ledger_link(tmp_path, "probe-words")
    monkeypatch.setattr(census, "_ledger_probe",
                        probe_state_answers("symlink", fault=True))
    code, out, err = run_census_in_process(repo, "--only", "intent")
    rows = [row for row in _json_rows(out) if row["check"] == "intent"]
    _assert_cannot_tell(rows, code)
    message = rows[0]["message"]
    assert len(message) <= 300, f"a row past the census's own bound: {message!r}"
    assert "/home/" not in message, f"a host path reached the row: {message!r}"
    assert "xxxx" not in message, f"fault text reached the row: {message!r}"
    assert RECORD_ID in message, message
    assert err == ""


def test_the_probe_falling_back_to_the_classifier_is_what_refuses_the_link(
        tmp_path, monkeypatch):
    """A probe that faults is no answer, and the classifier half takes over.

    ``probe_ledger`` reads the tree, so a caller handing this class a probe of its
    own can hand it one that faults (the census's own wrapper swallows nothing, and
    a probe is a read like any other). When it does, the class must not read the
    fault as "no link reported" and open the record: it classifies the ledger and
    ``noni/`` itself. The tree is the linked one and the probe raises, so only the
    fallback can produce the row — which is what separates this test from the one
    above, where the probe answers for a tree that is clean.
    """
    from noni import census_json, census_run, census_text

    repo = _planted_ledger_link(tmp_path, "probe-faults")

    def faults(_ledger):
        raise OSError("readdir: I/O error")

    census = census_run._census()
    # The history view answers through the root recorded for the run in flight; a
    # direct caller records it the way ``census_run._run`` does, or the citation
    # branch is never reached and the test would assert nothing.
    census._set_run_root(repo)
    found: list[dict] = []
    census_run._intent.check_intent(
        repo / "noni" / "direction" / "intent.md", repo / "noni" / "decisions",
        repo, found, False,
        row=census._row, rel_to_root=census._rel_to_root,
        file_kind=census._file_kind, fault_text=census_text.fault_text,
        load_json_strict=census_json.load_json_strict,
        commit_subject=census._intent_commit_subject,
        ledger_state=faults)
    row = _assert_cannot_tell(_intent_rows(found))
    assert "symlink" in row["message"], row
    assert RECORD_ID in row["message"], row
    assert "I/O error" not in json.dumps(row), (
        f"the probe's own fault text reached the row: {row['message']!r}")


def test_the_cited_record_refuses_a_ledger_link_on_the_classifier_alone(tmp_path,
                                                                        monkeypatch):
    """With the probe short-circuit gone, the classifier half still refuses the link.

    ``_ledger_why`` has two halves: the answer the run's probe already took, and the
    same two levels classified here for a caller that handed the class no probe. A
    gate that read only the probe would pass every whole-run test above — the run
    always probes — and still hand a linked ledger straight to the read for the other
    caller. So the probe is asked a state that is not the link (which is what the
    ledger module answers for a directory it could list), and the ledger itself is
    planted as the link. Only the classifier can see it, and only the classifier
    half can refuse on it.
    """
    import noni.census as census
    from noni import census_run

    repo = _planted_ledger_link(tmp_path, "classifier-only")
    ledger = repo / "noni" / "decisions"
    # The probe insists the ledger is an ordinary directory; the tree says otherwise.
    monkeypatch.setattr(census, "_ledger_probe", probe_state_answers("ok"))
    monkeypatch.setattr(census_run._intent, "_ledger_why",
                        _classifier_only_why(census_run._intent))
    found: list[dict] = []
    census_run._check_intent(repo / "noni" / "direction" / "intent.md",
                             ledger, repo, False, found)
    row = _assert_cannot_tell(_intent_rows(found))
    assert "symlink" in row["message"], row
    assert "ledger-lives-here" not in json.dumps(row), row
    assert census.WHOLE_ARTIFACT_KEY in row, (
        "the refusal this caller cannot lean on a probe for is not marked "
        "whole-artifact, so a filtered run would drop it and report itself clean")
