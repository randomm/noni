"""The item store's census group: every class, and the silence each class owes.

An absent store adds nothing (``tests/test_census_items_absent.py``); this module
asks what the group reports once the store holds something. Builders in
``tests/items_fixtures.py``; the malformed-shape table is shared with the writer's
suite through ``tests/items_shapes.py``.

Three rules run through the file and are asserted repeatedly, because each is a way
a read-only arbiter can lie:

- **A defect outranks the run's own blindness.** An item that is malformed and
  unreadable is reported as malformed: what the census says must not be its own
  limitation dressed up as a finding.
- **Blindness never reads as an empty store, and never as clean.** A store that
  cannot be listed, a file that cannot be read, an order the group needed and could
  not open: each earns its row, each row is a warn that ``--strict`` promotes, and a
  run that could not read part of the store does not certify the rest.
- **A class the artifact cannot answer stays silent.** ``item-dropped-in-order``
  reads an ``item`` field that only ``noni.order/2`` entries carry; against the
  ``noni.order/1`` artifact this version writes it reports nothing, which is the
  honest answer and not a pass.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from _harness import REPO, _git, subprocess_env
from items_fixtures import (
    BASELINE_ID,
    HEIR_ID,
    item_body,
    repo,
    run,
)
from items_shapes import FRESH, OLD, malformed_shapes, not_a_json_object_shapes

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"

STORE = "noni/items"


def _commit(tree: Path, message: str) -> None:
    """Commit whatever the builders just placed.

    A separate step from the write because some fixtures mutate the file after
    placing it: a builder that committed on the spot would record the bytes before
    the fixture had made them the shape under test.
    """
    _git(tree, "add", "-A")
    if _git(tree, "status", "--porcelain").stdout.strip():
        _git(tree, "commit", "-q", "-m", message)


def _item(tree: Path, **fields) -> Path:
    """One well-formed item in the store, named by the ``id`` its own body carries.

    The path follows the document and not the other way round, which is the shape the
    store's key rule makes canonical: a fixture that wants the two to disagree (the
    id-is-not-the-filename defect) passes ``item_id=`` and gets a file named
    ``idea-0001.json`` whose body declares ``idea-0002``.
    """
    declared = fields.get("item_id", "idea-0001")
    target = tree / STORE / f"{declared}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(item_body(**fields), indent=2) + "\n",
                      encoding="utf-8")
    return target


def _raw(tree: Path, name: str, text: str) -> Path:
    """Exact text at a store path, bypassing every builder."""
    target = tree / STORE / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def _record(tree: Path, record_id: str, status: str = "decided",
            supersedes: str | None = None) -> Path:
    """One ledger record as the census reads it: a JSON document under noni/decisions."""
    target = tree / "noni" / "decisions" / f"{record_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "id": record_id, "date": "2026-10-01T00:00:00Z",
        "asked_by": "developer",
        "questions": [{"id": "q1", "text": "File it?", "options": ["a", "b"],
                       "answer": "a"}],
        "by": "Replay", "scope": "item store", "status": status,
        "supersedes": supersedes,
    }, indent=2) + "\n", encoding="utf-8")
    return target


def _order(tree: Path, entries: list[dict], schema: str = "noni.order/1") -> Path:
    """The order artifact the items group reads, written by hand.

    Hand-written because ``noni.order/1`` has no ``item`` field and ``order.py`` would
    refuse one: the ``/2`` shape is exercised here so the class that reads it is not
    invented when the second schema version lands.
    """
    target = tree / "noni" / "direction" / "order.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"schema": schema, "entries": entries},
                                 indent=2) + "\n", encoding="utf-8")
    return target


def _run(tree: Path, *extra: str):
    """Commit what the fixtures placed, then run the census over the items group.

    The commit is part of the launch and not of the builders: the census reads the
    tree as git holds it, so a fixture that planted a shape and never committed it
    would be asking what the census says about a file nobody wrote yet.
    """
    _commit(tree, "items: fixture")
    return run(tree, *extra)


def _findings(tree: Path, *extra: str, commit: bool = True) -> list[dict]:
    """The findings of a run over the items group.

    ``commit`` is False for the fixture that mutates a committed file after the fact
    (an artifact whose mode was taken away, a body rewritten behind git's back): those
    tests have already committed what they mean to commit and a second ``git add``
    would fail on the very unreadability the test is asserting.
    """
    if commit:
        _commit(tree, "items: fixture")
    return run(tree, *extra)[1]


def _one(tree: Path, check: str, *extra: str) -> dict:
    rows = [row for row in _findings(tree, *extra) if row["check"] == check]
    assert len(rows) == 1, f"expected exactly one {check} row, got {rows}"
    return rows[0]


# --------------------------------------------------------------------------
# item-malformed: the file is there and is not the artifact
# --------------------------------------------------------------------------


def test_every_shape_the_writer_refuses_is_reported(tmp_path):
    """One row per rule of the schema, with the store's path in its artifact.

    Driven from the table in ``items_shapes`` that the writer's suite reads too, so a
    rule one side holds and the other does not fails here.
    """
    for index, (name, body, needle) in enumerate(malformed_shapes()):
        tree = repo(tmp_path, f"malformed-{index}")
        item_id = body.get("id") or "idea-0001"
        target = tree / STORE / f"{item_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        _commit(tree, f"items: {item_id}")
        exit_code, rows, out, err = _run(tree, "--only", "item-malformed")
        item_rows = [row for row in rows if row["check"] == "item-malformed"]
        assert item_rows, f"{name}: not reported: {out}{err}"
        assert needle.lower() in item_rows[0]["message"].lower(), (
            f"{name}: the row does not name the defect: {item_rows[0]['message']}")
        assert item_rows[0]["artifact"].endswith(f"noni/items/{item_id}.json"), (
            f"{name}: the row does not name the file: {item_rows[0]}")
        assert item_rows[0]["code"] == 52, f"{name}: wrong code: {item_rows[0]}"


def test_a_body_that_is_not_an_object_is_malformed(tmp_path):
    """An array, a string, a number, a null or nothing at all is not an item."""
    for index, (name, text) in enumerate(not_a_json_object_shapes()):
        tree = repo(tmp_path, f"notobj-{index}")
        _raw(tree, "idea-0001.json", text)
        rows = _findings(tree, "--only", "item-malformed")
        assert [row["check"] for row in rows] == ["item-malformed"], (
            f"{name}: {rows}")


def test_a_file_whose_name_is_not_the_item_it_declares_is_malformed(tmp_path):
    """The stem is the store's key and the ``id`` field restates it; two names is a defect."""
    tree = repo(tmp_path, "id-mismatch")
    _item(tree, item_id="idea-0002")
    # The file on disk is idea-0002.json and says idea-0002; move it under the other
    # name so the two disagree, which is the defect this fixture exists to plant.
    (tree / STORE / "idea-0001.json").write_bytes(
        (tree / STORE / "idea-0002.json").read_bytes())
    (tree / STORE / "idea-0002.json").unlink()
    row = _one(tree, "item-malformed", "--only", "item-malformed")
    assert "id" in row["message"].lower(), row["message"]
    assert row["artifact"].endswith("noni/items/idea-0001.json"), row


def test_a_malformed_item_does_not_silence_the_rest_of_the_store(tmp_path):
    """One broken file cannot make the group hold its tongue about the others."""
    tree = repo(tmp_path, "one-broken-one-fine")
    _item(tree, item_id="idea-0002")
    (tree / STORE / "idea-0001.json").write_bytes(
        (tree / STORE / "idea-0002.json").read_bytes())
    _item(tree, item_id="idea-0003", status="promoted")
    exit_code, rows, _out, _err = _run(
        tree, "--only", "item-malformed", "--only", "item-promoted-without-issue")
    assert {row["check"] for row in rows} == {"item-malformed",
                                              "item-promoted-without-issue"}, rows


def test_a_symlink_in_the_store_is_reported_never_read_through(tmp_path):
    """The census never follows a link, and says what it found rather than nothing."""
    tree = repo(tmp_path, "store-symlink")
    target = _item(tree)
    link = tree / STORE / "idea-0002.json"
    link.symlink_to(Path(target.name))
    _commit(tree, "items: link")
    rows = [row for row in _findings(tree, "--only", "item-malformed")
            if row["subject"] == "idea-0002"]
    assert len(rows) == 1 and rows[0]["check"] == "item-malformed", rows
    assert "symlink" in rows[0]["message"].lower(), rows[0]["message"]


def test_a_directory_in_the_store_is_reported(tmp_path):
    tree = repo(tmp_path, "store-directory-entry")
    (tree / STORE / "not-an-item.json").mkdir(parents=True)
    _commit(tree, "items: dir")
    rows = [row for row in _findings(tree, "--only", "item-malformed")]
    assert len(rows) == 1 and rows[0]["code"] == 52, rows


def test_unreadable_bytes_are_reported_and_survive_a_filter(tmp_path):
    """Bytes that are not UTF-8 are a defect of the store, and a whole-artifact one.

    ``whole_artifact`` is what keeps the row visible to a run whose ``--only`` named
    no class of the group: a store that cannot be read must never read as the clean
    verdict of a store that holds nothing.
    """
    tree = repo(tmp_path, "store-bad-bytes")
    _raw(tree, "idea-0001.json", "\ufffd not utf-8 at all")
    exit_code, rows, out, err = _run(tree, "--only", "item-stale")
    assert [row["check"] for row in rows] == ["item-malformed"], rows
    assert exit_code == 52, (exit_code, out, err)


# --------------------------------------------------------------------------
# item-reference-unresolved: the kill list's citations
# --------------------------------------------------------------------------


def test_a_dropped_item_citing_no_record_is_unresolved(tmp_path):
    tree = repo(tmp_path, "dangling-decision")
    _item(tree, status="dropped", decision="2026-01-01-ghost",
          why="out of scope")
    row = _one(tree, "item-reference-unresolved",
               "--only", "item-reference-unresolved")
    assert row["code"] == 55
    assert row["severity"] == "fail"
    assert "2026-01-01-ghost" in row["message"], row["message"]


def test_a_dropped_item_citing_a_superseded_record_names_the_heir(tmp_path):
    """The row names the successor when the chain has one, so the fix is actionable."""
    tree = repo(tmp_path, "superseded-decision")
    _record(tree, "2026-10-01-old", status="superseded")
    _record(tree, HEIR_ID, status="decided", supersedes="2026-10-01-old")
    _item(tree, status="dropped", decision="2026-10-01-old",
          why="superseded by a later call")
    row = _one(tree, "item-reference-unresolved",
               "--only", "item-reference-unresolved")
    assert "2026-10-01-old" in row["message"], row["message"]
    assert HEIR_ID in row["message"], f"no successor named: {row['message']}"


def test_a_dropped_item_citing_a_live_record_is_silent(tmp_path):
    tree = repo(tmp_path, "live-decision")
    _record(tree, BASELINE_ID)
    _item(tree, status="dropped", decision=BASELINE_ID, why="out of scope")
    assert _findings(tree, "--only", "item-reference-unresolved") == []


def test_a_candidate_carrying_no_decision_owes_no_citation(tmp_path):
    tree = repo(tmp_path, "no-citation")
    _item(tree)
    assert _findings(tree, "--only", "item-reference-unresolved") == []


def test_a_cited_record_this_run_cannot_read_is_a_warn(tmp_path):
    """The run's own blindness is never a verdict on the project.

    The record's file exists and is a symlink, so the group cannot answer whether the
    decision stands. That is a warn, promoted by ``--strict``, and the item is not
    also reported as citing nothing.
    """
    tree = repo(tmp_path, "unreadable-record")
    real = _record(tree, BASELINE_ID)
    link = tree / "noni" / "decisions" / "2026-10-02-link.json"
    link.symlink_to(Path(real.name))
    _commit(tree, "decisions: link")
    _item(tree, status="dropped", decision="2026-10-02-link", why="out of scope")
    rows = _findings(tree, "--only", "item-reference-unresolved")
    assert [row["check"] for row in rows] == ["item-reference-unresolved"], rows
    assert rows[0]["severity"] == "warn", rows[0]
    assert "cannot-tell" in rows[0]["message"].lower(), rows[0]["message"]
    assert _run(tree, "--only", "item-reference-unresolved")[0] == 0, \
        "a lone warn must not move the exit code"
    assert _run(tree, "--only", "item-reference-unresolved", "--strict")[0] == 55, \
        "--strict must promote the blindness row"


# --------------------------------------------------------------------------
# item-promoted-without-issue
# --------------------------------------------------------------------------


def test_promoted_without_an_issue_is_reported(tmp_path):
    tree = repo(tmp_path, "promoted-no-issue")
    _item(tree, status="promoted")
    row = _one(tree, "item-promoted-without-issue",
               "--only", "item-promoted-without-issue")
    assert row["code"] == 54
    assert "issue" in row["message"].lower(), row["message"]


def test_a_candidate_that_names_an_issue_is_malformed_not_promoted_to_nothing(tmp_path):
    """One defect, one class.

    The schema already refuses a status that carries an issue it does not owe, so the
    file is reported ``item-malformed`` and ``item-promoted-without-issue`` stays
    silent: two classes claiming one file under two codes is how a store starts
    reporting the same defect twice.
    """
    tree = repo(tmp_path, "candidate-issue")
    _item(tree, status="candidate", issue=7)
    rows = _findings(tree, "--only", "item-malformed",
                     "--only", "item-promoted-without-issue")
    assert [row["check"] for row in rows] == ["item-malformed"], rows


def test_a_dropped_item_that_names_an_issue_is_malformed_not_promoted_to_nothing(tmp_path):
    tree = repo(tmp_path, "dropped-issue")
    _item(tree, status="dropped", issue=7, decision=BASELINE_ID,
          why="out of scope")
    rows = _findings(tree, "--only", "item-malformed",
                     "--only", "item-promoted-without-issue")
    assert [row["check"] for row in rows] == ["item-malformed"], rows


def test_a_promoted_item_whose_issue_the_order_does_not_hold_is_reported(tmp_path):
    tree = repo(tmp_path, "promoted-not-ordered")
    _item(tree, status="promoted", issue=7)
    _order(tree, [{"issue": 9, "decision": BASELINE_ID, "confirmed": FRESH}])
    _commit(tree, "items and order")
    row = _one(tree, "item-promoted-without-issue",
               "--only", "item-promoted-without-issue")
    assert "7" in row["message"], row["message"]


def test_a_promoted_item_whose_issue_the_order_holds_is_silent(tmp_path):
    tree = repo(tmp_path, "promoted-ordered")
    _item(tree, status="promoted", issue=7)
    _order(tree, [{"issue": 7, "decision": BASELINE_ID, "confirmed": FRESH}])
    _commit(tree, "items and order")
    assert _findings(tree, "--only", "item-promoted-without-issue") == []


def test_an_unreadable_order_does_not_make_every_promoted_item_a_finding(tmp_path):
    """The inversion the blindness rule exists to prevent.

    An order this run could not open is not "an order that holds no such issue": the
    item is reported by nothing here, and the order's own group reports the file. The
    order is made unreadable by its mode rather than its bytes, because a file that is
    there and simply does not parse is a file this run *can* open, and "the order
    holds no such issue" is then the true report about it -- the ordering group's own
    malformed class says the file is broken, and this group may still say the item
    names an issue nothing holds.
    """
    tree = repo(tmp_path, "order-unreadable")
    _item(tree, status="promoted", issue=7)
    order = _order(tree, [{"issue": 7, "decision": BASELINE_ID,
                           "confirmed": FRESH}])
    _commit(tree, "items and order")
    # The mode is taken after the commit: git's own add cannot read a file it has no
    # permission to open, and the state under test is a committed artifact this run
    # cannot open, not a working tree git cannot stage.
    order.chmod(0o000)
    try:
        assert _findings(tree, "--only", "item-promoted-without-issue",
                         commit=False) == []
    finally:
        order.chmod(0o644)


# --------------------------------------------------------------------------
# item-dropped-in-order: declared, documented, and silent on a /1 order
# --------------------------------------------------------------------------


def test_the_class_is_declared_with_its_own_code_and_severity():
    from noni import census_report

    assert "item-dropped-in-order" in census_report.CHECKS
    assert census_report.CHECKS["item-dropped-in-order"][0] == 53
    assert census_report.CHECKS["item-dropped-in-order"][1] == "fail"


def test_a_noni_order_1_entry_cites_no_item_so_the_class_is_silent(tmp_path):
    """Every entry of ``noni.order/1`` names an issue and a decision and nothing else.

    The class reports nothing on this artifact, which is the honest answer about a
    file that cites no item and not a pass: sub-issue 2 gives entries an ``item``
    field and fills the class in.
    """
    tree = repo(tmp_path, "dropped-in-order-silent")
    _item(tree, status="dropped", decision=BASELINE_ID, why="out of scope")
    _order(tree, [{"issue": 7, "decision": BASELINE_ID, "confirmed": FRESH}])
    _commit(tree, "items and order")
    assert _findings(tree, "--only", "item-dropped-in-order") == []


def test_an_order_entry_that_cites_a_dropped_item_is_reported(tmp_path):
    """The shape ``noni.order/2`` will produce, exercised ahead of the schema bump.

    Written by hand because ``order.py`` refuses the field on a ``/1`` document: this
    is the census's reader tested against the artifact the next version carries, so
    the class is not a declaration with no behaviour behind it.
    """
    tree = repo(tmp_path, "dropped-in-order")
    _item(tree, status="dropped", decision=BASELINE_ID, why="out of scope")
    _order(tree, [{"issue": 7, "decision": BASELINE_ID, "confirmed": FRESH,
                   "item": "idea-0001"}], schema="noni.order/2")
    _commit(tree, "items and order")
    row = _one(tree, "item-dropped-in-order", "--only", "item-dropped-in-order")
    assert row["code"] == 53
    assert row["severity"] == "fail", row
    assert "idea-0001" in row["message"], row["message"]


def test_an_order_entry_citing_a_live_item_is_silent(tmp_path):
    tree = repo(tmp_path, "cited-live-item")
    _item(tree)
    _order(tree, [{"issue": 7, "decision": BASELINE_ID, "confirmed": FRESH,
                   "item": "idea-0001"}], schema="noni.order/2")
    _commit(tree, "items and order")
    assert _findings(tree, "--only", "item-dropped-in-order") == []


# --------------------------------------------------------------------------
# item-stale
# --------------------------------------------------------------------------


def test_a_candidate_past_the_threshold_is_stale(tmp_path):
    tree = repo(tmp_path, "stale-candidate")
    _item(tree, created=OLD)
    row = _one(tree, "item-stale", "--only", "item-stale")
    assert row["code"] == 56
    assert row["severity"] == "warn", "staleness is an observation, not a defect"
    assert _run(tree, "--only", "item-stale")[0] == 0, "a lone warn moves no code"


def test_a_candidate_inside_the_threshold_is_silent(tmp_path):
    tree = repo(tmp_path, "fresh-candidate")
    _item(tree, created=FRESH)
    assert _findings(tree, "--only", "item-stale") == []


def test_only_candidates_go_stale(tmp_path):
    """A promoted or dropped record is finished, so its age says nothing."""
    for status, extra in (("promoted", {"issue": 7}),
                          ("dropped", {"decision": BASELINE_ID,
                                       "why": "out of scope"})):
        tree = repo(tmp_path, f"stale-{status}")
        _record(tree, BASELINE_ID)
        _item(tree, status=status, created=OLD, **extra)
        assert _findings(tree, "--only", "item-stale") == [], f"{status}"


def test_a_given_threshold_applies_to_the_group(tmp_path):
    tree = repo(tmp_path, "stale-threshold")
    _item(tree, created="2026-10-20T00:00:00Z")
    assert _findings(tree, "--only", "item-stale") == []
    assert len(_findings(tree, "--only", "item-stale",
                         "--stale-after", "3d")) == 1


def test_a_malformed_created_never_goes_stale(tmp_path):
    """No timestamp is no age: the schema reports it and staleness says nothing."""
    tree = repo(tmp_path, "stale-malformed-created")
    _item(tree, created="yesterday")
    assert _findings(tree, "--only", "item-stale") == []


# --------------------------------------------------------------------------
# item-unlistable: the group's one blindness class
# --------------------------------------------------------------------------


def test_a_store_that_cannot_be_listed_is_reported_never_read_as_empty(tmp_path):
    tree = repo(tmp_path, "unlistable")
    _item(tree)
    _commit(tree, "items")
    store = tree / STORE
    store.chmod(0o000)
    try:
        rows = _findings(tree, "--only", "item-unlistable")
        assert [row["check"] for row in rows] == ["item-unlistable"], rows
        assert rows[0]["severity"] == "warn", rows[0]
        assert run(tree, "--only", "item-unlistable")[0] == 0, \
            "a lone warn moves no code"
        strict = run(tree, "--only", "item-unlistable", "--strict")
        assert strict[1][0]["severity"] == "fail", strict[1]
        assert strict[0] == 57, strict[0]
    finally:
        store.chmod(0o755)


def test_a_store_path_that_is_a_file_is_a_warning_never_a_silent_empty_store(tmp_path):
    """A named store path that is not a directory is blindness, not usage.

    The census does not refuse it the way a writer refuses a ``--repo`` that is not a
    directory: the census reads, so it reports what it could not read. The row is the
    group's one blindness class and ``--strict`` promotes it; the silence this test
    rules out is the one that would let a file where a store should be read as a
    project that filed no idea.
    """
    tree = repo(tmp_path, "store-is-a-file")
    (tree / "noni").mkdir(exist_ok=True)
    (tree / "noni" / "items").write_text("not a directory\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CENSUS), "--repo", str(tree), "--items",
         str(tree / "noni" / "items")],
        capture_output=True, text=True, env=subprocess_env(), timeout=120)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}{proc.stdout}"
    assert "item-unlistable" in proc.stdout, proc.stdout
    assert "noni/items" in proc.stdout, proc.stdout
    # --strict promotes the row, and the code the run exits with is the lowest class
    # code that fired: the throwaway tree has no deny-list either, so hygiene (50)
    # fires beside it and carries the code. The strict reader's own code is asserted
    # through the filter, which is where this class's number is pinned.
    strict = subprocess.run(
        [sys.executable, str(CENSUS), "--repo", str(tree), "--items",
         str(tree / "noni" / "items"), "--strict"],
        capture_output=True, text=True, env=subprocess_env(), timeout=120)
    assert "item-unlistable  FAIL" in strict.stdout, strict.stdout
    filtered = subprocess.run(
        [sys.executable, str(CENSUS), "--repo", str(tree), "--items",
         str(tree / "noni" / "items"), "--strict", "--only", "item-unlistable"],
        capture_output=True, text=True, env=subprocess_env(), timeout=120)
    assert filtered.returncode == 57, f"{filtered.returncode}: {filtered.stdout}"


