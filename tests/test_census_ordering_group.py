"""The ordering group's plumbing: ``--only``/``--skip``, ``--list``, lowest code wins.

Plus the state file's own refusals: a missing state file is malformed, never silence,
and its path never reaches the report verbatim.

Split out of ``tests/test_census_ordering.py``; the builders are in
``tests/ordering_fixtures.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys

from _harness import REPO, subprocess_env
from ordering_fixtures import (
    BASELINE_ID,
    _commit,
    _entry,
    _human,
    _order,
    _repo,
    rows_without_unasked_closed,
    _run,
    _seed,
    _state,
)
from quickstart_page import ordering_note_from_product

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"

ORDER_REL = "noni/direction/order.json"

STALE = "2026-09-01T00:00:00Z"

def test_a_state_map_that_is_an_object_of_the_right_shape_is_clean(tmp_path):
    """The counter-case to the table above: canonical keys and the two states
    the file may name must not be refused, or the strictness would be a bug
    rather than a rule."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID), _entry(12, BASELINE_ID))
    path = repo / "issue-state.json"
    path.write_text('{"7": "open", "12": "closed"}', encoding="utf-8")
    code, rows, out, err = _run(repo, "--issue-state", str(path))
    assert code == 0, (code, out, err)
    assert [(r["check"], r["subject"]) for r in rows] == [("ordering-closed", "#12")], rows


def test_a_missing_state_file_is_malformed_not_silence(tmp_path):
    """The flag was given and its file is not there: that is a broken input,
    whereas giving no flag at all is a class the run declines to evaluate."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID))
    code, rows, out, err = _run(repo, "--issue-state", str(repo / "absent.json"))
    assert code == 15, (code, out, err)
    assert rows[0]["subject"] == "issue-state", rows[0]


def test_the_state_file_path_never_reaches_the_report_verbatim(tmp_path):
    """The row names its subject as an id, and any path the message carries is
    reduced to <path>: a report must not print someone's home directory."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID))
    code, rows, _out, _err = _run(repo, "--issue-state", str(repo / "nowhere.json"))
    assert code == 15
    assert str(repo) not in json.dumps(rows), rows


def test_no_flag_means_the_closed_question_is_not_asked_and_says_so(tmp_path):
    """The census never contacts a tracker, so with no --issue-state the class
    is not evaluated. Silence would read as 'every ordered issue is open', so
    the human-readable run prints one note; the NDJSON stream stays
    findings-only, which is what keeps it byte-reproducible.

    The human half is more than the note (issue #117): the report's first line
    used to say "all checks passed" here, above the very note that says a check
    did not run, so the headline is pinned to name the class the note names and
    neither line may carry the all-clear wording of a run that skipped nothing.
    A skipped class earns no verdict of its own, so a run that counted no row
    still says `clean` on its summary line -- what it may not say is that every
    check ran. The exit code stays 0 for the same reason.

    Issue #148 changed the NDJSON half of this contract: "the class adds no row at
    all" was the very silence a CI step read as a pass, so the unasked question now
    carries one row of its class -- ``warn``, so the exit code stays 0 without
    ``--strict``, and the code the class earns under it. Pinned here to that one row
    and to its shape: the artifact as its subject, never an issue, because the fact is
    about the run and not about any ordered issue. A run that answered the class about
    an issue would fail this assertion rather than pass it.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID))
    code, rows, _out, _err = _run(repo)
    assert code == 0, (code, rows)
    assert [(r["check"], r["severity"], r["subject"]) for r in rows] == [
        ("ordering-closed", "warn", ORDER_REL)], rows
    assert all(r["message"].startswith("closed state not checked:") for r in rows), rows
    code, out, err = _human(repo)
    assert code == 0, (code, out, err)
    assert "ordering-closed was not evaluated" in out, out
    assert "never contacts a tracker" in out, out
    lines = out.splitlines()
    assert lines[0] != "census: no findings; all checks passed", (
        f"a run that skipped a check opened with the all-clear banner: {lines[0]!r}")
    assert "all checks passed" not in lines[0], (
        f"the first line claimed every check passed above the not-evaluated "
        f"note: {lines[0]!r}")
    assert "ordering-closed" in lines[0], (
        f"the first line did not name the class that did not run: {lines[0]!r}")
    # The class name and the note's own sentence come from the product, not from
    # a copy kept here: one scraper, three doc tests, this assertion.
    assert ordering_note_from_product() in out, out


def test_the_note_is_carried_by_both_modes_and_is_not_a_finding_row(tmp_path):
    """A notice about a class that did not run is not a finding, in either mode.

    The NDJSON contract is findings plus one summary row and a caller parses
    every line, so the note is not a line of its own -- it is the summary row's
    ``not_evaluated`` list (issue #97), which is what stops a ``--json`` consumer
    reading ``"counts": {}`` as 'nothing is closed'. Human mode keeps printing the
    same sentence as a ``note:`` line. Both halves are read from the same tree:
    the field is present when no ``--issue-state`` was given and absent when one
    was, so the signal tracks the flag and not the wall clock (see the
    reproducibility pair in ``tests/test_census_report_mode.py``).
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID))
    _code, _rows, out, _err = _run(repo)
    rows = [json.loads(line) for line in out.splitlines() if line.strip()]
    for row in rows:
        assert row["kind"] in ("finding", "summary"), row
    summaries = [row for row in rows if row["kind"] == "summary"]
    assert len(summaries) == 1, rows
    note = summaries[0]["not_evaluated"]
    assert any("ordering-closed was not evaluated" in line for line in note), note
    assert any("never contacts a tracker" in line for line in note), note
    # The same tree with the flag given: the class was evaluated, so the summary
    # says nothing -- the field is absent, not empty.
    path = _state(repo, {"7": "open"})
    _code, _rows, given, _err = _run(repo, "--issue-state", path)
    rows = [json.loads(line) for line in given.splitlines() if line.strip()]
    summary = [row for row in rows if row["kind"] == "summary"][0]
    assert "not_evaluated" not in summary, summary


