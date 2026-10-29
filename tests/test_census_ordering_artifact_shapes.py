"""The shapes a present artifact can have, and what each one earns.

A record that exists but cannot be read is not called absent, a symlink or a
directory at the artifact path is malformed and not skipped, a non-UTF-8 artifact
names its class without echoing bytes, and a superseded or unmatched decision is a
finding.

Split out of ``tests/test_census_ordering.py``; the builders are in
``tests/ordering_fixtures.py``.
"""

from __future__ import annotations

import json

import pytest
from _harness import _git, git_pin_date
from ordering_fixtures import _canonical, _commit, _entry, _order, _repo, _run, _seed

BASELINE_ID = "2026-10-01-baseline"

NOW = "2026-10-27T12:00:00Z"

ORDER_REL = "noni/direction/order.json"

def test_a_record_that_exists_but_cannot_be_read_is_not_called_absent(tmp_path):
    """"No such record" and "I could not read it" are different answers with
    different fixes, and ``order.py`` already says so with exit 3. A census row
    that calls an unreadable record a decision that matches no file sends the
    operator to repair an order whose record is there.

    The row must also survive a filter that named only the closed or stale class:
    the census could not answer the citation, and a run that observed that and
    reported nothing is not a clean run.

    Skipped where the reading user can read a 000-mode file (root): there the
    condition cannot be produced, and asserting the absence of a finding that
    cannot occur would pin nothing.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(3, BASELINE_ID))
    record = repo / "noni" / "decisions" / f"{BASELINE_ID}.json"
    record.chmod(0o000)
    try:
        code, rows, out, err = _run(repo)
        if code == 0:
            pytest.skip("the reading user can read a 000-mode file")
        assert code == 15, (code, out, err)
        assert [r["check"] for r in rows] == ["ordering-malformed"], rows
        message = rows[0]["message"]
        assert "could not read" in message, message
        assert "matches no record file" not in message, message
        # The same artifact, filtered to the classes the operator gates on: the
        # unreadable citation is the group's own fault to report, not the class
        # the caller happened to name.
        for extra in (("--only", "ordering-closed", "--strict"),
                      ("--only", "ordering-stale", "--strict")):
            code, rows, out, err = _run(repo, *extra)
            assert code == 15, f"{extra}: exit {code} rows={rows} err={err}"
            assert "could not read" in rows[0]["message"], rows[0]
    finally:
        record.chmod(0o644)


def test_an_empty_entries_list_is_clean(tmp_path):
    """An operator who wants nothing ordered next has said so: the list is
    empty, the artifact is well-formed, and there is nothing to report."""
    repo = _repo(tmp_path)
    _order(repo, _canonical([]))
    code, rows, out, err = _run(repo)
    assert code == 0, (code, out, err)
    assert rows == [], rows


def test_a_symlink_at_the_artifact_path_is_malformed_not_skipped(tmp_path):
    """The census will not read through a link, and the artifact is *there*: a
    row is the only honest answer, and 'nothing to report' would be a lie."""
    repo = _repo(tmp_path)
    (repo / "elsewhere.json").write_text(_canonical([_entry(1, BASELINE_ID)]),
                                         encoding="utf-8")
    _git(repo, "add", "elsewhere.json")
    git_pin_date(repo, NOW, "commit", "-q", "-m", "direction: seed elsewhere")
    target = repo / ORDER_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(repo / "elsewhere.json")
    code, rows, out, err = _run(repo)
    assert code == 15, (code, out, err)
    assert "symlink" in rows[0]["message"], rows[0]


def test_a_directory_at_the_artifact_path_is_malformed(tmp_path):
    repo = _repo(tmp_path)
    (repo / ORDER_REL).mkdir(parents=True)
    code, rows, out, err = _run(repo)
    assert code == 15, (code, out, err)
    assert "not a readable regular file" in rows[0]["message"], rows[0]


def test_a_non_utf8_artifact_names_the_class_without_echoing_bytes(tmp_path):
    """The bytes are untrusted content: the row says the file is not UTF-8 and
    quotes none of it, so a hostile artifact cannot put its own text in a
    report."""
    repo = _repo(tmp_path)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "spacer")
    target = repo / ORDER_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = b"\xff\xfe\x00garbage \x80\x81"
    target.write_bytes(payload)
    _git(repo, "add", ORDER_REL)
    git_pin_date(repo, NOW, "commit", "-q", "-m", "direction: broken")
    code, rows, _out, _err = _run(repo)
    assert code == 15
    assert rows[0]["message"] == "the order file is not valid UTF-8", rows[0]
    assert "garbage" not in rows[0]["message"]


def test_a_decision_that_matches_no_record_is_a_finding(tmp_path):
    """The citation is the operator's claim that a decision set this position;
    a record that does not exist makes that claim unverifiable, which is a
    malformed ordering rather than a clean one."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(3, "2026-01-01-ghost"))
    code, rows, out, err = _run(repo)
    assert code == 15, (code, out, err)
    assert rows[0]["subject"] == "#3", rows[0]
    assert "matches no record" in rows[0]["message"], rows[0]


