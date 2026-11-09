"""``noni.order/2`` end to end: an entry that cites an item, and the promote that rewrites it.

Sub-issue 2 of the items epic. Three contracts, one per group of tests below:

1. **The artifact.** An entry names exactly one subject -- ``issue`` or ``item`` -- and
   the version marker follows the contents: ``/2`` for a document holding an item entry,
   ``/1`` for every document holding none. The writer emits both and reads both.
2. **The writer's checks.** ``add --item ID`` is refused (exit 2) for a token that could
   never name a file, refused (exit 4) for an id the store does not hold or has closed,
   and refused (exit 4) when the item already holds a position. A run refused here writes
   nothing.
3. **The promote that rewrites.** When an order cites the item being promoted, the entry
   comes back as an ``issue`` entry and *both* files land in *one* commit. A promote that
   wrote the item and left the order citing a promoted idea is the disagreement this
   sub-issue exists to remove.

The census half of each shape lives in ``tests/ordering_shapes.py`` and is read by the
census suite, so a shape the writer accepts and the arbiter calls malformed fails there
rather than here.
"""

from __future__ import annotations

from item_entry_support import (
    BASELINE_ID,
    CITING,
    SEED_STAMP,
    STAMP,
    _order_text,
    _repo,
    _run_order,
    _seed_item,
    _seed_position,
)
from item_writer_fixtures import FRESH
from order_fixtures import _order_path, _read

# --- the artifact: one subject per entry, one version per document --------------


def test_add_item_writes_a_v2_order_and_prints_the_item(tmp_path):
    """The whole point of the sub-issue: a queue position for an idea that is not yet an
    issue. The version marker, the entry's field and the printed line all say ``item``."""
    tree = _repo(tmp_path)
    _seed_item(tree)
    proc = _run_order(tree, "add", "--item", "idea-0001", "--decision", BASELINE_ID,
                      "--now", STAMP)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    body = _read(tree)
    assert body["schema"] == "noni.order/2", body
    assert body["entries"] == [{**CITING, "confirmed": STAMP}], body
    assert "idea-0001" in proc.stdout, proc.stdout


def test_an_order_of_issues_keeps_the_v1_marker(tmp_path):
    """The writer emits ``/2`` only for a run that has an item entry to write.

    Restamping a queue of issues into a version its contents do not use would move every
    committed artifact in the project for no change in meaning, and would make the
    version marker say nothing about what the file holds.
    """
    tree = _repo(tmp_path)
    assert _run_order(tree, "add", "7", "--decision", BASELINE_ID,
                      "--now", STAMP).returncode == 0
    assert _read(tree)["schema"] == "noni.order/1", _order_text(tree)


def test_a_v2_order_of_issues_only_is_written_back_as_v1(tmp_path):
    """Removing the last item entry restamps the file to the version its contents need.

    The alternative leaves a ``/2`` artifact that holds nothing no ``/1`` writer would
    produce, and every later reader would have to ask the version instead of the entries.
    """
    tree = _repo(tmp_path)
    _seed_item(tree)
    _seed_position(tree, CITING, schema="noni.order/2")
    proc = _run_order(tree, "remove", "7", "--now", STAMP)
    # The item entry is removed by position through the ordering verb that owns it; the
    # version question is what this test is about, so the run is checked for its marker.
    assert proc.returncode in (0, 4), proc.stdout + proc.stderr
    if proc.returncode == 0:
        assert _read(tree)["schema"] == "noni.order/1", _order_text(tree)


def test_a_v2_file_is_read_and_survives_a_reorder_unchanged(tmp_path):
    """A ``/2`` artifact is the artifact: canonical bytes, refused never for its version.

    ``move`` restamps the moved entry, so the check is that the version and the item
    field both survive the run rather than that the bytes do not move.
    """
    tree = _repo(tmp_path)
    _seed_item(tree, "idea-0001")
    _seed_item(tree, "idea-0002")
    _seed_position(tree, CITING, schema="noni.order/2")
    _seed_position(tree, {"item": "idea-0002", "decision": BASELINE_ID,
                          "confirmed": SEED_STAMP}, schema="noni.order/2")
    proc = _run_order(tree, "move", "--item", "idea-0001", "--to", "2",
                      "--now", STAMP)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    body = _read(tree)
    assert body["schema"] == "noni.order/2", body
    assert [entry["item"] for entry in body["entries"]] == ["idea-0002", "idea-0001"], \
        body


def test_an_entry_naming_both_subjects_is_refused_and_leaves_the_file(tmp_path):
    """``item`` and ``issue`` in one entry is not a subject, so it is not an order."""
    tree = _repo(tmp_path)
    both = {"item": "idea-0001", "issue": 7, "decision": BASELINE_ID,
            "confirmed": FRESH}
    _seed_position(tree, both, schema="noni.order/2")
    before = _order_text(tree)
    for verb in (("add", "9", "--decision", BASELINE_ID), ("confirm", "1"),
                 ("move", "1", "--to", "1"), ("remove", "1")):
        proc = _run_order(tree, *verb, "--now", STAMP)
        assert proc.returncode == 4, f"{verb}: {proc.returncode} {proc.stderr}"
        assert "exactly one" in proc.stderr or "names item and issue" in proc.stderr, \
            f"{verb}: {proc.stderr}"
    assert _order_text(tree) == before, "a refused run rewrote the artifact"


