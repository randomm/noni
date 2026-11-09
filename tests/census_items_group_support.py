"""The shared launch and fixture helpers of the item group's census suites.

The item group is covered by two files -- ``tests/test_census_items_group.py`` for the
classes that read the store, and ``tests/test_census_items_stale.py`` for the ordering
and staleness questions and the group's whole-run behaviour -- and both need the same
three things: a way to put a file in the store, a way to commit what was planted, and a
way to launch the census over the items group and read its rows. Those live here so the
two suites hold one copy of the launch, which is the part a suite must not disagree
about.

The commit is part of the launch and not of the builders: the census reads the tree as
git holds it, so a fixture that planted a shape and never committed it would be asking
what the census says about a file nobody wrote yet. The one case that wants otherwise
(a file mutated after it was committed) passes ``commit=False``.
"""

from __future__ import annotations

import json
from pathlib import Path

from _harness import REPO, _git
from items_fixtures import item_body, run

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"

STORE = "noni/items"


def commit(tree: Path, message: str) -> None:
    """Commit whatever the builders just placed.

    A separate step from the write because some fixtures mutate the file after
    placing it: a builder that committed on the spot would record the bytes before
    the fixture had made them the shape under test.
    """
    _git(tree, "add", "-A")
    if _git(tree, "status", "--porcelain").stdout.strip():
        _git(tree, "commit", "-q", "-m", message)


def item(tree: Path, **fields) -> Path:
    """One well-formed item in the store, named by the ``id`` its own body carries.

    The path follows the document and not the other way round, which is the shape the
    store's key rule makes canonical: a fixture that wants the two to disagree (the
    id-is-not-the-filename defect) passes ``item_id=`` and gets a file named
    ``idea-0001.json`` whose body declares ``idea-0002``.
    """
    declared = fields.get("item_id", "idea-0001")
    target = tree / STORE / f"{declared}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(item_body(**fields), indent=2) + "\n",
                      encoding="utf-8")
    return target


def raw(tree: Path, name: str, text: str) -> Path:
    """Exact text at a store path, bypassing every builder."""
    target = tree / STORE / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def record(tree: Path, record_id: str, status: str = "decided",
           supersedes: str | None = None) -> Path:
    """One ledger record as the census reads it: a JSON document under noni/decisions.

    ``supersedes`` is the decision this record replaced -- the direction every reader of
    the ledger reads the field in, ``decide.py`` and ``orderstate._successor`` included.
    A fixture that wants the chain a superseded record actually sits on (the record that
    killed it, which is what the census's own successor question answers from) passes the
    pair the other way round: the replacing record names the replaced one, so a chain
    ``a <- b <- c`` is written as ``b`` superseding ``a`` and ``c`` superseding ``b``.
    """
    target = tree / "noni" / "decisions" / f"{record_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "id": record_id, "date": "2026-10-01T00:00:00Z",
        "asked_by": "developer",
        "questions": [{"id": "q1", "text": "File it?", "options": ["a", "b"],
                       "answer": "a"}],
        "by": "Replay", "scope": "item store", "status": status,
        "supersedes": supersedes,
    }, indent=2) + "\n", encoding="utf-8")
    return target


def order(tree: Path, entries: list[dict], schema: str = "noni.order/1") -> Path:
    """The order artifact the items group reads, written by hand.

    Hand-written because ``noni.order/1`` has no ``item`` field and ``order.py`` would
    refuse one: the ``/2`` shape is exercised here so the class that reads it is not
    invented when the second schema version lands.
    """
    target = tree / "noni" / "direction" / "order.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"schema": schema, "entries": entries},
                                 indent=2) + "\n", encoding="utf-8")
    return target


def launch(tree: Path, *extra: str):
    """Commit what the fixtures placed, then run the census over the items group."""
    commit(tree, "items: fixture")
    return run(tree, *extra)


def findings(tree: Path, *extra: str, commit_before: bool = True) -> list[dict]:
    """The findings of a run over the items group.

    ``commit_before`` is False for the fixture that mutates a committed file after the
    fact (an artifact whose mode was taken away, a body rewritten behind git's back):
    those tests have already committed what they mean to commit and a second
    ``git add`` would fail on the very unreadability the test is asserting.
    """
    if commit_before:
        commit(tree, "items: fixture")
    return run(tree, *extra)[1]


def one(tree: Path, check: str, *extra: str) -> dict:
    rows = [row for row in findings(tree, *extra) if row["check"] == check]
    assert len(rows) == 1, f"expected exactly one {check} row, got {rows}"
    return rows[0]
