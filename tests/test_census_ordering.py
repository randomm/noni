"""The census's ordering group: three classes over one artifact, honest exits.

The writer's half of the contract lives in tests/test_order_writer.py. This file
holds the arbiter's half, and the two files deliberately disagree about nothing:

- ``ordering-malformed`` (fail 15): the artifact exists and is not the artifact.
  A missing file is not a finding, because the ordering layer is optional.
- ``ordering-stale`` (warn 45): an entry confirmed before ``--now`` minus the
  threshold. Measured against ``--now`` alone, so two runs with one ``--now``
  emit one byte-stream.
- ``ordering-closed`` (warn 46): an entry whose issue the ``--issue-state`` map
  says is closed, plus the ``cannot-tell`` row for the issues that map omits.

Also pinned here: the two default thresholds are distinct (a session is stale at
7 days, an ordering at 30) and one explicit ``--stale-after`` overrides both;
the group honours ``--only``/``--skip`` like every other group; the closed
question is never silently skipped; and no row ever carries a machine-local path.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _harness import ORDER, REPO, _git, _init_repo, git_pin_date, subprocess_env

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"
FIXTURE = REPO / "tests" / "fixtures" / "ordering" / "order-valid.json"

ORDER_REL = "noni/direction/order.json"
NOW = "2026-10-27T12:00:00Z"
BASELINE_ID = "2026-10-01-baseline"
STALE = "2026-09-01T00:00:00Z"
FRESH = "2026-10-26T00:00:00Z"


def _canonical(entries: list[dict]) -> str:
    return json.dumps({"schema": "noni.order/1", "entries": entries}, indent=2) + "\n"


def _entry(issue: int, decision: str | None = None, confirmed: str = FRESH) -> dict:
    return {"issue": issue, "decision": decision, "confirmed": confirmed}


def _repo(tmp_path: Path, subdir: str = "repo", records: bool = True) -> Path:
    """A throwaway tree, optionally holding one committed decided record.

    The record exists so a ``decision`` citation can be answerable: the census
    looks an id up by its filename stem, and a test that cites one against an
    empty ledger is testing the missing-record path, not the one it named.
    """
    repo = _init_repo(tmp_path / subdir)
    if records:
        record = {
            "id": BASELINE_ID, "date": "2026-10-01T00:00:00Z", "asked_by": "developer",
            "questions": [{"id": "q1", "text": "Order?", "options": ["a", "b"], "answer": "a"}],
            "by": "Replay", "scope": "release ordering", "status": "decided",
            "supersedes": None,
        }
        _commit(repo, f"noni/decisions/{BASELINE_ID}.json",
                json.dumps(record, indent=2) + "\n", "2026-10-01T00:00:00Z")
    return repo


def _commit(repo: Path, rel: str, body: str, date: str = NOW) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", rel)
    git_pin_date(repo, date, "commit", "-q", "-m", f"direction: {rel}")


def _order(repo: Path, body: str, commit: bool = True) -> None:
    if commit:
        _commit(repo, ORDER_REL, body)
        return
    target = repo / ORDER_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def _seed(repo: Path, *entries: dict) -> None:
    _order(repo, _canonical([dict(e) for e in entries]))


ORDERING_CLASSES = ("ordering-malformed", "ordering-stale", "ordering-closed")


def _only(extra: tuple[str, ...]) -> list[str]:
    """The --only set the run asks for: the caller's own --only values when it
    named any (so a filtering test filters), else the whole ordering group.

    Named explicitly because --only is a filter, not a mode: with no --only at
    all the run would also report the sessions and ledger classes that a test
    here did not ask about.

    A test that names a class explicitly must name EVERY class whose row it
    wants: the census applies one row filter per group, so a class outside the
    --only set is dropped even though the group ran and produced it. That is the
    census's documented contract, and these helpers must not paper over it.
    """
    named = [extra[i + 1] for i, a in enumerate(extra) if a == "--only"]
    return named or list(ORDERING_CLASSES)


def _only_args(extra: tuple[str, ...]) -> list[str]:
    """The argv fragment the run is launched with: every --only/--skip the caller
    named (so a filtering test filters), plus the whole ordering group when the
    caller named no --only at all, plus the caller's remaining flags.

    One pass over ``extra``: a value that belongs to --only or --skip is consumed
    with its flag and never re-added, so the names appear exactly once whoever
    named them. A caller that named only --skip values still gets the group's
    --only set: the helper's job is to confine the run to the ordering group, and
    a bare --skip would otherwise let the ledger, session and hygiene classes in
    beside it.
    """
    args: list[str] = []
    named: list[str] = []
    index = 0
    while index < len(extra):
        arg = extra[index]
        if arg in ("--only", "--skip") and index + 1 < len(extra):
            value = extra[index + 1]
            if arg == "--only":
                named.append(value)
            args += [arg, value]
            index += 2
            continue
        args.append(arg)
        index += 1
    if not named:
        for check in ORDERING_CLASSES:
            args += ["--only", check]
    return args


def _run(repo: Path, *extra: str) -> tuple[int, list[dict], str, str]:
    """The census over the ordering group only, as NDJSON plus raw streams."""
    args = [sys.executable, str(CENSUS), "--repo", str(repo), "--json", "--now", NOW]
    args += _only_args(extra)
    proc = subprocess.run(args, capture_output=True, text=True, env=subprocess_env(),
                          timeout=120)
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return proc.returncode, [r for r in rows if r.get("kind") == "finding"], \
        proc.stdout, proc.stderr


def _code(repo: Path, *extra: str) -> int:
    """The exit code of a run used only as a precondition (root can read a
    000-mode file, where the unreadable-record fault cannot be produced)."""
    return _run(repo, *extra)[0]


def _human(repo: Path, *extra: str) -> tuple[int, str, str]:
    args = [sys.executable, str(CENSUS), "--repo", str(repo), "--now", NOW]
    args += _only_args(extra)
    proc = subprocess.run(args, capture_output=True, text=True, env=subprocess_env(),
                          timeout=120)
    return proc.returncode, proc.stdout, proc.stderr


# --- the absent artifact ------------------------------------------------------


def test_no_order_file_adds_no_ordering_row(tmp_path):
    """The ordering layer is optional: a project that has never ordered anything
    censuses with no ordering rows at all, and no exit code of its own. Contrast
    the ledger, whose absence is the ledger-empty warn."""
    repo = _repo(tmp_path)
    code, rows, out, err = _run(repo)
    assert code == 0, (code, out, err)
    assert rows == [], rows


def test_a_missing_file_is_not_reported_even_under_strict(tmp_path):
    """--strict promotes warnings, it does not invent findings: a run with
    nothing to report stays clean whatever the flag does to severities."""
    repo = _repo(tmp_path)
    code, rows, out, err = _run(repo, "--strict")
    assert code == 0, (code, out, err)
    assert rows == [], rows


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
    writer's mirror of this table is in tests/test_order_writer.py."""
    shapes = {
        "not an object": ("[]", "not a JSON object"),
        "missing schema": ('{"entries": []}', "missing field"),
        "missing entries": ('{"schema": "noni.order/1"}', "missing field"),
        "unknown top-level field": ('{"schema": "noni.order/1", "entries": [], "x": 1}',
                                    "unknown field"),
        "entries not a list": ('{"schema": "noni.order/1", "entries": 3}',
                               "entries is not an array"),
        "entry not an object": ('{"schema": "noni.order/1", "entries": [1]}',
                                "entry 1 is not an object"),
        "entry missing fields": ('{"schema": "noni.order/1", "entries": [{"issue": 1}]}',
                                 "missing field"),
        "entry with an extra field": ('{"schema": "noni.order/1", "entries": [{"issue": 1, '
                                      '"decision": null, "confirmed": '
                                      '"2026-10-26T00:00:00Z", "note": 1}]}',
                                      "unknown field"),
        "issue a string": ('{"schema": "noni.order/1", "entries": [{"issue": "1", '
                           '"decision": null, "confirmed": "2026-10-26T00:00:00Z"}]}',
                           "not a positive integer"),
        "issue a bool": ('{"schema": "noni.order/1", "entries": [{"issue": true, '
                         '"decision": null, "confirmed": "2026-10-26T00:00:00Z"}]}',
                         "not a positive integer"),
        "issue zero": ('{"schema": "noni.order/1", "entries": [{"issue": 0, '
                       '"decision": null, "confirmed": "2026-10-26T00:00:00Z"}]}',
                       "not a positive integer"),
        "issue listed twice": ('{"schema": "noni.order/1", "entries": [{"issue": 4, '
                               '"decision": null, "confirmed": "2026-10-26T00:00:00Z"}, '
                               '{"issue": 4, "decision": null, '
                               '"confirmed": "2026-10-26T00:00:00Z"}]}',
                               "appears more than once"),
        "decision a number": ('{"schema": "noni.order/1", "entries": [{"issue": 1, '
                              '"decision": 7, "confirmed": "2026-10-26T00:00:00Z"}]}',
                              "neither a record id nor null"),
        "decision blank": ('{"schema": "noni.order/1", "entries": [{"issue": 1, '
                           '"decision": "  ", "confirmed": "2026-10-26T00:00:00Z"}]}',
                           "neither a record id nor null"),
        "confirmed not a timestamp": ('{"schema": "noni.order/1", "entries": '
                                      '[{"issue": 1, "decision": null, '
                                      '"confirmed": "yesterday"}]}',
                                      "not a UTC timestamp"),
        "confirmed null": ('{"schema": "noni.order/1", "entries": [{"issue": 1, '
                           '"decision": null, "confirmed": null}]}',
                           "not a UTC timestamp"),
    }
    for index, (label, (body, needle)) in enumerate(sorted(shapes.items())):
        repo = _repo(tmp_path, f"malformed-{index}")
        _order(repo, body)
        code, rows, out, err = _run(repo)
        assert code == 15, f"{label}: exit {code} rows={rows} err={err}"
        assert rows and rows[0]["check"] == "ordering-malformed", f"{label}: {rows}"
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


