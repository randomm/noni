"""The shared malformed-shape table: the shapes the census reports and the writer refuses.

``order.py`` refuses an artifact it would have to overwrite (exit 4) and the
census reports the same artifact as ``ordering-malformed`` (exit 15). The two
rule sets are written twice on purpose — one reader in the writer, one in the
arbiter — which is exactly how they drift: a shape one side accepts and the
other refuses is a file nobody notices has rotted, because the writer will not
touch it and the census says nothing.

So the table lives here and both suites read it:
``tests/test_order_writer_artifact.py`` drives every shape through the writer and the
census, and ``tests/test_census_ordering_malformed.py`` drives every shape through the
census. Adding a rule to one side without the other fails here, not in the
field.

Each row carries a ``needle``: a fragment that must appear in the refusal or
the row's message. The two sides word the same defect differently, so a needle
is a word the two share rather than a full sentence.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from _harness import ORDER, REPO, _git, git_pin_date, subprocess_env

from noni.itemschema import WHY_MAX

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"
ORDER_REL = "noni/direction/order.json"
NOW = "2026-10-27T12:00:00Z"

# The three ordering checks, so a census over an artifact arbitrates the artifact
# and nothing else: the hygiene class would report the absence of a deny-list in
# a throwaway tree, and the ledger and session groups have their own tests.
ORDERING_CLASSES = ("ordering-malformed", "ordering-stale", "ordering-closed")

# A confirmed stamp inside the default 30-day window of NOW, so a shape that is
# otherwise well-formed is never also reported as stale.
FRESH = "2026-10-26T00:00:00Z"

# A live record id every shape of the table can cite: an entry must cite a
# decision (issue #97), so a shape under test needs a value that is not itself
# the defect. The census's ledger fixture holds a record of this name.
BASELINE_ID = "2026-10-01-baseline"


def entry(issue: int, decision: str = BASELINE_ID, confirmed: str = FRESH) -> dict:
    """One well-formed entry, for composing a body around the shape under test."""
    return {"issue": issue, "decision": decision, "confirmed": confirmed}


def canonical(entries: list[dict]) -> str:
    """The canonical bytes for ``entries``, written the way the writer does.

    Hand-written here rather than taken from the product's renderer: this module
    is imported by the suites that test that renderer, and a shape table that
    cannot be built without it would make every row of the table depend on the
    thing it is checking.
    """
    return json.dumps({"schema": "noni.order/1", "entries": entries}, indent=2) + "\n"


def _entries(raw_entries: str) -> str:
    """A document whose ``entries`` is the raw JSON text ``raw_entries``.

    Raw because the shapes of a malformed *document* (an entry that is a number,
    a repeated key inside an entry) cannot be spelled with a Python dict.
    """
    return '{"schema": "noni.order/1", "entries": ' + raw_entries + "}"


def _entries_v2(raw_entries: str) -> str:
    """``_entries`` at the item version, for the shapes only ``/2`` can carry.

    The version is the document's own claim about its entries' shape, so a ``/2``
    shape has to be spelled as a ``/2`` document: an ``item`` inside a ``/1`` file is
    a different defect (the unknown-field rule) and is tabled separately.
    """
    return '{"schema": "noni.order/2", "entries": ' + raw_entries + "}"


# The two fields every entry has always carried, spelled once for the ``/2`` shapes so
# a table row says what differs about the entry rather than repeating what does not.
_ENTRY_TAIL = '"decision": "2026-10-01-baseline", "confirmed": "2026-10-26T00:00:00Z"'


# The whole set both rule sets must agree on. A shape the census must report and
# the writer must refuse, with the fragment each side's answer must carry.
MALFORMED_SHAPES: dict[str, tuple[str, str]] = {
    # The document's own fields.
    "not an object": ("[]", "not a JSON object"),
    "not valid JSON": ("{not json", "not valid JSON"),
    "wrong schema": ('{"schema": "nope", "entries": []}', "noni.order/1"),
    "missing schema": ('{"entries": []}', "missing field"),
    "missing entries": ('{"schema": "noni.order/1"}', "missing field"),
    "unknown top-level field": ('{"schema": "noni.order/1", "entries": [], "x": 1}',
                                "unknown field"),
    "entries not a list": ('{"schema": "noni.order/1", "entries": 3}',
                           "entries is not an array"),
    # The entries and their fields.
    "entry not an object": (_entries("[7]"), "is not an object"),
    "entry missing fields": (_entries('[{"issue": 1}]'), "missing field"),
    "entry with an unknown field": (_entries(
        '[{"issue": 1, "decision": "2026-10-01-baseline", "confirmed": "2026-10-26T00:00:00Z", "note": 1}]'),
        "unknown field"),
    "issue a string": (_entries(
        '[{"issue": "1", "decision": "2026-10-01-baseline", "confirmed": "2026-10-26T00:00:00Z"}]'),
        "not a positive integer"),
    "issue a bool": (_entries(
        '[{"issue": true, "decision": "2026-10-01-baseline", "confirmed": "2026-10-26T00:00:00Z"}]'),
        "not a positive integer"),
    "issue zero": (_entries(
        '[{"issue": 0, "decision": "2026-10-01-baseline", "confirmed": "2026-10-26T00:00:00Z"}]'),
        "not a positive integer"),
    "issue listed twice": (_entries(
        '[{"issue": 4, "decision": "2026-10-01-baseline", "confirmed": "2026-10-26T00:00:00Z"}, '
        '{"issue": 4, "decision": "2026-10-01-baseline", "confirmed": "2026-10-26T00:00:00Z"}]'),
        "appears more than once"),
    "decision a number": (_entries(
        '[{"issue": 1, "decision": 7, "confirmed": "2026-10-26T00:00:00Z"}]'),
        "neither a record id nor null"),
    "decision blank": (_entries(
        '[{"issue": 1, "decision": "  ", "confirmed": "2026-10-26T00:00:00Z"}]'),
        "neither a record id nor null"),
    # A null decision is the state the anti-fabrication rule removed (issue #97):
    # every entry cites the record that set its position, so a JSON null earns a
    # row from the census and a refusal from every verb, each naming the entry
    # index. The absent key is the row above (``missing field``), so the two
    # sentences cannot be confused with one another.
    "decision null": (_entries(
        '[{"issue": 1, "decision": null, "confirmed": "2026-10-26T00:00:00Z"}]'),
        "decision is neither a record id nor null"),
    "decision absent": (_entries(
        '[{"issue": 1, "confirmed": "2026-10-26T00:00:00Z"}]'), "missing field"),
    "confirmed not a timestamp": (_entries(
        '[{"issue": 1, "decision": "2026-10-01-baseline", "confirmed": "yesterday"}]'),
        "not a UTC timestamp"),
    "confirmed null": (_entries(
        '[{"issue": 1, "decision": "2026-10-01-baseline", "confirmed": null}]'), "not a UTC timestamp"),
    # A stamp with no offset names no instant, so neither side treats it as one.
    "confirmed has no offset": (_entries(
        '[{"issue": 1, "decision": "2026-10-01-baseline", "confirmed": "2026-10-26T00:00:00"}]'),
        "not a UTC timestamp"),
    # The document-level JSON literals no noni writer can name.
    # A non-finite literal is refused by both readers, and the two reach that
    # answer by different routes (the census calls the whole file unparseable,
    # the writer refuses at the entry that carries it), so the row and the
    # refusal are checked for the exit code and the class, not for shared words.
    "an overflowed literal": (_entries(
        '[{"issue": 1, "decision": "2026-10-01-baseline", "confirmed": 1e400}]'), None),
    "a NaN in a number position": (_entries(
        '[{"issue": NaN, "decision": "2026-10-01-baseline", "confirmed": "2026-10-26T00:00:00Z"}]'), None),
    "an Infinity in a number position": (_entries(
        '[{"issue": 1, "decision": "2026-10-01-baseline", "confirmed": "2026-10-26T00:00:00Z", '
        '"n": Infinity}]'), None),
    # A repeated key is not a document either reader can answer for: last-wins
    # would let the entry carry a value no line of the file's text states. The
    # writer reaches the same verdict by its canonical-bytes comparison, which
    # no renderer emits, so both sides refuse -- by different routes again.
    # The decision given twice, every other field well-formed: last-wins reports
    # an entry that cites nothing while an earlier line of the file says it cites
    # a record, so no rule of the shape answers this document.
    "a repeated decision key": (_entries(
        '[{"issue": 3, "decision": "2026-10-01-baseline", "decision": "2026-10-01-baseline", '
        '"confirmed": "2026-10-26T00:00:00Z"}]'), None),
    # The issue given twice: last-wins would let the entry name 4 while an
    # earlier line of the file says 3, which no rule of the shape reports.
    "a repeated issue key": (_entries(
        '[{"issue": 3, "issue": 4, "decision": "2026-10-01-baseline", '
        '"confirmed": "2026-10-26T00:00:00Z"}]'), None),
    "a repeated schema key": ('{"schema": "noni.order/1", "schema": "noni.order/1", '
                              '"entries": []}', None),
    "a repeated entries key": ('{"schema": "noni.order/1", "entries": [], '
                               '"entries": []}', None),
    # --- the optional ``why`` a run records with ``add --why`` ----------------------
    # The rationale is the one optional field an entry may carry, so it is where the two
    # rule sets are most likely to drift: each side holds its own copy of the rule (the
    # writer asks the ledger's module, the arbiter keeps a local copy because it loads
    # by path), and a ``why`` one side refuses is an artifact the other can write and
    # nobody can repair. The good value is tabled as a clean shape below.
    "why blank": (_entries(
        '[{"issue": 1, "decision": "2026-10-01-baseline", '
        '"confirmed": "2026-10-26T00:00:00Z", "why": ""}]'), "why"),
    "why only spaces": (_entries(
        '[{"issue": 1, "decision": "2026-10-01-baseline", '
        '"confirmed": "2026-10-26T00:00:00Z", "why": "   "}]'), "why"),
    "why two lines": (_entries(
        '[{"issue": 1, "decision": "2026-10-01-baseline", '
        '"confirmed": "2026-10-26T00:00:00Z", "why": "one\\ntwo"}]'), "why"),
    "why past the bound": (_entries(
        '[{"issue": 1, "decision": "2026-10-01-baseline", '
        '"confirmed": "2026-10-26T00:00:00Z", "why": "' + "a" * (WHY_MAX + 1)
        + '"}]'), "why"),
    "why is not a string": (_entries(
        '[{"issue": 1, "decision": "2026-10-01-baseline", '
        '"confirmed": "2026-10-26T00:00:00Z", "why": 7}]'), "why"),
    "why is null": (_entries(
        '[{"issue": 1, "decision": "2026-10-01-baseline", '
        '"confirmed": "2026-10-26T00:00:00Z", "why": null}]'), "why"),
    # --- the ``noni.order/2`` entries, where an entry may cite an item ------------
    # The whole ``/2`` set is tabled here rather than only in the item suites because
    # this table is what holds the two rule sets together: a ``/2`` file the writer
    # emits and the arbiter calls malformed is the drift these rows exist to catch,
    # and it is exactly the bug a ``/2`` entry that owes *both* subjects produced.
    "item listed twice": (_entries_v2(
        '[{"item": "idea-0001", ' + _ENTRY_TAIL + '}, '
        '{"item": "idea-0001", ' + _ENTRY_TAIL + '}]'),
        "appears more than once"),
    "item names both subjects": (_entries_v2(
        '[{"item": "idea-0001", "issue": 7, ' + _ENTRY_TAIL + '}]'),
        "exactly one"),
    "item names neither subject": (_entries_v2(
        '[{' + _ENTRY_TAIL + '}]'), "exactly one"),
    "item is not an id": (_entries_v2(
        '[{"item": "Not An Id", ' + _ENTRY_TAIL + '}]'), "is not an item id"),
    "item ends in .json": (_entries_v2(
        '[{"item": "idea-0001.json", ' + _ENTRY_TAIL + '}]'), "is not an item id"),
    # The field its version never declared: the unknown-field rule, on both sides, and
    # not the subject rule -- which is what keeps "the writer emits ``/2``" the only
    # way a ``/2`` artifact ever appears.
    "item inside a v1 document": (_entries(
        '[{"item": "idea-0001", ' + _ENTRY_TAIL + '}]'), "unknown field"),
}


def _clean_shapes() -> dict[str, str]:
    """Documents both rule sets must call clean, spelled as raw JSON text.

    The other half of the agreement: a table of refusals only proves the two sides
    agree about what is wrong. These are the shapes the writer emits and the arbiter
    must never call ``ordering-malformed`` -- and the ``/2`` item entry is the shape
    whose refusal by one side alone would make every queue of ideas a permanent
    refusal, since no verb can rewrite a file it cannot re-render.
    """
    return {
        "a v2 entry that cites an item": _entries_v2(
            '[{"item": "idea-0001", ' + _ENTRY_TAIL + '}]'),
        "a v2 file that mixes an item entry and an issue entry": _entries_v2(
            '[{"item": "idea-0001", ' + _ENTRY_TAIL + '}, '
            '{"issue": 7, ' + _ENTRY_TAIL + '}]'),
        "a v2 file holding nothing": _entries_v2("[]"),
        # An entry that carries the optional rationale, at the bound and inside it: the
        # shape ``add --why`` emits, which neither side may call malformed -- a refusal
        # here would be an order no verb can rewrite.
        "an entry carrying a reason": _entries(
            '[{"issue": 1, "decision": "2026-10-01-baseline", '
            '"confirmed": "2026-10-26T00:00:00Z", "why": "the train leaves at six"}]'),
        "an entry at the rationale bound": _entries(
            '[{"issue": 1, "decision": "2026-10-01-baseline", '
            '"confirmed": "2026-10-26T00:00:00Z", "why": "' + "a" * WHY_MAX
            + '"}]'),
        "a v2 entry citing an item and carrying a reason": _entries_v2(
            '[{"item": "idea-0001", ' + _ENTRY_TAIL + ', "why": "filed, not scheduled"}]'),
    }


def issue_state_shapes() -> dict[str, tuple[str, str]]:
    """The shapes an ``--issue-state`` file may hold that neither side accepts.

    A map with a repeated key, a non-canonical key or a state word outside the
    two it may name: each is a broken input the census must report rather than
    read as 'nothing is closed', so the row is a finding and the exit is 15."""
    return {
        "an issue given twice": ('{"7": "open", "7": "closed"}', ""),
        "a zero-padded key": ('{"07": "open"}', "not an issue number"),
        "a negative key": ('{"-7": "open"}', "not an issue number"),
        "a zero key": ('{"0": "open"}', "not an issue number"),
        "an empty key": ('{"": "open"}', "not an issue number"),
        "a non-numeric key": ('{"seven": "open"}', "not an issue number"),
        "a state word it may not name": ('{"7": "perhaps"}', "not 'open' or 'closed'"),
        "a null state": ('{"7": null}', "not 'open' or 'closed'"),
    }


def commit_artifact(repo: Path, body: str) -> None:
    """Put ``body`` at the artifact path and commit it as the writer would."""
    target = repo / ORDER_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", ORDER_REL)
    git_pin_date(repo, NOW, "commit", "-q", "-m", "direction: shape")


def run_census(repo: Path, *extra: str) -> tuple[int, list[dict], str]:
    """The census over the three ordering classes: the arbiter's answer."""
    args = [sys.executable, str(CENSUS), "--repo", str(repo), "--json", "--now", NOW]
    for check in ORDERING_CLASSES:
        args += ["--only", check]
    args += list(extra)
    proc = subprocess.run(args, capture_output=True, text=True, env=subprocess_env(),
                          timeout=120)
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return proc.returncode, [r for r in rows if r.get("kind") == "finding"], \
        proc.stdout + proc.stderr


