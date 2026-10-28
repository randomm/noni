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

import contextlib
import importlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

# In-process driving needs the census as a module (tests/conftest.py puts its
# directory on sys.path); the subprocess runners above use the path constant.
import census
import pytest
from _harness import (
    ORDER,
    REPO,
    SRC,
    _git,
    _harness_source,
    _init_repo,
    git_pin_date,
    subprocess_env,
)
from ordering_shapes import MALFORMED_SHAPES as SHAPES
from ordering_shapes import issue_state_shapes

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"
SCRIPTS = SRC / "noni"
FIXTURE = REPO / "tests" / "fixtures" / "ordering" / "order-valid.json"

ORDER_REL = "noni/direction/order.json"
NOW = "2026-10-27T12:00:00Z"
BASELINE_ID = "2026-10-01-baseline"
STALE = "2026-09-01T00:00:00Z"
FRESH = "2026-10-26T00:00:00Z"


def _canonical(entries: list[dict]) -> str:
    return json.dumps({"schema": "noni.order/1", "entries": entries}, indent=2) + "\n"


def _many_huge_fields() -> str:
    """A well-formed entry that also carries ten unknown fields with huge names.

    The join of the per-entry complaints is where an unbounded row is easiest to
    reach: one problem per unknown field, each naming a value read from the file.
    """
    junk = ", ".join(f'"{"f" * 300}{index}": 1' for index in range(10))
    return ('{"schema": "noni.order/1", "entries": [{"issue": 7, "decision": null, '
            '"confirmed": "' + FRESH + '", ' + junk + "}]}")


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


@contextlib.contextmanager
def _listing_faults(ledger: Path, text: str = "input/output error"):
    """Make the ORDERING GROUP'S read of ``ledger`` fault for the block.

    Two seams, because the group now reads the ledger through the run's one
    listing and a fault has to reach both halves of a run that does not have one:

    - ``census_ordering.check_ordering`` is patched to hand the readers ``None``
      for ``names``, which is what asks the readers to read the directory
      themselves (the census normally hands them the probe's names, so without
      this the group's read would not exist to fault);
    - ``census_ordering_readers.listing_helper`` is the name that read then
      calls, patched to raise for ``ledger``.

    Patching ``Path.iterdir`` instead would fault every listing of the run at
    once, so the ledger group would report the very same fault with a
    whole-artifact row of its own that survives every ``--only``/``--skip`` set
    (the probe-honesty rule in ``keep``), and no assertion of this file's group
    could name a row of its own without also naming that one. Faulting this
    group's read alone is what lets each test here pin this group's rows
    exactly. The ledger group's own half of the same fault is pinned by
    ``test_an_unlistable_ledger_is_reported_by_the_ledger_group_too``, which
    patches ``Path.iterdir`` instead, and by ``tests/test_census_ledger_probe.py``
    and ``tests/test_census_exit_codes.py``.

    The fault is raised as a bare ``OSError(text)``: that is the shape whose
    text the census must render without leaking a path, and the probe carries
    whatever the fault's ``str()`` holds (see ``test_census_ledger_probe``).

    Used with ``_run_in_process``, not with ``_run``: the census runs as a
    subprocess there, and a patch of this interpreter cannot reach it.
    """
    ordering = importlib.import_module("noni.census_ordering")
    readers = importlib.import_module("noni.census_ordering_readers")
    real_check = ordering.check_ordering
    real_helper = readers.listing_helper
    target = Path(ledger)

    def check_without_names(*args, **kwargs):
        # Ask the group to read the ledger for itself, so the read below exists
        # to fault (see ``names`` on ``check_ordering``).
        kwargs["names"] = None
        return real_check(*args, **kwargs)

    def boom(path):
        if Path(path) == target:
            raise OSError(text)
        return real_helper(path)

    ordering.check_ordering = check_without_names
    readers.listing_helper = boom
    try:
        yield
    finally:
        ordering.check_ordering = real_check
        readers.listing_helper = real_helper


@contextlib.contextmanager
def _ordering_record_read_faults(ledger: Path, text: str = "input/output error"):
    """The same fault as ``_listing_faults``, without the ``names`` override.

    For the test that pins the wiring of the run's one listing: it faults the
    readers' own ``listing_helper`` and leaves the census's names in place, so a
    run that still reached that helper for a group the probe already read fails
    there rather than passing on the probe's names. Kept separate from
    ``_listing_faults`` precisely so that test cannot be satisfied by the seam
    the other tests rely on.
    """
    readers = importlib.import_module("noni.census_ordering_readers")
    real_helper = readers.listing_helper
    target = Path(ledger)

    def boom(path):
        if Path(path) == target:
            raise OSError(text)
        return real_helper(path)

    readers.listing_helper = boom
    try:
        yield
    finally:
        readers.listing_helper = real_helper