def test_a_superseded_decision_is_a_finding_naming_its_successor(tmp_path):
    """An ordering that cites a record the chain moved past is an ordering
    nobody voted for any more -- the same reasoning order.py applies before it
    writes, so the two halves cannot disagree."""
    repo = _repo(tmp_path)
    successor = "2026-10-20-scheduler"
    record = {
        "id": successor, "date": "2026-10-20T00:00:00Z", "asked_by": "developer",
        "questions": [{"id": "q1", "text": "Order?", "options": ["a", "b"], "answer": "a"}],
        "by": "Replay", "scope": "release ordering", "status": "decided",
        "supersedes": BASELINE_ID,
    }
    _commit(repo, f"noni/decisions/{successor}.json", json.dumps(record, indent=2) + "\n")
    baseline = repo / "noni" / "decisions" / f"{BASELINE_ID}.json"
    body = json.loads(baseline.read_text(encoding="utf-8"))
    body["status"] = "superseded"
    baseline.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    _git(repo, "add", baseline.relative_to(repo).as_posix())
    git_pin_date(repo, NOW, "commit", "-q", "-m", "steering: supersede")
    _seed(repo, _entry(3, BASELINE_ID))
    code, rows, out, err = _run(repo)
    assert code == 15, (code, out, err)
    assert "superseded" in rows[0]["message"], rows[0]
    assert successor in rows[0]["message"], rows[0]


def test_a_decision_of_null_is_never_a_finding(tmp_path):
    """'The operator placed this, no record is cited' is a state the file
    carries, not a defect: only a named citation is checked."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(3, None))
    code, rows, out, err = _run(repo)
    assert code == 0, (code, out, err)
    assert rows == [], rows


def test_a_confirmed_stamp_without_an_offset_is_malformed(tmp_path):
    """A stamp with no UTC offset names no instant, so the arbiter must not
    compare it against ``--now``: the writer's ``orderschema.parse_confirmed``
    already refuses one, and a census that read it as UTC would call clean an
    artifact its own writer refuses to touch."""
    repo = _repo(tmp_path)
    _order(repo, _canonical([_entry(3, None, "2026-10-26T00:00:00")]))
    code, rows, out, err = _run(repo)
    assert code == 15, (code, out, err)
    assert [r["check"] for r in rows] == ["ordering-malformed"], rows
    assert "not a UTC timestamp" in rows[0]["message"], rows[0]


def test_a_repeated_decision_key_is_malformed_and_not_last_wins(tmp_path):
    """``decision`` given twice in an otherwise well-formed entry.

    Under ``json.loads``' default last-wins the entry cites nothing while an
    earlier line of the same file says it cites a record, so the census reported
    this artifact clean (verified against the pre-fix reader: exit 0) at the same
    time its writer refused it -- an artifact nobody could repair, because the one
    command that touches it says no. The strict reader refuses the document, and
    the row is the group's whole-artifact row, not a per-entry one: no entry of a
    file whose keys cannot be read is answerable.
    """
    for index, body in enumerate((
        '{"schema": "noni.order/1", "entries": [{"issue": 3, "decision": '
        '"2026-10-01-baseline", "decision": null, '
        '"confirmed": "2026-10-26T00:00:00Z"}]}',
        '{"schema": "noni.order/1", "entries": [{"issue": 3, "issue": 4, '
        '"decision": null, "confirmed": "2026-10-26T00:00:00Z"}]}',
    )):
        repo = _repo(tmp_path, f"last-wins-{index}")
        _order(repo, body)
        code, rows, out, err = _run(repo)
        assert code == 15, f"{body}: exit {code} rows={rows} err={err}"
        assert [r["check"] for r in rows] == ["ordering-malformed"], rows
        assert rows[0]["subject"] == ORDER_REL, rows[0]


def test_a_repeated_key_in_the_document_is_malformed(tmp_path):
    """The same rule one level up: ``entries`` given twice is not a document
    with two lists, it is a document nobody can say what it holds."""
    repo = _repo(tmp_path)
    _order(repo, '{"schema": "noni.order/1", "entries": [], "entries": []}')
    code, rows, out, err = _run(repo)
    assert code == 15, (code, out, err)
    assert [r["check"] for r in rows] == ["ordering-malformed"], rows