def run_writer(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """order.py over ``repo`` with the arguments given: the writer's answer."""
    cmd = [sys.executable, str(ORDER), "--repo", str(repo), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=subprocess_env(),
                          timeout=120)
    return proc


def writer_text(proc: subprocess.CompletedProcess[str]) -> str:
    """Everything a writer run said, for an assertion message."""
    return proc.stdout + proc.stderr


# The depth that overflows the standard reader. How deep a JSON document the
# interpreter will still parse depends on the interpreter: 3.11 gives up near
# ``sys.getrecursionlimit()`` (default 1000: measured to break at about 990
# levels under pytest), later builds go on to a few thousand before the C stack
# itself gives out, so the RecursionError arms are reachable on 3.11 and not
# merely theoretical. Before the bound, one such file at either path turned a
# writer run into a traceback.
DEEP = 100000


def _deep(depth: int = DEEP) -> str:
    """Legal JSON text nested ``depth`` levels: ``json.loads`` overflows on it.

    Built as text: the value it describes is the one the standard reader cannot
    build, so a fixture that parsed it first could not test the reader meant to
    survive it.
    """
    return "[" * depth + "1" + "]" * depth


def _deep_artifact(confirmed: str) -> str:
    """An otherwise well-formed artifact whose entry carries one extra field
    nested ``DEEP`` levels.

    ``confirmed`` is required and not defaulted: the writer's suite plants this
    artifact at its own ``STAMP`` and the census's suite at its own ``FRESH``,
    and a default would silently pick one side's bytes for the other.
    """
    if not isinstance(confirmed, str):
        raise TypeError("confirmed must be a timestamp string")
    return ('{"schema": "noni.order/1", "entries": [{"issue": 7, "decision": null, '
            '"confirmed": "' + confirmed + '", "x": ' + _deep() + "}]}")


# The table, spelled as a value so a suite reads the set it drives rather than
# calling a builder and wondering whether it is complete.
CLEAN_SHAPES = _clean_shapes()
