"""The item store's shape: the bytes ``item.py`` writes and the rules it obeys.

Mechanics, not the writer's contract: what ``noni.item/1`` looks like on disk, the
one rendering the writer emits, the id an operator may name, and the checks that
decide whether a file already at ``noni/items/<id>.json`` is an item this writer
may touch. ``item.py`` owns the verbs, the exit codes and the commit; this module
owns the form, so the census's arbiter and the writer's refusal are held to one
definition rather than two.

An item is one idea the operator filed: a candidate for the order, with the reason
it was dropped recorded rather than deleted. One file per item, one writer per file.
The canonical form is a byte contract, not a JSON one: the keys are written in the
order they are documented (never sorted), at two-space indent, with one trailing
newline. ``item.py`` refuses a file whose bytes it would render differently rather
than quietly reformatting something the operator committed.

The strict reader is not forked here. Both this writer's reads and the census's go
through the package's one strict JSON reader: a third copy of the same four
refusals is the drift the reader parity test exists to catch.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from . import ledger_schema

# The artifact: one file per item, one schema, one writer per file. The census
# reads the same directory from its --items option (default <repo>/noni/items).
ITEM_SCHEMA = "noni.item/1"
ITEM_DIR = "noni/items"

# The three states an item carries. ``candidate`` is the filed idea waiting for a
# position; ``promoted`` is one the order holds; ``dropped`` is one nobody is going
# to work, recorded rather than deleted.
STATUS_CANDIDATE = "candidate"
STATUS_PROMOTED = "promoted"
STATUS_DROPPED = "dropped"
STATUSES: tuple[str, ...] = (STATUS_CANDIDATE, STATUS_PROMOTED, STATUS_DROPPED)

# The two states with an answer: an item in one of them has been decided, and a run
# that would move it again is refused rather than allowed to rewrite that answer.
TERMINAL_STATUSES: tuple[str, ...] = (STATUS_PROMOTED, STATUS_DROPPED)

# The fields of one item, in the order they are written. ``id`` is the file's own
# name restated inside it, so a hand-made file whose contents disagree with its stem
# is a finding rather than a mystery.
ITEM_FIELDS: tuple[str, ...] = ("schema", "id", "title", "status", "created",
                                "issue", "decision", "why")

# The fields every item must carry a value for. The other three are always written
# and may be null; ``dropped`` owes two of them (see ``_dropped_problems``).
REQUIRED_FIELDS: tuple[str, ...] = ("schema", "id", "title", "status", "created")

# The longest ``why`` the writer accepts, in code points. A dropped item owes a
# reason and the reason is a sentence, not an essay: the bound is what makes a
# refusal line, a census row and a terminal listing all finite. It is compared with
# ``len`` over code points and nothing normalises the text, so an operator measuring
# a limit measures the text they see. One constant for the writer and the census: a
# second literal is how the two come to disagree about a value one side wrote.
WHY_MAX = 280

# The longest title, in code points. A title is one line of a listing, and the bound
# keeps every row of that listing finite without asking the operator to compose
# within a column width.
TITLE_MAX = 200

# An item id is what ``item.py`` builds a path from, so it is refused before any
# path is built: lowercase letters, digits and dashes, opening with a letter or a
# digit. The two suffix rules beside the regex are in :func:`is_item_id`.
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


def item_rel(item_id: str) -> str:
    """The path of one item, spelled the way the writer and the census spell it."""
    return f"{ITEM_DIR}/{item_id}.json"


def is_item_id(value: object) -> bool:
    """Whether ``value`` is an id this writer may name a file for.

    The regex half alone is not enough. ``.json`` is refused because the census
    keys an item by its file's stem, so a name carrying the suffix would be one
    item named two ways; a trailing dot is refused because the filesystem hides it
    and the stem no longer names anything. Both halves are asked here so the
    writer, the census and the shared shape table ask one question.
    """
    return (isinstance(value, str) and not value.endswith(".json")
            and not value.endswith(".") and bool(ID_RE.fullmatch(value)))


def parse_timestamp(value: object) -> datetime | None:
    """The UTC instant ``value`` names, or None when it names none.

    A bare time names no instant, so it answers None and both the writer and the
    census call the field malformed rather than judge its item stale or fresh
    against a minute nobody chose. Shared by both sides for the reason ``WHY_MAX``
    is shared: two parsers of one stamp field is two answers.
    """
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.astimezone(timezone.utc)


def id_problems(value: dict, stem: str) -> list[str]:
    """Why the ``id`` field of a parsed document does not name its own file.

    Asked separately from ``problems`` because it is answered by a different
    resource: the rest of the rules need only the bytes this run read, while this one
    needs the name the directory gave the file. Keeping them in one function would
    force every caller to hold a stem it does not use (the writer's is the one it was
    handed) and would let the census treat a mismatch as the state that stops it from
    describing the item at all. It is not: a file whose two names disagree still
    states a status, an age and citations worth checking.
    """
    if "id" not in value:
        return []
    item_id = value["id"]
    if not is_item_id(item_id):
        # ``problems`` already reported the shape; this is the same field's rule
        # against the stem, and a name that is not an id at all cannot match a stem.
        return []
    if item_id != stem:
        return [f"id {item_id!r} does not match the file name {stem}.json, so the "
                "store holds one item under two names"]
    return []


def problems(value: object) -> list[str]:
    """Why ``value`` is not an item this writer may write over, [] when it is.

    The same rules the census reports as ``item-malformed``, applied before the
    write, so a shape the arbiter would refuse is never one the verb accepted. The
    two rule sets are written twice on purpose (one reader in the writer, one in
    the arbiter) and held together by the one table in ``tests/items_shapes.py``,
    which drives both suites: a shape the writer takes and the census refuses, or
    the other way round, fails there rather than in the field.
    """
    if not isinstance(value, dict):
        return ["the file is not a JSON object"]
    found: list[str] = []
    missing = [field for field in REQUIRED_FIELDS if field not in value]
    if missing:
        found.append("missing field(s): " + ", ".join(missing))
    extra = sorted(k for k in value if k not in ITEM_FIELDS)
    if extra:
        found.append("unknown field(s): " + ", ".join(extra))
    if "schema" in value and value["schema"] != ITEM_SCHEMA:
        found.append(f"schema is {value['schema']!r}, not {ITEM_SCHEMA!r}")
    _id_problems(value, found)
    _title_problems(value, found)
    _status_problems(value, found)
    _created_problems(value, found)
    _citation_problems(value, found)
    return found


def _id_problems(value: dict, found: list[str]) -> None:
    """The id's own rule. Whether it matches its file's stem is the census's."""
    if "id" not in value:
        return
    item_id = value["id"]
    if not is_item_id(item_id):
        found.append(f"id {item_id!r} is not a lowercase id of letters, digits "
                     "and dashes")


