"""A clean artifact, ``ordering-stale`` (warn 45) and ``ordering-closed`` (warn 46).

Staleness is measured against ``--now`` alone and the two default thresholds are
distinct; the closed question is asked only when a state map was given, and the
cannot-tell row says when it was not.

Split out of ``tests/test_census_ordering.py``; the builders are in
``tests/ordering_fixtures.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from _harness import REPO
from ordering_fixtures import _commit, _entry, _repo, _run, _seed
from ordering_shapes import issue_state_shapes

BASELINE_ID = "2026-10-01-baseline"

FIXTURE = REPO / "tests" / "fixtures" / "ordering" / "order-valid.json"

FRESH = "2026-10-26T00:00:00Z"

ORDER_REL = "noni/direction/order.json"

STALE = "2026-09-01T00:00:00Z"

def test_a_committed_canonical_artifact_is_clean(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(3, BASELINE_ID), _entry(4, BASELINE_ID))
    code, rows, out, err = _run(repo)
    assert code == 0, (code, out, err)
    assert rows == [], rows


def test_the_shared_fixture_censuses_clean(tmp_path):
    """The fixture both test files share is the documented artifact, so the
    arbiter must accept it byte for byte."""
    repo = _repo(tmp_path)
    _commit(repo, ORDER_REL, FIXTURE.read_text(encoding="utf-8"))
    code, rows, out, err = _run(repo)
    assert code == 0, (code, out, err)
    assert rows == [], rows


# --- ordering-stale -----------------------------------------------------------


def test_a_confirmed_time_past_the_threshold_is_a_warn_at_forty_five(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID, STALE))
    code, rows, out, err = _run(repo, "--stale-after", "7")
    assert code == 0, (code, out, err)  # a warn never moves the exit on its own
    assert [r["check"] for r in rows] == ["ordering-stale"], rows
    assert rows[0]["code"] == 45 and rows[0]["severity"] == "warn"
    assert rows[0]["subject"] == "#7", rows[0]
    assert rows[0]["message"].startswith("stale:"), rows[0]


def test_the_stale_row_says_so_under_strict(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID, STALE))
    code, rows, out, err = _run(repo, "--stale-after", "7", "--strict")
    assert code == 45, (code, out, err)
    assert rows[0]["severity"] == "fail", rows[0]


def test_the_two_default_thresholds_are_distinct(tmp_path):
    """A session is stale at 7 days; an ordering that was confirmed three weeks
    ago is still the operator's word. Collapsing the two would report a healthy
    queue as stale the moment the sessions group's default applied to it."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID, "2026-10-10T00:00:00Z"))  # 17 days old
    code, rows, _out, _err = _run(repo)
    assert code == 0 and rows == [], (code, rows)
    # The same run, asked for the sessions default: now it is stale.
    code, rows, _out, _err = _run(repo, "--stale-after", "7")
    assert [r["check"] for r in rows] == ["ordering-stale"], rows


def test_the_threshold_boundary_is_exclusive(tmp_path):
    """Exactly the threshold is not past it: 'stale' means older than the
    window, and a row for an entry at the boundary would make a 30-day window
    a 29-day one."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID, "2026-10-20T12:00:00Z"))  # exactly 7 days before --now
    code, rows, _out, _err = _run(repo, "--stale-after", "7")
    assert code == 0 and rows == [], (code, rows)
    just_past = _repo(tmp_path, "past")
    _seed(just_past, _entry(7, BASELINE_ID, "2026-10-20T11:59:59Z"))
    code, rows, _out, _err = _run(just_past, "--stale-after", "7")
    assert [r["check"] for r in rows] == ["ordering-stale"], rows


def test_staleness_is_measured_against_now_alone(tmp_path):
    """Two runs with one --now and one artifact emit one byte-stream: a stale
    row built from the wall clock would make a census run unreproducible, which
    is the property every other time-based class already holds."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID, STALE))
    _a, rows_a, out_a, _ea = _run(repo, "--stale-after", "7")
    _b, rows_b, out_b, _eb = _run(repo, "--stale-after", "7")
    assert out_a == out_b, "the ordering rows are not reproducible"
    assert rows_a == rows_b


def test_every_stale_entry_gets_its_own_row(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID, STALE), _entry(8, BASELINE_ID, STALE), _entry(9, BASELINE_ID, FRESH))
    code, rows, _out, _err = _run(repo, "--stale-after", "7")
    assert [r["subject"] for r in rows] == ["#7", "#8"], rows


# --- ordering-closed ----------------------------------------------------------


def _state(repo: Path, mapping: dict[str, str]) -> str:
    path = repo / "issue-state.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    return str(path)


