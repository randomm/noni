"""``ordering-malformed`` (fail 15): the artifact exists and is not the artifact.

A missing file is not a finding, because the ordering layer is optional; the writer's
half of the contract lives in ``tests/test_order_writer.py``. An unreadable ledger is
never blamed on every entry and never reads as clean.

Split out of ``tests/test_census_ordering.py``; the builders are in
``tests/ordering_fixtures.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from _harness import ORDER, REPO, _git, git_pin_date, subprocess_env
from ordering_fixtures import (
    _canonical,
    _code,
    _entry,
    _order,
    _repo,
    _run,
    _seed,
    _state,
)
from ordering_shapes import MALFORMED_SHAPES as SHAPES

BASELINE_ID = "2026-10-01-baseline"

FRESH = "2026-10-26T00:00:00Z"

NOW = "2026-10-27T12:00:00Z"

ORDERING_CLASSES = ("ordering-malformed", "ordering-stale", "ordering-closed")

ORDER_REL = "noni/direction/order.json"

STALE = "2026-09-01T00:00:00Z"

# --- ordering-malformed -------------------------------------------------------


def test_unparseable_bytes_are_a_finding_at_fifteen(tmp_path):
    repo = _repo(tmp_path)
    _order(repo, "{not json")
    code, rows, out, err = _run(repo)
    assert code == 15, (code, out, err)
    assert [r["check"] for r in rows] == ["ordering-malformed"], rows
    assert rows[0]["code"] == 15 and rows[0]["severity"] == "fail"
    assert "not valid JSON" in rows[0]["message"], rows[0]
    assert rows[0]["subject"] == ORDER_REL, rows[0]
    assert rows[0]["artifact"] == ORDER_REL, rows[0]


def test_a_wrong_schema_is_a_finding(tmp_path):
    repo = _repo(tmp_path)
    _order(repo, json.dumps({"schema": "noni.order/2", "entries": []}))
    code, rows, _out, _err = _run(repo)
    assert code == 15
    assert "noni.order/1" in rows[0]["message"], rows[0]


def test_the_malformed_shapes_are_all_reported(tmp_path):
    """The whole set the class owns, one repo each: a shape the census does not
    report is a shape that would rot unnoticed in a committed artifact. The
    table is the shared one (``tests/ordering_shapes.py``), so the writer's
    mirror of it cannot drift from this side without a failure here."""
    for index, (label, (body, needle)) in enumerate(sorted(SHAPES.items())):
        repo = _repo(tmp_path, f"malformed-{index}")
        _order(repo, body)
        code, rows, out, err = _run(repo)
        assert code == 15, f"{label}: exit {code} rows={rows} err={err}"
        assert rows and rows[0]["check"] == "ordering-malformed", f"{label}: {rows}"
        if needle:
            assert needle in rows[0]["message"], f"{label}: {rows[0]}"


def test_a_non_finite_literal_is_unparseable_for_every_class_of_the_group(tmp_path):
    """A legal JSON literal that no writer can name (``1e400``, ``NaN``,
    ``Infinity``) makes the artifact unparseable for the *whole* group, not a
    defect one class happens to mention.

    Two of the four cases matter most: a run filtered to the classes the operator
    actually gates on (``--only ordering-stale --strict``,
    ``--only ordering-closed --strict``) and a run that skips the malformed class.
    Before the fix json read the literal into ``inf``, only ``ordering-malformed``
    noticed, and the group's row filter discarded that lone row -- so the run the
    operator reads exited 0 clean while a different filter on the same artifact
    called it malformed at 15. The arbiter contradicted itself, and the verdict
    the operator is told to gate on was the clean one.
    """
    bodies = {
        "an overflowed literal": '{"schema": "noni.order/1", "entries": '
                                 '[{"issue": 1, "decision": null, "confirmed": 1e400}]}',
        "a NaN in a number position": '{"schema": "noni.order/1", "entries": '
                                       '[{"issue": NaN, "decision": null, "confirmed": '
                                       '"2026-10-26T00:00:00Z"}]}',
        "an Infinity in a number position": '{"schema": "noni.order/1", "entries": '
                                             '[{"issue": 1, "decision": null, "confirmed": '
                                             '"2026-10-26T00:00:00Z", "n": Infinity}]}',
    }
    filters = (
        (),
        # A whole-artifact row survives a filter that did not name its class, so
        # every one of these exits 15: see
        # test_a_whole_artifact_row_survives_a_filter_that_did_not_name_its_class
        # for the filter rule itself.
        ("--only", "ordering-closed", "--strict"),
        ("--only", "ordering-stale", "--strict"),
        ("--skip", "ordering-malformed"),
    )
    for index, (label, body) in enumerate(bodies.items()):
        repo = _repo(tmp_path, f"nonfinite-{index}")
        _order(repo, body)
        state = _state(repo, {"1": "closed"})
        for extra in filters:
            code, rows, out, err = _run(repo, "--issue-state", state, *extra)
            assert code == 15, f"{label} {extra}: exit {code} rows={rows} out={out} err={err}"
            assert rows and rows[0]["check"] == "ordering-malformed", f"{label} {extra}: {rows}"


def test_a_whole_artifact_row_survives_a_filter_that_did_not_name_its_class(tmp_path):
    """The filter rule this class depends on, pinned directly.

    A group's --only filter keeps the rows of the classes it names and drops the
    rest -- that is what --only is for. What it must not drop is the row saying
    "I could not read the file you asked me to check": a run whose only ordering
    row was that one used to exit 0 clean under ``--only ordering-closed --strict``,
    which is the inversion the probe-honesty rule forbids. The same artifact under
    the same two filters therefore has to exit 15 with the malformed row present,
    while a per-entry row of a class the filter omits still disappears.
    """
    body = ('{"schema": "noni.order/1", "entries": [{"issue": 1, "decision": null, '
            '"confirmed": 1e400}]}')
    for index, extra in enumerate((
        ("--only", "ordering-closed", "--strict"),
        ("--only", "ordering-stale", "--strict"),
        ("--skip", "ordering-malformed"),
    )):
        repo = _repo(tmp_path, f"whole-artifact-{index}")
        _order(repo, body)
        state = _state(repo, {"1": "closed"})
        code, rows, out, err = _run(repo, "--issue-state", state, *extra)
        assert code == 15, f"{extra}: exit {code} rows={rows} out={out} err={err}"
        assert [r["check"] for r in rows] == ["ordering-malformed"], f"{extra}: {rows}"
        assert rows[0]["severity"] == "fail", rows[0]
    # The per-entry half of the rule is untouched: a stale row of a class the
    # filter omits is still dropped, so --only is still a filter.
    clean = _repo(tmp_path, "per-entry-filter")
    _seed(clean, _entry(7, None, STALE))
    state = _state(clean, {"7": "open"})
    code, rows, _out, _err = _run(clean, "--only", "ordering-closed", "--stale-after", "7",
                                  "--issue-state", state)
    assert code == 0 and rows == [], (code, rows)


def test_the_whole_artifact_rule_is_documented_where_the_filter_is_documented():
    """The filter rule this file depends on is an operator-facing contract, not
    an implementation detail of one reporter.

    ``--only`` is advertised as "run only the named check", and the one
    exception to it is that a row about a file a group was asked to read is
    reported whatever the filter names. A reader who is not told that reads an
    empty filtered run as "nothing was wrong" when the group in fact could not
    read its input -- the same inversion as a clean exit on an unreadable
    artifact, arriving through the documentation instead of the code. So the
    sentence must live where the flag is documented: `--only` is the only thing
    the rule is an exception *to*, which is what makes the row filter, rather
    than some other loop, the code a "tidy it up" edit would silently revert.
    """
    text = (REPO / "skills" / "census" / "SKILL.md").read_text(encoding="utf-8")
    row = next((line for line in text.splitlines()
                if line.startswith("| `--only CHECK`")), "")
    assert "dropped" in row, f"the --only row does not state what the filter drops: {row!r}"
    # The exception, named by the two nouns that make it recognisable: a row
    # about the *file a group was asked to read* survives the *filter*.
    assert "file a group was asked to read" in row, (
        f"the --only row omits the exception: {row!r}")
    assert "filter" in row and "reported" in row, (
        f"the --only row does not say the row is reported anyway: {row!r}")


def test_the_filter_keeps_a_whole_artifact_row_of_any_unnamed_class(tmp_path):
    """The visibility rule, pinned structurally: one fault of the group's own
    read, then the same artifact re-read under every single-class filter of the
    group plus a run that skips the malformed class entirely.

    The examples elsewhere in this file pin one artifact each (a non-finite
    literal, an unreadable record). What they do not pin is the *rule*: an
    author who reads the ``or`` term of the row filter as dead code -- nothing
    outside census.py names the concept, and one call site even puts the marker
    on a row whose subject is an entry -- can delete it and keep every existing
    name green. This test drives each kind of group-level fault through every
    filter and asserts the exact row set: the row must be *reported*, at its
    class, code and fail severity, and it must be the only row, so a filter
    widened into a no-op fails here too rather than only in the per-entry tests.
    """
    faults = {
        # The artifact itself: a number no writer can name.
        "an unreadable artifact": (
            '{"schema": "noni.order/1", "entries": '
            '[{"issue": 1, "decision": null, "confirmed": 1e400}]}', {}, False),
        # The group's other input: the state file the operator was asked to supply.
        "an unreadable state file": (_canonical([_entry(7, None)]),
                                     {"7": "perhaps"}, True),
        # A fault of the ledger the whole group's read depends on: every entry
        # is fresh, so the class that is not malformed has a row of its own to
        # be filtered to and the citation row cannot hide behind a stale entry
        # (skipped where the reading user can read a 000-mode file, as the
        # chmod test does).
        "an unreadable cited record": (_canonical([_entry(3, BASELINE_ID)]),
                                       {}, False),
    }
    filters = tuple(
        tuple(["--only", check] + (["--strict"] if strict else []))
        for check in ORDERING_CLASSES for strict in (False, True)
    ) + (("--skip", "ordering-malformed"),)
    for index, (label, (body, state_map, given_state)) in enumerate(faults.items()):
        repo = _repo(tmp_path, f"rule-{index}")
        _order(repo, body)
        record = repo / "noni" / "decisions" / f"{BASELINE_ID}.json"
        record.chmod(0o000)
        try:
            # The precondition is the unfiltered run: only there can the census
            # say it could not read the cited record. With the run already
            # filtered to one class a stale entry lifts the exit on its own and
            # an all-open state map yields no row at all, so a filtered probe
            # would read a healthy-but-filtered run as "root can read this" and
            # skip a case that is in fact producible.
            if _code(repo) == 0:
                pytest.skip("the reading user can read a 000-mode file")
            argv = (("--issue-state", _state(repo, state_map)) if given_state else ())
            for extra in filters:
                code, rows, out, err = _run(repo, *argv, *extra)
                assert code == 15, f"{label} {extra}: exit {code} rows={rows} out={out} err={err}"
                assert [r["check"] for r in rows] == ["ordering-malformed"], (
                    f"{label} {extra}: {rows}")
                assert rows[0]["severity"] == "fail", f"{label} {extra}: {rows[0]}"
                assert rows[0]["code"] == 15, f"{label} {extra}: {rows[0]}"
        finally:
            record.chmod(0o644)


def test_the_marker_never_reaches_the_reported_row(tmp_path):
    """The marker is an internal row field, and the row shape is a promise.

    ``_render`` builds each NDJSON object from the fields it names, so today no
    internal key can leak into the stream. That is true of the *renderer*, and a
    renderer that passed the row through, or gained a field copied from it, has
    no test at all: an underscore-keyed entry in a noni.census/1 row is a schema
    change nobody agreed to, and would be reproducible byte-for-byte into
    whatever consumed it. Pinning the emitted keys therefore belongs to the row
    contract, not to whichever helper happens to read the marker.
    """
    repo = _repo(tmp_path)
    _order(repo, '{"schema": "noni.order/1", "entries": '
                 '[{"issue": 1, "decision": null, "confirmed": 1e400}]}')
    code, rows, out, err = _run(repo, "--only", "ordering-closed", "--strict")
    assert code == 15, (code, out, err)
    assert rows, "the whole-artifact row is what this run must report"
    for row in rows:
        legal = {"schema", "kind", "check", "code", "severity", "subject",
                 "artifact", "message", "fix"}
        assert set(row) == legal, f"row keys drifted from noni.census/1: {sorted(row)}"
        assert not any(k.startswith("_") for k in row), f"internal key emitted: {row}"
    summary = [json.loads(line) for line in out.splitlines() if "summary" in line]
    assert len(summary) == 1, out
    assert set(summary[0]) == {"schema", "kind", "ok", "exit", "counts"}, summary[0]


def test_the_writer_and_the_census_refuse_the_same_non_finite_artifact(tmp_path):
    """The drift the ``_order_problems`` docstring promises is impossible, pinned
    on the one shape that used to produce it: the writer refuses the file (exit 4)
    and every class of the census says so too (exit 15). One side calling it clean
    is the bug this pins shut."""
    body = ('{"schema": "noni.order/1", "entries": [{"issue": 1, "decision": null, '
            '"confirmed": 1e400}]}')
    repo = _repo(tmp_path, "nonfinite-both-sides")
    _order(repo, body)
    writer = subprocess.run(
        [sys.executable, str(ORDER), "--repo", str(repo), "confirm", "--now", NOW],
        capture_output=True, text=True, env=subprocess_env(), timeout=120)
    assert writer.returncode == 4, (writer.returncode, writer.stdout, writer.stderr)
    code, rows, out, err = _run(repo)
    assert code == 15, (code, out, err)
    assert [r["check"] for r in rows] == ["ordering-malformed"], rows


def test_a_blank_decision_is_malformed_so_the_writer_and_census_agree(tmp_path):
    """``decision: ""`` and ``"   "`` match no record file, so the census's mirror
    of the writer's rule must ask for more than "is it a string": a hand-repaired
    artifact that the census called clean while the writer refused to touch it
    would stay that way forever, because the operator has no command that can
    repair it."""
    for index, blank in enumerate(("", "   ")):
        repo = _repo(tmp_path, f"blank-decision-{index}")
        _order(repo, _canonical([_entry(3, None, FRESH)]))
        target = repo / ORDER_REL
        target.write_text(json.dumps(
            {"schema": "noni.order/1", "entries": [{"issue": 3, "decision": blank,
                                                     "confirmed": FRESH}]}, indent=2) + "\n",
            encoding="utf-8")
        _git(repo, "add", ORDER_REL)
        git_pin_date(repo, NOW, "commit", "-q", "-m", "direction: blank decision")
        code, rows, out, err = _run(repo)
        assert code == 15, f"blank {blank!r}: exit {code} rows={rows} err={err}"
        assert [r["check"] for r in rows] == ["ordering-malformed"], rows
        assert "neither a record id nor null" in rows[0]["message"], rows[0]