def _title_problems(value: dict, found: list[str]) -> None:
    """A title is one non-blank line within ``TITLE_MAX`` code points."""
    if "title" not in value:
        return
    title = value["title"]
    if not ledger_schema.is_single_line(title):
        found.append("title is not a non-blank single-line string")
    elif len(title) > TITLE_MAX:
        found.append(f"title is {len(title)} characters, past the {TITLE_MAX} limit")


def _status_problems(value: dict, found: list[str]) -> None:
    """The status word, and the fields that status owes."""
    if "status" not in value:
        return
    status = value["status"]
    if status not in STATUSES:
        found.append("status " + repr(status) + " is not one of "
                     + ", ".join(STATUSES))
        return
    if status == STATUS_DROPPED:
        _dropped_problems(value, found)
    elif value.get("why") is not None:
        # ``why`` is the dropped item's reason. On any other status it states
        # something the item does not do, so it is refused rather than left to
        # read as a reason nobody dropped anything for.
        found.append("why is only carried by a dropped item")


def _dropped_problems(value: dict, found: list[str]) -> None:
    """What a dropped item owes: a decision, a reason, and no issue it became."""
    if not ledger_schema.is_non_empty_string(value.get("decision")):
        found.append("a dropped item cites no decision record")
    if not ledger_schema.is_single_line(value.get("why")):
        found.append("a dropped item carries no reason")
    elif len(value["why"]) > WHY_MAX:
        found.append(f"why is {len(value['why'])} characters, past the {WHY_MAX} limit")
    if value.get("issue") is not None:
        found.append("a dropped item still names an issue")


def _created_problems(value: dict, found: list[str]) -> None:
    """The created stamp, or the sentence saying it names no instant."""
    if "created" not in value:
        return
    if parse_timestamp(value["created"]) is None:
        found.append(f"created {value['created']!r} is not a UTC timestamp")


def _citation_problems(value: dict, found: list[str]) -> None:
    """The issue an item became, when it carries one."""
    if "issue" not in value or value["issue"] is None:
        return
    issue = value["issue"]
    if not isinstance(issue, int) or isinstance(issue, bool) or issue < 1:
        found.append(f"issue {issue!r} is not a positive integer")


def item_bytes(body: dict) -> bytes:
    """The exact bytes the writer writes for ``body``.

    Keys in the documented order (never sorted), two-space indent, one trailing
    newline. ``allow_nan=False`` is the whole refusal of a non-finite number.
    """
    document = {field: body[field] for field in ITEM_FIELDS if field in body}
    text = json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    return text.encode("utf-8")


def body_of(value: dict) -> dict:
    """The item mapping a parsed file holds, in canonical key order."""
    return {field: value[field] for field in ITEM_FIELDS if field in value}


def entry(item_id: str, title: str, status: str, created: str,
          issue: int | None = None, decision: str | None = None,
          why: str | None = None) -> dict:
    """One item in the documented key order."""
    return {"schema": ITEM_SCHEMA, "id": item_id, "title": title, "status": status,
            "created": created, "issue": issue, "decision": decision, "why": why}
