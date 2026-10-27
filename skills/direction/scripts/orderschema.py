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


def holds_non_finite(value: object) -> bool:
    """Whether ``value`` holds a float json read in that is not finite.

    ``math.isfinite`` catches the overflowed literal (json hands back ``inf``
    for ``1e400``). A bool is a bool, never a number, so an order this writer
    emits still parses.
    """
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(holds_non_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(holds_non_finite(item) for item in value)
    return False


def refuse_constant(token: str) -> float:
    """The reader's answer to ``NaN``/``Infinity``/``-Infinity``: refuse the token.

    Raising is how ``parse_constant`` refuses; the ``ValueError`` travels the
    same except arm as a malformed document, so no token is named back.
    """
    raise ValueError(f"not a JSON number: {token}")


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
