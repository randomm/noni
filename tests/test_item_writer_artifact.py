"""What the artifact is made of, and what the writer will not touch.

The store's bytes are the contract the census arbitrates, so this suite checks them
from the writer's side: the canonical form, the shapes the writer refuses to overwrite,
and the states of the *path* that stop it reading at all.

The shape table is the shared one in ``tests/items_shapes.py``, which the census suite
drives too. The two rule sets are written twice on purpose (one reader in the writer,
one in the arbiter), which is exactly how they drift, so one list read twice is the
check: a shape the census reports and the writer would happily write over is a file
nobody notices has rotted.

Path states are the second half of the story. A refusal that reformats or truncates a
committed file is as destructive as a refusal that never happened, so every refusal
here asserts the bytes on disk afterwards, and a symlink is asserted to still be a
symlink: reading through a link puts a file outside the tree into the writer's
decisions, and writing onto one replaces somebody's link with an item file.
"""

from __future__ import annotations

import json
from pathlib import Path

from _harness import _git
from item_writer_fixtures import (
    BASELINE_ID,
    FRESH,
    NOW,
    commit,
    item_path,
    raw_item,
    read,
    repo,
    run_item,
    seed_item,
    seed_record,
)
from items_shapes import canonical, malformed_shapes, not_a_json_object_shapes

CLEAN = {"schema": "noni.item/1", "id": "idea-0001", "title": "Say hello first",
         "status": "candidate", "created": FRESH}


def _seed_canonical(tree) -> Path:
    """The committed artifact, in exactly the bytes the writer itself produces.

    For the cases that need a file already in the store in canonical form, as opposed
    to the byte tests, which plant their own bytes.
    """
    target = item_path(tree, "idea-0001")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical(CLEAN), encoding="utf-8")
    commit(tree, "items: canonical")
    return target


# --------------------------------------------------------------------------
# The bytes the writer produces
# --------------------------------------------------------------------------


def test_the_written_bytes_are_the_documented_canonical_form(tmp_path):
    """Key order, two-space indent, one trailing newline: the artifact is a byte contract.

    The census compares a file's bytes against what its reader would render, so an
    indent change here is a store reported malformed in its entirety, and a writer that
    sorted its keys would produce valid JSON the next run refuses.
    """
    tree = repo(tmp_path)
    assert run_item(tree, "add", "idea-0001", "--title", "Say hello first",
                    "--now", NOW).returncode == 0
    seed_record(tree)
    # The other two verbs' bytes too, so all four statuses of the schema are checked
    # against the renderer rather than only the one ``add`` produces.
    assert run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                    "--why", "out of scope", "--now", NOW).returncode == 0
    assert list(json.loads(item_path(tree, "idea-0001").read_bytes())) == [
        "schema", "id", "title", "status", "created", "decision", "why"]
    assert run_item(tree, "add", "idea-0002", "--title", "t",
                    "--now", NOW).returncode == 0
    assert run_item(tree, "promote", "idea-0002", "--issue", "7",
                    "--now", NOW).returncode == 0
    assert list(json.loads(item_path(tree, "idea-0002").read_bytes())) == [
        "schema", "id", "title", "status", "created", "issue"]
    raw = item_path(tree, "idea-0001").read_bytes()
    assert raw == canonical(read(tree, "idea-0001")).encode("utf-8"), \
        "the file is not in the form the writer renders"
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert b'\n  "id": "idea-0001",' in raw, "two-space indent"


def test_a_non_canonical_file_is_refused_rather_than_reformatted(tmp_path):
    """Valid, well-shaped, one-space indented: the operator committed it.

    Reformatting a committed file is not this run's to do, and the refusal is the only
    honest answer -- writing the canonical form over it would silently decide that
    somebody else's whitespace was the bug.
    """
    tree = repo(tmp_path)
    body = json.dumps(CLEAN, indent=1) + "\n"
    raw_item(tree, "idea-0001", body)
    proc = run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                    "--why", "out of scope", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "canonical" in proc.stderr.lower(), proc.stderr
    assert item_path(tree, "idea-0001").read_text(encoding="utf-8") == body


