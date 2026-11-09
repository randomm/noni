"""The order artifact's canonical bytes, including the item field of ``noni.order/2``.

A helper module (never named ``test_*``), for the suites that have to plant an order the
reader will accept. ``seed_order`` in ``item_writer_fixtures`` takes exact text because
the shapes a test wants include the ones no writer produces; a test that means "an order,
in the artifact's own form" cannot use an indent of its own choosing, because non-canonical
bytes are a *malformed* order to this reader and the case it meant to make is silently a
different case.

The shape is spelled here in the writer's own idiom -- keys in the documented order, two
spaces, one trailing newline, the three fields a ``noni.order/1`` entry owns -- and not
reached through ``orderschema.order_bytes``, because that renderer *drops* the ``item``
key on its way to the bytes and the citing case needs it. The parity that matters is with
what the item reader accepts: the reader compares the file against
``orderstate.render(orderstate.body_of(value))``, whose entry projection names exactly
``issue``, ``decision`` and ``confirmed``, so a file carrying an ``item`` key as well can
still be the canonical bytes of the document it holds.
"""

from __future__ import annotations

import json
from typing import Any

ENTRY_FIELDS = ("issue", "decision", "confirmed")


def order_bytes(entries: list[dict[str, Any]], *,
                schema: str = "noni.order/1",
                extra_fields: tuple[str, ...] = ("item",)) -> str:
    """The canonical text of an order whose entries hold ``entries``.

    ``extra_fields`` names the fields an entry carries beyond the three the writer
    writes, and the default carries ``item``: a document that holds one keeps it in its
    bytes (deleting it from a file is not something a reader may do), and a document
    that holds none renders identically, so one helper spells both the ``/1`` artifact
    and the citing shape sub-issue 2 gives ``/2``.
    """
    rendered = [{field: entry[field] for field in (*ENTRY_FIELDS, *extra_fields)
                 if field in entry} for entry in entries]
    return json.dumps({"schema": schema, "entries": rendered},
                      indent=2, ensure_ascii=False, allow_nan=False) + "\n"
