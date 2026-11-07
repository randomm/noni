"""The path guard: every ``noni/`` component this writer may not read or write through.

The rule (docs/PRODUCT.md 7): every directory from the state root down to the artifact
is asked of ``lstat`` before the first read, write or mkdir, and a component that is a
symlink, a plain file, a socket or a device is refused. Absent is admitted, because the
first ``add`` creates ``noni/items/``.

The code is 2, the code docs/PRODUCT.md 7 gives ``item`` for a wrong path, and that is
the point of asking before reading: a run that only found out at the ``mkdir`` would
answer 3 and describe the tree as broken when the tree is merely obstructed, and the
operator would go looking for a fault there is no repair for.

``order.py`` and ``intent.py`` carry the same guard for the same reason (issue #104),
and the reason they needed it is the case this suite is really about: a linked
directory above the artifact answered "already there" to ``exists()``, the
``mkdir(parents=True)`` through the link was a no-op, and the file landed outside the
tree with exit 0. A leaf-only check cannot see that, so the guard walks every component
and these tests plant the link at each one.

The state-root question itself is only asked of the verbs that read or write state:
``add`` is admitted as the sanctioned creator of ``noni/items/``, and ``list`` creates
nothing and is admitted too (an absent store is an empty listing, which is the answer
the census gives for the same tree). ``drop`` and ``promote`` create nothing and are
refused a tree that holds no ``noni/``.
"""

from __future__ import annotations

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

CANDIDATE = {"schema": "noni.item/1", "id": "idea-0001", "title": "t",
             "status": "candidate", "created": FRESH}

# The verbs that create nothing, and so owe the state-root question.
READERS = ("drop", "promote")

# One argv per reader that reaches the guard: drop's citation is resolved after the
# item is read, and promote reads the item first, so both must have an item to find.
def _argv(verb: str) -> list[str]:
    if verb == "drop":
        return ["drop", "idea-0001", "--decision", BASELINE_ID, "--why", "x",
                "--now", NOW]
    return ["promote", "idea-0001", "--issue", "7", "--now", NOW]


def _plant_repo(tmp_path, subdir: str):
    """A tree with a ledger and one item, so a reader has something to reach for."""
    tree = repo(tmp_path, subdir)
    seed_record(tree)
    seed_item(tree, dict(CANDIDATE))
    return tree


def _plant_linked_dir(tree, outside, rel: str) -> None:
    """Make ``rel`` under ``--repo`` a symlink to a real outside directory."""
    target = outside / rel
    target.mkdir(parents=True, exist_ok=True)
    local = tree / rel
    local.parent.mkdir(parents=True, exist_ok=True)
    local.symlink_to(target)


def _write_decoy(outside, rel: str, name: str) -> tuple[object, str]:
    """Put the file the writer would have written at the same name outside.

    Returns the decoy's path and its original text, so the assertion "nothing was
    written outside" is a statement about a real file rather than about absence.
    """
    decoy = outside / rel / name
    decoy.parent.mkdir(parents=True, exist_ok=True)
    text = '{"schema": "decoy"}\n'
    decoy.write_text(text, encoding="utf-8")
    return decoy, text


# --------------------------------------------------------------------------
# The state root: a tree that holds no noni/
# --------------------------------------------------------------------------


def test_a_reader_refuses_a_tree_that_holds_no_noni_directory(tmp_path):
    """Not "no such item": the sentence must describe the ``--repo``, not the item.

    The pilot's failure was answering "no decision record ... is in the ledger" about a
    repository that holds no ledger at all -- true of the ledger, useless as an account
    of the wrong ``--repo``. The same trap for the store is "no item idea-0001 is
    filed", which sends the operator to the item when the argument is what is wrong.
    """
    for verb in READERS:
        tree = repo(tmp_path, f"no-noni-{verb}")
        proc = run_item(tree, *_argv(verb))
        assert proc.returncode == 2, f"{verb}: {proc.returncode} {proc.stderr}"
        assert "is not a noni state root" in proc.stderr, f"{verb}: {proc.stderr}"
        assert "no item" not in proc.stderr.lower(), f"{verb}: {proc.stderr}"
        assert not item_path(tree, "idea-0001").exists()


