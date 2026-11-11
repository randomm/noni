"""The artifact's shape: the bytes ``order.py`` writes and the rules it obeys.

Mechanics, not the writer's contract: what an order looks like on disk, the one
rendering the writer emits, and the checks that decide
whether a file already at the path is an order this writer may extend.
``order.py`` owns the verbs, the exit codes and the commit; this module owns the
form, so the census's arbiter and the writer's refusal are held to one definition
rather than two.

One version is written and one is read. ``noni.order/1``
is the only artifact this writer writes: each entry names an issue. The item store and
its ``noni.order/2`` marker were removed, so a file that still states ``/2`` or carries
an entry with an ``item`` key is not silently rewritten down to ``/1``: every reader and
the arbiter report it with a message that says item entries are no longer supported and
tells the operator to re-add each one as an issue entry.

The canonical form is a byte contract, not a JSON one: the artifact is a small
operator file that is read and hand-edited, so its keys are written in the order
they are documented (never sorted), at two-space indent, with one trailing
newline. ``order.py`` refuses a file whose bytes it would render differently
rather than quietly reformatting something the operator committed.
"""

from __future__ import annotations

import json
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

# The one version this writer writes and the only one a reader accepts. The census
# reads the same path from its --ordering option (default
# <repo>/noni/direction/order.json).
ORDER_SCHEMA = "noni.order/1"
# The version the item store used to stamp an order with. It is kept as a name so
# both sides of the writer/arbiter split can say *why* a file carrying it is refused:
# it is a migration refusal, not a wrong-schema defect, and the sentence the operator
# reads has to name the repair. Nothing accepts it.
REMOVED_ITEM_SCHEMA = "noni.order/2"
# A file whose ``schema`` names nothing in this tuple is a defect the whole document
# shares, reported by :func:`problems` on both sides of the writer/arbiter split.
ORDER_SCHEMAS: tuple[str, ...] = (ORDER_SCHEMA,)
ORDER_DIR = "noni/direction"
ORDER_FILE = "order.json"
ORDER_REL = f"{ORDER_DIR}/{ORDER_FILE}"

# The fields of one entry, in the order they are written. Position in the
# entries list is the order; it is not a field. ``why`` is the operator's one line
# of reason for the position, written by ``order.py add --why`` and optional: an entry
# without it is the three-field shape every order written before it holds, byte for
# byte. Its shape and its bound are the ledger's (``ledger_schema.why_problems``), the
# same rule a record's rationale obeys. Each field is named by a constant of its own so
# a reader that prints one of them (the brief's row, the writer's listing) names the
# artifact's field rather than a string that outlives a rename.
DECISION_FIELD = "decision"
CONFIRMED_FIELD = "confirmed"
ENTRY_FIELDS = ("issue", DECISION_FIELD, CONFIRMED_FIELD, WHY_FIELD)

# The key the item store used to give an entry its citation, and the repair sentence
# every reader gives a file that still carries it. Named here so the writer, the
# arbiter and the census all refuse the same key with one sentence, and so the
# migration message is spelled in one place rather than three.
ITEM_FIELD = "item"
MIGRATION_HINT = ("item entries are no longer supported: re-add each one with "
                  "'order.py add ISSUE --decision ID' after filing it as an issue")

# The order block as it is printed: position right-aligned in three columns, so
# a 400-entry order stays one readable column.
POSITION_WIDTH = 3

def entry_issue(entry: object) -> object:
    """The issue ``entry`` names, or ``None`` when it names none.

    One reader of the field for the whole family, so asking through here makes
    "names no issue" a value a caller can branch on rather than a ``KeyError``.
    """
    if not isinstance(entry, dict):
        return None
    issue = entry.get("issue")
    if isinstance(issue, bool) or not isinstance(issue, int):
        return None
    return issue


def has_item_entry(entries_or_body: object) -> bool:
    """Whether any entry carries the removed ``item`` field.

    The question that decides whether a run may touch the artifact at all: one entry
    carrying the key makes the whole file a pre-removal artifact that no verb rewrites.
    Accepts the entries list or the whole body, which is what the writer and the
    renderer each hand it.
    """
    entries = (entries_or_body.get("entries")
               if isinstance(entries_or_body, dict) else entries_or_body)
    if not isinstance(entries, list):
        return False
    return any(isinstance(entry, dict) and ITEM_FIELD in entry for entry in entries)