@contextlib.contextmanager
def _listing_faults_all_reads(ledger: Path, text: str = "input/output error"):
    """Make EVERY ledger listing of the run fault, for the duration of the block.

    The seam is ``Path.iterdir``, the call every reader of the ledger ends at
    (``census_ledger.listing_helper`` uses ``iterdir`` precisely because ``glob``
    swallows the ``OSError`` a readdir raises and yields nothing). Unlike
    ``_listing_faults``, which faults the ordering group's read alone, this
    reaches the probe, the record pass and the ordering readers at once: it is
    the seam for the tests that pin what the whole run says about one fault.

    Used with ``_run_in_process``, not with ``_run``: the census runs as a
    subprocess there, and a patch of this interpreter cannot reach it.
    """
    real_iterdir = Path.iterdir
    target = Path(ledger)

    def boom(self):
        if self == target:
            raise OSError(text)
        return real_iterdir(self)

    Path.iterdir = boom
    try:
        yield
    finally:
        Path.iterdir = real_iterdir


def _run_in_process(repo: Path, *extra: str) -> tuple[int, list[dict], str, str]:
    """The census over the ordering group only, driven in this interpreter.

    The file's other runners launch a subprocess, which is what the coverage gate
    measures and what every behavioural test here uses. This one calls
    ``census.main`` directly so a test can reach a fault inside the interpreter --
    a listing that raises -- that no file permission can plant. The argument set
    is built exactly as ``_run`` builds it, so the two differ in one thing only:
    whether the census runs here or there.
    """
    argv = ["--repo", str(repo), "--json", "--now", NOW]
    argv += _only_args(extra)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(sys.stderr):
        code = census.main(argv)
    rows = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
    return code, [r for r in rows if r.get("kind") == "finding"], buffer.getvalue(), ""


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


def test_an_unlistable_ledger_is_reported_and_never_reads_as_clean(tmp_path):
    """A ledger whose listing itself faults answers nothing, and silence about
    that is a clean verdict on a run that checked no citation at all.

    The census lists the ledger with ``Path.glob``. When that call faults while an
    entry cites a decision, the group adds one whole-artifact row naming the
    fault, so the run is never clean: the row is a fail-class one, it exits 15 on
    its own and under ``--strict`` alike, and whole-artifact is what keeps it
    through every ``--only``/``--skip`` set (see ``keep`` in census.py).

    Distinguished from ``test_an_unreadable_ledger_does_not_blame_every_entry``:
    there the ledger path is not a directory, so the listing never runs and the
    ledger's own classes own the report. Here the path is a real directory whose
    listing faults -- an I/O fault of this tree, which no other class of the run
    can see, and the artifact is the one both sides gate on.

    The census runs in-process for this one (``_run_in_process``): the fault is
    inside the interpreter, and a subprocess would not see it."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(3, BASELINE_ID))
    with _listing_faults(repo / "noni" / "decisions"):
        code, rows, out, err = _run_in_process(repo)
        # ordering-malformed is a fail class, so the run is not clean with or
        # without --strict: the row is the whole point of the test.
        assert code == 15, (code, out, err)
        assert [r["check"] for r in rows] == ["ordering-malformed"], rows
        assert rows[0]["severity"] == "fail", rows[0]
        assert rows[0]["subject"] == ORDER_REL, rows[0]
        assert "noni/decisions" in rows[0]["message"], rows[0]
        # The OSError's own text reaches the row. It goes through the census's
        # machine-local-path scrubbing, which is anchored so that it stops at
        # absolute and home paths and leaves this errno text whole; the
        # assertions are written by substring, not by the whole phrase, so they
        # hold whichever way the scrub lands.
        assert "OSError" in rows[0]["message"], rows[0]
        assert "input" in rows[0]["message"], rows[0]
        # A whole-artifact row survives a filter that named none of its classes.
        for extra in (("--only", "ordering-stale", "--strict"),
                      ("--only", "ordering-closed", "--strict"),
                      ("--skip", "ordering-malformed", "--strict")):
            strict, strict_rows, s_out, s_err = _run_in_process(repo, *extra)
            assert strict == 15, f"{extra}: exit {strict} rows={strict_rows} {s_err}"
            assert [r["check"] for r in strict_rows] == ["ordering-malformed"], strict_rows
        strict, strict_rows, out, err = _run_in_process(repo, "--strict")
        assert strict == 15, (strict, out, err)


def test_an_unlistable_ledger_without_a_citation_adds_no_row(tmp_path):
    """Nothing was looked up, so nothing was left unchecked: an entry with no
    ``decision`` cannot have had its citation silently skipped, and the run
    stays clean. The row reports a check the run could not perform, not a fault
    of the ledger in general -- that is the ledger group's own report."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(3, None))
    with _listing_faults(repo / "noni" / "decisions"):
        code, rows, out, err = _run_in_process(repo, "--strict")
        assert code == 0, (code, out, err)
        assert rows == [], rows