def test_add_creates_the_store_in_a_tree_with_no_noni_directory(tmp_path):
    """The sanctioned creator: the first ``add`` is how ``noni/items/`` comes into being."""
    tree = repo(tmp_path)
    proc = run_item(tree, "add", "idea-0001", "--title", "t", "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    assert item_path(tree, "idea-0001").is_file()


def test_list_answers_an_empty_store_for_a_tree_with_no_noni_directory(tmp_path):
    """The read that creates nothing is not refused for creating nothing.

    The census gives an absent store exit 0, so a tool that showed the operator the
    store had to be able to say "empty" about the same tree, or the two answers would
    contradict each other on one repository.
    """
    tree = repo(tmp_path)
    proc = run_item(tree, "list")
    assert proc.returncode == 0, proc.stderr
    assert "0 item" in proc.stdout, proc.stdout


# --------------------------------------------------------------------------
# A linked component above the artifact
# --------------------------------------------------------------------------


def test_a_linked_items_directory_is_refused_never_written_through(tmp_path):
    """The bug this guard exists for, at the store itself.

    ``exists()`` + ``mkdir(parents=True)`` through a link is a no-op and the artifact
    lands outside, with exit 0. The decoy sits at the very name the writer would have
    used, so the untouched-bytes assertion is about that file.
    """
    tree = repo(tmp_path)
    outside = tmp_path / "outside"
    _plant_linked_dir(tree, outside, "noni/items")
    decoy, text = _write_decoy(outside, "noni/items", "idea-0002.json")
    proc = run_item(tree, "add", "idea-0002", "--title", "t", "--now", NOW)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "symlink" in proc.stderr.lower(), proc.stderr
    assert "noni/items" in proc.stderr, proc.stderr
    assert (tree / "noni" / "items").is_symlink(), "the run unmade the planted link"
    assert decoy.read_text(encoding="utf-8") == text, "the run wrote outside the tree"


def test_a_link_where_the_store_parent_was_hides_the_directory_and_is_refused(tmp_path):
    """A link at ``noni`` is refused even though ``noni/items`` is real underneath it.

    A leaf-only question resolves the link and hears "directory" for the component
    below, then writes into the outside tree. This is the case the guard walks every
    component for, and the one ``exists()`` + ``mkdir`` could not see at all.
    """
    tree = repo(tmp_path)
    outside = tmp_path / "outside"
    (outside / "noni" / "items").mkdir(parents=True)
    (tree / "noni").symlink_to(outside / "noni")
    decoy, text = _write_decoy(outside, "noni/items", "idea-0002.json")
    proc = run_item(tree, "add", "idea-0002", "--title", "t", "--now", NOW)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "symlink" in proc.stderr.lower(), proc.stderr
    assert (tree / "noni").is_symlink(), "the run unmade the planted link"
    assert decoy.read_text(encoding="utf-8") == text


def test_a_linked_ledger_directory_is_refused(tmp_path):
    """``noni/decisions`` is guarded too: ``drop`` reads it, so its links are refused.

    The guard's list is every directory the verb reaches, not only the one it writes:
    reading a ledger through a link puts records from outside the state root into a
    decision about what this project dropped.
    """
    tree = repo(tmp_path)
    seed_item(tree, dict(CANDIDATE))
    outside = tmp_path / "outside"
    _plant_linked_dir(tree, outside, "noni/decisions")
    # The linked ledger holds a record the run would otherwise accept, so a pass would
    # be silent and the drop would be committed.
    (outside / "noni" / "decisions" / f"{BASELINE_ID}.json").write_text(
        '{"id": "decoy"}\n', encoding="utf-8")
    commit(tree, "ledger linked")
    proc = run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                    "--why", "out of scope", "--now", NOW)
    assert proc.returncode == 2, proc.stderr
    assert "symlink" in proc.stderr.lower(), proc.stderr


def test_a_dangling_link_at_the_item_path_is_refused_not_read_as_absent(tmp_path):
    """A link to nothing is a link, not an absence.

    ``ENOENT`` from ``stat`` on a dangling link looks like "no file here", and the
    reader that trusted it would file the item over what is somebody's placeholder. The
    guard asks ``lstat``, which sees the link itself.
    """
    tree = repo(tmp_path)
    seed_record(tree)
    item_path(tree, "idea-0001").parent.mkdir(parents=True, exist_ok=True)
    item_path(tree, "idea-0001").symlink_to(tree / "nowhere.json")
    commit(tree, "dangling")
    proc = run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                    "--why", "x", "--now", NOW)
    assert proc.returncode == 3, proc.stderr
    assert "no item" not in proc.stderr.lower(), proc.stderr
    assert item_path(tree, "idea-0001").is_symlink()


# --------------------------------------------------------------------------
# The order path, which promote reads
# --------------------------------------------------------------------------


def test_a_linked_order_file_is_refused_as_a_fault_not_answered_around(tmp_path):
    """Promote reads the order to decide its refusal, so an unreadable order is a fault.

    The two answers must not collapse: "no entry cites it" (promote) and "the order
    could not be read" (stop) are different, and a run that answered the first from a
    file it never opened would promote an item the order still names.
    """
    tree = _plant_repo(tmp_path, "linked-order")
    seed_order(tree, [{"issue": 7, "decision": BASELINE_ID, "confirmed": FRESH}])
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "order.json").write_text('{"schema": "decoy"}\n', encoding="utf-8")
    order = tree / "noni" / "direction" / "order.json"
    order.unlink()
    order.symlink_to(outside / "order.json")
    commit(tree, "order linked")
    proc = run_item(tree, "promote", "idea-0001", "--issue", "7", "--now", NOW)
    assert proc.returncode == 3, proc.stderr
    assert "order.json" in proc.stderr, proc.stderr
    assert (outside / "order.json").read_text(encoding="utf-8") == \
        '{"schema": "decoy"}\n'


def test_a_real_order_that_does_not_cite_the_item_promotes(tmp_path):
    """The guard's counterpart: an ordinary order is read, and answers the question.

    Without this case a guard that refused every order would keep every other test in
    this file green, because they all assert refusals.
    """
    tree = _plant_repo(tmp_path, "clean-order")
    seed_order(tree, [{"issue": 7, "decision": BASELINE_ID, "confirmed": FRESH}])
    assert run_item(tree, "promote", "idea-0001", "--issue", "7",
                    "--now", NOW).returncode == 0
