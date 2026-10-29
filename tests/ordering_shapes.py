"""The shared malformed-shape table: the shapes the census reports and the writer refuses.

``order.py`` refuses an artifact it would have to overwrite (exit 4) and the
census reports the same artifact as ``ordering-malformed`` (exit 15). The two
rule sets are written twice on purpose — one reader in the writer, one in the
arbiter — which is exactly how they drift: a shape one side accepts and the
other refuses is a file nobody notices has rotted, because the writer will not
touch it and the census says nothing.

So the table lives here and both suites read it:
``tests/test_order_writer.py`` drives every shape through the writer and the
census, and ``tests/test_census_ordering.py`` drives every shape through the
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


def entry(issue: int, decision: str | None = None, confirmed: str = FRESH) -> dict:
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
        '[{"issue": 1, "decision": null, "confirmed": "2026-10-26T00:00:00Z", "note": 1}]'),
        "unknown field"),
    "issue a string": (_entries(
        '[{"issue": "1", "decision": null, "confirmed": "2026-10-26T00:00:00Z"}]'),
        "not a positive integer"),
    "issue a bool": (_entries(
        '[{"issue": true, "decision": null, "confirmed": "2026-10-26T00:00:00Z"}]'),
        "not a positive integer"),
    "issue zero": (_entries(
        '[{"issue": 0, "decision": null, "confirmed": "2026-10-26T00:00:00Z"}]'),
        "not a positive integer"),
    "issue listed twice": (_entries(
        '[{"issue": 4, "decision": null, "confirmed": "2026-10-26T00:00:00Z"}, '
        '{"issue": 4, "decision": null, "confirmed": "2026-10-26T00:00:00Z"}]'),
        "appears more than once"),
    "decision a number": (_entries(
        '[{"issue": 1, "decision": 7, "confirmed": "2026-10-26T00:00:00Z"}]'),
        "neither a record id nor null"),
    "decision blank": (_entries(
        '[{"issue": 1, "decision": "  ", "confirmed": "2026-10-26T00:00:00Z"}]'),
        "neither a record id nor null"),
    "confirmed not a timestamp": (_entries(
        '[{"issue": 1, "decision": null, "confirmed": "yesterday"}]'),
        "not a UTC timestamp"),
    "confirmed null": (_entries(
        '[{"issue": 1, "decision": null, "confirmed": null}]'), "not a UTC timestamp"),
    # A stamp with no offset names no instant, so neither side treats it as one.
    "confirmed has no offset": (_entries(
        '[{"issue": 1, "decision": null, "confirmed": "2026-10-26T00:00:00"}]'),
        "not a UTC timestamp"),
    # The document-level JSON literals no noni writer can name.
    # A non-finite literal is refused by both readers, and the two reach that
    # answer by different routes (the census calls the whole file unparseable,
    # the writer refuses at the entry that carries it), so the row and the
    # refusal are checked for the exit code and the class, not for shared words.
    "an overflowed literal": (_entries(
        '[{"issue": 1, "decision": null, "confirmed": 1e400}]'), None),
    "a NaN in a number position": (_entries(
        '[{"issue": NaN, "decision": null, "confirmed": "2026-10-26T00:00:00Z"}]'), None),
    "an Infinity in a number position": (_entries(
        '[{"issue": 1, "decision": null, "confirmed": "2026-10-26T00:00:00Z", '
        '"n": Infinity}]'), None),
    # A repeated key is not a document either reader can answer for: last-wins
    # would let the entry carry a value no line of the file's text states. The
    # writer reaches the same verdict by its canonical-bytes comparison, which
    # no renderer emits, so both sides refuse -- by different routes again.
    # The decision given twice, every other field well-formed: last-wins reports
    # an entry that cites nothing while an earlier line of the file says it cites
    # a record, so no rule of the shape answers this document.
    "a repeated decision key": (_entries(
        '[{"issue": 3, "decision": "2026-10-01-baseline", "decision": null, '
        '"confirmed": "2026-10-26T00:00:00Z"}]'), None),
    # The issue given twice: last-wins would let the entry name 4 while an
    # earlier line of the file says 3, which no rule of the shape reports.
    "a repeated issue key": (_entries(
        '[{"issue": 3, "issue": 4, "decision": null, '
        '"confirmed": "2026-10-26T00:00:00Z"}]'), None),
    "a repeated schema key": ('{"schema": "noni.order/1", "schema": "noni.order/1", '
                              '"entries": []}', None),
    "a repeated entries key": ('{"schema": "noni.order/1", "entries": [], '
                               '"entries": []}', None),
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