def test_no_note_when_the_state_file_was_given(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID))
    path = _state(repo, {"7": "open"})
    code, out, err = _human(repo, "--issue-state", path)
    assert code == 0, (code, out, err)
    assert "was not evaluated" not in out, out


# --ordering / --only / --skip --------------------------------------------------


def test_the_ordering_path_can_be_overridden(tmp_path):
    """The flag exists so an operator can census an artifact that does not sit
    at the default path; the group must read what it is pointed at."""
    repo = _repo(tmp_path)
    outside = repo / "elsewhere" / "order.json"
    outside.parent.mkdir(parents=True)
    outside.write_text('{"schema": "nope", "entries": []}', encoding="utf-8")
    code, rows, _out, _err = _run(repo, "--ordering", str(outside))
    assert code == 15, code
    assert "noni.order/1" in rows[0]["message"], rows[0]


def test_the_group_honours_only_and_skip(tmp_path):
    """One --only/--skip rule for all four groups: a class the caller did not
    ask for is never reported, and no group runs work whose rows it discards."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID, STALE))
    path = _state(repo, {"7": "closed"})
    args = ("--issue-state", path, "--stale-after", "7")
    only_stale = _run(repo, "--only", "ordering-stale", *args)
    assert [r["check"] for r in only_stale[1]] == ["ordering-stale"], only_stale[1]
    only_closed = _run(repo, "--only", "ordering-closed", *args)
    assert [r["check"] for r in only_closed[1]] == ["ordering-closed"], only_closed[1]
    skipped = _run(repo, "--skip", "ordering-stale", "--skip", "ordering-closed", *args)
    assert skipped[1] == [], skipped[1]


def test_the_three_classes_are_listed_by_the_list_flag(tmp_path):
    proc = subprocess.run([sys.executable, str(CENSUS), "--list"], capture_output=True,
                          text=True, env=subprocess_env(), timeout=60)
    listed = set(proc.stdout.split())
    assert {"ordering-malformed", "ordering-stale", "ordering-closed"} <= listed


def test_the_lowest_code_wins_across_the_group(tmp_path):
    """A run that fires a fail and two warns exits at the fail's code (15),
    because the group's warnings never lift the verdict on their own."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(0, BASELINE_ID, STALE))  # malformed and stale at once
    code, rows, out, err = _run(repo, "--stale-after", "7")
    assert code == 15, (code, out, err)
    # The tree holds issues and no --issue-state, so the class also reports its own
    # unasked row; this test isolates the group, and that row belongs to the fixture.
    assert {r["check"] for r in rows_without_unasked_closed(rows)} == {
        "ordering-malformed"}, rows


def test_a_broken_state_file_is_reported_even_when_the_artifact_is_broken(tmp_path):
    """A caller who filtered to one class still sees the half they asked about:
    the state file's own fault is not hidden behind the artifact's."""
    repo = _repo(tmp_path)
    _order(repo, "{not json")
    path = repo / "issue-state.json"
    path.write_text("[1]", encoding="utf-8")
    code, rows, _out, _err = _run(repo, "--issue-state", str(path),
                                  "--only", "ordering-malformed")
    assert code == 15
    subjects = {r["subject"] for r in rows}
    assert subjects == {ORDER_REL, "issue-state"}, rows


def test_the_ordering_group_reads_no_class_but_the_ordering_ones(tmp_path):
    """Isolation of the group: a run with no ``--only`` of its own still reports
    only ordering rows, beside a tree whose ledger group fails on its own."""
    repo = _repo(tmp_path)
    # A record the ledger group reports (``ledger-record``, 10) sits in the same
    # tree: the bare run reaches every group, so a leak would show up here as a
    # ledger row or the ledger's code rather than the ordering pair below.
    _commit(repo, "noni/decisions/2026-10-02-not-json.json", "{ not json\n")
    _seed(repo, _entry(3, "2026-01-01-ghost"))
    code, rows, _out, _err = _run(repo)
    # The tree holds issues and no --issue-state, so the class also reports its own
    # unasked row; this test isolates the group, and that row belongs to the fixture.
    assert {r["check"] for r in rows_without_unasked_closed(rows)} == {
        "ordering-malformed"}, rows
    assert code == 15, code