def test_an_unreadable_ledger_does_not_blame_every_entry(tmp_path):
    """A ledger the census cannot list answers nothing, so no entry's decision
    may be reported as matching no file: the ordering group stays silent and
    leaves the ledger's own classes to report the tree."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(3, BASELINE_ID))
    shutil.rmtree(repo / "noni" / "decisions")
    (repo / "noni" / "decisions").write_text("not a directory", encoding="utf-8")
    code, rows, out, err = _run(repo)
    assert code == 0, (code, out, err)
    assert rows == [], rows


def test_a_committed_canonical_artifact_is_clean(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(3, BASELINE_ID), _entry(4, None))
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
    _seed(repo, _entry(7, None, "2026-10-20T12:00:00Z"))  # exactly 7 days before --now
    code, rows, _out, _err = _run(repo, "--stale-after", "7")
    assert code == 0 and rows == [], (code, rows)
    just_past = _repo(tmp_path, "past")
    _seed(just_past, _entry(7, None, "2026-10-20T11:59:59Z"))
    code, rows, _out, _err = _run(just_past, "--stale-after", "7")
    assert [r["check"] for r in rows] == ["ordering-stale"], rows


def test_staleness_is_measured_against_now_alone(tmp_path):
    """Two runs with one --now and one artifact emit one byte-stream: a stale
    row built from the wall clock would make a census run unreproducible, which
    is the property every other time-based class already holds."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None, STALE))
    _a, rows_a, out_a, _ea = _run(repo, "--stale-after", "7")
    _b, rows_b, out_b, _eb = _run(repo, "--stale-after", "7")
    assert out_a == out_b, "the ordering rows are not reproducible"
    assert rows_a == rows_b


