"""A store the run cannot list stops every verb; it never reaches the interpreter.

The listing of ``noni/items/`` is one read shared by ``list``, the duplicate-title scan
of ``add`` and the scan that backs it for ``drop``/``promote``. When that listing faults
-- a directory nobody may read, a plain file where the store should be, a FIFO somebody
left there -- the read hands the writer a refusal and the writer returns its code. The
bug this suite holds shut: the refusal once returned the code in the *paths* slot, so a
caller that unpacked ``(paths, code)``, tested the code and then iterated ``paths`` died
with ``TypeError: 'int' object is not iterable``. A traceback is not an exit code: the
operator sees neither the code nor the two lines that say what to repair.

Every case is therefore asserted three ways: the code, the refusal lines, and that no
traceback reached the terminal. A FIFO is created with ``os.mkfifo`` and run under the
launcher's own timeout precisely because a blocking open of one is the shape that would
hang the run instead of refusing it. The chmod-000 case runs only where a 000 directory
really refuses this process (see :func:`_cases`), and restores the mode before any
assertion that has to open something under the store.

Two of the shapes are refused by the state-root guard before the listing is ever asked
(a plain file or a FIFO at the store path is a wrong path, not a faulty read), and the
guard's own code is what those cases assert on the verbs that run the guard.
"""

from __future__ import annotations

import json
import os
import stat

from item_writer_fixtures import FRESH, NOW, commit, repo, run_item

STORE = "noni/items"


def _unreadable_store(tree) -> None:
    """A store directory the run may not read (chmod 000)."""
    store = tree / STORE
    store.mkdir(parents=True)
    os.chmod(store, 0)


def _unreadable_store_with_item(tree) -> None:
    """A 000 store holding one committed candidate, readable at its own path.

    The shape the two verbs that read an item need: the item read has to succeed and
    the *listing* has to be the read that faults, or the run would be refused for the
    wrong reason and assert nothing about the listing.
    """
    store = tree / STORE
    store.mkdir(parents=True)
    (store / "idea-0001.json").write_text(json.dumps(
        {"schema": "noni.item/1", "id": "idea-0001", "title": "T",
         "status": "candidate", "created": FRESH}, indent=2) + "\n",
        encoding="utf-8")
    commit(tree, "items: seed")
    os.chmod(store, 0)


def _file_store(tree) -> None:
    """A plain file where the store directory should be."""
    (tree / "noni").mkdir(parents=True, exist_ok=True)
    (tree / STORE).write_text("not a store\n", encoding="utf-8")


def _fifo_store(tree) -> None:
    """A FIFO where the store directory should be.

    Created with ``os.mkfifo`` and never opened by the fixture: an ordinary open of a
    FIFO with no other end blocks forever, which is the hang the census's own
    ``O_NONBLOCK`` rule exists to avoid and the reason these runs are launched under a
    timeout.
    """
    (tree / "noni").mkdir(parents=True, exist_ok=True)
    os.mkfifo(tree / STORE)


def _unreadable_is_a_fault(probe: object) -> bool:
    """Whether a chmod-000 directory really refuses *this* process's read.

    A root run (or one holding ``CAP_DAC_OVERRIDE``) reads a 000 directory anyway, so
    the case would assert nothing about a refusal it never had to make. The question is
    answered by asking the filesystem rather than by reading ``geteuid``: what decides
    the case is whether the read is refused here.
    """
    probe.mkdir(parents=True)
    os.chmod(probe, 0)
    try:
        list(probe.iterdir())
    except PermissionError:
        return True
    finally:
        os.chmod(probe, stat.S_IRWXU)
    return False


def _cases(tmp_path, *, with_item: bool = False):
    """The three store shapes, minus the one this process cannot produce.

    ``with_item`` swaps in the store that already holds the item under test, for the
    verbs whose first read is the item itself.
    """
    unreadable = (_unreadable_store_with_item if with_item
                  else _unreadable_store)
    cases = [("file", _file_store), ("fifo", _fifo_store)]
    if _unreadable_is_a_fault(tmp_path / "probe-store"):
        cases.insert(0, ("unreadable", unreadable))
    return cases


def _restore(tree) -> None:
    """Put the mode back so an assertion can open what is under the store."""
    os.chmod(tree / STORE, stat.S_IRWXU)


