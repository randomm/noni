"""The artifact's shape: the bytes ``order.py`` writes and the rules it obeys.

Mechanics, not the writer's contract: what an order looks like on disk, the one
rendering the writer emits for each schema version, and the checks that decide
whether a file already at the path is an order this writer may extend.
``order.py`` owns the verbs, the exit codes and the commit; this module owns the
form, so the census's arbiter and the writer's refusal are held to one definition
rather than two.

Two versions are read, one is written. ``noni.order/1`` is the artifact every
order written before items existed holds: each entry names an issue. ``noni.order/2``
gives an entry a second way to name what it holds -- ``item``, the id of a file in
the item store -- because an idea that has not become an issue yet is still work the
operator wants next. The writer emits ``/2`` for the one run that has an item entry
to write and ``/1`` for every run over an order that holds none, so a queue of
issues is never restamped into a version its contents do not need. The reader and
the arbiter accept both.

The canonical form is a byte contract, not a JSON one: the artifact is a small
operator file that is read and hand-edited, so its keys are written in the order
they are documented (never sorted), at two-space indent, with one trailing
newline. ``order.py`` refuses a file whose bytes it would render differently
rather than quietly reformatting something the operator committed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone


def _why():
    """The rationale rule module, reached the way this module itself is reached.

    Both routes this file is loaded by have to work, and a relative import at the top
    is an ``ImportError`` for the bare one, so every neighbour here is resolved on first
    use; see :func:`_reader`, whose shape this copies.
    """
    try:
        from . import _why as module
        return module
    except ImportError:  # no package: the rule sits beside this file on disk
        import importlib.util
        from pathlib import Path

        source = Path(__file__).with_name("_why.py")
        spec = importlib.util.spec_from_file_location("_why", source)
        if spec is None or spec.loader is None:  # pragma: no cover - fixed path
            raise RuntimeError(f"cannot load the rationale rule at {source}") from None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


# One module object, remembered, the way :func:`_reader` remembers its reader.
_WHY: object = None


def _why_rule():
    """The remembered :func:`_why` module."""
    global _WHY
    if _WHY is None:
        globals()["_WHY"] = _why()
    return _WHY


# The rationale's key, from the module that states its rule, so the artifact's field
# list, the record's field list and every refusal name one field.
WHY_FIELD = _why_rule().WHY_FIELD

# The item store's own rules, written out rather than imported. The reason is the one
# this module has always had for spelling its constants here instead of taking them from
# somewhere else (see ``ORDER_SCHEMA`` and the field lists): the test harness loads this
# file by path into a module with no package, so a relative import of ``itemschema``
# would be an ``ImportError`` for every consumer that reaches the artifact's shape that
# way. What the duplication costs is held down by the shared shape table
# (``tests/ordering_shapes.py``), which asserts the same id grammar against
# ``itemschema.ID_RE`` from the other side, so a rule changed in one place and not the
# other fails a test rather than shipping.
_ITEM_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}")
_ITEM_ID_MAX = 80


def _is_item_id(value: object) -> bool:
    """Whether ``value`` is the id shape :mod:`noni.itemschema` defines.

    The whole item side of validation, spelled once: the id grammar, the length bound
    and the two suffix rules that keep one item named one way. This is the store's
    ``itemschema.is_item_id`` read from the other side, held to it by the shared shape
    table; a number, a boolean or any other type is not an id.
    """
    return (isinstance(value, str) and len(value) <= _ITEM_ID_MAX
            and not value.endswith(".json") and not value.endswith(".")
            and _ITEM_ID_RE.fullmatch(value) is not None)

# The artifact: one file, one writer, two schema versions. The census reads the
# same path from its --ordering option (default <repo>/noni/direction/order.json).
# ``ORDER_SCHEMA`` is what a run writes when nothing it plans cites an item, so
# the constant still names the version of a queue of issues; the version a body is
# rendered under is decided per body by :func:`schema_for`.
ORDER_SCHEMA = "noni.order/1"
# The version whose entries may cite an item instead of an issue. An order is
# written under it only when one of its entries actually carries ``item``.
ORDER_SCHEMA_V2 = "noni.order/2"
# Both versions a reader accepts. A file whose ``schema`` names nothing here is a
# defect the whole document shares, reported by :func:`problems` on both sides of
# the writer/arbiter split.
ORDER_SCHEMAS: tuple[str, ...] = (ORDER_SCHEMA, ORDER_SCHEMA_V2)
ORDER_DIR = "noni/direction"
ORDER_FILE = "order.json"
ORDER_REL = f"{ORDER_DIR}/{ORDER_FILE}"

# The fields of one entry, in the order they are written. Position in the
# entries list is the order; it is not a field. ``why`` is the operator's one line
# of reason for the position, written by ``order.py add --why`` and optional: an entry
# without it is the three-field shape every order written before it holds, byte for
# byte. Its shape and its bound are the ledger's (``ledger_schema.why_problems``), the
# same rule a record's rationale obeys.
ENTRY_FIELDS = ("issue", "decision", "confirmed", WHY_FIELD)
# The same fields for a ``/2`` entry, with ``item`` stated where it is written:
# first when the entry cites an item, in place of ``issue``, and never beside it.
# The tuple is the documented key order, which is also the byte order the
# canonical form keeps, so this line and :func:`order_bytes` are one contract.
ENTRY_FIELDS_V2 = ("item", "issue", "decision", "confirmed", WHY_FIELD)

# The key that gives an entry its item citation, named here so the arbiter, the item
# store's census group and this writer all name one field.
ITEM_FIELD = "item"

# The order block as it is printed: position right-aligned in three columns, so
# a 400-entry order stays one readable column.
POSITION_WIDTH = 3

def entry_issue(entry: object) -> object:
    """The issue ``entry`` names, or ``None`` when it names none.

    One reader of the field for the whole family: a ``/2`` entry may carry no ``issue``
    at all, so asking through here makes "names no issue" a value a caller can branch
    on rather than a ``KeyError``.
    """
    if not isinstance(entry, dict):
        return None
    issue = entry.get("issue")
    if isinstance(issue, bool) or not isinstance(issue, int):
        return None
    return issue


def entry_item(entry: object) -> object:
    """The item id ``entry`` cites, or ``None`` when it cites none.

    The counterpart of :func:`entry_issue` for the ``/2`` field: an entry that
    names an item is identified by that id, and one that names neither is answered
    ``None`` rather than raising.
    """
    if not isinstance(entry, dict):
        return None
    cited = entry.get(ITEM_FIELD)
    return cited if isinstance(cited, str) else None


def has_item_entry(entries_or_body: object) -> bool:
    """Whether any entry carries the ``item`` field.

    The question that decides which version a run writes: one item entry makes a
    ``/2`` document, so a reorder of a queue of issues never restamps the file's
    version. Accepts the entries list or the whole body, which is what the writer and
    the renderer each hand it.
    """
    entries = (entries_or_body.get("entries")
               if isinstance(entries_or_body, dict) else entries_or_body)
    if not isinstance(entries, list):
        return False
    return any(isinstance(entry, dict) and ITEM_FIELD in entry for entry in entries)


def listed_issues(entries: object) -> set:
    """The issues ``entries`` already hold, so an add can refuse a second position.

    Read through :func:`entry_issue`, so a ``/2`` entry that names an item rather than
    an issue contributes nothing rather than a ``KeyError``, and a bool or a string in
    the field is not an issue either.
    """
    if not isinstance(entries, list):
        return set()
    return {issue for issue in map(entry_issue, entries) if issue is not None}


def schema_for(body: dict) -> str:
    """The schema version these entries are the canonical bytes of.

    ``/2`` when an entry cites an item, ``/1`` otherwise. One rule for the writer,
    the reader's canonical comparison and the arbiter, so a file the writer emits
    is always the file the reader re-renders byte for byte.
    """
    return ORDER_SCHEMA_V2 if has_item_entry(body) else ORDER_SCHEMA


def entry_fields(schema: object) -> tuple[str, ...]:
    """The documented fields of one entry of ``schema``, in the order they are written.

    The single place the two versions' field lists are stated, read by the shape
    checks and the renderer alike: a field added to one and not the other is an
    artifact whose own writer calls it malformed.
    """
    return ENTRY_FIELDS_V2 if schema == ORDER_SCHEMA_V2 else ENTRY_FIELDS


def order_bytes(body: dict) -> bytes:
    """The exact bytes the writer writes for ``body``.

    Keys in the documented order (never sorted), two-space indent, one trailing
    newline. ``allow_nan=False`` is the whole refusal of a non-finite number.

    The version is the body's own ``schema``, and each entry is projected through
    the fields that version documents -- ``item`` where it holds it, in place of
    ``issue``, and the optional ``why`` last when the entry carries one. A projection
    named from a constant rather than the entry's own keys is what makes the canonical
    comparison mean something: a renderer that handed back the file's keys verbatim
    would certify any bytes, and a renderer that dropped a documented field on the way
    out (``item``, or ``why``) would make every canonical file carrying it a permanent
    refusal, since no verb could rewrite what it cannot re-render.
    """
    schema = body.get("schema")
    fields = entry_fields(schema)
    # The projection is the whole point of the renderer: a document's bytes are its
    # version's documented keys and nothing else, so a ``/2`` entry written by hand with
    # both subjects, or with a key the version never declared, cannot be rendered and is
    # refused as non-canonical rather than quietly reformatted. Dropping the unknown key
    # on the way out would let the canonical comparison certify bytes the reader itself
    # had just changed.
    entries = [{field: e[field] for field in fields if field in e}
               for e in body["entries"]]
    text = json.dumps({"schema": schema or ORDER_SCHEMA, "entries": entries},
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
    if "schema" in value and value["schema"] not in ORDER_SCHEMAS:
        found.append("schema is " + repr(value["schema"]) + ", not "
                     + " or ".join(repr(name) for name in ORDER_SCHEMAS))
    if "entries" not in value:
        # The document's own fields are the whole answer: there is nothing to
        # check inside a list the file does not have.
        return found
    _entry_problems(value["entries"], found, value.get("schema"))
    return found


def _entry_problems(entries: object, found: list[str],
                    schema: object = ORDER_SCHEMA) -> None:
    """Append why ``entries`` is not a list of well-formed entries to ``found``.

    Split from :func:`problems` so each half reads as one rule set: the
    document's own fields, then the entries' fields. A duplicate ``issue`` is
    reported once per repeat, and a non-integer is not also counted as a
    duplicate, because a caller who fixes the type gets a second answer rather
    than a surprise. An item id is held to the same uniqueness: an order that
    cited one idea twice would hold two positions nobody chose.

    ``schema`` picks the field list, so the rules of the version a file states are
    the rules it is answered by -- which is what keeps a ``/2`` file holding an
    ``item`` clean here and clean for the arbiter, and keeps an ``item`` entry
    inside a ``/1`` document an unknown field, which is what it is.
    """
    if not isinstance(entries, list):
        found.append("entries is not an array")
        return
    fields = entry_fields(schema)
    seen: set[int] = set()
    seen_items: set[str] = set()
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            found.append(f"entry {index} is not an object")
            continue
        # The entry's own fields, chosen by the field it carries rather than by the
        # document's marker alone: a ``/2`` entry cites an idea and owes ``item``, and one
        # that names an issue owes ``issue``. Asking the whole ``/2`` list for both keys
        # would refuse the very shape the version exists to allow.
        required = _entry_required(entry, fields, schema)
        gap = [field for field in required if field not in entry]
        if gap:
            found.append(f"entry {index} is missing field(s): " + ", ".join(gap))
        junk = sorted(k for k in entry if k not in fields)
        if junk:
            found.append(f"entry {index} has unknown field(s): " + ", ".join(junk))
        _entry_subject_problems(index, entry, schema, found)
        _entry_field_problems(index, entry, found)
        issue = entry.get("issue")
        if isinstance(issue, int):
            if issue in seen:
                found.append(f"issue {issue} appears more than once")
            seen.add(issue)
        cited = entry.get(ITEM_FIELD)
        if isinstance(cited, str):
            if cited in seen_items:
                found.append(f"item {cited} appears more than once")
            seen_items.add(cited)


def _entry_required(entry: dict, fields: tuple[str, ...],
                     schema: object) -> tuple[str, ...]:
    """The fields one entry of ``schema`` owes, given the subject it names.

    ``decision`` and ``confirmed`` every entry carries; the subject is the one field the
    entry itself chooses, and ``why`` is the one field no entry owes. Under ``/1`` the
    subject is always ``issue``, so the ``item`` a ``/1`` entry carries is left out of the
    required list and the unknown-field rule names it -- the honest description of a key
    the document's own version never declared.
    """
    owed = tuple(field for field in fields if field != WHY_FIELD)
    if schema != ORDER_SCHEMA_V2:
        return owed
    if ITEM_FIELD in entry:
        return tuple(f for f in owed if f != "issue")
    return tuple(f for f in owed if f != ITEM_FIELD)


def _entry_subject_problems(index: int, entry: dict, schema: object,
                           found: list[str]) -> None:
    """The rule an entry's subject obeys, appended to ``found``.

    Exactly one of ``issue`` and ``item``: an order cannot say what an entry holds
    twice over, and it cannot say nothing. The two shapes are refused with the one
    sentence because they are the one mistake -- an entry whose subject is not the
    one its version allows. A ``/1`` entry carrying ``item`` is reported by the
    unknown-field rule of :func:`_entry_problems` above, which is the honest name
    for a field the document's own version never declared, so nothing is reported
    twice here.
    """
    if schema != ORDER_SCHEMA_V2:
        return
    carries_issue = "issue" in entry
    carries_item = ITEM_FIELD in entry
    if carries_issue == carries_item:
        found.append(f"entry {index} names {ITEM_FIELD} and issue: an entry names "
                     "exactly one of them")


def _entry_field_problems(index: int, entry: dict, found: list[str]) -> None:
    """The per-field rules of one entry, appended to ``found``."""
    if WHY_FIELD in entry:
        # The ledger's rationale rule, asked through the module that states it, so one
        # line of reason is one line wherever it is written. The arbiter keeps its own
        # copy (``census_ordering._why_problems``) for the reason its field lists are
        # copies, and the shared shape table holds the two to one answer.
        found.extend(f"entry {index} {problem}"
                     for problem in _why_rule().why_problems(entry))
    if ITEM_FIELD in entry:
        cited = entry[ITEM_FIELD]
        if not _is_item_id(cited):
            # An id outside the store's rule can never name a file under
            # noni/items/, so it is refused before any path is built from the token.
            found.append(f"entry {index} {ITEM_FIELD} {cited!r} is not an item id")
    if "issue" in entry:
        issue = entry["issue"]
        if not isinstance(issue, int) or isinstance(issue, bool) or issue < 1:
            found.append(f"entry {index} issue {issue!r} is not a positive integer")
    if "decision" in entry:
        decision = entry["decision"]
        if not (isinstance(decision, str) and decision.strip()):
            # Every entry cites a decision, whoever placed it: a position with no
            # record behind it is an ordering nobody can look up or replay, so a
            # JSON null is refused like a blank string. A missing key is the
            # entry-gaps report above, never this one: the two sentences tell a
            # reader whether a repair is an id or a key.
            found.append(f"entry {index} decision is neither a record id nor null")
    confirmed = entry.get("confirmed")
    if "confirmed" in entry and (not isinstance(confirmed, str)
                                 or parse_confirmed(confirmed) is None):
        found.append(f"entry {index} confirmed is not a UTC timestamp")


def entry(issue: int | None = None, decision: str | None = None,
          confirmed: str = "", item: str | None = None,
          why: str | None = None) -> dict:
    """One entry in the documented key order.

    Two subjects, never both: an entry names the issue it is or the item it cites.
    ``item`` comes first because an item entry writes that key where an issue entry
    writes ``issue``. ``why`` is written last and only when the caller was given a
    reason, so an entry built without one renders the bytes the artifact held before
    the field existed -- the promise the record's optional fields keep. The shape rules
    refuse a document carrying both subjects or neither.
    """
    subject = {ITEM_FIELD: item} if item is not None else {"issue": issue}
    body = {**subject, "decision": decision, "confirmed": confirmed}
    if why is not None:
        body[WHY_FIELD] = why
    return body


def why_problems(entry: dict) -> list[str]:
    """What one entry's ``why`` gets wrong, as problem strings naming the field.

    The artifact's name for :func:`noni._why.why_problems`: the flag refusal, the
    pre-write shape check and the arbiter ask one question of one rationale, so a value
    cannot be legal in the ledger and illegal here. No ``why`` key answers no problem.
    """
    return _why_rule().why_problems(entry)


def why_max() -> int:
    """The rationale bound, read from :data:`noni.itemschema.WHY_MAX`, the one owner."""
    return _why_rule().why_max()


_READER: object = None


def _reader():
    """The strict JSON reader, reached the way this module itself is reached.

    This file is loaded two ways and both have to work: as ``noni.orderschema`` inside
    the package, and as a bare module exec'd from its own path (the test harness does
    the latter, and the census would have to do the same if it ever asked the writer's
    questions). A relative import at the top of the file is an ``ImportError`` for the
    second route, so the reader is resolved on first use instead: the package's copy
    when there is a package to ask, and this module's own directory beside it when
    there is not.

    Resolved once and remembered, because every JSON read of a file this writer did not
    write goes through it and the answer cannot change mid-run.
    """
    global _READER
    if _READER is None:
        try:
            from . import order_json as reader
        except ImportError:  # no package: the reader sits beside this file on disk
            import importlib.util
            from pathlib import Path

            source = Path(__file__).with_name("order_json.py")
            spec = importlib.util.spec_from_file_location("order_json", source)
            if spec is None or spec.loader is None:  # pragma: no cover - fixed path
                raise RuntimeError(f"cannot load the strict reader at {source}"
                                   ) from None
            reader = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(reader)
        globals()["_READER"] = reader
    return _READER


def load_json_checked(raw: bytes, depth: int | None = None) -> object:
    """The value ``raw`` holds, refusing what this writer could never have written.

    The strict reader lives in :mod:`noni.order_json` beside the four refusals it
    applies; this is the name every reader of an artifact, an item or a decision
    record calls, so the contract has one entry point and the file that explains it
    is the file that implements it. ``depth`` defaults to the reader's own bound.
    """
    reader = _reader()
    return reader.load_json_checked(raw, reader.MAX_DEPTH if depth is None else depth)


# The strict reader's rules, re-exported under the names the writer's own tests and
# readers have always asked them by. They are re-exports of one object and not copies:
# :mod:`noni.order_json` is the file that explains why ``NaN``, an overflowed literal,
# a duplicate key and a pathological nesting are each refused, and this is the name the
# artifact's contract is looked up under. ``tests/ordering_shapes.py`` holds the
# census's parallel copies to the same rules.
MAX_DEPTH = _reader().MAX_DEPTH
holds_non_finite = _reader().holds_non_finite
refuse_constant = _reader().refuse_constant
reject_duplicate_keys = _reader().reject_duplicate_keys
