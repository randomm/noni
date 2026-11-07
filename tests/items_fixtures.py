"""Shared builders for the census's items group tests and the item writer's suite.

A fixture repo that holds one committed decided record plus any items the caller
names, the runners that drive the census for it, and the fault injectors that break
one group's read alone. Held in a non-test module so the items test files build the
same repo and pytest never collects the builders as tests. The counterpart of
``tests/ordering_fixtures.py``, written beside it rather than extended: the ordering
builders own the order artifact and its ``--issue-state`` seams, and a group's
builders stay the file that group's six tests read.

The shape tables are deliberately not here: ``tests/items_shapes.py`` is read by the
writer's suite too, so it stays where both sides can see it.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
from pathlib import Path

from _harness import REPO, _git, _init_repo, git_pin_date, subprocess_env

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"

BASELINE_ID = "2026-10-01-baseline"

HEIR_ID = "2026-11-01-heir"

FRESH = "2026-10-26T00:00:00Z"

STALE = "2026-01-01T00:00:00Z"

NOW = "2026-10-27T12:00:00Z"

ITEM_REL_DIR = "noni/items"

ORDER_REL = "noni/direction/order.json"

ITEM_CLASSES = ("item-malformed", "item-dropped-in-order",
                "item-promoted-without-issue", "item-reference-unresolved",
                "item-stale", "item-unlistable")


def item_body(item_id: str = "idea-0001", status: str = "candidate",
              created: str = FRESH, issue: int | None = None,
              decision: str | None = None, why: str | None = None,
              title: str = "An idea", schema: str = "noni.item/1") -> dict:
    """One item document in the documented key order, holding all eight fields.

    Built here rather than through ``itemschema.entry`` so a test can hand the census
    a shape the writer would refuse: a builder that validated what it emitted could
    not plant the malformed file it exists to plant.

    The three optional fields are **omitted** when they name nothing, which is what
    the writer itself produces (``itemschema.item_bytes`` writes only the keys a body
    holds). The two shapes are not interchangeable and the schema tells them apart: a
    ``dropped`` item with ``"why": null`` is a hand-edited artifact it refuses, and one
    that carries no ``why`` key at all is the same defect reported by the same rule
    with a different document underneath. A builder that always emitted all eight keys
    could not produce the clean file, because a promoted item's own ``"issue": null``
    is one of the shapes the reader refuses.
    """
    body: dict = {"schema": schema, "id": item_id, "title": title,
                  "status": status, "created": created}
    if issue is not None:
        body["issue"] = issue
    if decision is not None:
        body["decision"] = decision
    if why is not None:
        body["why"] = why
    return body


def item_bytes(body: dict) -> str:
    return json.dumps(body, indent=2) + "\n"


def _record(record_id: str = BASELINE_ID, status: str = "decided",
            supersedes: str | None = None, date: str = "2026-10-01T00:00:00Z") -> str:
    return json.dumps({
        "id": record_id, "date": date, "asked_by": "developer",
        "questions": [{"id": "q1", "text": "Order?", "options": ["a", "b"],
                       "answer": "a"}],
        "by": "Replay", "scope": "release ordering", "status": status,
        "supersedes": supersedes,
    }, indent=2) + "\n"


def commit(repo: Path, rel: str, body: str, date: str = NOW) -> None:
    """One committed file, dated, in a throwaway tree."""
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", rel)
    git_pin_date(repo, date, "commit", "-q", "-m", f"items: {rel}")


def repo(tmp_path: Path, subdir: str = "repo", records: bool = True) -> Path:
    """A throwaway tree, optionally holding one committed decided record.

    The record exists so an item's ``decision`` citation can be answerable: the
    census looks an id up by its filename stem, and a test that cites one against an
    empty ledger is testing the missing-record path, not the one it named.
    """
    tree = _init_repo(tmp_path / subdir)
    if records:
        commit(tree, f"noni/decisions/{BASELINE_ID}.json", _record(),
               "2026-10-01T00:00:00Z")
    return tree


def add_item(tree: Path, body: dict, committed: bool = True) -> Path:
    """Put one item document in the store, named by its own ``id``."""
    target = tree / ITEM_REL_DIR / f"{body['id']}.json"
    text = item_bytes(body)
    if committed:
        commit(tree, f"{ITEM_REL_DIR}/{body['id']}.json", text)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def write_raw(tree: Path, name: str, raw: bytes, committed: bool = True) -> Path:
    """Put exact bytes at a store path, bypassing every builder.

    For the shapes no ``item_body`` can produce: non-UTF-8 bytes, a document the
    strict reader refuses, a key stated twice, or bytes that are the artifact but not
    in the canonical form.
    """
    target = tree / ITEM_REL_DIR / name
    if committed:
        commit(tree, f"{ITEM_REL_DIR}/{name}", "")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return target


def order(tree: Path, issues: list[int], committed: bool = True) -> Path:
    """The one order artifact the items group reads, holding ``issues``."""
    body = json.dumps({"schema": "noni.order/1", "entries": [
        {"issue": issue, "decision": BASELINE_ID, "confirmed": FRESH}
        for issue in issues]}, indent=2) + "\n"
    if committed:
        commit(tree, ORDER_REL, body)
        return tree / ORDER_REL
    target = tree / ORDER_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


def supersede(tree: Path) -> str:
    """Supersede the baseline record with a live heir, and name the heir's id."""
    commit(tree, f"noni/decisions/{HEIR_ID}.json",
           _record(HEIR_ID, "decided", BASELINE_ID, "2026-11-01T00:00:00Z"),
           "2026-11-01T00:00:00Z")
    commit(tree, f"noni/decisions/{BASELINE_ID}.json",
           _record(BASELINE_ID, "superseded"), "2026-11-01T00:00:00Z")
    return HEIR_ID


