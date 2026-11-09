"""What a promote write leaves behind when it raises before it wrote anything.

``item_promote.write`` makes the order directory before it touches either path, and that
mkdir can itself raise. The undo in the verb is handed what the write saw at the item
path through ``seen``; a fault that came first left no observation there at all, and the
one arm of the undo that removes a file must not treat "not observed" as "this run made
it" -- deleting a committed candidate while reporting an I/O refusal is worse than the
fault it is rolling back.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from item_writer_fixtures import (
    BASELINE_ID,
    FRESH,
    NOW,
    commit,
    item_path,
    repo,
    run_item,
    seed_item,
    seed_order,
    seed_record,
)

from noni import item_promote, itemschema

SRC = Path(__file__).resolve().parent.parent / "src"

CANDIDATE = {"schema": "noni.item/1", "id": "idea-0001", "title": "t",
             "status": "candidate", "created": FRESH}

ENTRIES = [{"issue": 9, "decision": BASELINE_ID, "confirmed": FRESH}]

# What a child promote prints when it took the two-path branch and the item write is the
# half that raised: the order writer's own wording of an OSError, which is the module the
# verb delegates ``written`` to.
FAILED_WRITE = "could not be written"


def _tree(tmp_path):
    """A repo with a ledger, a committed candidate and a committed ordinary order."""
    tree = repo(tmp_path)
    seed_record(tree)
    seed_item(tree, dict(CANDIDATE))
    seed_order(tree, [dict(e) for e in ENTRIES])
    return tree


def _obstruct_direction(tree: Path) -> None:
    """Replace the committed order directory with a plain file, then commit that.

    The obstruction is committed so HEAD, the index and the worktree agree: the run must
    fail on the directory it has to make, not on a dirty tree the freshness guard would
    refuse first.
    """
    direction = tree / "noni" / "direction"
    direction.rename(tree / "noni" / "direction.kept")
    direction.write_text("not a directory", encoding="utf-8")
    commit(tree, "chore: obstruct the order directory")


def _sitecustomize(tree: Path) -> dict:
    """An env whose child makes the order write raise after the item landed.

    ``noni/direction`` is a plain file, so the mkdir is the step that fails. Making the
    *item* write raise as well (it would, on its own, once the directory exists) is the
    fault this test needs: the run reaches the verb's undo having written nothing, which
    is the one state where the undo has no file of its own to remove.
    """
    custom = tree / "_fault"
    custom.mkdir()
    (custom / "sitecustomize.py").write_text(
        "import os\n"
        "from noni import order_gitwrite\n"
        "_real = order_gitwrite.write_atomic\n\n"
        "def _boom(path, data):\n"
        "    if path.name == 'idea-0001.json':\n"
        "        os.chmod(path.parent, 0o500)\n"
        "    return _real(path, data)\n\n"
        "order_gitwrite.write_atomic = _boom\n",
        encoding="utf-8")
    return {"PYTHONPATH": os.pathsep.join([str(custom), str(SRC)])}


def _pair(item_id: str = "idea-0001",
          before: bytes | None = None) -> item_promote.Pair:
    body = itemschema.entry(item_id, "t", "promoted", NOW, 42)
    return item_promote.plan(body, [dict(e) for e in ENTRIES],
                             itemschema.item_rel(item_id), before)


def test_the_undo_is_asked_only_of_a_write_that_observed_the_item_path():
    """The handler keeps its guard: an empty ``seen`` means nothing was written.

    ``seen["item_existed"]`` is read only once the handler knows ``seen`` is non-empty,
    so the one state where the undo has no right to remove a file cannot reach the arm
    that removes one. A ``.get`` with its default would answer False there, which is
    exactly the reading that deleted a committed candidate.
    """
    source = (SRC / "noni" / "item_promote_verb.py").read_text(encoding="utf-8")
    assert 'seen.get("item_existed")' not in source
    assert 'if not seen' in source


def test_the_write_records_the_item_path_before_making_the_directory(tmp_path):
    """``seen`` carries the fact even when the very first step is the one that raised."""
    tree = _tree(tmp_path)
    _obstruct_direction(tree)

    seen: dict = {}
    try:
        item_promote.write(tree, _pair(), seen)
    except OSError as exc:
        assert type(exc).__name__ == "FileExistsError", exc
        assert seen == {"item_existed": True}, seen
    else:
        raise AssertionError("the obstructed directory should have raised")


def test_a_promote_whose_writes_both_failed_leaves_the_record_it_found(tmp_path):
    """End to end: two failed writes, an unobserved item path, and a record still there.

    The whole verb runs, so the assertion is about the candidate on disk rather than
    about what :func:`noni.item_promote.rollback` was handed, and the report is the I/O
    refusal rather than a promote that did not happen.
    """
    tree = _tree(tmp_path)
    before = item_path(tree, "idea-0001").read_bytes()
    _obstruct_direction(tree)

    proc = run_item(tree, "promote", "idea-0001", "--issue", "42", "--now", NOW,
                    env=_sitecustomize(tree))
    assert proc.returncode == 3, proc.stderr
    assert FAILED_WRITE in proc.stderr, proc.stderr
    assert item_path(tree, "idea-0001").read_bytes() == before, (
        "the undo deleted a candidate this run never wrote")


def test_the_item_path_observed_as_absent_is_removed_by_the_undo(tmp_path):
    """The counterpart: when the run did make the file, the undo is entitled to remove it.

    The item path held nothing and the item write is what raises, so ``seen`` records
    False and the undo has a file of this run's making to take away -- and takes it,
    while the order goes back to the bytes this run read.
    """
    tree = repo(tmp_path)
    seed_record(tree)
    seed_order(tree, [dict(e) for e in ENTRIES])
    committed = (tree / "noni" / "direction" / "order.json").read_bytes()

    seen: dict = {}
    with pytest.raises(OSError):
        item_promote.write(tree, _pair(before=committed), seen, _raise_on_item)
    assert seen == {"item_existed": False}, seen
    assert item_promote.rollback(tree, _pair(before=committed),
                                 bool(seen["item_existed"])) is None
    assert not item_path(tree, "idea-0001").exists()
    assert (tree / "noni" / "direction" / "order.json").read_bytes() == committed


def _raise_on_item(path: Path, data: bytes) -> None:
    """The item half of the write, failing the way a read-only file system fails it."""
    raise OSError(30, "Read-only file system")
