"""Shared builders for the item writer's suites.

One throwaway git tree with a committed source file and no ``noni/``, the runners
that drive ``item.py`` against it, and the seeding helpers the verb tests need. The
counterpart of ``tests/order_fixtures.py``, written beside it rather than extended:
the order fixtures own the order artifact and its citation rules, and a writer's
fixtures stay the file that writer's suites read.

The shape table is deliberately not here. ``tests/items_shapes.py`` is read by the
census suite too, so it holds only the shapes and no way to put one on disk: a table
that needed the writer's own fixtures to build would make every row of it depend on
the thing it is checking.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from _harness import _git, git_pin_date

ITEMS_REL = "noni/items"

# A committed decided record every citation can name, and a second one for the
# supersede path. Built in the JSON form the ledger's reader takes, so the writer's
# citation check answers without the decide writer being in the test.
BASELINE_ID = "2026-10-01-baseline"
HEIR_ID = "2026-11-01-heir"

NOW = "2026-10-27T12:00:00Z"
FRESH = "2026-10-26T00:00:00Z"
OLD = "2026-01-01T00:00:00Z"

SOURCE = "def main() -> int:\n    return 0\n"


def repo(tmp_path: Path, subdir: str = "repo") -> Path:
    """A committed git tree holding source and no ``noni/`` at all.

    This is the tree every writer test starts from: a real work tree (the writers'
    git probes answer differently on one with no commit), with the state directory
    absent so a verb that needs it is refused for needing it.
    """
    tree = tmp_path / subdir
    tree.mkdir(parents=True, exist_ok=True)
    _git(tree, "init", "-q", "-b", "main")
    (tree / "src").mkdir()
    (tree / "src" / "main.py").write_text(SOURCE, encoding="utf-8")
    _git(tree, "add", ".")
    git_pin_date(tree, "2026-10-01T00:00:00Z", "commit", "-q", "-m", "init")
    return tree


def item_path(tree: Path, item_id: str) -> Path:
    """The path one item lives at, spelled the way the writer spells it."""
    return tree / ITEMS_REL / f"{item_id}.json"


def seed_item(tree: Path, body: dict, *, committed: bool = True) -> Path:
    """Put one item document in the store, bypassing the writer entirely.

    The fixture for every shape the writer must refuse to overwrite: the writer
    refuses what the tests ask it to refuse, so the shapes have to be planted.
    """
    target = item_path(tree, body["id"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    if committed:
        commit(tree, f"items: seed {body['id']}")
    return target


def raw_item(tree: Path, item_id: str, text: str, *,
             committed: bool = True) -> Path:
    """Exact bytes at an item path, for the shapes no builder can express."""
    target = item_path(tree, item_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    if committed:
        commit(tree, f"items: raw {item_id}")
    return target


def seed_record(tree: Path, record_id: str = BASELINE_ID, status: str = "decided",
                supersedes: str | None = None, *,
                committed: bool = True) -> Path:
    """One ledger record, so a citation can be answered without the decide writer."""
    target = tree / "noni" / "decisions" / f"{record_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "id": record_id, "date": "2026-10-01T00:00:00Z",
        "asked_by": "developer",
        "questions": [{"id": "q1", "text": "Kill it?", "options": ["a", "b"],
                       "answer": "a"}],
        "by": "Replay", "scope": "item store", "status": status,
        "supersedes": supersedes,
    }, indent=2) + "\n", encoding="utf-8")
    if committed:
        commit(tree, f"decisions: seed {record_id}")
    return target


def seed_order(tree: Path, entries: list[dict], *,
               schema: str = "noni.order/1", committed: bool = True) -> Path:
    """The order artifact, written by hand.

    Hand-written because ``noni.order/1`` has no ``item`` field and ``order.py`` would
    refuse one, and because the writer's promote refusal has to be tested against an
    order that cites an item -- the ``/2`` shape sub-issue 2 will produce.
    """
    target = tree / "noni" / "direction" / "order.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"schema": schema, "entries": entries},
                                 indent=2) + "\n", encoding="utf-8")
    if committed:
        commit(tree, "order: seed")
    return target


def commit(tree: Path, message: str, date: str = NOW) -> None:
    """Stage and commit whatever the fixtures just placed, dated deterministically."""
    _git(tree, "add", "-A")
    if _git(tree, "status", "--porcelain").stdout.strip():
        git_pin_date(tree, date, "commit", "-q", "-m", message)


def run_item(tree: Path, *args: str, cwd: Path | None = None,
             env: dict | None = None) -> subprocess.CompletedProcess[str]:
    """One ``item.py`` run against ``tree``, capturing its streams.

    A thin wrapper over the harness runner, which owns the environment: coverage's
    hook, the pinned ``PYTHONPATH`` that makes the child import *this* tree's
    ``noni``, and the git identity the verbs commit under. This fixture only adds
    ``--repo``, so the caller owns the command line the exit-code tests assert on.

    Never raises on a non-zero exit: every assertion here is about the code, so the
    caller compares it. The runner carries a 120s timeout, per the project rule that
    anything that could hang is run under one.
    """
    from harness_runners import run_item as _run_item

    return _run_item(tree, *args, env=env, cwd=cwd)


def read(tree: Path, item_id: str) -> dict:
    """The stored document, parsed. Fails the test if the file is not there."""
    return json.loads(item_path(tree, item_id).read_text(encoding="utf-8"))


def committed_paths(tree: Path) -> list[str]:
    """The paths the last commit holds, so a test can name what the run wrote."""
    return _git(tree, "ls-files").stdout.split()