def test_an_unlistable_ledger_is_reported_by_the_ledger_group_too(tmp_path):
    """Both groups read the ledger through the one listing, and both say so.

    Since the ledger group, the ordering group and the probe share
    ``census_ledger.listing_helper``, an injected readdir fault is visible to
    both classes at once. Each reports it in its own class: the ordering group's
    row says which check it could not perform, and the ledger group's says the
    append-only question went unanswered. The point of this test is that the
    ordering arm's fault -- injected at the ordering group's own seam by
    ``_listing_faults`` -- does not stand in for the ledger group's, which is
    why this one faults ``Path.iterdir``: the read every group shares.

    Run unfiltered (no ``--only`` at all), so no group's rows are dropped by a
    filter: the fault row of each group is whole-artifact and survives on its own
    merits. ``--skip hygiene`` is named because hygiene always reports, and its
    "deny-list class inactive" row belongs to no ledger or ordering contract."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(3, BASELINE_ID))
    with _listing_faults_all_reads(repo / "noni" / "decisions"):
        code, rows, out, err = _run_in_process(repo, "--skip", "hygiene")
        checks = sorted(r["check"] for r in rows)
        assert checks == ["ledger-edited", "ordering-malformed"], (checks, out, err)
        ledger_rows = [r for r in rows if r["check"] == "ledger-edited"]
        assert len(ledger_rows) == 1, rows
        assert ledger_rows[0]["subject"] == "noni/decisions", ledger_rows[0]
        assert "input/output error" in [
            r["message"] for r in rows if r["check"] == "ordering-malformed"][0]
        # Both classes are fail classes here: the ordering row is a fail class
        # outright, and --strict promotes the ledger group's cannot-tell warn.
        assert code == 15, (code, out, err)


def _ordering_host_faults() -> list[tuple[OSError, tuple[str, ...]]]:
    """The faults whose filename the scrubber keeps losing, and their parts.

    Built at runtime, never literals: a tracked file carrying one of these paths
    would trip the census's own hygiene class. A non-ASCII component with a space
    in it, and the bare home of a service account -- the two shapes the path arms
    of ``census_text._stripped`` cannot be relied on to catch, which is why the
    row is built without the filename rather than scrubbed after it.
    """
    return [
        (OSError(13, "Permission denied", "/home/someone/\u00fcn\u00ef c\u00f6de/my dir/"),
         ("someone", "\u00fcn\u00ef", "c\u00f6de", "my dir")),
        (OSError(13, "Permission denied", "~deploy"), ("deploy",)),
    ]


@contextlib.contextmanager
def _listing_fault(ledger: Path, fault: OSError):
    """Fault the ordering group's read of ``ledger`` with one given exception.

    ``_listing_faults`` raises a bare ``OSError(text)``, which is the shape every
    other test here wants. This one takes the exception itself, for the test that
    needs the filename a real fault carries.
    """
    ordering = importlib.import_module("noni.census_ordering")
    readers = importlib.import_module("noni.census_ordering_readers")
    real_check = ordering.check_ordering
    real_helper = readers.listing_helper
    target = Path(ledger)

    def check_without_names(*args, **kwargs):
        kwargs["names"] = None
        return real_check(*args, **kwargs)

    def boom(path):
        if Path(path) == target:
            raise fault
        return real_helper(path)

    ordering.check_ordering = check_without_names
    readers.listing_helper = boom
    try:
        yield
    finally:
        ordering.check_ordering = real_check
        readers.listing_helper = real_helper


@pytest.mark.parametrize("case", range(2))
def test_the_listing_fault_row_carries_no_part_of_the_filename(tmp_path, case):
    """The ordering group's row for an unlistable ledger names the fault, never a path.

    The same rule the ledger group's row obeys, pinned at this group's own seam:
    the fault text is built from the exception's class and its ``strerror``, so a
    filename the scrubber would have missed never reaches the row. The words and
    the ledger still have to appear -- a row that lost them to stay clean would
    fail here, not just the leak assertions.
    """
    repo = _repo(tmp_path, f"fault-no-filename-{case}")
    _seed(repo, _entry(3, BASELINE_ID))
    fault, parts = _ordering_host_faults()[case]
    with _listing_fault(repo / "noni" / "decisions", fault):
        code, rows, out, err = _run_in_process(repo)
    assert code == 15, (code, out, err)
    assert [r["check"] for r in rows] == ["ordering-malformed"], rows
    row = rows[0]
    for field in ("subject", "artifact", "message"):
        for part in parts:
            assert part not in row[field], f"{part!r} leaked into {field}: {row[field]!r}"
        assert "/home/someone" not in row[field], row[field]
    assert "Permission denied" in row["message"], row["message"]
    assert "PermissionError" in row["message"], row["message"]


def test_both_groups_name_an_unreadable_ledger_with_one_identifier(tmp_path):
    """One unreadable ledger, two rows, one name for it.

    The ledger group's row and the ordering group's row both report a ledger this
    run could not list, and an operator reading the report joins them by that
    name. The ordering group used to derive it by running the census's own
    root-relative path through the scrubber, which is the wrong tool for a path
    the census wrote itself: scrub a root-relative path and what comes back is a
    marker, not the directory. Both rows take the name from
    ``census_ledger.ledger_name`` instead, which is the census's one answer to
    "what do I call a ledger I could not read".

    The out-of-tree ``--ledger`` is the case that decides it: there the path is
    not rootable, so the identifier is a bare last segment and a scrubber handed
    the same path would have printed a host directory instead. Both groups read
    the ledger through the run's one listing, so faulting that listing is what
    leaves the two of them without an answer -- and the run is in-process because
    the fault lives in this interpreter.
    """
    repo = _repo(tmp_path, "shared-ledger-identifier")
    _seed(repo, _entry(3, BASELINE_ID))
    outside = tmp_path / "ledger-home" / "decisions"
    outside.mkdir(parents=True)
    (outside / f"{BASELINE_ID}.json").write_text(
        json.dumps({"id": BASELINE_ID, "date": "2026-10-01T00:00:00Z", "asked_by": "developer",
                    "questions": [{"id": "q1", "text": "Order?", "options": ["a", "b"],
                                   "answer": "a"}], "by": "Replay",
                    "scope": "release ordering", "status": "decided", "supersedes": None},
                   indent=2) + "\n",
        encoding="utf-8")
    with _listing_faults_all_reads(outside, "input/output error"):
        # ``--only ordering-malformed`` rather than the helper's default set: that
        # one confines the run to the ordering group, whose whole-artifact fault
        # row survives whatever it names, and the ledger group's own row for the
        # same fault is wanted here too -- which is what makes the two rows' name
        # for the ledger comparable.
        code, rows, out, err = _run_in_process(repo, "--ledger", str(outside),
                                               "--only", "ordering-malformed")
    assert code == 15, (code, out, err)
    by_check = {r["check"]: r for r in rows}
    assert sorted(by_check) == ["ledger-edited", "ordering-malformed"], rows
    ledger_row, ordering_row = by_check["ledger-edited"], by_check["ordering-malformed"]
    # The identifier the ledger group uses, in the ordering group's prose too.
    assert ledger_row["subject"] == "decisions", ledger_row
    assert "the decision ledger (decisions)" in ordering_row["message"], ordering_row["message"]
    for field in ("subject", "artifact", "message"):
        assert str(outside) not in ordering_row[field], ordering_row[field]
        assert "ledger-home" not in ordering_row[field], ordering_row[field]


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
        _seed(repo, _entry(7, None))
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
        _seed(repo, _entry(7, None))
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


def _strict_reader_copy(name: str, filename: str):
    """One module of the strict-reading pair, loaded by path from its own dir.

    The census's reader and the writer's reader are two copies of the same four
    refusals, and each side's suite has traditionally tested its own. Loading
    them by path here lets one assertion cover both without either test file
    importing the other side's package name.
    """
    spec = importlib.util.spec_from_file_location(f"noni_strict_copy_{name}",
                                                  SCRIPTS / filename)
    if spec is None or spec.loader is None:  # pragma: no cover - the path is fixed
        raise AssertionError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_strict_reader_refusals_never_echo_file_content():
    """Both strict readers' own refusals are composed of this product's words.

    ``json``'s duplicate-key and constant refusals used to name the offending key
    or literal, and their ``ValueError`` is what the readers turn into a row: an
    artifact somebody else wrote would have had its content printed in a report
    that promises not to. The readers catch the exception and answer with fixed
    wording today, so the pin belongs one level down -- on the two refusals
    themselves, in both copies -- where a future author reaching for the
    offending token meets a failure instead of a row that leaks.
    """
    for name, filename in (("census_json", "census_json.py"),
                           ("orderschema", "orderschema.py")):
        module = _strict_reader_copy(name, filename)
        with pytest.raises(ValueError) as duplicate:
            module.reject_duplicate_keys([("secret-key", 1), ("secret-key", 2)])
        assert "secret-key" not in str(duplicate.value), (filename, duplicate.value)
        assert "duplicate key" in str(duplicate.value), (filename, duplicate.value)
        for token in ("NaN", "Infinity", "-Infinity"):
            with pytest.raises(ValueError) as constant:
                json.loads(token, parse_constant=module.refuse_constant)
            assert token not in str(constant.value), (filename, token, constant.value)
            assert "not a JSON number" in str(constant.value), (filename, constant.value)
        load = module.load_json_strict if name == "census_json" \
            else module.load_json_checked
        # The bytes are an unpaired surrogate: no UTF-8 sequence encodes one, so
        # the decode that opens the reader is what refuses them. Spelled as an
        # escape because the thing under test is bytes no encoder will produce.
        undecodable = b'{"a": "\xed\xa0\x80"}'
        with pytest.raises(UnicodeDecodeError):
            load(undecodable, depth=8)


def test_a_composed_row_keeps_the_paths_it_names_while_staying_bounded(tmp_path):
    """Clipping a row is not scrubbing it.

    The bound on a composed row exists to cap what an untrusted file can push into
    a report; it must not also rewrite the root-relative paths this census derived
    itself. A row that called the ledger ``<path>`` would tell the operator that a
    listing failed and nothing about what to look at, so the two halves of the
    census's message primitive stay separate: foreign text is stripped and
    clipped, this run's own sentence is clipped alone.
    """
    repo = _repo(tmp_path, "composed-paths")
    _seed(repo, _entry(3, "2026-10-01-ghost"))
    code, rows, out, err = _run(repo)
    assert code == 15, (code, rows, out, err)
    message = rows[0]["message"]
    assert len(message) <= 300, f"{len(message)} chars: {message[:80]}"
    assert "noni/decisions" in message, message
    assert "<path>" not in message, message


def test_an_unlistable_ledger_row_stays_within_the_message_bound(tmp_path):
    """The listing fault a row quotes is foreign text and is bounded as a whole.

    The fault text is an ``OSError`` from this tree, so it arrives through the
    census's ``bounded`` for the piece inside the sentence -- but the finished row
    is that sentence around it, and a fault whose ``strerror`` runs to thousands
    of characters used to compose a row far past the bound every other row of the
    report keeps. The words this run chose still appear; the fault's own text
    still appears; neither is unbounded.

    In-process like the other injected-fault test here: the fault is inside the
    interpreter, and a subprocess would not see it.
    """
    repo = _repo(tmp_path, "long-listing-fault")
    _seed(repo, _entry(3, BASELINE_ID))
    with _listing_faults(repo / "noni" / "decisions",
                         "input/output error: " + "u" * 5000):
        code, rows, out, err = _run_in_process(repo)
    assert code == 15, (code, rows, out, err)
    assert [r["check"] for r in rows] == ["ordering-malformed"], rows
    message = rows[0]["message"]
    assert len(message) <= 300, f"{len(message)} chars: {message[:80]}"
    assert "noni/decisions" in message, message
    assert "OSError" in message, message
    assert "input" in message, message
    assert "u" * 5000 not in message, message


def test_an_entry_value_of_any_length_is_bounded_in_the_row(tmp_path):
    """The per-entry shape problems are joined and bounded as one message.

    The problems the census composes from the artifact's own values went through
    ``bounded`` never at all: the row was the join of every complaint, each of
    which quotes a value read from a file somebody else wrote. One 5000-character
    ``issue`` value therefore composed a row of thousands of characters.
    """
    bodies = {
        "a huge issue value": '{"schema": "noni.order/1", "entries": '
                              '[{"issue": "' + "i" * 5000 + '", "decision": null, '
                              '"confirmed": "' + FRESH + '"}]}',
        "a huge decision value": '{"schema": "noni.order/1", "entries": '
                                 '[{"issue": 7, "decision": "' + "d" * 5000 + '", '
                                 '"confirmed": "' + FRESH + '"}]}',
        "many huge unknown fields": _many_huge_fields(),
    }
    for index, (label, body) in enumerate(sorted(bodies.items())):
        repo = _repo(tmp_path, f"long-value-{index}")
        _order(repo, body)
        code, rows, out, err = _run(repo)
        assert code == 15, f"{label}: exit {code} rows={rows} err={err[-500:]}"
        assert [r["check"] for r in rows] == ["ordering-malformed"], f"{label}: {rows}"
        for row in rows:
            assert len(row["message"]) <= 300, \
                f"{label}: {len(row['message'])} chars: {row['message'][:80]}"
        assert "i" * 5000 not in json.dumps(rows), label
        assert "d" * 5000 not in json.dumps(rows), label


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


# --- a pathological nesting ---------------------------------------------------

# ``json.loads`` walks nesting with the interpreter's own stack, so a document
# that nests past the recursion budget raises RecursionError -- which is NOT a
# ValueError, so it is not caught by the arms every reader here already has for
# a malformed file. Where the budget runs out depends on the interpreter: 3.11
# gives up near ``sys.getrecursionlimit()`` (default 1000: measured to break at
# about 990 levels under pytest), later builds go on to a few thousand before the
# C stack itself gives out. The ``RecursionError`` arms below are therefore
# reachable, not theoretical: on 3.11 the ordinary decoder refuses a document
# this deep before this product's bound is consulted.
# Before the bound, one such file ended the whole run with a traceback: an
# arbiter that crashes answers nothing, and a report that never prints is the
# same lie as one that prints "clean".
DEEP = 100000


def _deep(depth: int = DEEP) -> str:
    """Legal JSON text nested ``depth`` levels: ``json.loads`` overflows on it.

    Built as text and not by rendering a Python value -- the value is the one the
    standard reader cannot build, so a fixture that had to parse it first could
    not test the reader that is supposed to survive it.
    """
    return "[" * depth + "1" + "]" * depth


def _deep_artifact() -> str:
    """An otherwise well-formed artifact whose entry carries one extra field
    nested ``DEEP`` levels."""
    return ('{"schema": "noni.order/1", "entries": [{"issue": 7, "decision": null, '
            '"confirmed": "' + FRESH + '", "x": ' + _deep() + "}]}")


def test_a_deeply_nested_artifact_is_malformed_and_not_a_traceback(tmp_path):
    """The pathological nesting is the ordinary ``ordering-malformed`` row: the
    artifact is there and is not the artifact, and the run exits at the class's
    own code with the class's own fixed wording."""
    repo = _repo(tmp_path, "deep-artifact")
    _order(repo, _deep_artifact())
    code, rows, out, err = _run(repo)
    combined = out + err
    assert "RecursionError" not in combined, combined[-2000:]
    assert code == 15, (code, rows, combined[-2000:])
    assert [r["check"] for r in rows] == ["ordering-malformed"], rows
    assert rows[0]["subject"] == ORDER_REL, rows[0]
    assert rows[0]["message"] == "the order file is not valid JSON", rows[0]


