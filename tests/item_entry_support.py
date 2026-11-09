"""The scaffolding the two ``noni.order/2`` suites share.

Sub-issue 2 of the items epic is tested in two files, one per contract that can break:
``test_order_writer_item_entries.py`` for the artifact and the writer's checks, and
``test_order_writer_promote_rewrite.py`` for the promote that rewrites two artifacts in
one commit. Both need the same five things -- an item in the store, an order at a given
version, the writer's own canonical bytes, the paths one commit touched, and a rival
writer that moves HEAD without touching the working file -- and a copy in each file
would be two fixtures to keep honest.

The rival helper is the one worth reading before changing: a rival that rewrote the
working file would be answered by the guard's *file* comparison, and a rival whose queue
cites nothing at all is a legitimate "there is nothing to rewrite" rather than a race.
What the two-phase promote needs to meet is a HEAD that moved while the file it read
did not, which only a clone-and-fetch rival produces.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

from _harness import _git
from item_writer_fixtures import BASELINE_ID, FRESH, NOW, commit, seed_item
from order_canonical import order_bytes
from order_fixtures import _order, _order_path, _repo

__all__ = [
    "BASELINE_ID", "CITING", "FRESH", "NOW", "SEED_STAMP", "STAMP",
    "UNCITED",
    "_candidate_with_citing_order", "_clone_commit", "_committed_paths",
    "_head_commit_count", "_order_canonical", "_order_text", "_repo",
    "_rival_commit", "_run_order", "_seed_item", "_seed_position",
]

STAMP = "2026-10-27T12:00:00Z"

# An entry of the shape ``noni.order/2`` owns: the idea's own id where a ``/1`` entry
# would carry an issue number, and the two fields every entry has always carried.
# The stamp every seeded entry carries, and the one every writer run in these files
# stamps with: they differ so a run's own bytes are never already on disk (a no-change
# run takes the writer's shortcut and returns before the freshness guard is reached).
SEED_STAMP = FRESH
CITING = {"item": "idea-0001", "decision": BASELINE_ID, "confirmed": SEED_STAMP}
UNCITED = {"issue": 7, "decision": BASELINE_ID, "confirmed": SEED_STAMP}


def _run_order(tree, *args):
    """``order.py`` against ``tree`` with exactly these arguments."""
    return _order(tree, *args)


def _seed_item(tree, item_id="idea-0001", status="candidate"):
    seed_item(tree, {"schema": "noni.item/1", "id": item_id, "title": "Cache the "
                     "census", "status": status, "created": FRESH})
    return item_id


def _order_text(tree) -> str:
    return _order_path(tree).read_text(encoding="utf-8")


def _committed_paths(tree) -> list[str]:
    """The paths the last commit holds, so a test can name what one commit wrote."""
    return _git(tree, "log", "-1", "--pretty=", "--name-only").stdout.split()


def _head_commit_count(tree) -> int:
    return len(_git(tree, "rev-list", "--all").stdout.split())


def _order_canonical(entries: list[dict[str, Any]], schema: str) -> str:
    """The artifact's canonical bytes for ``entries`` at the version ``schema``."""
    return order_bytes(entries, schema=schema)


def _seed_position(tree, entry: dict[str, Any], *, schema: str, committed: bool = True) -> None:
    """Append one entry to the artifact, in the artifact's own canonical bytes.

    An empty ``entry`` creates or restamps the file without adding anything, which is how
    a test asks for "an order holding nothing at version X".
    """
    path = _order_path(tree)
    existing = []
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))["entries"]
    entries = [*existing, dict(entry)] if entry else [*existing]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_order_canonical(entries, schema), encoding="utf-8")
    if committed:
        commit(tree, "direction: seed")


def _candidate_with_citing_order(tmp_path, *, also=()) -> Any:
    """A tree holding one candidate item, and an order whose first entry cites it.

    ``also`` files further ideas and appends an entry citing each, which is how the
    "a /2 file stays /2" case is built without a second test's worth of scaffolding.
    """
    tree = _repo(tmp_path, "citing")
    _seed_item(tree, "idea-0001")
    entries = [dict(CITING)]
    for extra in also:
        _seed_item(tree, extra)
        entries.append({"item": extra, "decision": BASELINE_ID,
                        "confirmed": SEED_STAMP})
    path = _order_path(tree)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_order_canonical(entries, "noni.order/2"), encoding="utf-8")
    commit(tree, "direction: seed the citing order")
    return tree


def _rival_commit(tree):
    """Commit a different order over this run's head, the way a second writer would.

    Returns the rival's committed text so the caller can say the refusal left *that*
    order in place rather than the bytes this run planned.

    The rival's artifact is a ``/2`` file that cites a *different* idea, which is what
    makes this a race rather than a different question: an order that cites nothing at
    all is a legitimate answer ("there is nothing to rewrite"), so a rival that merely
    emptied the queue would be answered with a promote rather than a refusal, and the
    entry this run read would be gone. Cited by another name, the queue still says
    "items are ordered", and the only honest reply is the guard's.
    """
    text = _order_canonical([{"issue": 99, "decision": BASELINE_ID,
                              "confirmed": FRESH},
                             {"item": "idea-0009", "decision": BASELINE_ID,
                              "confirmed": FRESH}], "noni.order/2")
    rival = _clone_commit(tree, text, "direction: rival")
    assert rival, "the fetch left HEAD where it was, so nothing moved under this run"
    return text


def _clone_commit(tree, text: str, message: str) -> str:
    """Commit ``text`` as another writer and bring the commit into ``tree``'s HEAD.

    Returns the fetched HEAD so the caller can assert the move really happened: a
    fixture that quietly failed to advance HEAD would turn the refusal it tests for into
    a success it mistakes for one.

    The rival's commit is brought in by fetch alone: HEAD moves, and nothing touches the
    working file, which is exactly the state a rival writer leaves. A checkout of the
    rival commit would move the file too, and the run would then be answering the file
    comparison rather than the HEAD comparison the promote's guard is about.
    """
    other = tree.parent / "rival"
    _git(tree, "clone", "-q", "--no-hardlinks", str(tree), str(other))
    _git(other, "config", "user.name", "Rival")
    _git(other, "config", "user.email", "rival@fixture.invalid")
    (other / "noni" / "direction" / "order.json").write_text(text, encoding="utf-8")
    commit(other, message)
    fetched = subprocess.run(["git", "-C", str(tree), "fetch", "-q", str(other),
                              "HEAD"], capture_output=True, text=True)
    assert fetched.returncode == 0, fetched.stderr
    moved = subprocess.run(["git", "-C", str(tree), "update-ref", "HEAD", "FETCH_HEAD"],
                           capture_output=True, text=True)
    assert moved.returncode == 0, moved.stderr
    head = subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert head == _git(other, "rev-parse", "HEAD").stdout.strip(), \
        "the fetch left HEAD where it was, so nothing moved under this run"
    return head
