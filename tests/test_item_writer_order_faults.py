"""``promote`` and the order: one state of the artifact, one code, no silent pass.

Promote is item-only in this sub-issue, so the single question it asks the direction
layer is "does an order entry cite this item". The bug this suite holds shut: the read
that answers it collapsed a *plain file*, a *directory* and an *unreadable file* at
``noni/direction/order.json`` into "absent", so a promote proceeded on an order it never
read and agreed with a run that had read an order citing nothing.

The codes are the ones ``order.py`` already gives the same states (PM ruling on #124):
only a genuinely absent artifact is "no order"; a symlink, a directory, a device or a
file this run cannot read is exit 3; bytes that do not parse or are not the artifact are
exit 4; and an entry that cites the item is exit 4 naming the order path.

The citing entry is a ``noni.order/2`` shape -- an entry carrying the ``item`` key the
``/1`` entry schema does not name. Sub-issue 2 (#123) owns that artifact; to this ticket's
reader such a file is simply not a canonical ``/1`` order, so it is refused exit 4 naming
the order path, which is the ruled behaviour until #123 lands.
"""

from __future__ import annotations

import json
import os

from item_writer_fixtures import (
    BASELINE_ID,
    FRESH,
    NOW,
    commit,
    item_path,
    repo,
    run_item,
    seed_item,
)
from order_canonical import order_bytes

ORDER_REL = "noni/direction/order.json"
CITED = {"issue": 7, "decision": BASELINE_ID, "confirmed": FRESH,
         "item": "idea-0001"}
UNCITED = {"issue": 7, "decision": BASELINE_ID, "confirmed": FRESH}


def _order_text(entries):
    """The artifact's canonical bytes for ``entries``.

    The writer's own shape, so these tests ask about the artifact rather than about the
    indent a fixture happened to choose: a non-canonical file is a *malformed* order to
    this reader (exit 4), and a test that meant "an order citing this item" has to hand
    over the bytes the ``/1`` writer produces.
    """
    return order_bytes(entries)


def _seed_order_text(tree, text, *, committed=True):
    """Exact bytes at the order path.

    The fixture for every order state this suite asks about. ``seed_order`` in the
    writer's fixtures takes *entries* and projects them through the writer's own field
    list, which drops the ``item`` key the citing cases need; these tests own the bytes
    so the artifact under test is the one they name.
    """
    path = _order_file(tree)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if committed:
        commit(tree, "order: seed")
    return path


def _unreadable_order(tree) -> None:
    """An artifact whose bytes are on disk and whose *open* is refused.

    chmod 000 on the file is the fault this case wants. chmod 000 on its parent is not:
    it denies the directory's traversal bit too, so the kernel reports the file itself
    as unreachable (``ENOENT``) and the run answers a different question -- correctly,
    so the case would pass for the wrong reason.
    """
    path = _seed_order_text(tree, _order_text([CITED]))
    os.chmod(path, 0)


def _candidate(tmp_path, name):
    """A tree holding one candidate item and nothing else of the direction layer."""
    tree = repo(tmp_path, name)
    seed_item(tree, {"schema": "noni.item/1", "id": "idea-0001", "title": "t",
                     "status": "candidate", "created": FRESH})
    return tree


def _promote(tree):
    return run_item(tree, "promote", "idea-0001", "--issue", "7", "--now", NOW)


def _order_file(tree):
    return tree / "noni" / "direction" / "order.json"


def test_promote_with_no_order_at_all_promotes_and_writes_only_the_item(tmp_path):
    """An absent artifact is an answer ("no entry cites it"), not a fault.

    The one case in which the run is meant to proceed: it writes the item and nothing
    else, so a promote of an unordered project stays the single-path commit the writer
    promises.
    """
    tree = _candidate(tmp_path, "order-absent")
    proc = _promote(tree)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(item_path(tree, "idea-0001").read_text(
        encoding="utf-8"))["status"] == "promoted"
    assert not _order_file(tree).exists(), "promote wrote the order it never read"
    assert not (tree / "noni" / "direction").exists(), (
        "promote created the direction directory out of an absent order")


def test_promote_refuses_an_unreadable_order_at_exit_three(tmp_path):
    """A file the run cannot read is exit 3, exactly as ``order.py`` maps it.

    The unreadable order is the state the collapsing bug made most dangerous: a run that
    read nothing answered "no entry cites it" and promoted.
    """
    tree = _candidate(tmp_path, "order-unreadable")
    _unreadable_order(tree)
    try:
        proc = _promote(tree)
    finally:
        os.chmod(_order_file(tree), 0o644)
    joined = proc.stdout + proc.stderr
    assert proc.returncode == 3, joined
    assert ORDER_REL in joined, joined
    assert "Traceback" not in joined, joined
    assert "could not be read" in joined, (
        f"the refusal did not say what faulted: {joined}")
    assert '"status": "candidate"' in item_path(tree, "idea-0001").read_text(
        encoding="utf-8"), "the promote wrote despite the fault"