def test_a_deeply_nested_state_file_is_malformed_and_not_a_traceback(tmp_path):
    """The ``--issue-state`` reader is a second call into the same decoder, so it
    needs the same answer: the row is the state file's own and the run still
    exits 15 rather than dying."""
    repo = _repo(tmp_path, "deep-state")
    _seed(repo, _entry(7, None))
    path = repo / "issue-state.json"
    path.write_text(_deep(), encoding="utf-8")
    code, rows, out, err = _run(repo, "--issue-state", str(path))
    combined = out + err
    assert "RecursionError" not in combined, combined[-2000:]
    assert code == 15, (code, rows, combined[-2000:])
    assert [(r["check"], r["subject"]) for r in rows] == [
        ("ordering-malformed", "issue-state")], rows
    assert "is not valid JSON" in rows[0]["message"], rows[0]


def test_a_deep_document_is_refused_before_the_decoder_overflows():
    """Which rule refuses a pathological nesting, and why it has to be that one.

    ``json.loads`` walks nesting on the interpreter's own stack and gives up at
    a depth the build sets: on 3.11 that is near ``sys.getrecursionlimit()``,
    measured to break just under the default 1000, so the ``RecursionError`` arms
    of the readers are reachable there and not merely theoretical. Catching more
    exception types is still not the fix: a run is honest only if it never
    reaches the overflow. So the document here is one the standard reader can
    build on every supported interpreter -- past this product's bound, well
    inside the interpreter's budget -- and what refuses it is the bound alone. It
    raises the ``ValueError`` the callers already catch rather than leaving a
    ``RecursionError`` for them to miss.
    """
    module = importlib.import_module("census_json")
    # Above the product's bound, below the depth at which this interpreter's own
    # decoder gives up. That ceiling is a property of the build -- measured just
    # under the default limit of 1000 on 3.11, and several thousand on 3.12 and
    # 3.13 -- so twice the bound sits in that window on every supported version.
    # The assertion is the premise: a host that lowers the recursion limit below
    # the decoder's reach says so here, not on the line that reads the document.
    inside = module.MAX_DEPTH * 2
    budget = sys.getrecursionlimit()
    assert inside > module.MAX_DEPTH, (
        f"{inside} levels is not past the bound of {module.MAX_DEPTH}, so the "
        "bound is not what answered")
    assert inside < budget, (
        f"{inside} levels is not inside the recursion budget of {budget}")
    body = "[" * inside + "1" + "]" * inside
    assert json.loads(body), "the standard reader must still be able to build this"
    try:
        module.load_json_strict(("{" + '"a": ' + body + "}").encode())
    except ValueError as e:
        assert str(module.MAX_DEPTH) in str(e), \
            f"refused for another reason, so the bound is not what answered: {e}"
    else:
        raise AssertionError("a document nested past the bound was accepted")