def migration_problems(value: object) -> list[str]:
    """Why ``value`` is a pre-removal order that no verb may rewrite, [] when it is not.

    Two shapes, both answered with the one repair sentence: a document that still
    states the removed version's marker, and an entry that still carries the item key.
    Neither is read as a ``/1`` order and neither is quietly restamped -- the writer
    rebuilds the whole list on every verb, so accepting either would delete the
    operator's entry. The answer is a refusal naming the repair, and it is asked by
    the writer's reader, the writer itself and the arbiter alike.
    """
    if not isinstance(value, dict):
        return []
    found: list[str] = []
    if value.get("schema") == REMOVED_ITEM_SCHEMA:
        found.append(f"schema is {REMOVED_ITEM_SCHEMA!r}: {MIGRATION_HINT}")
    if has_item_entry(value):
        found.append(f"an entry carries {ITEM_FIELD}: {MIGRATION_HINT}")
    return found


def listed_issues(entries: object) -> set:
    """The issues ``entries`` already hold, so an add can refuse a second position.

    Read through :func:`entry_issue`, so an entry that names no issue contributes
    nothing rather than a ``KeyError``, and a bool or a string in the field is not an
    issue either.
    """
    if not isinstance(entries, list):
        return set()
    return {issue for issue in map(entry_issue, entries) if issue is not None}


def order_bytes(body: dict) -> bytes:
    """The exact bytes the writer writes for ``body``.

    Keys in the documented order (never sorted), two-space indent, one trailing
    newline. ``allow_nan=False`` is the whole refusal of a non-finite number.

    The version is the body's own ``schema``, and each entry is projected through the
    fields the artifact documents -- ``issue``, then the optional ``why`` last when the
    entry carries one. A projection named from a constant rather than the entry's own
    keys is what makes the canonical comparison mean something: a renderer that handed
    back the file's keys verbatim would certify any bytes, and a renderer that dropped
    a documented field on the way out (``why``) would make every canonical file
    carrying it a permanent refusal, since no verb could rewrite what it cannot
    re-render.
    """
    schema = body.get("schema")
    # The projection is the whole point of the renderer: a document's bytes are its
    # documented keys and nothing else, so an entry written by hand with a
    # key it never declared cannot be rendered and is refused as non-canonical
    # rather than quietly reformatted. Dropping the unknown key on the way out would let
    # the canonical comparison certify bytes the reader itself had just changed.
    entries = [{field: e[field] for field in ENTRY_FIELDS if field in e}
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

    The pre-removal shapes are answered first and with the migration sentence, and the
    entry pass is then skipped: an entry whose subject is the removed ``item`` key would
    otherwise be reported a second time as a missing or unknown field, which is a
    description of a defect the repair does not touch.
    """
    if not isinstance(value, dict):
        return ["the file is not a JSON object"]
    migrated = migration_problems(value)
    if migrated:
        return migrated
    found: list[str] = []
    missing = [field for field in ("schema", "entries") if field not in value]
    if missing:
        found.append("missing field(s): " + ", ".join(missing))
    extra = sorted(k for k in value if k not in ("schema", "entries"))
    if extra:
        found.append("unknown field(s): " + ", ".join(extra))
    if "schema" in value and value["schema"] not in ORDER_SCHEMAS:
        found.append("schema is " + repr(value["schema"]) + ", not "
                     + repr(ORDER_SCHEMA))
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

    Every entry is answered by the one field list the artifact documents, which is what
    keeps a file the writer emits clean here and clean for the arbiter.
    """
    if not isinstance(entries, list):
        found.append("entries is not an array")
        return
    seen: set[int] = set()
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            found.append(f"entry {index} is not an object")
            continue
        gap = [field for field in _ENTRY_OWED if field not in entry]
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


# The fields every entry owes: the subject and the two provenance fields. ``why`` is
# the one field no entry owes, so the list is spelled beside :data:`ENTRY_FIELDS` and
# not derived from it: an entry that omits the reason is the shape the artifact held
# before the field existed.
_ENTRY_OWED = ("issue", "decision", "confirmed")


def _entry_field_problems(index: int, entry: dict, found: list[str]) -> None:
    """The per-field rules of one entry, appended to ``found``."""
    if WHY_FIELD in entry:
        # The ledger's rationale rule, asked through the module that states it, so one
        # line of reason is one line wherever it is written. The arbiter keeps its own
        # copy (``census_ordering._why_problems``) for the reason its field lists are
        # copies, and the shared shape table holds the two to one answer.
        found.extend(f"entry {index} {problem}"
                     for problem in _why_rule().why_problems(entry))
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
          confirmed: str = "", why: str | None = None) -> dict:
    """One entry in the documented key order.

    One subject: an entry names the issue it is. ``why`` is written last and only when
    the caller was given a reason, so an entry built without one renders the bytes the
    artifact held before the field existed -- the promise the record's optional fields
    keep. The shape rules refuse an entry naming no subject.
    """
    body = {"issue": issue, "decision": decision, "confirmed": confirmed}
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
    """The rationale bound, read from :data:`noni._why.WHY_MAX`, the one owner."""
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
    applies; this is the name every reader of an artifact or a decision
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
