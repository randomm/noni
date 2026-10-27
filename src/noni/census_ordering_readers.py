"""The ordering group's reads: the artifact, the ``--issue-state`` map, the ledger.

Split from ``census_ordering.py`` so each file stays the size one responsibility
is worth: ``census_ordering.py`` owns the three classes, their rows and the
verdicts over them, and this module owns the reads those verdicts are made from.
It is loaded by path from ``census.py`` under a name of the census's own and
handed to the group at the call, so neither file puts a directory on ``sys.path``,
where a lookalike earlier on the path could be trusted as the census's checks.

Three reads, one standard:

- :func:`load_order` — ``noni/direction/order.json``, which is optional: absent
  is an answer, not a fault. Its shape rules are handed in at the call, so the
  field list keeps one owner (``census_ordering``).
- :func:`load_issue_state` — the map an adapter or the operator produced, whose
  keys must be the issue numbers the closed check looks up.
- :func:`ledger_records` — the decision records under ``noni/decisions/``, with
  an honest account of what this run could and could not look at.

Every one of them parses through a strict reader handed in at the call — the
census passes its own ``census_json.load_json_strict`` — so what this arbiter can
read is exactly what ``order.py`` can write, and an artifact the writer refuses
is never one the census calls clean under the classes the operator gates on. The
reader is an argument rather than an import for the same reason the path
classifier and the message bounder are: a bare-name import would let any module
named ``census_json`` earlier on ``sys.path`` be trusted as the census's strict
reader.

Nothing here prints, exits, or builds a row: each answer travels back as a value
and the caller turns it into the row its own class owns. The census's path
classifier and message bounder arrive as arguments for the same reason — this
module never redefines what a readable path or a bounded foreign message means.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, NamedTuple

# A decision record id is what decide.py writes: <YYYY-MM-DD>-<slug> of
# lowercase letters, digits and dashes. The same shape the writer refuses a
# name outside of, so a name that could escape the ledger directory is refused
# here too, before a path is built from it.
RECORD_ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*")

# The offset a stamp must carry to name an instant: a trailing Z, or a +hh:mm
# (or +hh, or +hhmm) at the end of the string. Checked on the text rather than
# on the parsed datetime because the census's own _parse_iso assumes UTC for a
# bare time — tzinfo is None is exactly the case this rule refuses, and the
# reader that would have answered it cannot be the one asked.
_ZONE_RE = re.compile(r"(?:[Zz]|[+-]\d{2}(?::?\d{2})?)$")


def names_zone(stamp: str) -> bool:
    """Whether the ISO-8601 text ``stamp`` states its offset from UTC.

    ``2026-10-26T00:00:00`` names no instant; ``...Z`` and ``...+02:00`` do. The
    writer's ``orderschema.parse_confirmed`` refuses the first, and this is the
    census's half of the same rule: a committed artifact this arbiter reads as a
    time while its writer calls it malformed is an artifact nobody can repair,
    because the only command that touches it refuses to.
    """
    return bool(_ZONE_RE.search(stamp))


def is_canonical_issue(key: object) -> bool:
    """Whether ``key`` is the canonical ASCII decimal spelling of a positive issue.

    ``isdigit`` alone admits ``"\u0660"``-style digits and would let ``"007"``
    through; the round trip through ``int`` is the rest of the rule, and it is what
    makes a key the same string the closed check builds from the entry's own
    issue. A padded or signed key can never match an entry, so accepting one
    would turn an issue the file does name into a silent cannot-tell row.

    ``isascii`` is not decoration: ``isdigit`` is True for a superscript or an
    Arabic-Indic digit, and ``int`` refuses both, so a key of ``"\u00b2"`` used to
    reach ``int`` and raise out of the census. The digits are accepted only where
    the two predicates agree, and ``int`` is never asked about a character it
    would refuse.
    """
    return (isinstance(key, str) and key.isascii() and key.isdecimal()
            and str(int(key)) == key and int(key) >= 1)


def load_order(order: Path, file_kind, bounded, parse_iso, shape: Callable[[object], list[str]],
               load_json: Callable[[bytes], object], clipped: Callable[[str], str]
               ) -> tuple[list[dict] | None, str | None]:
    """The order's entries, or (None, the reason it is not an order).

    Absent is not a problem: the ordering layer is optional, so no file means no
    ordering rows at all (contrast the ledger, whose absence is its own warn
    class). Anything else at the path that the census cannot read — a symlink it
    will not follow, a directory, unparseable bytes, a non-finite number, a
    repeated key, a nesting too deep to parse, a wrong schema — is the
    ``ordering-malformed`` finding, because the artifact is there and is not the
    artifact.

    ``shape`` is the artifact's rules, applied to the parsed value: they live with
    the classes that report them, and a copy here would be a second contract for
    one field list. ``load_json`` is the census's strict reader, handed in rather
    than imported so this module never trusts a bare name off ``sys.path``.
    ``clipped`` is the census's own length rule, applied to the problems once they
    are one sentence: each quotes a value read from the file, and the readers
    module carries no bound of its own any more than it carries a reader.
    """
    kind, problem = file_kind(order)
    if kind == "absent":
        return [], None
    if kind != "regular":
        return None, f"the order file is not a readable regular file: {problem}"
    try:
        raw = order.read_bytes()
    except OSError as e:
        return None, f"the order file is unreadable: {bounded(str(e))}"
    try:
        value = load_json(raw)
    except UnicodeDecodeError:
        # The exception text carries the offending bytes, which are untrusted
        # file content; the fixed wording names the class without echoing them.
        return None, "the order file is not valid UTF-8"
    except (json.JSONDecodeError, ValueError, RecursionError):
        # ValueError is the non-finite, duplicate-key or over-deep refusal, and
        # its text names content read from the file, so the wording is fixed.
        # RecursionError is named because it is no kind of ValueError. The strict
        # reader bounds the depth, so a document between the bound and the
        # interpreter's own ceiling is refused with a ValueError; past that ceiling
        # the decoder raises first (on 3.11 that ceiling sits just under the
        # recursion limit, about 990 levels at the default 1000, where later
        # builds reach roughly 10k and beyond). The arm is therefore reachable, not
        # decorative: without it the run would die on this line rather than answer
        # with the row the artifact already earns.
        return None, "the order file is not valid JSON"
    problems = shape(value)
    if problems:
        # The joined problems quote values read out of the file (an entry's issue,
        # decision or unknown key names), so the finished sentence is clipped: the
        # bound every other row of the report keeps is a property of the row, not
        # of one fragment inside it. ``clipped`` and not ``bounded`` because the
        # shape's own wording names root-relative paths the row must keep.
        return None, clipped("; ".join(problems))
    return list(value["entries"]), None


class IssueState(NamedTuple):
    """What --issue-state handed over.

    Three states, because the census treats them differently: ``given`` False
    (the flag was not passed) means the closed question is not asked at all; a
    ``problem`` means the file that was named does not answer, which is an
    ``ordering-malformed`` finding; a ``map`` answers for the issues it names and
    stays silent on the rest (which becomes a cannot-tell row).
    """
    map: dict[str, str] | None
    problem: str | None
    given: bool


def load_issue_state(path: Path | None, states: tuple[str, ...], file_kind, bounded,
                     load_json: Callable[[bytes], object]) -> IssueState:
    """The ``--issue-state`` map (issue -> open|closed), with its state.

    A file the operator or an adapter produced that does not parse, or whose
    values are not the two states it may name, is reported as
    ``ordering-malformed`` by the caller: a typo in the state file must stop the
    closed check from reading "no row" as "nothing is closed".

    The bytes go through the strict reader the artifact gets, so a map that
    names one issue twice is refused rather than answered twice over: the last
    line is not the file's answer when the file also states the opposite one.

    Every problem this function returns is the whole composed message passed
    through ``bounded``: the row's text is built from keys and state words read
    out of a file somebody else wrote, so the bound is applied to the finished
    sentence and not only to the path inside it.
    """
    if path is None:
        return IssueState(None, None, False)
    name = bounded(str(path))
    kind, problem = file_kind(path)
    if kind != "regular":
        return IssueState(None, bounded(f"the --issue-state file ({name}) is not a "
                                        f"readable regular file: {problem}"), True)
    try:
        raw = path.read_bytes()
    except OSError as e:
        return IssueState(None, bounded(f"the --issue-state file ({name}) is "
                                        f"unreadable: {bounded(str(e))}"), True)
    try:
        value = load_json(raw)
    except UnicodeDecodeError:
        # As for the artifact: the text carries untrusted bytes, so the row names
        # the class instead of echoing them.
        return IssueState(None, bounded(f"the --issue-state file ({name}) is not "
                                        "valid UTF-8"), True)
    except (json.JSONDecodeError, ValueError, RecursionError):
        # A duplicate key, a non-finite literal or an over-deep nesting raises
        # ValueError; its text names content read from the file, so the wording
        # is fixed. RecursionError is named for the same reason as in load_order:
        # it is not a ValueError, and past the interpreter's own ceiling (on 3.11
        # about 990 levels at the default recursion limit of 1000) the standard
        # decoder raises it before this product's bound is consulted.
        return IssueState(None, bounded(f"the --issue-state file ({name}) is not "
                                        "valid JSON"), True)
    if not isinstance(value, dict):
        return IssueState(None, bounded(f"the --issue-state file ({name}) is not a "
                                        "JSON object mapping issue numbers to open or "
                                        "closed"), True)
    state: dict[str, str] = {}
    bad: list[str] = []
    for key, item in value.items():
        if not is_canonical_issue(key):
            bad.append(f"key {key!r} is not an issue number")
            continue
        if item not in states:
            bad.append(f"issue {key} state {item!r} is not "
                       + " or ".join(repr(word) for word in states))
            continue
        state[key] = item
    if bad:
        return IssueState(None, bounded(f"the --issue-state file ({name}) is "
                                        "malformed: " + "; ".join(sorted(bad)[:4])), True)
    return IssueState(state, None, True)


def ledger_records(ledger: Path, file_kind, load_json: Callable[[bytes], object]
                   ) -> tuple[dict[str, dict], bool, set[str], bool, str | None]:
    """The records the ledger holds, keyed by filename stem, plus three answers
    about the read: whether any lookup could be made, which names could not be
    read, whether the listing ran at all, and why it faulted if it did.

    An entry's ``decision`` cites a record by the stem of
    ``noni/decisions/<id>.json`` — the path decide.py names its records by, and
    the census's own chain analysis keys the chain on the ``id`` field that
    writer puts in that file. The two agree by construction in every record the
    writer produced, so the stem is what 'matches a file in the ledger' means
    here; a record whose body disagrees with its name is the ledger's own
    ``ledger-record`` / ``ledger-chain`` finding, not an ordering one.

    The body is kept because the closed question needs its ``status`` and its
    ``supersedes``: an ordering that cites a record the chain has moved past is
    an ordering nobody voted for any more, which is the reasoning order.py
    applies before it writes, and the two halves must answer alike.

    Two kinds of unreadable answer, because the caller treats them differently:
    a record that does not *parse* is left out of the map — it is not a record,
    and the ledger's own ``ledger-record`` class owns reporting it — while a
    record that exists but cannot be *read* (permissions, a symlink, a device, an
    I/O fault) is recorded in the third element. The distinction is the census's
    half of what ``order.py`` already distinguishes: "no such record" is a defect
    of the order, "I could not read it" is a fault of this tree, and a row that
    calls the second the first is not honest about what this run observed.

    The second element says whether a lookup could be made at all — a ledger that
    answered nothing must not have every entry's decision reported as matching no
    file — and the fourth then carries the OSError's own text, because a row that
    says only "could not be listed" sends the operator to look for a missing
    directory when the tree answered with a fault. ``ledger-empty`` in the ledger
    group words its listing fault the same way for the same reason.

    The third element separates the two ways nothing was looked up, because the
    caller reports them differently: ``listed`` False means the listing never ran
    (the path is absent or is not a directory — a state of the tree the ledger
    group's own ``ledger-empty`` row owns, so ordering adds nothing) and True with
    a fault text means the listing ran and faulted, a fault of this run's read
    that no other class of the run sees.
    """
    kind, _problem = file_kind(ledger, kind="dir")
    if kind != "regular":
        # An absent ledger is a readable answer ('no records'), not a fault, and
        # a path that is not a directory is a state of the tree: in neither case
        # did this run attempt a read worth reporting. Ordering does not
        # re-report what ledger-empty already owns.
        return {}, kind == "absent", set(), False, None
    try:
        paths = sorted(ledger.glob("*.json"))
    except OSError as e:
        # Bounded wording only: the text is an exception from this tree, and a
        # census row never prints a machine-local absolute path.
        return {}, False, set(), True, f"{e.__class__.__name__}: {e.strerror or e}"
    records: dict[str, dict] = {}
    unreadable: set[str] = set()
    for candidate in paths:
        stem = candidate.name[: -len(".json")]
        fkind, _fproblem = file_kind(candidate)
        if fkind != "regular":
            # Exists but is not something this run may read: never read through
            # a link, never treated as absent.
            unreadable.add(stem)
            continue
        try:
            raw = candidate.read_bytes()
        except OSError:
            unreadable.add(stem)
            continue
        try:
            value = load_json(raw)
        except (UnicodeDecodeError, ValueError, RecursionError, json.JSONDecodeError):
            # A record that does not parse is no record: the ledger group owns
            # reporting it, so it is left out of the map. RecursionError is named
            # because it is not a ValueError: this reader bounds its depth, so a
            # document short of the interpreter's own ceiling is a ValueError, but
            # past it the decoder raises first (on 3.11 that ceiling is about 990
            # levels at the default recursion limit). A reader without the arm would
            # end the whole run here instead of skipping one file.
            continue
        if isinstance(value, dict):
            records[stem] = value
    return records, True, unreadable, True, None


def decision_problem(stem: str, records: dict[str, dict],
                     unreadable: set[str] | frozenset[str],
                     record_statuses: tuple[str, ...], status_superseded: str,
                     ) -> str | None:
    """Why an entry may not cite the record ``stem``, or None when it may.

    Four answers, in the order the writer gives them: the record is there but
    this run could not read it, no file with that name, a status the ledger's own
    vocabulary does not hold, and a record the chain has moved past. The last
    names the successor, because the reader's next action is to cite that one
    instead — the same hint order.py prints when it refuses the same citation
    before writing.

    ``unreadable`` is the stems the listing found but could not read: answered
    first and separately, because "could not be read" is an environment fault
    with an environment's fix, not a defect in the order. ``order.py`` says the
    same thing with exit 3; a census row that called it a malformed order would
    send the operator to repair a file that is fine.

    The status vocabulary is handed in rather than written here: it is the
    ledger's, and the group that reports the answer owns what its words mean.
    """
    if stem in unreadable:
        return (f"decision {stem!r} is a record file this run could not read: the ledger "
                "holds it, but it is not a readable regular file, so whether the citation "
                "stands cannot be answered")
    if stem not in records:
        return f"decision {stem!r} matches no record file in the ledger"
    record = records[stem]
    status = record.get("status")
    if status not in record_statuses:
        return (f"decision {stem!r} carries status {status!r}, not one of "
                + ", ".join(record_statuses))
    if status != status_superseded:
        return None
    successors = sorted(rid for rid, other in records.items()
                        if other.get("supersedes") == stem
                        and other.get("status") != status_superseded
                        and isinstance(rid, str) and RECORD_ID_RE.fullmatch(rid))
    if successors:
        return (f"decision {stem!r} is {status_superseded} by {successors[-1]}, so its "
                "order no longer stands")
    return f"decision {stem!r} is {status_superseded}, so its order no longer stands"
