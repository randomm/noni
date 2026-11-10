"""The order's canonical bytes and shape, read by a module that loads nothing.

``census_ordering.py`` is loaded by path and imports nothing from the writer's package
(``noni.orderschema`` and ``noni.orderstate`` are the writer's own modules, and a census
that imported them would trust any lookalike earlier on ``sys.path``). That is why the
census's copies of the field lists and the version name live in
``census_ordering`` itself. This module is the other half of that arrangement: the same
two questions the *writer* answers -- is this document the artifact, and what are its
canonical bytes -- answered for a caller that cannot ask the writer.

Three checks, the same three ``orderstate.read_order`` applies before it lets a verb
extend a file, and in the same order, because the codes the caller gives the three
outcomes differ:

1. the strict reader, for the bytes no noni writer emits (a non-finite number, a
   duplicate key, nesting past the bound);
2. ``problems``, for the document's shape;
3. the canonical comparison, because a file the writer would render differently is
   refused rather than reformatted -- an order the operator committed is not this run's
   to rewrite.

A caller may hand its own strict reader (the census hands ``census_json.load_json_strict``)
so what the arbiter can read is exactly what the writer can write, and no second copy of
that reader's four refusals is born here.
"""

from __future__ import annotations

import json
from typing import Callable

from . import orderschema, orderstate


class ReadRefused(Exception):
    """The bytes are not the artifact, or are not in the form the writer writes.

    Carries the two-line pair the caller prints; the code it returns is the caller's
    choice, because the three outcomes this module distinguishes take different codes in
    different writers and the one table of codes stays with the writer that publishes it.
    """

    def __init__(self, headline: str, hint: str) -> None:
        super().__init__(headline)
        self.headline = headline
        self.hint = hint


def load_strict(raw: bytes) -> object:
    """Parse ``raw`` with the writer's own strict reader, refusing what it refuses.

    The default for callers with no reader of their own. The four refusals -- non-finite
    numbers, a duplicate key, nesting past the bound, text that is not JSON at all -- are
    raised as :class:`ReadRefused` rather than left as a ``ValueError`` the caller has to
    know to expect.
    """
    try:
        return orderschema.load_json_checked(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError,
            RecursionError) as exc:
        raise ReadRefused(f"{orderschema.ORDER_REL} is not valid JSON this reader can "
                          "extend", _repair_hint("")) from exc


def _repair_hint(why: str) -> str:
    """The 'repair the artifact' hint, naming the versions a repair may use.

    The one version is named because it is the only one a reader accepts: a file that
    states another is refused for what it says, not repaired by this reader.
    """
    return (f"repair the file {why} (it must hold "
            + repr(orderschema.ORDER_SCHEMA)
            + ") or remove it and rebuild the order with the order writer")


def problems(value: object) -> list[str]:
    """Why ``value`` is not an order the writer would extend; [] when it is.

    A pass-through of the writer's own rule, kept as this module's name so a caller that
    cannot import ``orderschema`` still asks the one question, and so the answer it gets
    is the answer the writer gives rather than a census-side paraphrase of it.
    """
    return orderschema.problems(value)


def read(raw: bytes, load_json: Callable[[bytes], object] | None = None
         ) -> tuple[dict, bytes]:
    """The document ``raw`` holds, checked against the form the writer writes.

    Returns ``({schema, entries}, raw)``; raises :class:`ReadRefused` for bytes that do
    not parse, are not the artifact's shape, or are not the canonical bytes of the
    document they hold. The document's own ``schema`` is carried through, so a
    ``/2`` file is compared against ``/2`` bytes and a ``/1`` one against ``/1`` --
    asking the renderer for the other version would make every file of one version a
    permanent refusal of the other.
    """
    value = (load_strict if load_json is None else load_json)(raw)
    if not isinstance(value, dict):
        raise ReadRefused(f"{orderschema.ORDER_REL} is not a JSON object this reader "
                          "can extend", _repair_hint(""))
    found = orderschema.problems(value)
    if found:
        raise ReadRefused(f"{orderschema.ORDER_REL} is not an order this writer "
                          "writes: " + "; ".join(found), _repair_hint("to the "
                                                                      "documented shape"))
    body = {"schema": value["schema"], "entries": value["entries"]}
    canonical = orderstate.render(body)
    if isinstance(canonical, orderstate.RenderRefused):
        raise ReadRefused(canonical.headline, canonical.hint)
    if canonical != raw:
        raise ReadRefused(f"{orderschema.ORDER_REL} is not in the canonical form this "
                          "writer writes (its keys, their order or its indent)",
                          "have the order writer write it, or repair and commit it in "
                          "that form, then re-run")
    return body, raw


def render(body: dict) -> bytes | orderstate.RenderRefused:
    """The canonical bytes of ``body``, or the refusal naming why none exist.

    The writer's renderer, reached through the one module that owns it, so the bytes
    this reader compares a file against are exactly the bytes a verb would write.
    """
    return orderstate.render(body)
