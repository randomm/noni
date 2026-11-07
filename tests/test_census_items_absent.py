"""The item store is optional: a project that never filed an idea.

No item rows at all and no exit code of its own, and ``--strict`` does not invent a
finding where there is nothing to report. Contrast a store the caller *named* with
``--items`` and this run could not open: that is a finding, because a path the
operator pointed the census at and the run cannot read is not the same answer as a
path that is simply not there. The counterpart of
``tests/test_census_ordering_absent.py``, whose two cases these are.

Builders in ``tests/items_fixtures.py``.
"""

from __future__ import annotations

from items_fixtures import code, repo, run


def test_no_items_directory_adds_no_item_row(tmp_path):
    """The store is optional: a project that has never filed an idea censuses with
    no item rows at all, and no exit code of its own. Contrast the ledger, whose
    absence is the ledger-empty warn."""
    tree = repo(tmp_path)
    exit_code, rows, out, err = run(tree)
    assert exit_code == 0, (exit_code, out, err)
    assert rows == [], rows


def test_a_missing_store_is_not_reported_even_under_strict(tmp_path):
    """--strict promotes warnings, it does not invent findings: a run with nothing to
    report stays clean whatever the flag does to severities."""
    tree = repo(tmp_path)
    exit_code, rows, out, err = run(tree, "--strict")
    assert exit_code == 0, (exit_code, out, err)
    assert rows == [], rows


def test_an_empty_store_adds_no_item_row(tmp_path):
    """A store that exists and holds nothing is the state after the last item was
    cleaned out, and it reads the same as no store at all: nothing to check, nothing
    to report. The directory is committed empty by a file and then emptied, which is
    the only way git carries it."""
    tree = repo(tmp_path)
    (tree / "noni" / "items").mkdir(parents=True, exist_ok=True)
    exit_code, rows, out, err = run(tree)
    assert exit_code == 0, (exit_code, out, err)
    assert rows == [], rows


def test_an_empty_store_adds_no_item_row_under_strict(tmp_path):
    tree = repo(tmp_path)
    (tree / "noni" / "items").mkdir(parents=True, exist_ok=True)
    exit_code, rows, out, err = run(tree, "--strict")
    assert exit_code == 0, (exit_code, out, err)
    assert rows == [], rows


def test_an_absent_path_named_by_items_is_still_silence(tmp_path):
    """``--items`` moves the store; it does not make absence a finding.

    The ruling the flag carries is about blindness, not about presence: a path the
    caller named that this run could not *open* is reported, because the run holds an
    answer about a store it cannot see. A path the caller named that the filesystem
    says is not there is the ordinary state of a project with no store, and a flag
    must not turn it into a warning an operator cannot act on.
    """
    tree = repo(tmp_path)
    exit_code, rows, out, err = run(tree, "--items",
                                    str(tree / "noni" / "nowhere"))
    assert exit_code == 0, (exit_code, out, err)
    assert rows == [], rows
    assert "item-" not in out, out


def test_a_store_the_caller_named_and_this_run_cannot_open_is_a_row(tmp_path):
    """The other half of the ruling: present and unreadable is never silence.

    The two cases differ only in what the filesystem answers, so they are pinned
    together here: an absent named path is clean and a present named path whose open
    was refused is a row. A probe that answered the empty listing for both would pass
    the first test and fail this one.
    """
    tree = repo(tmp_path)
    store = tree / "noni" / "items"
    store.mkdir(parents=True)
    (store / "a.json").write_text("{}", encoding="utf-8")
    store.chmod(0o000)
    try:
        exit_code, rows, out, err = run(tree, "--items", str(store))
    finally:
        store.chmod(0o755)
    assert exit_code == 0, (exit_code, out, err)
    assert [row["check"] for row in rows] == ["item-unlistable"], rows
    assert rows[0]["severity"] == "warn", rows


def test_an_unreadable_store_earns_the_row_its_default_path_would_too(tmp_path):
    """The gate does not depend on the flag: a default store that exists and cannot
    be opened is owed its read whatever filter named no class of the group."""
    tree = repo(tmp_path)
    store = tree / "noni" / "items"
    store.mkdir(parents=True)
    (store / "a.json").write_text("{}", encoding="utf-8")
    store.chmod(0o000)
    try:
        assert code(tree, "--only", "item-stale") == 0
        _exit_code, rows, _out, _err = run(tree, "--only", "item-stale")
    finally:
        store.chmod(0o755)
    assert [row["check"] for row in rows] == ["item-unlistable"], rows