def test_a_closed_issue_is_reported_at_forty_six(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID), _entry(8, BASELINE_ID))
    path = _state(repo, {"7": "closed", "8": "open"})
    code, rows, out, err = _run(repo, "--issue-state", path)
    assert code == 0, (code, out, err)  # a warn, so the verdict stays clean
    assert [(r["check"], r["subject"]) for r in rows] == [("ordering-closed", "#7")], rows
    assert rows[0]["code"] == 46 and rows[0]["severity"] == "warn"
    assert rows[0]["message"].startswith("closed:"), rows[0]


def test_the_closed_row_says_so_under_strict(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID))
    path = _state(repo, {"7": "closed"})
    code, rows, _out, _err = _run(repo, "--issue-state", path, "--strict")
    assert code == 46, code
    assert rows[0]["severity"] == "fail", rows[0]


def test_an_issue_the_map_omits_gets_a_cannot_tell_row(tmp_path):
    """Probe honesty: a partial map is not evidence that everything else is
    open. The row belongs to ordering-closed because that is the question it
    could not answer."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID), _entry(8, BASELINE_ID))
    path = _state(repo, {"8": "open"})
    code, rows, _out, _err = _run(repo, "--issue-state", path)
    assert [(r["subject"], r["message"].startswith("cannot-tell:")) for r in rows] == [
        ("#7", True)], rows
    assert code == 0, code


def test_an_unlisted_map_is_malformed_never_read_as_all_open(tmp_path):
    """A typo in the file the operator produced must stop the closed check
    reading 'no rows' as 'nothing is closed': the run reports the bad input."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID))
    path = repo / "issue-state.json"
    path.write_text('{"7": "maybe"}', encoding="utf-8")
    code, rows, out, err = _run(repo, "--issue-state", str(path))
    assert code == 15, (code, out, err)
    assert rows[0]["subject"] == "issue-state", rows[0]
    assert "not 'open' or 'closed'" in rows[0]["message"], rows[0]


def test_a_map_that_is_not_an_object_is_malformed(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID))
    path = repo / "issue-state.json"
    path.write_text("[7]", encoding="utf-8")
    code, rows, _out, _err = _run(repo, "--issue-state", str(path))
    assert code == 15
    assert "not a JSON object" in rows[0]["message"], rows[0]


def test_the_state_map_keys_must_be_canonical_and_unique(tmp_path):
    """Every shape an ``--issue-state`` file can hold that answers nothing for
    an issue, one file each: a repeated key (last-wins would say one thing for
    an issue and the file's text the opposite), and a key that is not the
    canonical decimal form of a positive issue number.

    ``str(int(key)) == key`` is the whole rule, and it is what makes a lookup
    answerable at all: the entry's issue is rendered as ``str(int(...))``, so a
    padded or signed key can never match an entry and would silently become a
    cannot-tell row for an issue the file does name. The shared table lives in
    ``tests/ordering_shapes.py`` so the writer's mirror cannot drift.
    """
    for index, (label, (body, needle)) in enumerate(sorted(issue_state_shapes().items())):
        repo = _repo(tmp_path, f"state-{index}")
        _seed(repo, _entry(7, BASELINE_ID))
        path = repo / "issue-state.json"
        path.write_text(body, encoding="utf-8")
        code, rows, out, err = _run(repo, "--issue-state", str(path))
        assert code == 15, f"{label}: exit {code} rows={rows} err={err}"
        assert rows and rows[0]["check"] == "ordering-malformed", f"{label}: {rows}"
        assert rows[0]["subject"] == "issue-state", f"{label}: {rows[0]}"
        if needle:
            assert needle in rows[0]["message"], f"{label}: {rows[0]}"


def test_a_non_ascii_digit_key_is_malformed_and_not_a_traceback(tmp_path):
    """A key the census must refuse before ``int`` is ever asked about it.

    ``str.isdigit`` is True for a superscript or an Arabic-Indic digit, but
    ``int`` accepts only ASCII decimal digits, so the canonical form used to
    reach ``int`` for a key like ``"\u00b2"`` and the census died on
    ``ValueError`` in the middle of the run. An arbiter that crashes answers
    nothing: the artifact that holds one such key is the ordinary malformed row
    at exit 15, with the class's own wording and no traceback on either stream.
    """
    for index, key in enumerate(("\u00b2", "\u0667")):
        repo = _repo(tmp_path, f"nonascii-key-{index}")
        _seed(repo, _entry(7, BASELINE_ID))
        path = repo / "issue-state.json"
        path.write_text(json.dumps({key: "open"}), encoding="utf-8")
        code, rows, out, err = _run(repo, "--issue-state", str(path))
        combined = out + err
        assert "Traceback" not in combined, combined[-2000:]
        assert "ValueError" not in combined, combined[-2000:]
        assert code == 15, (key, code, rows, combined[-2000:])
        assert rows and rows[0]["check"] == "ordering-malformed", rows
        assert rows[0]["subject"] == "issue-state", rows[0]
        assert "not an issue number" in rows[0]["message"], rows[0]
