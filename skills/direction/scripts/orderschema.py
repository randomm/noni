"""The artifact's shape: the bytes ``order.py`` writes and the rules it obeys.

Mechanics, not the writer's contract: what ``noni.order/1`` looks like on disk,
the one rendering the writer emits, and the checks that decide whether a file
already at the path is an order this writer may extend. ``order.py`` owns the
verbs, the exit codes and the commit; this module owns the form, so the census's
arbiter and the writer's refusal are held to one definition rather than two.

The canonical form is a byte contract, not a JSON one: the artifact is a small
operator file that is read and hand-edited, so its keys are written in the order
they are documented (never sorted), at two-space indent, with one trailing
newline. ``order.py`` refuses a file whose bytes it would render differently
rather than quietly reformatting something the operator committed.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

# The artifact: one file, one schema, one writer. The census reads the same
# path from its --ordering option (default <repo>/noni/direction/order.json).
ORDER_SCHEMA = "noni.order/1"
ORDER_DIR = "noni/direction"
ORDER_FILE = "order.json"
ORDER_REL = f"{ORDER_DIR}/{ORDER_FILE}"

# The fields of one entry, in the order they are written. Position in the
# entries list is the order; it is not a field.
ENTRY_FIELDS = ("issue", "decision", "confirmed")

# The order block as it is printed: position right-aligned in three columns, so
# a 400-entry order stays one readable column.
POSITION_WIDTH = 3

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
    same except arm as a malformed document, so no token is named back.
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
    ``ValueError`` into its whole-file refusal or its unreadable-record fault,
    exactly as it does for ``refuse_constant``.

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


def order_bytes(body: dict) -> bytes:
    """The exact bytes the writer writes for ``body``.

    Keys in the documented order (never sorted), two-space indent, one trailing
    newline. ``allow_nan=False`` is the whole refusal of a non-finite number.
    """
    entries = [{"issue": e["issue"], "decision": e["decision"],
                "confirmed": e["confirmed"]} for e in body["entries"]]
    text = json.dumps({"schema": ORDER_SCHEMA, "entries": entries},
                      indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    return text.encode("utf-8")


def parse_confirmed(value: str) -> datetime | None:
    """The timestamp ``value`` names, or None when it is not one.

    A bare time is read as UTC; a stamp with no offset is not a timestamp this
    writer can compare against anything, so it answers None and the caller
    reports the entry as malformed.
    """
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.astimezone(timezone.utc)


def problems(value: object) -> list[str]:
    """Why ``value`` is not an order this writer may extend, [] when it is.

    The same rules the census reports as ``ordering-malformed``, applied before
    the write: an order whose entries the census would reject is refused here
    too, so a writer run never turns a half-broken artifact into a fully written
    one, and an entry list this command cannot reason about (a missing key, a
    non-integer issue, a null confirmed) is never overwritten on top of.
    """
    if not isinstance(value, dict):
        return ["the file is not a JSON object"]
    found: list[str] = []
    missing = [field for field in ("schema", "entries") if field not in value]
    if missing:
        found.append("missing field(s): " + ", ".join(missing))
    extra = sorted(k for k in value if k not in ("schema", "entries"))
    if extra:
        found.append("unknown field(s): " + ", ".join(extra))
    if "schema" in value and value["schema"] != ORDER_SCHEMA:
        found.append(f"schema is {value['schema']!r}, not {ORDER_SCHEMA!r}")
    if "entries" not in value:
        # The document's own fields are the whole answer: there is nothing to
        # check inside a list the file does not have.
        return found
    _entry_problems(value["entries"], found)
    return found


def _entry_problems(entries: object, found: list[str]) -> None:
    """Append why ``entries`` is not a list of well-formed entries to ``found``.

    Split from :func:`problems` so each half reads as one rule set: the
    document's own fields, then the entries' fields. A duplicate ``issue`` is
    reported once per repeat, and a non-integer is not also counted as a
    duplicate, because a caller who fixes the type gets a second answer rather
    than a surprise.
    """
    if not isinstance(entries, list):
        found.append("entries is not an array")
        return
    seen: set[int] = set()
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            found.append(f"entry {index} is not an object")
            continue
        gap = [field for field in ENTRY_FIELDS if field not in entry]
        if gap:
            found.append(f"entry {index} is missing field(s): " + ", ".join(gap))
        junk = sorted(k for k in entry if k not in ENTRY_FIELDS)
        if junk:
            found.append(f"entry {index} has unknown field(s): " + ", ".join(junk))
        _entry_field_problems(index, entry, found)
        issue = entry.get("issue")
        if isinstance(issue, int):
            if issue in seen:
                found.append(f"issue {issue} appears more than once")
            seen.add(issue)


def _entry_field_problems(index: int, entry: dict, found: list[str]) -> None:
    """The per-field rules of one entry, appended to ``found``."""
    if "issue" in entry:
        issue = entry["issue"]
        if not isinstance(issue, int) or isinstance(issue, bool) or issue < 1:
            found.append(f"entry {index} issue {issue!r} is not a positive integer")
    if "decision" in entry:
        decision = entry["decision"]
        if decision is not None and not (isinstance(decision, str) and decision.strip()):
            # A blank id is no id: it matches no record file, so an entry that
            # claims it is malformed rather than a decision nobody can look up.
            found.append(f"entry {index} decision is neither a record id nor null")
    confirmed = entry.get("confirmed")
    if "confirmed" in entry and (not isinstance(confirmed, str)
                                 or parse_confirmed(confirmed) is None):
        found.append(f"entry {index} confirmed is not a UTC timestamp")


def entry(issue: int, decision: str | None, confirmed: str) -> dict:
    """One entry in the documented key order."""
    return {"issue": issue, "decision": decision, "confirmed": confirmed}