def test_a_key_order_that_is_not_the_documented_one_is_refused(tmp_path):
    """Sorted keys are still valid JSON and still the wrong bytes."""
    tree = repo(tmp_path)
    body = json.dumps(CLEAN, indent=2, sort_keys=True) + "\n"
    raw_item(tree, "idea-0001", body)
    proc = run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                    "--why", "out of scope", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert item_path(tree, "idea-0001").read_text(encoding="utf-8") == body


def test_an_unknown_field_is_refused(tmp_path):
    """A key the schema does not name is not this artifact, whoever wrote it.

    Driven through ``promote`` rather than ``drop``: ``drop`` resolves its
    ``--decision`` against the ledger before it opens the item, so a drop of a file
    holding an unknown key would answer the citation question and never reach the
    shape. The shape questions are asked by the verb that only reads the item.
    """
    tree = repo(tmp_path)
    # Written in the file's own key order rather than through the fixture's renderer,
    # which keeps only the documented fields (that is what makes it a renderer and not
    # a copy of the schema) and would drop the key this case exists to plant.
    text = json.dumps({**CLEAN, "priority": 1}, indent=2) + "\n"
    raw_item(tree, "idea-0001", text)
    proc = run_item(tree, "promote", "idea-0001", "--issue", "7", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "priority" in proc.stderr, proc.stderr
    assert item_path(tree, "idea-0001").read_text(encoding="utf-8") == text


# --------------------------------------------------------------------------
# The shared shape table: every rule, refused and left untouched
# --------------------------------------------------------------------------


def test_every_shape_the_writer_refuses_is_left_byte_identical(tmp_path):
    """The whole table, not a sample, driven through the writer.

    Read from the same list ``tests/test_census_items_group.py`` drives through the
    census, so a rule one side holds and the other does not fails here. The second
    assertion of each case is the one that matters most: a refusal that rewrote the
    file would turn a malformed artifact into a lost one.
    """
    for index, (name, body, _needle) in enumerate(malformed_shapes()):
        tree = repo(tmp_path, f"shape-{index}")
        # The id on disk is always one the command line can name: an id the schema
        # refuses is planted under a valid name, so this suite drives the *file's*
        # shape past the argv id check (which has its own suite), and every case reaches
        # the reader that has to refuse it.
        item_id = "idea-0001"
        raw_item(tree, item_id, canonical(body))
        seed_record(tree)
        proc = run_item(tree, "drop", item_id, "--decision", BASELINE_ID,
                        "--why", "out of scope", "--now", NOW)
        assert proc.returncode == 4, f"{name}: exit {proc.returncode} {proc.stderr}"
        assert item_path(tree, item_id).read_text(encoding="utf-8") == canonical(body),\
            f"{name}: the refused file was rewritten"


def test_a_body_that_is_not_a_json_object_is_refused(tmp_path):
    """Non-JSON, an array, a scalar: none of them is an item, and none is rewritten."""
    for name, text in not_a_json_object_shapes():
        tree = repo(tmp_path, name.replace(" ", "-"))
        raw_item(tree, "idea-0001", text)
        proc = run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                        "--why", "out of scope", "--now", NOW)
        assert proc.returncode == 4, f"{name}: exit {proc.returncode} {proc.stderr}"
        assert item_path(tree, "idea-0001").read_text(encoding="utf-8") == text,\
            f"{name}: the refused file was rewritten"


def test_an_id_that_is_not_the_file_s_own_name_is_refused(tmp_path):
    """The path is the name; a file whose contents name another item is two claims.

    The census reports it as ``item-malformed`` and the writer will not touch it,
    because a drop of ``alpha`` that followed the contents would have rewritten
    ``beta`` and left ``alpha`` filed as nothing.
    """
    tree = repo(tmp_path)
    raw_item(tree, "alpha", canonical({**CLEAN, "id": "beta"}))
    proc = run_item(tree, "drop", "alpha", "--decision", BASELINE_ID,
                    "--why", "out of scope", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert item_path(tree, "alpha").is_file()


# --------------------------------------------------------------------------
# The path itself: states that stop the read, not the item
# --------------------------------------------------------------------------


def test_the_item_path_being_a_directory_is_an_environment_fault(tmp_path):
    tree = repo(tmp_path)
    item_path(tree, "idea-0001").mkdir(parents=True)
    proc = run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                    "--why", "out of scope", "--now", NOW)
    assert proc.returncode == 3, proc.stderr
    assert "regular file" in proc.stderr.lower(), proc.stderr