def test_a_deeply_nested_ledger_record_leaves_the_run_alive(tmp_path):
    """The ledger read is the group's third reader. A record that does not parse
    is left out of the map for the ledger group to report, so here the entry's
    citation simply matches no record: a deep record must not end the run."""
    repo = _repo(tmp_path, "deep-ledger")
    _seed(repo, _entry(7, "2026-01-01-ghost"))
    record = repo / "noni" / "decisions" / "2026-01-01-ghost.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(_deep(), encoding="utf-8")
    code, rows, out, err = _run(repo)
    combined = out + err
    assert "RecursionError" not in combined, combined[-2000:]
    assert code == 15, (code, rows, combined[-2000:])
    assert [r["check"] for r in rows] == ["ordering-malformed"], rows
    assert "matches no record file" in rows[0]["message"], rows[0]


def test_the_strict_reader_walks_a_deep_value_without_recursing():
    """The non-finite walk and the depth bound are both iterative with their own
    stack.

    ``json.loads`` cannot build a value this deep, so the value is assembled by
    hand -- which is exactly the shape a reader would have to survive if the
    decoder were ever to hand one over. A recursive walk answers the question by
    dying, and a reader that dies on the shape of a document reports nothing
    about it.
    """
    module = importlib.import_module("census_json")
    for depth in (DEEP,):
        deep: list = []
        cursor = deep
        for _ in range(depth):
            child: list = []
            cursor.append(child)
            cursor = child
        cursor.append("x")
        assert module.holds_non_finite(deep) is False, depth
        cursor[-1] = float("inf")
        assert module.holds_non_finite(deep) is True, depth