def test_promote_refuses_a_directory_at_the_order_path_at_exit_three(tmp_path):
    """A directory is not an empty order: nothing was read, so nothing is answered."""
    tree = _candidate(tmp_path, "order-dir")
    _order_file(tree).mkdir(parents=True)
    proc = _promote(tree)
    joined = proc.stdout + proc.stderr
    assert proc.returncode == 3, joined
    assert ORDER_REL in joined, joined
    assert "Traceback" not in joined, joined
    assert '"status": "candidate"' in item_path(tree, "idea-0001").read_text(
        encoding="utf-8"), "the promote wrote over an order it never read"


def test_promote_refuses_a_plain_file_at_the_order_path_at_exit_three(tmp_path):
    """A plain file the run cannot read at the artifact path is exit 3, not absence.

    The state-root guard does not cover the order (it walks the state root, the store
    and the ledger), so this is the reader's own question to answer. A file it *can*
    read is a different state and a different code: bytes that are not the artifact are
    exit 4 (the malformed case below), and only an unreadable one is the environment's
    exit 3 -- which is what the shape has to be here, since a prose file is a
    non-artifact and would otherwise be refused for the wrong reason by the right code.
    """
    tree = _candidate(tmp_path, "order-file")
    _order_file(tree).parent.mkdir(parents=True, exist_ok=True)
    _order_file(tree).write_text("just some prose\n", encoding="utf-8")
    os.chmod(_order_file(tree), 0)
    try:
        proc = _promote(tree)
    finally:
        os.chmod(_order_file(tree), 0o644)
    joined = proc.stdout + proc.stderr
    assert proc.returncode == 3, joined
    assert ORDER_REL in joined, joined
    assert "Traceback" not in joined, joined
    assert '"status": "candidate"' in item_path(tree, "idea-0001").read_text(
        encoding="utf-8")


def test_promote_refuses_a_malformed_order_at_exit_four(tmp_path):
    """Bytes that are not the artifact are exit 4, exactly as ``order.py`` maps them.

    Three shapes the same class owns: bytes that do not parse, a document that is not
    the artifact's shape, and canonical bytes no writer produced. All three are faults
    of the file rather than of the environment, so all three take the refusal code and
    none takes the I/O code.
    """
    for name, text in (("unparseable", "not json at all {{"),
                       ("wrong-shape", json.dumps({"schema": "noni.order/1"})),
                       ("non-canonical", json.dumps(
                           {"schema": "noni.order/1", "entries": [UNCITED]}))):
        tree = _candidate(tmp_path, f"order-{name}")
        _seed_order_text(tree, text)
        proc = _promote(tree)
        joined = proc.stdout + proc.stderr
        assert proc.returncode == 4, f"{name}: {proc.returncode} {joined}"
        assert ORDER_REL in joined, f"{name}: names no artifact: {joined}"
        assert "Traceback" not in joined, f"{name}: {joined}"
        assert '"status": "candidate"' in item_path(tree, "idea-0001").read_text(
            encoding="utf-8"), f"{name}: the promote wrote over a malformed order"


def test_promote_refuses_an_order_entry_that_cites_the_item(tmp_path):
    """An order whose entries cite an item is refused, naming the order path.

    The citing shape is ``noni.order/2``'s, which this ticket does not own: today's
    reader sees an entry carrying a key the ``/1`` entry schema does not name, which is
    not an artifact it can vouch for, so the ruling's exit 4 (name the order path, say
    the order is what has to change) is reached as a malformed order. Sub-issue 2 (#123)
    replaces this refusal with the same-commit rewrite; what is pinned here is that the
    citing file is *never* promoted through, whatever code the refusal carries.
    """
    for name, text in (("citing /1 entry", _order_text([CITED])),
                       ("/2 schema", order_bytes([CITED], schema="noni.order/2"))):
        tree = _candidate(tmp_path, f"order-{name}")
        _seed_order_text(tree, text)
        proc = _promote(tree)
        joined = proc.stdout + proc.stderr
        assert proc.returncode == 4, f"{name}: {proc.returncode} {joined}"
        assert ORDER_REL in joined, f"{name}: names no artifact: {joined}"
        assert "Traceback" not in joined, f"{name}: {joined}"
        assert '"status": "candidate"' in item_path(tree, "idea-0001").read_text(
            encoding="utf-8"), f"{name}: the promote wrote despite the citation"


def test_promote_prompts_nothing_when_no_entry_cites_the_item(tmp_path):
    """The refusal is about the citation, not about the order being there.

    Pinned beside the refusal so the two cannot be confused: an order this run read in
    full, whose entries cite something else, is the state a promote runs on. The issue is
    one that order does not list -- promoting to an issue the queue already holds is a
    refusal of its own, and this case asks the other question.
    """
    tree = _candidate(tmp_path, "order-uncited")
    _seed_order_text(tree, _order_text([UNCITED]))
    proc = run_item(tree, "promote", "idea-0001", "--issue", "42", "--now", NOW)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(item_path(tree, "idea-0001").read_text(
        encoding="utf-8"))["status"] == "promoted"