def test_a_symlink_at_the_item_path_is_refused_never_followed(tmp_path):
    """Outside the tree, and still a link afterwards.

    The decoy sits at the very name the writer would have used, so "nothing was
    written outside" is a statement about a real file rather than about absence.
    """
    tree = repo(tmp_path)
    (tree / "elsewhere.json").write_text(canonical(CLEAN), encoding="utf-8")
    item_path(tree, "idea-0001").parent.mkdir(parents=True, exist_ok=True)
    item_path(tree, "idea-0001").symlink_to(tree / "elsewhere.json")
    commit(tree, "items: link")
    proc = run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                    "--why", "out of scope", "--now", NOW)
    assert proc.returncode == 3, proc.stderr
    assert "symlink" in proc.stderr.lower(), proc.stderr
    assert item_path(tree, "idea-0001").is_symlink(), "the writer replaced a link"
    assert (tree / "elsewhere.json").read_text(encoding="utf-8") == canonical(CLEAN)


def test_an_unreadable_item_file_is_an_environment_fault(tmp_path):
    tree = repo(tmp_path)
    seed_item(tree, dict(CLEAN))
    item_path(tree, "idea-0001").chmod(0)
    try:
        proc = run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                        "--why", "out of scope", "--now", NOW)
    finally:
        item_path(tree, "idea-0001").chmod(0o644)
    if proc.returncode != 3:  # pragma: no cover - root can read a 000 file
        import pytest
        pytest.skip("the reading user can read a 000-mode file")
    assert "could not be read" in proc.stderr.lower(), proc.stderr


def test_a_store_that_is_a_plain_file_is_refused_by_the_path_guard(tmp_path):
    """``noni/items/`` itself obstructed: no verb reads through it or writes through it.

    The guard asks every component under ``--repo`` of ``lstat`` before the first read,
    so an items directory that is a plain file is refused on the writer's own wrong-path
    code (2, the code docs/PRODUCT.md 7 gives ``item`` for a wrong path) rather than the
    3 a later read would answer: the run never touches the tree, which is the whole
    point of asking before reading.
    """
    tree = repo(tmp_path)
    (tree / "noni").mkdir()
    (tree / "noni" / "items").write_text("obstructed\n", encoding="utf-8")
    commit(tree, "items: obstructed store")
    for argv in (["drop", "idea-0001", "--decision", BASELINE_ID, "--why", "x"],
                 ["promote", "idea-0001", "--issue", "7"]):
        proc = run_item(tree, *argv, "--now", NOW)
        assert proc.returncode == 2, f"{argv[0]}: {proc.returncode} {proc.stderr}"
    assert (tree / "noni" / "items").read_text(encoding="utf-8") == "obstructed\n"


def test_a_link_inside_the_store_directory_hides_the_directory_and_is_refused(tmp_path):
    """``noni/items`` a link to an outside directory: the writer must not write there.

    The guard walks every component under ``--repo`` of ``lstat`` before the first
    read, so the run refuses on its own wrong-path code (2) rather than answering "the
    item is not filed" from a listing of somebody else's directory.
    """
    tree = repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "idea-0001.json").write_text(canonical(CLEAN), encoding="utf-8")
    (tree / "noni").mkdir()
    (tree / "noni" / "items").symlink_to(outside)
    commit(tree, "items: linked store")
    proc = run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                    "--why", "out of scope", "--now", NOW)
    assert proc.returncode == 2, proc.stderr
    assert "symlink" in proc.stderr.lower(), proc.stderr
    assert (tree / "noni" / "items").is_symlink(), "the run unmade the planted link"
    assert (outside / "idea-0001.json").read_text(encoding="utf-8") == canonical(CLEAN)


def test_a_write_leaves_no_stray_files_and_no_staging_behind(tmp_path):
    """After a successful verb the tree is clean and the index is not half-filled.

    A writer that staged the file and failed to commit (or committed and left the
    index dirty) leaves the next run of any tool in this tree reading a state no commit
    holds, which is the state the census is not built to answer.
    """
    tree = repo(tmp_path)
    assert run_item(tree, "add", "idea-0001", "--title", "t", "--now", NOW).returncode == 0
    assert _git(tree, "status", "--porcelain").stdout.strip() == "", \
        _git(tree, "status", "--porcelain").stdout
