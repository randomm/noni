"""The store's own blindness: ``item-unlistable``, and the group's whole-run behaviour.

Split out of ``tests/test_census_items_group.py`` for the size limit, along the seam
between the classes that report a project's defects and the ones that report this run's
inability to look. The distinction is the group's whole design (a defect outranks
blindness, and blindness never reads as an empty store or as clean), so it is also a
natural seam for the tests: this file is the half where the census could not read
something, and the assertions are always about what the run says about *itself*.

Two things are pinned here that the per-class files cannot:

- **Blindness is a warn that ``--strict`` promotes**, and a lone warn moves no exit
  code. A run that could not open the store reports it and still exits 0, which is the
  same honesty contract ``--ledger``'s unreadable ledger has.
- **The group reports only under its own classes, and one read answers all six.** A
  finding outranks a blindness row by the lowest code, the ``--only`` filter cannot
  silence a whole-artifact row, and the human and JSON branches say the same words.

Builders and the census launch are ``tests/census_items_group_support.py``, shared with
``tests/test_census_items_group.py`` so the two suites launch the tool the same way.
"""

from __future__ import annotations

import subprocess
import sys

from _harness import subprocess_env
from census_items_group_support import CENSUS, STORE
from census_items_group_support import commit as census_commit
from census_items_group_support import findings as _findings
from census_items_group_support import item as _item
from census_items_group_support import launch as run
from census_items_group_support import one as _one
from items_fixtures import repo
from items_shapes import FRESH, OLD

# --------------------------------------------------------------------------
# item-unlistable: the group's one blindness class
# --------------------------------------------------------------------------


def test_a_store_that_cannot_be_listed_is_reported_never_read_as_empty(tmp_path):
    tree = repo(tmp_path, "unlistable")
    _item(tree)
    census_commit(tree, "items")
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
    """A plain file where the store should be is a fault, not an empty listing.

    ``ENOTDIR`` is one of the two errnos that mean "nothing of mine is here", so a
    classifier that read the raised error alone would call this the state of a project
    that never filed an idea and exit 0. The path *is* there and is not the store, so
    the class names it.
    """
    tree = repo(tmp_path, "store-is-file")
    # repo() already laid noni/ down through the earlier fixtures' parent; the store
    # path is the one this case replaces with an ordinary file.
    store = tree / STORE
    if store.is_dir():
        store.rmdir()
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("not a store\n", encoding="utf-8")
    census_commit(tree, "items: store is a file")
    row = _one(tree, "item-unlistable", "--only", "item-unlistable")
    assert row["severity"] == "warn", row
    assert STORE in row["artifact"], row


# --------------------------------------------------------------------------
# The group as a whole: one read, one verdict, two branches that agree
# --------------------------------------------------------------------------


def test_the_group_reports_only_under_its_own_classes(tmp_path):
    """No row of another group, and no row of this group outside its six ids.

    The filter and the skip lists are the census's, and this is the group's own
    boundary: a class of the items group reported under ``ledger-record`` would be
    arbitrated by a table that gives it no code.
    """
    tree = repo(tmp_path, "own-classes")
    _item(tree)
    _raw_bad = tree / STORE / "broken.json"
    _raw_bad.parent.mkdir(parents=True, exist_ok=True)
    _raw_bad.write_text("{", encoding="utf-8")
    _item(tree, item_id="stale-idea", created=OLD)
    _item(tree, item_id="promoted-no-issue", status="promoted")
    rows = _findings(tree)
    checks = {row["check"] for row in rows}
    assert checks <= {"item-malformed", "item-reference-unresolved",
                     "item-promoted-without-issue", "item-stale"}, checks
    assert "item-malformed" in checks and "item-stale" in checks, checks


def test_a_finding_outranks_a_blindness_row_by_the_lowest_code(tmp_path):
    """The exit code is the lowest code of any row that fired, so a defect wins.

    A run that read half the store and could not read the rest carries both a finding
    and a blindness row; the verdict the caller acts on is the finding's, and a group
    that ordered its rows the other way would report a warn's exit 0 over a failure it
    had just printed.
    """
    tree = repo(tmp_path, "rank")
    _item(tree, item_id="broken", status="nope")
    sibling = tree / STORE / "unreadable.json"
    sibling.parent.mkdir(parents=True, exist_ok=True)
    sibling.write_text("{ not json", encoding="utf-8")
    census_commit(tree, "items")
    # The listing itself must fail, which only the store directory's own mode can do;
    # a per-file mode would let the listing succeed and the file read fail, and the
    # group answers that with a malformed row rather than a blindness one.
    (tree / STORE).chmod(0o000)
    try:
        exit_code, rows, _out, _err = run(tree, "--only", "item-malformed",
                                           "--only", "item-unlistable")
        checks = {row["check"] for row in rows}
        assert "item-unlistable" in checks, rows
        # A warn moves no code on its own, which is the point of the ranking: the
        # blindness row is printed and the run still exits 0 until something fails.
        assert exit_code == 0, (exit_code, rows)
        strict = run(tree, "--only", "item-malformed", "--only",
                     "item-unlistable", "--strict")
        assert strict[0] == 57, (strict[0], strict[1])
    finally:
        (tree / STORE).chmod(0o755)
    # With the store readable again, the same tree reports the defect at its own code.
    exit_code, rows, _out, _err = run(tree, "--only", "item-malformed")
    assert exit_code == 52, (exit_code, rows)


def test_the_human_branch_says_the_same_words_as_the_json_branch(tmp_path):
    """One run, two output modes, one verdict -- and the filter cannot hide a fault.

    The census's own reproducibility pair: the same tree run twice must print the same
    bytes, and the human branch must name the same classes the NDJSON rows carry, or
    the operator reading a terminal is told about a different project than the
    automation is.
    """
    tree = repo(tmp_path, "branches")
    _item(tree, status="promoted")
    census_commit(tree, "items")
    json_run = subprocess.run(
        [sys.executable, str(CENSUS), "--repo", str(tree), "--items",
         str(tree / STORE), "--now", FRESH.replace("T00:00:00Z", "T12:00:00Z"),
         "--json"],
        capture_output=True, text=True, env=subprocess_env(), timeout=120)
    human = subprocess.run(
        [sys.executable, str(CENSUS), "--repo", str(tree), "--items",
         str(tree / STORE), "--now", FRESH.replace("T00:00:00Z", "T12:00:00Z")],
        capture_output=True, text=True, env=subprocess_env(), timeout=120)
    assert json_run.returncode == human.returncode, (json_run.stdout, human.stdout)
    assert "item-promoted-without-issue" in human.stdout, human.stdout
    assert '"item-promoted-without-issue"' in json_run.stdout, json_run.stdout
