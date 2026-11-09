"""The promote that rewrites two artifacts: the item, and the order entry that cited it.

Sub-issue 2 of the items epic, the half that can leave the two artifacts disagreeing:
when an order cites the item being promoted, the entry comes back as an ``issue`` entry
and *both* files land in *one* commit. A promote that wrote the item and left the order
citing a promoted idea is the disagreement this sub-issue exists to remove, so the tests
below are about the commit as much as the rewrite -- which paths one commit holds, that
HEAD moves once, what the lost-update guard does when a rival writes the order under the
run, and what ``--no-commit`` leaves behind.

The artifact and the writer's ``--item`` checks are the other file, and the scaffolding
both need (the seeded citing order, the canonical bytes, the rival writer that moves HEAD
without touching the file) is ``tests/item_entry_support.py``.
"""

from __future__ import annotations

import json

from item_entry_support import (
    BASELINE_ID,
    FRESH,
    NOW,
    STAMP,
    UNCITED,
    _candidate_with_citing_order,
    _committed_paths,
    _head_commit_count,
    _order_text,
    _repo,
    _rival_commit,
    _run_order,
    _seed_item,
    _seed_position,
)
from item_writer_fixtures import item_path, run_item
from order_fixtures import _census_ordering, _read

# --- the promote that rewrites both artifacts -----------------------------------


def test_promote_rewrites_the_citing_entry_in_the_same_commit(tmp_path):
    """The contract of the sub-issue: the entry and the item move together.

    One commit, both paths, and no moment at which a reader of the committed tree sees
    an order citing an item the store calls promoted -- which is what the two paths in
    one ``git commit --only`` are for.
    """
    tree = _candidate_with_citing_order(tmp_path)
    proc = run_item(tree, "promote", "idea-0001", "--issue", "42", "--now", NOW)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    body = json.loads(_order_text(tree))
    assert body["entries"] == [{"issue": 42, "decision": BASELINE_ID,
                                "confirmed": FRESH}], body
    assert json.loads(item_path(tree, "idea-0001").read_text())["status"] == "promoted"
    assert sorted(_committed_paths(tree)) == sorted([
        "noni/direction/order.json", "noni/items/idea-0001.json"]), _committed_paths(tree)


def test_promote_of_a_cited_item_moves_head_once(tmp_path):
    """Two paths, one commit: a two-commit promote would leave a half state in history.

    The order of the two writes is also pinned by this: an item written and committed
    before its order is a promote that can be interrupted into the exact disagreement the
    census classes were written to report.
    """
    tree = _candidate_with_citing_order(tmp_path)
    before = _head_commit_count(tree)
    assert run_item(tree, "promote", "idea-0001", "--issue", "42",
                    "--now", NOW).returncode == 0
    assert _head_commit_count(tree) == before + 1


def test_promote_leaves_a_v2_order_v2_while_an_item_entry_remains(tmp_path):
    """The version follows the entries, so a second idea still ordered keeps ``/2``."""
    tree = _candidate_with_citing_order(tmp_path, also=("idea-0002",))
    assert run_item(tree, "promote", "idea-0001", "--issue", "42",
                    "--now", NOW).returncode == 0
    body = json.loads(_order_text(tree))
    assert body["schema"] == "noni.order/2", body
    assert [entry.get("item") for entry in body["entries"]] == [None, "idea-0002"], body


def test_promote_of_the_last_item_entry_lands_the_order_on_v1(tmp_path):
    """When the rewritten list holds no item entry the artifact is a ``/1`` document."""
    tree = _candidate_with_citing_order(tmp_path)
    assert run_item(tree, "promote", "idea-0001", "--issue", "42",
                    "--now", NOW).returncode == 0
    assert json.loads(_order_text(tree))["schema"] == "noni.order/1"


def test_promote_writes_nothing_when_the_order_moved_under_it(tmp_path):
    """The lost-update guard covers the two-path write, not just the order's own writer.

    A rival commits an order between this run's read and its write: the promote refuses,
    and neither the item nor the order is left holding bytes the other does not agree
    with. The rival's artifact is a ``/2`` file that cites a *different* idea, which is
    what makes this a race rather than a different question: an order that cites nothing
    at all is a legitimate answer ("there is nothing to rewrite"), so a rival that merely
    emptied the queue would be answered with a promote rather than a refusal, and the
    entry this run read would be gone. Cited by another name, the queue still says
    "items are ordered", and the only honest reply is the guard's.
    """
    tree = _candidate_with_citing_order(tmp_path)
    rival = _rival_commit(tree)
    proc = run_item(tree, "promote", "idea-0001", "--issue", "42", "--now", NOW)
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "changed since it was read" in proc.stderr, proc.stderr
    assert json.loads(item_path(tree, "idea-0001").read_text())["status"] == "candidate"
    # The working file still holds the bytes this run read (HEAD moved, the file did
    # not, which is what made the guard answer at all), so a refused run leaving them
    # behind is the whole claim: nothing written, nothing staged, nothing committed.
    assert [entry.get("item") for entry in
            json.loads(_order_text(tree))["entries"]] == ["idea-0001"], \
        "a refused promote rewrote the queue"
    assert rival is not None