def test_the_census_lists_the_ledger_through_the_one_shared_helper():
    """The listing is one function, the run takes it once, and nothing uses ``glob``.

    ``census_ledger.listing_helper`` is the one rule for "which files are a
    ledger record", it is called from the probe alone, and the two passes that
    want the answer -- the record pass of ``census.py`` and the ordering readers
    -- are handed the probe's names. A second listing rule would be a second
    answer, and only the ``iterdir`` half would raise on a readdir fault: the
    ``glob`` half would report the unreadable directory as an empty one, which is
    the dishonesty the probe exists to prevent. This pins the wiring at the
    source, so a change back to ``glob``, or back to a second readdir, fails here
    and not in a silent row.

    The session register keeps its own ``glob`` deliberately: it lists ``*.md``
    registers, not ledger records, and is another class's business.

    The readers module reaches the helper through a module attribute and not a
    call it closes over, so the ordering group's own read stays a seam a test can
    fault on its own -- see ``_listing_faults``. Reaching it through a private
    name, or binding it at the call, would make every ordering-fault test here
    fault the ledger group's read as well."""
    census_src = _harness_source(CENSUS)
    assert "if probe.state != \"ok\" or probe.names is None:" in census_src, \
        "the record pass no longer reads its names off the probe"
    assert "sorted(probe.names)" in census_src, \
        "the record pass no longer reads the probe's names"
    assert "_ledger.listing_helper(ledger)" not in census_src, \
        "the record pass lists the ledger again: the run must take one readdir"
    assert "findings, ledger_probe.names)" in census_src, \
        "the ordering group is no longer handed the run's one listing"
    readers_src = (SCRIPTS / "census_ordering_readers.py").read_text(encoding="utf-8")
    assert "names = listing_helper(ledger)" in readers_src, \
        "the ordering group no longer lists the ledger through the shared helper"
    assert "from .census_ledger import listing_helper" in readers_src, \
        "the ordering group no longer reaches the shared helper by a patchable name"
    assert "if names is None:" in readers_src, \
        "the readers no longer fall back to their own listing, so the group's " \
        "read has no seam to fault on"
    assert "ledger.glob" not in readers_src, \
        "the ordering group lists the ledger with glob, which swallows the fault"
    assert "ledger.glob" not in census_src, \
        "the census lists the ledger with glob, which swallows the fault"
    ledger_src = (SCRIPTS / "census_ledger.py").read_text(encoding="utf-8")
    assert "ledger.iterdir()" in ledger_src, \
        "the shared helper must list with iterdir, the call that raises"