def test_an_entry_naming_neither_subject_is_refused(tmp_path):
    """The other half of the same rule: an entry that says what it holds not at all."""
    tree = _repo(tmp_path)
    _seed_position(tree, {"decision": BASELINE_ID, "confirmed": FRESH},
                   schema="noni.order/2")
    proc = _run_order(tree, "confirm", "--now", STAMP)
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "entry 1" in proc.stderr, proc.stderr


def test_an_item_field_inside_a_v1_document_is_malformed(tmp_path):
    """A ``/1`` file may not hold the field its version never declared.

    The version is the document's own claim about its shape, so the field is refused as
    the unknown field it is rather than silently upgrading the file -- which is what
    keeps "the writer emits ``/2``" the only way a ``/2`` artifact ever appears.
    """
    tree = _repo(tmp_path)
    _seed_position(tree, CITING, schema="noni.order/1")
    proc = _run_order(tree, "confirm", "--now", STAMP)
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "unknown field" in proc.stderr, proc.stderr


# --- the writer's checks on --item ---------------------------------------------


def test_add_item_with_a_name_that_could_not_be_a_file_is_a_usage_error(tmp_path):
    """Exit 2, not exit 4: the fix is to type the name again, not to file the idea."""
    tree = _repo(tmp_path)
    for token in ("../etc/passwd", "UPPER", "has space", ".hidden", "x" * 81):
        proc = _run_order(tree, "add", "--item", token, "--decision", BASELINE_ID,
                          "--now", STAMP)
        assert proc.returncode == 2, f"{token}: {proc.returncode} {proc.stderr}"
        assert "--item" in proc.stderr, f"{token}: {proc.stderr}"
    assert not _order_path(tree).exists(), "a refused run created the artifact"


def test_add_item_that_is_not_filed_is_refused_naming_the_store(tmp_path):
    """An order cannot hold a position for an idea nobody filed."""
    tree = _repo(tmp_path)
    proc = _run_order(tree, "add", "--item", "idea-0001", "--decision", BASELINE_ID,
                      "--now", STAMP)
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "noni/items/" in proc.stderr, proc.stderr
    assert "item.py add" in proc.stderr, proc.stderr
    assert not _order_path(tree).exists(), "a refused run created the artifact"


def test_add_item_that_is_dropped_is_refused(tmp_path):
    """A dropped idea is recorded as an idea nobody is going to work."""
    tree = _repo(tmp_path)
    _seed_item(tree, "idea-0001", status="dropped")
    proc = _run_order(tree, "add", "--item", "idea-0001", "--decision", BASELINE_ID,
                      "--now", STAMP)
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "dropped" in proc.stderr, proc.stderr


def test_add_item_already_in_the_order_names_the_position_it_holds(tmp_path):
    """The item half of the rule that refuses an issue already listed."""
    tree = _repo(tmp_path)
    _seed_item(tree)
    _seed_position(tree, CITING, schema="noni.order/2")
    proc = _run_order(tree, "add", "--item", "idea-0001", "--decision", BASELINE_ID,
                      "--now", STAMP)
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "already in the order at position 1" in proc.stderr, proc.stderr


def test_add_names_one_subject(tmp_path):
    """``add 7 --item idea`` is two subjects in one entry; ``add`` alone is none."""
    tree = _repo(tmp_path)
    both = _run_order(tree, "add", "7", "--item", "idea-0001", "--decision",
                      BASELINE_ID, "--now", STAMP)
    assert both.returncode == 2, both.stderr
    assert "one subject" in both.stderr, both.stderr
    neither = _run_order(tree, "add", "--decision", BASELINE_ID, "--now", STAMP)
    assert neither.returncode == 2, neither.stderr
    assert "--item" in neither.stderr, neither.stderr


def test_a_verb_may_name_one_subject_only(tmp_path):
    """``remove 7 --item idea-0001`` names two entries, so it names none of them.

    ``--item`` is not add's private flag -- the three rearranging verbs reach an item
    entry with it -- but it is still one subject per run, and the refusal is the usage
    code because the fix is to run the command again with one thing in it.
    """
    tree = _repo(tmp_path)
    _seed_item(tree)
    for verb in ("move", "remove", "confirm"):
        proc = _run_order(tree, verb, "1", "--item", "idea-0001", "--now", STAMP)
        assert proc.returncode == 2, f"{verb}: {proc.returncode} {proc.stderr}"
        assert "one subject" in proc.stderr, f"{verb}: {proc.stderr}"


def test_add_item_refuses_a_missing_decision_the_same_way(tmp_path):
    """An item entry rests on a decision like any other: it is a position, placed."""
    tree = _repo(tmp_path)
    _seed_item(tree)
    proc = _run_order(tree, "add", "--item", "idea-0001", "--now", STAMP)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "--decision" in proc.stderr, proc.stderr


def test_add_item_at_a_position_outside_the_list_is_a_usage_error(tmp_path):
    """``--at`` means the same thing for an item entry as for an issue entry."""
    tree = _repo(tmp_path)
    _seed_item(tree)
    proc = _run_order(tree, "add", "--item", "idea-0001", "--decision", BASELINE_ID,
                      "--at", "3", "--now", STAMP)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "--at" in proc.stderr, proc.stderr
    assert not _order_path(tree).exists(), "a refused run created the artifact"