def only_args(extra: tuple[str, ...]) -> list[str]:
    """The argv fragment a run is launched with: the caller's own --only/--skip
    names, plus the whole items group when the caller named no --only at all.

    One pass over ``extra``: a value belonging to --only or --skip is consumed with
    its flag and never re-added, so the names appear exactly once whoever named them.
    A caller that named only --skip values still gets the group's --only set: the
    helper's job is to confine the run to the items group, and a bare --skip would
    otherwise let the ledger, session and hygiene classes in beside it.
    """
    args: list[str] = []
    named: list[str] = []
    index = 0
    while index < len(extra):
        arg = extra[index]
        if arg in ("--only", "--skip") and index + 1 < len(extra):
            value = extra[index + 1]
            if arg == "--only":
                named.append(value)
            args += [arg, value]
            index += 2
            continue
        args.append(arg)
        index += 1
    if not named:
        for check in ITEM_CLASSES:
            args += ["--only", check]
    return args


def _launch(tree: Path, *extra: str, json_out: bool = True):
    args = [sys.executable, str(CENSUS), "--repo", str(tree), "--now", NOW]
    if json_out:
        args.append("--json")
    args += only_args(extra)
    return subprocess.run(args, capture_output=True, text=True,
                          env=subprocess_env(), timeout=120)


def run(tree: Path, *extra: str) -> tuple[int, list[dict], str, str]:
    """The census over the items group only, as NDJSON plus raw streams."""
    proc = _launch(tree, *extra)
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return proc.returncode, [r for r in rows if r.get("kind") == "finding"], \
        proc.stdout, proc.stderr


def code(tree: Path, *extra: str) -> int:
    """The exit code of a run used only as a precondition."""
    return run(tree, *extra)[0]


def human(tree: Path, *extra: str) -> tuple[int, str, str]:
    proc = _launch(tree, *extra, json_out=False)
    return proc.returncode, proc.stdout, proc.stderr


def item_rows(rows: list[dict]) -> list[dict]:
    """Only the rows of the items group, so a stray row cannot pass a test by luck."""
    return [row for row in rows if row["check"] in ITEM_CLASSES]


def checks(rows: list[dict]) -> list[str]:
    return sorted(row["check"] for row in item_rows(rows))


@contextlib.contextmanager
def listing_faults(store: Path):
    """Make the store's one readdir fault for the block, on a directory that exists.

    The census reads the store once, through ``census._items_listing``, so one patch
    on that name is the whole fault: the gate that decides the group is owed a read
    and the rows that report it are then the answer of the read that failed, which is
    the property the group's probe-honesty rule rests on. The fault is produced by the
    real probe against a directory whose mode was taken away, so its text is a real
    fault text and not one this file invented; the mode is restored on the way out so
    pytest can still clean the tree up.
    """
    from noni import census, census_items_readers

    real = census._items_listing

    def faulted(_items: Path):
        store.chmod(0o000)
        try:
            return census_items_readers.items_listing(store)
        finally:
            store.chmod(0o755)

    census._items_listing = faulted
    try:
        yield
    finally:
        store.chmod(0o755)
        census._items_listing = real
