"""The artifact's strict JSON reader: the four refusals a noni writer never emits.

``json.loads`` alone answers four kinds of file no ``order.py`` run could have
written as though they were ordinary documents: a ``NaN`` or ``Infinity`` literal,
an overflowed number that decodes to ``inf`` with no token to stop, a key stated
twice (last one wins), and a document nested deep enough to make the decoder
recurse past the interpreter's limit. Each of those is refused here, so a reader
that reaches an artifact or a decision record says "not what this
product wrote" instead of inventing a document out of the file's shape.

The census holds its own copy of these rules (``noni.census_json``) for the one
reason the census has for all its copies: it is loaded by path and imports nothing
from the writer's package. ``tests/ordering_shapes.py`` is what holds the two to
one contract, so a bound changed on one side and not the other fails a test.

Nothing here prints or exits: each refusal is a ``ValueError`` whose wording names
the writer's own limit and never a token, a key or a number read from the file --
the caller is the one that prints, and the bytes it prints are not this file's to
choose.
"""

from __future__ import annotations

import json
import math

# The deepest nesting this writer reads. It renders two levels for the artifact
# (document, entries, entry) and a record a few more, so a document a thousand
# levels deep is not a file this product wrote.
#
# The bound is also what makes the two reads safe, and the number cannot simply
# be raised. Where ``json.loads`` gives up on a nesting depends on the interpreter.
# On 3.11 it follows the interpreter's recursion limit and stops just under it
# (measured at about 990 levels under the default limit of 1000, and a little
# lower under pytest); later versions decode far deeper before the C stack itself
# gives out (measured at roughly 10k on 3.12 and 3.13, and 50k on 3.14). Two
# things follow. Between the bound and the interpreter's own ceiling, where any
# document this writer could plausibly be handed lands, this bound answers first
# with the ValueError the callers already catch. Past that ceiling the decoder
# raises RecursionError before this walk is reached, which is why the readers name
# that exception in their except arms rather than trusting the bound alone: on
# 3.11 the arm is reachable, not theoretical. A reader without it would meet a
# RecursionError, which is not a ValueError and so escapes the except arms that
# catches every other malformed file: the run would die on one pathological
# document rather than refuse it.
MAX_DEPTH = 256


def holds_non_finite(value: object) -> bool:
    """Whether ``value`` holds a float json read in that is not finite.

    ``math.isfinite`` catches the overflowed literal (json hands back ``inf``
    for ``1e400``). A bool is a bool, never a number, so an order this writer
    emits still parses.

    The walk is iterative with its own stack, never recursive: a document that
    nests deeper than the interpreter's limit makes a recursive walk raise
    ``RecursionError`` inside the reader, and a reader that dies on the shape of
    a file answers nothing about it.
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


def _depth_of(value: object, cutoff: int) -> int:
    """How deep ``value`` nests, stopping at ``cutoff`` — a caller only asks 'too deep?'.

    Iterative for the same reason :func:`holds_non_finite` is: the question is
    asked of documents that may be pathological, and a recursive answer to it
    would be the crash the question exists to prevent.
    """
    deepest = 1
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if depth > deepest:
            deepest = depth
            if deepest >= cutoff:
                return deepest
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend((child, depth + 1) for child in item)
    return deepest


def refuse_constant(token: str) -> float:
    """The reader's answer to ``NaN``/``Infinity``/``-Infinity``: refuse the token.

    Raising is how ``parse_constant`` refuses; the ``ValueError`` travels the
    same except arm as a malformed document. The wording is fixed and names no
    token: the token is bytes read from a file this writer did not write, and a
    refusal that quotes it hands that content to whoever prints the refusal.
    """
    raise ValueError("not a JSON number")


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    """The object ``pairs`` describes, refusing a key stated twice.

    ``json`` answers a repeated key by keeping the last value and dropping the
    rest, which is an answer no line of the file's own text supports: an entry
    that says ``"decision": "a", "decision": null`` is not an entry that cites
    nothing, and a reader that reports it as one has invented a document. A
    duplicate key is a defect of the read the whole file shares, so the refusal
    is raised here — before any entry is examined — and the caller turns the
    ``ValueError`` into its whole-file refusal or its unreadable-record fault,
    exactly as it does for ``refuse_constant``.

    This is the ``object_pairs_hook`` half of what :func:`refuse_constant` is for
    ``NaN``: the literal the standard reader accepts and a noni writer never
    emits.
    """
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            # Content-free wording: the key is text read from a file this writer
            # did not write, and this ValueError is what the caller prints.
            raise ValueError("duplicate key")
        seen.add(key)
    return dict(pairs)


def load_json_checked(raw: bytes, depth: int = MAX_DEPTH) -> object:
    """The value ``raw`` holds, refusing what this writer could never have written.

    One call, four refusals: the three JSON literals no noni writer emits
    (``refuse_constant``, ``holds_non_finite``, ``reject_duplicate_keys``) and a
    nesting past ``depth``. Between that bound and the depth at which the
    interpreter's own decoder gives up (on 3.11 just under the recursion limit,
    about 990 levels at the default 1000, and far deeper on later versions) the
    bound answers first, raising the ``ValueError`` the callers already catch
    where the decoder would have raised a ``RecursionError`` that is not a
    ``ValueError``. Past that ceiling the decoder raises first, which is why the
    readers still name ``RecursionError`` in their except arms: that arm is what
    turns the decoder's own giving up into a refusal instead of a crash. The
    bound's ``ValueError`` names the writer's own limit, so no
    text from the file is echoed.

    Every JSON read this writer makes of a file it did not write goes through
    here: the artifact and the decision records it cites answer the same
    questions, and two readers of one contract is how they drift.
    """
    value = json.loads(raw.decode("utf-8"), parse_constant=refuse_constant,
                       object_pairs_hook=reject_duplicate_keys)
    if _depth_of(value, depth + 1) > depth:
        raise ValueError(f"nested deeper than {depth} levels")
    if holds_non_finite(value):
        raise ValueError("non-finite number")
    return value
