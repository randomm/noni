"""The ordering group's strict JSON read, shared by every file the group parses.

Split from ``census_ordering.py`` so each file stays the size one responsibility
is worth. This module owns one question — what bytes may be called a noni JSON
document — and the three modules that read noni JSON under the census answer it
the same way by going through here.

Four refusals, because the standard reader accepts four things no noni writer
can name:

- ``NaN``/``Infinity``/``-Infinity`` are not JSON at all and :func:`refuse_constant`
  stops them at the token.
- ``1e400`` is legal JSON whose value no writer can write back; it arrives as
  ``inf`` with no token to stop, so :func:`holds_non_finite` walks the parsed
  value for it.
- a repeated key is legal JSON text whose meaning the standard reader invents
  (last one wins), and :func:`reject_duplicate_keys` refuses it before any entry
  is examined.
- a document nested past any depth a noni writer renders is refused by the depth
  bound in :func:`load_json_strict`, which answers with a ``ValueError`` before
  the decoder is left to reach its own limit: a ``RecursionError`` is not a
  ``ValueError``, so a reader that relied on the decoder alone would crash
  the run instead of reporting the file.

Raises ``ValueError`` for all four; the caller turns that into the
whole-artifact row its own class owns, with fixed wording, because the
exception's own text names content read from an untrusted file.
"""

from __future__ import annotations

import json
import math

# The deepest nesting any noni writer renders: the artifact is two levels
# (document, entries, entry) and a decision record a few more, so a document a
# thousand levels deep is not a file this product wrote.
#
# The bound is also what makes the read safe, and the number cannot simply be
# raised. Where ``json.loads`` gives up on a nesting depends on the interpreter.
# On 3.11 it follows the interpreter's recursion limit and stops just under it
# (measured at about 990 levels under the default limit of 1000, and a little
# lower under pytest); later versions decode far deeper before the C stack itself
# gives out (measured at roughly 10k on 3.12 and 3.13, and 50k on 3.14). Two
# things follow. Between the bound and the interpreter's own ceiling, which is
# where a document larger than any writer emits but smaller than a pathological
# one lands, this bound answers first with the ValueError the callers already
# catch. Past that ceiling the decoder raises RecursionError before this walk is
# reached at all, which is why the readers name that exception in their except
# arms rather than trusting the bound alone: it is reachable on 3.11, not
# theoretical. RecursionError is not a ValueError, so a reader without that arm
# would die on one pathological document instead of reporting it.
MAX_DEPTH = 256


def refuse_constant(token: str) -> float:
    """The reader's answer to ``NaN``/``Infinity``/``-Infinity``: refuse the token.

    Raising is how ``parse_constant`` refuses; the ValueError travels the same
    except arm as a malformed document. The wording is fixed and names no token:
    the token is text read from an untrusted file, and a reader whose refusal
    quotes it hands that content to whatever turns the exception into a row.
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
    ``ValueError`` into its whole-artifact row, exactly as it does for the other
    bytes no noni writer can name.

    This is the ``object_pairs_hook`` half of what :func:`refuse_constant` is for
    ``NaN``: the literal the standard reader accepts and a noni writer never
    emits.
    """
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            # Content-free wording: the key is text read from an untrusted file,
            # and this ValueError is what the caller turns into a row.
            raise ValueError("duplicate key")
        seen.add(key)
    return dict(pairs)


def holds_non_finite(value: object) -> bool:
    """Whether ``value`` holds a float json read in that is not finite.

    The census's copy of ``orderschema.holds_non_finite``: the census reads the
    artifact, the ledger and the state file without importing the writer's
    helpers, so the walk lives with the reader that needs it. A bool is a bool,
    never a number, so an artifact every writer emits still parses.

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


def load_json_strict(raw: bytes, depth: int = MAX_DEPTH) -> object:
    """The value ``raw`` holds, refusing everything a noni writer would not emit.

    The census's own copy of the reading half of the ordering contract (the
    writer's copy is ``orderschema.refuse_constant`` plus
    ``orderschema.holds_non_finite``): the four refusals above, applied to one
    ``json.loads`` call. Without them, a JSON literal that no writer can
    name is read in as a float or a last-wins dict, the entry that carries it is
    reported by one class alone, and every other class calls the file clean.

    Decoding happens here too, so a non-UTF-8 file raises UnicodeDecodeError
    rather than reaching json with a machine's bytes still in it.

    The depth bound is the fourth refusal, and it refuses the same kind of thing:
    nothing a noni writer renders nests anywhere near it. Between the bound and
    the depth at which the interpreter's own decoder gives up (on 3.11 just under
    the recursion limit, about 990 levels at the default 1000, and far deeper on
    later versions) this bound answers first, with the ``ValueError`` the callers
    already catch rather than a ``RecursionError`` that is not a ``ValueError``.
    Past that ceiling the decoder raises first, which is why the readers still
    name ``RecursionError`` in their except arms: that arm is what turns the
    decoder's own giving up into a reported row rather than a crash. The bound's
    ``ValueError`` names the
    caller's own limit, so a pathological nesting
    is the malformed row every other unreadable shape already is, and no text from
    the file is echoed.
    """
    value = json.loads(raw.decode("utf-8"), parse_constant=refuse_constant,
                       object_pairs_hook=reject_duplicate_keys)
    if _depth_of(value, depth + 1) > depth:
        raise ValueError(f"nested deeper than {depth} levels")
    if holds_non_finite(value):
        raise ValueError("non-finite number")
    return value