# --------------------------------------------------------------------------
# the group's place in the exit code and the filters
# --------------------------------------------------------------------------


def test_the_group_reports_only_under_its_own_classes(tmp_path):
    """A run whose filter named no class of the group sees no item row at all.

    Run twice, because the two output branches are different renderers of one report
    and a row that reaches one need not reach the other: ``--json`` emits one line per
    finding and the human branch prints its own lines, and a filter that leaked in only
    one mode would be invisible to a test that read the other. The non-``--json`` half
    is the shape of the run the operator actually types, and it must not print a row of
    a class they never asked for.
    """
    tree = repo(tmp_path, "group-gated")
    _item(tree, status="promoted")
    _commit(tree, "items: fixture")
    for extra in (["--json"], []):
        proc = subprocess.run([sys.executable, str(CENSUS), "--repo", str(tree),
                               "--only", "session-stalled", *extra],
                              capture_output=True, text=True,
                              env=subprocess_env(), timeout=120)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "item-" not in proc.stdout, (extra, proc.stdout)
    # And the same store, filtered to its own class, does report: the filter is what
    # hides the row here, not a group that never ran.
    shown = subprocess.run([sys.executable, str(CENSUS), "--repo", str(tree),
                            "--only", "item-promoted-without-issue"],
                           capture_output=True, text=True,
                           env=subprocess_env(), timeout=120)
    assert shown.returncode == 54, (shown.returncode, shown.stdout)