def test_promote_no_commit_leaves_both_files_uncommitted(tmp_path):
    """``--no-commit`` writes the same two paths and runs no git at all.

    The census reads the working tree, so the line has to name both paths: a caller that
    committed only the item would put the disagreement back.
    """
    tree = _candidate_with_citing_order(tmp_path)
    heads = _head_commit_count(tree)
    proc = run_item(tree, "promote", "idea-0001", "--issue", "42", "--now", STAMP,
                    "--no-commit")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _head_commit_count(tree) == heads
    assert "order.json" in proc.stdout and "idea-0001.json" in proc.stdout, proc.stdout
    assert json.loads(_order_text(tree))["entries"][0].get("issue") == 42


def test_promote_of_an_uncited_item_writes_only_the_item(tmp_path):
    """The ordinary promote is unchanged: an order that cites nothing is left alone.

    Pinned beside the rewriting cases so the two cannot be confused, and so a project
    that never ordered its ideas sees no new file and no version marker from a promote.
    """
    tree = _repo(tmp_path, "uncited")
    _seed_item(tree)
    _seed_position(tree, UNCITED, schema="noni.order/1", committed=True)
    order_before = _order_text(tree)
    proc = run_item(tree, "promote", "idea-0001", "--issue", "42", "--now", NOW)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _order_text(tree) == order_before, "the order was rewritten for nothing"
    assert json.loads(item_path(tree, "idea-0001").read_text())["status"] == "promoted"
    assert _committed_paths(tree) == ["noni/items/idea-0001.json"]


def test_promote_is_idempotent_on_a_fully_rewritten_pair(tmp_path):
    """A repeat of a finished promote reports unchanged and moves no HEAD.

    Both files are compared, not one: an item already promoted beside an order that
    already names its issue is a run with nothing left to do, and committing unchanged
    bytes would move HEAD for no content.
    """
    tree = _candidate_with_citing_order(tmp_path)
    assert run_item(tree, "promote", "idea-0001", "--issue", "42",
                    "--now", STAMP).returncode == 0
    heads = _head_commit_count(tree)
    proc = run_item(tree, "promote", "idea-0001", "--issue", "42", "--now", STAMP)
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "already promoted" in proc.stderr, proc.stderr
    assert _head_commit_count(tree) == heads, proc.stdout + proc.stderr
    # The bytes of the finished promote are the writer's own canonical output: the
    # rewrite named the issue, dropped the item key and restamped nothing.
    body = json.loads(_order_text(tree))
    assert body["entries"] == [{"issue": 42, "decision": BASELINE_ID,
                                "confirmed": FRESH}], body


def test_the_census_reads_the_rewritten_order_as_clean(tmp_path):
    """The writer's output is the arbiter's clean case, on both versions.

    The two sides of the split have to answer one document alike, or a promote that the
    writer calls success is a census failure the operator cannot repair by re-running
    anything.
    """
    tree = _candidate_with_citing_order(tmp_path)
    assert run_item(tree, "promote", "idea-0001", "--issue", "42",
                    "--now", NOW).returncode == 0
    code, rows, both = _census_ordering(tree)
    assert code == 0, f"{code} {rows} {both}"


def test_add_item_then_promote_is_the_whole_lifecycle(tmp_path):
    """An idea is filed, ordered, promoted, and the queue ends up naming the issue.

    The end-to-end path the sub-issue promises, in the order an operator would run it.
    """
    tree = _repo(tmp_path, "lifecycle")
    _seed_item(tree)
    assert _run_order(tree, "add", "--item", "idea-0001", "--decision", BASELINE_ID,
                      "--now", STAMP).returncode == 0
    assert _read(tree)["schema"] == "noni.order/2"
    assert run_item(tree, "promote", "idea-0001", "--issue", "42",
                    "--now", STAMP).returncode == 0
    assert _read(tree) == {"schema": "noni.order/1",
                           "entries": [{"issue": 42, "decision": BASELINE_ID,
                                        "confirmed": STAMP}]}
