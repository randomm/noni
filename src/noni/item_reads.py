"""The two reads ``item.py`` borrows from the direction layer: the order and a record.

Mechanics, not the writer's contract. ``item.py`` owns the verbs, the exit codes and
the commit; ``orderstate.py`` owns the reads of the order artifact and the ledger as
*the order writer* needs them, with the refusal wording that writer prints. A promote
needs a different answer from the same file -- not "may this run write over the
order" but "does any entry cite this item" -- and asking the first question to get
the second is how a run that read nothing comes back agreeing with a run that read
an order citing nothing. So the two reads a *reader* of that state needs live here,
beside the module they read through, and reach the artifact's rules through
``orderstate`` and ``orderschema`` rather than a third copy of either.

Nothing here prints, exits or decides an exit code: each answer travels back as a
value, and the caller words its own refusal.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import orderschema, orderstate


def read_order_entries_or_fault(path: Path) -> list[dict] | None:
    """The entries of a canonical ``noni.order/1`` file, or None when it is not one.

    The order read a reader asks. Unlike :func:`noni.orderstate.read_order` it
    refuses nothing, because a caller that only wants to know whether an entry cites
    something gets an honest answer from an absent file (an empty list) and no answer
    at all from a file it could not read (``None``). The distinction is the caller's
    to word; this function's whole job is to keep it from collapsing silently into
    "no entry cites it", which would let a promote through on an order the run never
    read.

    Returns ``None`` for every state in which no reading was made: the path is not a
    readable regular file, the bytes do not parse, the shape is not the artifact, or
    the bytes are not the canonical form the order family writes. Returns ``[]`` for
    the one state that is an answer rather than a fault: no file at all, which is the
    state of a project that has never ordered anything.

    The strict reader and the shape rules are the ones ``orderstate`` and
    ``orderschema`` already own, reached as package imports -- the writer's reads and
    the arbiter's reads of one file must be one definition, and the ``RecursionError``
    arm is named because it is no kind of ``ValueError``: the depth bound answers for
    a document short of the interpreter's own ceiling, past which the decoder raises
    this one first.
    """
    kind, _why = orderstate.file_kind(path)
    if kind == "absent":
        return []
    if kind != "regular":
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        value = orderschema.load_json_checked(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(value, dict) or orderschema.problems(value):
        return None
    if orderstate.render(orderstate.body_of(value)) != raw:
        # The canonical comparison, asked of the same renderer the order writer
        # compares against: a file the writer would refuse is a file whose entries
        # this run cannot vouch for, so it answers nothing rather than something.
        return None
    return [dict(item) for item in value["entries"]]


def order_cites_item(repo: Path, item_id: str) -> tuple[bool, bool]:
    """(cited, answered): whether an order entry cites ``item_id``, and whether that
    question could be answered at all.

    The one question ``item.py promote`` asks of the direction layer, and the two
    answers it must not confuse: ``False`` with ``answered`` True is the order this
    run read and found no citation in, and ``False`` with ``answered`` False is no
    reading at all -- which the caller refuses rather than promotes through.

    The entry's own key is asked with ``.get`` because the item field of the order is
    sub-issue 2's: a ``noni.order/1`` entry carries ``issue``, ``decision`` and
    ``confirmed`` and nothing else, so today nothing cites an item and the honest
    answer is the empty scan. The day the order gains the field, the scan already
    asks the right question and only the order's schema changes.
    """
    entries = read_order_entries_or_fault(repo / orderschema.ORDER_REL)
    if entries is None:
        return False, False
    return any(entry.get("item") == item_id for entry in entries), True
