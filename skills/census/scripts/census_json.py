"""The ordering group's strict JSON read, shared by every file the group parses.

Split from ``census_ordering.py`` so each file stays the size one responsibility
is worth. This module owns one question — what bytes may be called a noni JSON
document — and the three modules that read noni JSON under the census answer it
the same way by going through here.

Three refusals, because the standard reader accepts three things no noni writer
can name:

- ``NaN``/``Infinity``/``-Infinity`` are not JSON at all and :func:`refuse_constant`
  stops them at the token.
- ``1e400`` is legal JSON whose value no writer can write back; it arrives as
  ``inf`` with no token to stop, so :func:`holds_non_finite` walks the parsed
  value for it.
- a repeated key is legal JSON text whose meaning the standard reader invents
  (last one wins), and :func:`reject_duplicate_keys` refuses it before any entry
  is examined.

Raises ``ValueError`` for all three; the caller turns that into the whole-artifact
row its own class owns, with fixed wording, because the exception's own text names
content read from an untrusted file.
"""

from __future__ import annotations

import json
import math


def refuse_constant(token: str) -> float:
    """The reader's answer to ``NaN``/``Infinity``/``-Infinity``: refuse the token.

    Raising is how ``parse_constant`` refuses; the ValueError travels the same
    except arm as a malformed document, so no token from an untrusted file is
    named back in a row.
    """
    raise ValueError(f"not a JSON number: {token}")


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
            raise ValueError(f"duplicate key: {key}")
        seen.add(key)
    return dict(pairs)


def holds_non_finite(value: object) -> bool:
    """Whether ``value`` holds a float json read in that is not finite.

    The census's copy of ``orderschema.holds_non_finite``: the census reads the
    artifact, the ledger and the state file without importing the writer's
    helpers, so the walk lives with the reader that needs it. A bool is a bool,
    never a number, so an artifact every writer emits still parses.
    """
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(holds_non_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(holds_non_finite(item) for item in value)
    return False


def load_json_strict(raw: bytes) -> object:
    """The value ``raw`` holds, refusing everything a noni writer would not emit.

    The census's own copy of the reading half of the ordering contract (the
    writer's copy is ``orderschema.refuse_constant`` plus
    ``orderschema.holds_non_finite``): the three refusals above, applied to one
    ``json.loads`` call. Without all three, a JSON literal that no writer can
    name is read in as a float or a last-wins dict, the entry that carries it is
    reported by one class alone, and every other class calls the file clean.

    Decoding happens here too, so a non-UTF-8 file raises UnicodeDecodeError
    rather than reaching json with a machine's bytes still in it.
    """
    value = json.loads(raw.decode("utf-8"), parse_constant=refuse_constant,
                       object_pairs_hook=reject_duplicate_keys)
    if holds_non_finite(value):
        raise ValueError("non-finite number")
    return value
