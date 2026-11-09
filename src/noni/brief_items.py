"""The item-store read the brief's ``candidates`` block is built from.

Split from ``brief.py`` for the 500-line source cap, beside ``brief_intent.py`` and for
the same reason: ``brief.py`` owns the command line, the budget and what each block
prints, and this module owns the store listing that block consumes. Both files are the
brief's own reads of artifacts that the *writers* of those artifacts read differently:
``item.py`` reads the store to refuse a duplicate title and the census reads it to
arbitrate six classes, and neither answer is the one a screen of the freshest ideas
needs.

The rule this read is built on: a file the listing could not make sense of contributes
no row and no complaint. This is a listing, not an arbiter. The census's items group is
what reports a malformed, unlistable or stale item, and it runs in the same process a
moment later to produce the brief's summary line, so a listing that died on one broken
file -- or that printed its own version of the fault -- would be a second, weaker copy of
a report the tree already gets.
"""

from __future__ import annotations

from pathlib import Path

from . import itemschema, orderschema

# The one suffix this listing opens a file for. The store names its files ``<id>.json``
# through :func:`noni.itemschema.item_rel` and refuses an id carrying the suffix, so the
# suffix is part of what an item file's name is; it is spelled here because the store's
# module holds it inside that one renderer and a listing needs it as a filter. Asked of
# every path before it is opened, and asked once, so a directory named ``x.json`` and a
# file named ``notes.md`` are both answered without being read.
ITEM_SUFFIX = ".json"


def candidates(store: Path) -> list[dict]:
    """The candidate items under ``store``, newest ``created`` first.

    One ``iterdir`` of the store and one read per regular file whose name ends in the store's
    own suffix. An absent store, a path that is not a directory, a refused listing, a file the
    strict reader refuses and a document that is not the item its own shape describes all
    contribute no row. A document whose ``id`` disagrees with its file's stem contributes
    nothing either: the id is what the row prints, and printing an idea under a name its own
    file denies it is the one harm this listing could do.

    Two filters run before any file is opened, both of them the listing's rather than the
    store's. A directory is not an item and is never opened: the reader that followed one would
    report the same word for ``noni/items/notes.md`` and for a subdirectory called ``x.json``,
    and a listing of ideas that read a directory's bytes was never a listing. The suffix is
    asked of the store's own constant for the same reason the census's items group asks it:
    the store's files are named ``<id>.json`` by the writer, so anything else is not one of
    them, and reading a file the listing then refuses is work a screen should not do.

    The sort is over ``(created, id)`` and reversed, so a tie on the stamp has one answer: the
    id breaks it, which is the field of an item that is unique within the store by rule, and so
    the order is a property of the tree rather than of the order ``iterdir`` happened to return
    the names in. Two runs over one tree therefore print the same bytes.
    """
    try:
        paths = sorted(store.iterdir())
    except (OSError, ValueError):
        # A declined listing is the state the census's ``item-unlistable`` class exists
        # to word; here it is the empty listing, which prints the block's header alone.
        return []
    named = [path for path in paths
             if path.suffix == ITEM_SUFFIX and path.is_file()]
    bodies = [body for body in (_candidate_body(path) for path in named)
              if body is not None]
    return sorted(bodies, key=lambda body: (body["created"], body["id"]),
                  reverse=True)


def candidate_title(root: Path, item_id: str) -> str | None:
    """The title of the item ``item_id``, or None when no readable item holds it.

    The lookup an order entry of ``noni.order/2`` needs: the entry cites an id and the
    row wants to say what the idea is. An unreadable file, bytes the strict reader
    refuses, a document that is not an item, an item that names itself other than the
    file's stem, and an id that is not an id at all all answer None, and the caller
    prints the citation it has rather than a title it did not read.

    An id outside the store's own rule is refused before any path is built from it --
    the rule every reader of the store applies, and the reason a citation from a hand-
    edited artifact cannot name a file outside ``noni/items/`` through this call.
    """
    if not itemschema.is_item_id(item_id):
        return None
    value = _read_item(root / itemschema.ITEM_DIR / f"{item_id}.json")
    if value is None or value.get("id") != item_id:
        return None
    title = value.get("title")
    return title if isinstance(title, str) else None


def _candidate_body(path: Path) -> dict | None:
    """The candidate ``path`` holds, or None: not readable, not an item, not a candidate.

    The shape rules are the store's own (:func:`noni.itemschema.problems`), asked before
    anything of the file is used, and then the one question that is this listing's: is
    it a candidate. A promoted or dropped item is the census's ``item-stale`` and the
    kill list's content, not a row of this block.

    ``created`` travels as the file's own text: :func:`noni.itemschema.problems` has
    already refused a stamp that names no instant, and re-rendering an instant that its
    writer already wrote in canonical form would put a second formatting of one field
    between the store and the screen.
    """
    value = _read_item(path)
    if value is None:
        return None
    body = itemschema.body_of(value)
    if body["id"] != path.stem or body["status"] != itemschema.STATUS_CANDIDATE:
        return None
    return body


def _read_item(path: Path) -> dict | None:
    """The item document at ``path``, or None when this run holds no such document.

    The package's one strict JSON reader, so the four things no noni writer emits (a
    non-finite number, an overflowed literal, a key stated twice, a nesting past the
    bound) are refused here exactly as they are by the store's writer and the census's
    items group -- one reader for one contract, and no third copy. ``RecursionError`` is
    named because it is no kind of ``ValueError``: the bound answers short of the
    interpreter's own ceiling, past which the decoder raises first, and an arm that did
    not name it would let one pathological file take the run down with it.
    """
    try:
        value = orderschema.load_json_checked(path.read_bytes())
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(value, dict) or itemschema.problems(value):
        return None
    return value
