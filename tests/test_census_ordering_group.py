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
    _commit,
    _entry,
    _human,
    _order,
    _repo,
    _run,
    _seed,
    _state,
)

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"

ORDER_REL = "noni/direction/order.json"

STALE = "2026-09-01T00:00:00Z"

def test_a_state_map_that_is_an_object_of_the_right_shape_is_clean(tmp_path):
    """The counter-case to the table above: canonical keys and the two states
    the file may name must not be refused, or the strictness would be a bug
    rather than a rule."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None), _entry(12, None))
    path = repo / "issue-state.json"
    path.write_text('{"7": "open", "12": "closed"}', encoding="utf-8")
    code, rows, out, err = _run(repo, "--issue-state", str(path))
    assert code == 0, (code, out, err)
    assert [(r["check"], r["subject"]) for r in rows] == [("ordering-closed", "#12")], rows


def test_a_missing_state_file_is_malformed_not_silence(tmp_path):
    """The flag was given and its file is not there: that is a broken input,
    whereas giving no flag at all is a class the run declines to evaluate."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None))
    code, rows, out, err = _run(repo, "--issue-state", str(repo / "absent.json"))
    assert code == 15, (code, out, err)
    assert rows[0]["subject"] == "issue-state", rows[0]


def test_the_state_file_path_never_reaches_the_report_verbatim(tmp_path):
    """The row names its subject as an id, and any path the message carries is
    reduced to <path>: a report must not print someone's home directory."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None))
    code, rows, _out, _err = _run(repo, "--issue-state", str(repo / "nowhere.json"))
    assert code == 15
    assert str(repo) not in json.dumps(rows), rows


def test_no_flag_means_the_closed_question_is_not_asked_and_says_so(tmp_path):
    """The census never contacts a tracker, so with no --issue-state the class
    is not evaluated. Silence would read as 'every ordered issue is open', so
    the human-readable run prints one note; the NDJSON stream stays
    findings-only, which is what keeps it byte-reproducible."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None))
    code, rows, _out, _err = _run(repo)
    assert code == 0 and rows == [], (code, rows)
    code, out, err = _human(repo)
    assert code == 0, (code, out, err)
    assert "ordering-closed was not evaluated" in out, out
    assert "never contacts a tracker" in out, out


def test_the_note_is_not_in_the_json_stream(tmp_path):
    """A notice about a class that did not run is not a finding: the NDJSON
    contract is findings plus one summary row, and a caller parses every line."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None))
    _code, _rows, out, _err = _run(repo)
    for line in out.splitlines():
        assert line.strip() == "" or json.loads(line)["kind"] in ("finding", "summary"), line


def test_no_note_when_the_state_file_was_given(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None))
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
    _seed(repo, _entry(7, None, STALE))
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
    _seed(repo, _entry(0, None, STALE))  # malformed and stale at once
    code, rows, out, err = _run(repo, "--stale-after", "7")
    assert code == 15, (code, out, err)
    assert {r["check"] for r in rows} == {"ordering-malformed"}, rows


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


def test_the_ordering_group_does_not_read_the_sessions_or_the_ledger_classes(tmp_path):
    """Isolation of the group: a tree whose sessions are broken still reports
    only ordering rows when only the ordering classes were asked for."""
    repo = _repo(tmp_path)
    _commit(repo, "noni/sessions/2026-10-01-aaaaaa.md", "no fields at all\n")
    _seed(repo, _entry(3, "2026-01-01-ghost"))
    code, rows, _out, _err = _run(repo)
    assert {r["check"] for r in rows} == {"ordering-malformed"}, rows
    assert code == 15, code