def test_every_stale_entry_gets_its_own_row(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None, STALE), _entry(8, None, STALE), _entry(9, None, FRESH))
    code, rows, _out, _err = _run(repo, "--stale-after", "7")
    assert [r["subject"] for r in rows] == ["#7", "#8"], rows


# --- ordering-closed ----------------------------------------------------------


def _state(repo: Path, mapping: dict[str, str]) -> str:
    path = repo / "issue-state.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    return str(path)


def test_a_closed_issue_is_reported_at_forty_six(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID), _entry(8, None))
    path = _state(repo, {"7": "closed", "8": "open"})
    code, rows, out, err = _run(repo, "--issue-state", path)
    assert code == 0, (code, out, err)  # a warn, so the verdict stays clean
    assert [(r["check"], r["subject"]) for r in rows] == [("ordering-closed", "#7")], rows
    assert rows[0]["code"] == 46 and rows[0]["severity"] == "warn"
    assert rows[0]["message"].startswith("closed:"), rows[0]


def test_the_closed_row_says_so_under_strict(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None))
    path = _state(repo, {"7": "closed"})
    code, rows, _out, _err = _run(repo, "--issue-state", path, "--strict")
    assert code == 46, code
    assert rows[0]["severity"] == "fail", rows[0]


def test_an_issue_the_map_omits_gets_a_cannot_tell_row(tmp_path):
    """Probe honesty: a partial map is not evidence that everything else is
    open. The row belongs to ordering-closed because that is the question it
    could not answer."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None), _entry(8, None))
    path = _state(repo, {"8": "open"})
    code, rows, _out, _err = _run(repo, "--issue-state", path)
    assert [(r["subject"], r["message"].startswith("cannot-tell:")) for r in rows] == [
        ("#7", True)], rows
    assert code == 0, code


def test_an_unlisted_map_is_malformed_never_read_as_all_open(tmp_path):
    """A typo in the file the operator produced must stop the closed check
    reading 'no rows' as 'nothing is closed': the run reports the bad input."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None))
    path = repo / "issue-state.json"
    path.write_text('{"7": "maybe"}', encoding="utf-8")
    code, rows, out, err = _run(repo, "--issue-state", str(path))
    assert code == 15, (code, out, err)
    assert rows[0]["subject"] == "issue-state", rows[0]
    assert "not 'open' or 'closed'" in rows[0]["message"], rows[0]


def test_a_map_that_is_not_an_object_is_malformed(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, None))
    path = repo / "issue-state.json"
    path.write_text("[7]", encoding="utf-8")
    code, rows, _out, _err = _run(repo, "--issue-state", str(path))
    assert code == 15
    assert "not a JSON object" in rows[0]["message"], rows[0]


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