def test_the_ordering_group_reads_the_probe_names_and_not_the_directory(
    tmp_path, monkeypatch
):
    """The wiring above, seen from the run: the group's own listing is never called.

    ``_ordering_record_read_faults`` faults the readers' ``listing_helper`` and
    leaves the census's names alone, so it reaches nothing while the run hands
    the group the probe's names. It is a control, not a duplicate of
    ``_listing_faults``: that one asks the group to read for itself and proves
    the fault is reported, this one proves a run that could have a second readdir
    does not have one. An ordering row naming a fault here is a group that walked
    the directory behind the probe's back.
    """
    repo = _repo(tmp_path, "group-reads-probe-names")
    _seed(repo, _entry(3, BASELINE_ID))
    with _ordering_record_read_faults(repo / "noni" / "decisions"):
        code, rows, out, err = _run_in_process(repo)
    assert code == 0, (code, rows, out, err)
    assert rows == [], rows


def test_the_readers_take_the_strict_reader_as_an_argument(tmp_path):
    """The strict reader is bound at the call, not imported by bare name.

    ``census.py`` loads every split-out module by path under a name of its own
    precisely so that nothing on ``sys.path`` can be trusted as the census's own
    code -- but a ``from census_json import ...`` inside the readers module put
    the choice of that reader back in ``sys.path``'s hands. Passing it in like
    ``file_kind``, ``bounded`` and ``parse_iso`` already are is what closes it. The
    message clipper arrives the same way, so the readers module carries no second
    definition of what a bounded row means.
    """
    source = (SCRIPTS / "census_ordering_readers.py").read_text(encoding="utf-8")
    assert "from census_json import" not in source
    assert "import census_json" not in source
    readers = importlib.import_module("noni.census_ordering_readers")

    def refusing(raw: bytes) -> object:
        raise ValueError("a reader from elsewhere on sys.path was used")

    order = tmp_path / "order.json"
    order.write_text('{"schema": "noni.order/1", "entries": []}', encoding="utf-8")
    entries, problem = readers.load_order(
        order, lambda path, kind="file": ("regular", None), lambda text: text,
        lambda text: None, lambda value: [], refusing, lambda text: text)
    assert entries is None, entries
    assert problem == "the order file is not valid JSON", problem

    ledger = tmp_path / "decisions"
    ledger.mkdir()
    (ledger / "2026-01-01-a.json").write_text("{}", encoding="utf-8")
    records, readable, unreadable, listed, fault = readers.ledger_records(
        ledger, lambda path, kind="file": ("regular", None), refusing)
    assert (records, readable, unreadable, listed, fault) == ({}, True, set(), True, None)