def _assert_refused(proc, shape: str, verb: str, *, listed: bool) -> None:
    """Exit 3, two refusal lines, no traceback -- or the guard's exit 2.

    ``listed`` says whether this verb reaches the listing at all on this shape: the
    verbs that run the state-root guard refuse a non-directory store there, with the
    usage code docs/PRODUCT.md 7 gives ``item`` for a wrong path, and only the
    unreadable-directory case ever reaches the listing's own refusal on them.
    """
    joined = proc.stdout + proc.stderr
    assert "Traceback" not in joined, f"{shape} store, {verb}: {joined}"
    assert STORE in joined, f"{shape} store, {verb}: names no path: {joined}"
    if listed:
        assert proc.returncode == 3, (
            f"{shape} store, {verb}: expected exit 3, got "
            f"{proc.returncode}\n{joined}")
        assert "could not be listed" in joined, (
            f"{shape} store, {verb}: no refusal line: {joined}")
    else:
        assert proc.returncode == 2, (
            f"{shape} store, {verb}: expected the guard's exit 2, got "
            f"{proc.returncode}\n{joined}")


def test_list_refuses_an_unlistable_store(tmp_path):
    """``list`` over an unlistable store prints its refusal and exits 3.

    ``list`` runs no state-root guard (a tree with no store has nothing to list, which
    is the census's own answer), so all three shapes reach the listing here.
    """
    for shape, setup in _cases(tmp_path):
        tree = repo(tmp_path, f"list-{shape}")
        setup(tree)
        proc = run_item(tree, "list")
        _assert_refused(proc, shape, "list", listed=True)
        if shape == "unreadable":
            _restore(tree)


def test_a_store_that_cannot_be_listed_never_reads_as_an_empty_one(tmp_path):
    """The fault is the difference between exit 3 and a false "0 items".

    A plain file, a FIFO and an unreadable directory all share this assertion: each
    would otherwise answer "the store holds nothing", which is the verdict of a project
    that never filed an idea, given to a project whose store this run never opened.
    """
    for shape, setup in _cases(tmp_path):
        tree = repo(tmp_path, f"empty-{shape}")
        setup(tree)
        proc = run_item(tree, "list")
        joined = proc.stdout + proc.stderr
        assert "0 item" not in joined, f"{shape}: the fault read as an empty store"
        assert proc.returncode == 3, f"{shape}: {joined}"
        if shape == "unreadable":
            _restore(tree)


def test_add_refuses_an_unlistable_store(tmp_path):
    """``add`` asks the store for a duplicate title, so a faulted listing stops it.

    The scan is why the listing is taken at all on this verb: handed an empty listing
    it would answer "no dropped item carries that title", so a run that could not list
    has to stop rather than file a second record for an idea already killed. The
    unreadable-directory case asserts exit 3 and that nothing was written; the other
    two are refused by the state-root guard ahead of the listing.
    """
    for shape, setup in _cases(tmp_path):
        tree = repo(tmp_path, f"add-{shape}")
        setup(tree)
        proc = run_item(tree, "add", "idea-0001", "--title", "T", "--now", NOW)
        _assert_refused(proc, shape, "add", listed=shape == "unreadable")
        if shape == "unreadable":
            _restore(tree)
        assert not (tree / STORE / "idea-0001.json").exists(), (
            f"{shape}: the add wrote through a store it could not read")


def test_drop_refuses_an_unlistable_store(tmp_path):
    """``drop`` stops on a store it cannot list rather than closing an item."""
    for shape, setup in _cases(tmp_path, with_item=True):
        tree = repo(tmp_path, f"drop-{shape}")
        setup(tree)
        proc = run_item(tree, "drop", "idea-0001", "--decision",
                        "2026-10-01-baseline", "--why", "out of scope",
                        "--now", NOW)
        listed = shape == "unreadable"
        _assert_refused(proc, shape, "drop", listed=listed)
        if shape == "unreadable":
            _restore(tree)
            body = (tree / STORE / "idea-0001.json").read_text(encoding="utf-8")
            assert '"status": "dropped"' not in body, (
                f"{shape}: drop rewrote an item through a store it could not list")
            continue
        assert not (tree / STORE / "idea-0001.json").exists(), (
            f"{shape}: drop wrote through a store it could not read")


def test_promote_refuses_an_unlistable_store(tmp_path):
    """``promote`` reaches the same listing, so the same fault stops it too."""
    for shape, setup in _cases(tmp_path, with_item=True):
        tree = repo(tmp_path, f"promote-{shape}")
        setup(tree)
        proc = run_item(tree, "promote", "idea-0001", "--issue", "7", "--now", NOW)
        listed = shape == "unreadable"
        _assert_refused(proc, shape, "promote", listed=listed)
        if shape == "unreadable":
            _restore(tree)
            body = (tree / STORE / "idea-0001.json").read_text(encoding="utf-8")
            assert '"status": "promoted"' not in body, (
                f"{shape}: promote rewrote an item through a store it could not list")
            continue
        assert not (tree / STORE / "idea-0001.json").exists(), (
            f"{shape}: promote wrote through a store it could not read")