def test_a_finding_outranks_a_blindness_row_by_the_lowest_code(tmp_path):
    """Two rows at once, and the defect carries the exit code.

    One item promoted to nothing (a fail row) and one file whose bytes are broken
    (a malformed row): the lower of the two codes wins, which is why the item band
    sits in one contiguous run and the findings are numbered below the blindnesses.
    """
    tree = repo(tmp_path, "finding-beats-blindness")
    _item(tree, status="promoted")
    _raw(tree, "idea-0002.json", "{broken\n")
    exit_code, rows, _out, _err = _run(
        tree, "--only", "item-malformed", "--only", "item-promoted-without-issue")
    assert {row["check"] for row in rows} == {"item-malformed",
                                              "item-promoted-without-issue"}, rows
    assert exit_code == 52, exit_code


def test_the_human_branch_says_the_same_words_as_the_json_branch(tmp_path):
    """The row that carries the code also carries its class name and its file.

    Both branches sort findings the same way and render the same fields, so an
    operator reading stdout can act without a ``--json`` consumer.
    """
    tree = repo(tmp_path, "human-mode")
    _item(tree, status="promoted")
    _record(tree, BASELINE_ID)
    from items_fixtures import human

    exit_code, out, err = human(tree, "--only", "item-promoted-without-issue")
    assert exit_code == 54, (exit_code, out, err)
    assert "item-promoted-without-issue" in out, out
    assert "idea-0001" in out, out
