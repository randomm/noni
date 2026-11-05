"""What the bytes of a decision record may be called a record.

Split from ``gitwrite.py`` (issue #102), which owns the git call, the atomic
write and the probes that read a supersede target's committed bytes. This module
owns the one question those probes ask about the bytes they read: the write stays
with the writer, the read rule lives here, and ``gitwrite.record_object``
delegates so the writer has one call and this file one owner.

Three things a plain ``json.loads`` does not answer with a refusal:

- a nesting past the interpreter's own stack raises ``RecursionError``, which is
  no kind of ``ValueError``, so an arm naming only that misses it. Where the
  decoder gives up is a property of the build: measured at the default recursion
  limit of 1000, 3.11 stops just under it, 3.12 and 3.13 near 10000, 3.14 near
  60000, and all four at 100000 levels.
- an integer literal past the interpreter's 4300-digit conversion limit raises
  ``ValueError`` out of ``int()``, not out of the decoder's grammar.
- a value the decoder did build can still overflow the walk that inspects it, if
  that walk recurses. Which is why :func:`holds_non_finite` is iterative, as the
  copies in ``orderschema`` and ``census_json`` already are.

None of the three reaches a caller: a target the writer cannot read is the
writer's "not a readable JSON object" refusal, and a run that died instead
printed no refusal, wrote nothing, and left the operator to guess which of its
two records the run had choked on.
"""

from __future__ import annotations

import json
import math


def record_object(raw: bytes) -> dict | None:
    """The record object ``raw`` holds, or None when it is not one. Decoding
    happens here, not in json.loads' reader, so a non-UTF-8 record answers "not a
    record" instead of a traceback, and its bytes are never echoed.

    Two refusals, one fact: a record holding a number this writer cannot name is
    not a record whatever field carries it. ``parse_constant`` refuses the three
    bare tokens json reads by default (``NaN``, ``Infinity``, ``-Infinity``), which
    are not JSON at all; :func:`holds_non_finite` then walks the parsed structure
    for the legal literal that overflows to the same value with no token to stop.
    Reading either into a float would put a value no writer can emit back on disk.

    The four arms are the four ways this decoder declines to answer. Besides the
    malformed text and the refused token, ``ValueError`` is what a number literal
    past the interpreter's 4300-digit integer limit raises, and ``RecursionError``
    is what a nesting past the interpreter's own stack raises - and it is no kind
    of ``ValueError``, so naming the one never named the other. Either escaping
    would turn a target this writer cannot read into a traceback instead of the
    refusal it earns.
    """
    try:
        record = json.loads(raw.decode("utf-8"), parse_constant=refuse_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(record, dict) or holds_non_finite(record):
        return None
    return record


def holds_non_finite(value: object) -> bool:
    """Whether ``value`` holds a float json read in that is not finite.

    ``math.isfinite`` is what catches the overflowed literal (json hands back
    ``inf`` for ``1e400``). A bool is a bool, never a number, so a record every
    writer emits still parses.

    The walk is iterative with its own stack, never recursive, as the copies in
    ``orderschema`` and ``census_json`` are: a value that nests past the
    interpreter's budget makes a recursive walk raise ``RecursionError`` inside
    the reader, and a reader that dies on the shape of a record answers nothing
    about it.
    """
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, float):
            if not math.isfinite(item):
                return True
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
    return False


def refuse_constant(token: str) -> float:
    """The reader's answer to ``NaN``/``Infinity``/``-Infinity``: refuse the token.

    ``parse_constant`` is asked to return the value; raising is how it refuses, and
    the ``ValueError`` travels the same except arm as a malformed document, so no
    token is named back to the operator.
    """
    raise ValueError(f"not a JSON number: {token}")