def test_the_census_hands_its_own_strict_reader_to_the_group():
    """The argument is wired, not merely available: the census passes the reader
    it loaded beside itself, so a lookalike cannot answer for the artifact.

    The clipper is pinned in the same breath: the rows this group composes are
    clipped by the census's own rule, not by a bound the group invents for itself.
    """
    source = _harness_source(CENSUS)
    assert "load_json_strict=_census_json.load_json_strict" in source, \
        "the ordering group is not handed the census's own strict reader"
    assert "clipped=_clipped" in source, \
        "the ordering group is not handed the census's own message clipper"


def test_the_state_row_bounds_the_whole_composed_message(tmp_path):
    """The row's text is built out of keys and state words read from a file
    somebody else wrote.

    ``bounded`` was applied to the path inside the sentence and to each
    individual complaint, but never to the finished message, so four complaints
    of any length each composed a row far past the 300-character bound every
    other row of the report keeps. The bound now wraps the whole message, so
    neither a 5000-character key nor a 5000-character state word reaches a
    report verbatim.
    """
    for index, body in enumerate((json.dumps({"x" * 5000: "open"}),
                                  json.dumps({"7": "y" * 5000}),
                                  json.dumps({"7": "open", "y" * 5000: "nope",
                                              "z" * 5000: "perhaps",
                                              "w" * 5000: "maybe"}))):
        repo = _repo(tmp_path, f"long-state-{index}")
        _seed(repo, _entry(7, None))
        path = repo / "issue-state.json"
        path.write_text(body, encoding="utf-8")
        code, rows, out, err = _run(repo, "--issue-state", str(path))
        assert code == 15, (index, code, rows, err[-500:])
        assert rows[0]["subject"] == "issue-state", rows[0]
        assert len(rows[0]["message"]) <= 300, \
            f"{index}: {len(rows[0]['message'])} chars: {rows[0]['message'][:80]}"
        assert "x" * 5000 not in rows[0]["message"], rows[0]
        assert "y" * 5000 not in rows[0]["message"], rows[0]
