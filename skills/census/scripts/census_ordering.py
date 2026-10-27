"""The census's ordering group: the three classes over ``noni/direction/order.json``.

Split from ``census.py`` so each file stays the size one responsibility is
worth: ``census.py`` owns the CLI, the exit-code table, the row shape and the
group wiring, and this module owns the ordering reads and their three classes.
It is loaded by path from ``census.py`` — the census never puts a directory on
``sys.path``, where a lookalike earlier on the path could be trusted as its
ordering checks — and the two row mechanics it needs (``_row`` and
``_rel_to_root``) are handed in at the call, so the census keeps its single
owner of the row shape.

Three classes, one read of the artifact:

- ``ordering-malformed`` (fail 15): the artifact exists and is not the artifact.
- ``ordering-stale`` (warn 45): an entry nobody confirmed within the threshold.
- ``ordering-closed`` (warn 46): an entry whose issue the ``--issue-state`` map
  says is closed, plus the ``cannot-tell`` rows for the issues it does not name.

Nothing here prints or exits: every answer is appended to the caller's
``findings`` list through the ``row`` factory it supplies.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, NamedTuple

# The artifact's shape, the census's side of the contract order.py writes to.
ORDER_SCHEMA = "noni.order/1"
ORDER_REQUIRED_FIELDS = ("schema", "entries")
ORDER_ENTRY_FIELDS = ("issue", "decision", "confirmed")

# The two states an --issue-state map answers for one issue, plus the third
# state a map cannot answer at all: an issue the file does not mention. The
# words are the census's own, never a value read from the file's contents.
ISSUE_STATE_OPEN = "open"
ISSUE_STATE_CLOSED = "closed"

# The three status words a decision record may hold. A chain analysis reads
# them everywhere a verdict about 'does this record still stand' is made; the
# same words in the same set are what ordering's decision lookup answers for,
# so a hand-edited status outside this set decides nothing about an order.
RECORD_STATUSES = ("decided", "open", "superseded")
STATUS_SUPERSEDED = "superseded"

# A decision record id is what decide.py writes: <YYYY-MM-DD>-<slug> of
# lowercase letters, digits and dashes. The same shape the writer refuses a
# name outside of, so a name that could escape the ledger directory is refused
# here too, before a path is built from it.
RECORD_ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*")

# The two subjects the ordering class uses for the rows that are not about one
# entry: a whole-file malformation, and the --issue-state file that did not
# parse. Like hygiene's `deny-list` / `hygiene scan` subjects, they are the
# machine-readable discriminator between whole-artifact and per-entry rows.
ORDER_DEFAULT_SUBJECT = "noni/direction/order.json"
ISSUE_STATE_SUBJECT = "issue-state"


def _order_problems(value: object, parse_iso) -> list[str]:
    """Why ``value`` is not an order the census can read; [] when it is.

    The rules of ``noni.order/1`` as one list, so the row the class reports and
    the refusal order.py applies before writing cannot drift apart: the writer
    refuses what this census would report, which is what keeps a writer run from
    producing an artifact this arbiter calls malformed. The census reads with the
    writer's own reader (see :func:`_load_order`), so the two answer the same
    document alike, and a non-finite number is refused here as the backstop for
    a parsed value that came from anywhere but that reader.

    A blank ``decision`` is a defect, not a string: it matches no record file, so
    the census's own mirror of the writer's rule asks for more than ``isinstance(
    decision, str)`` — otherwise a hand-repaired artifact could stay clean here
    while the writer refuses to touch it.

    An empty ``entries`` list with the right schema is clean, not a finding: an
    operator who wants nothing ordered next has said so, and the census reports
    no ordering rows for it.
    """
    if not isinstance(value, dict):
        return ["the order file is not a JSON object"]
    problems: list[str] = []
    if _holds_non_finite(value):
        # The one legal number whose value no writer can name: json reads 1e400
        # into inf with no token to stop it, and an inf would reach a row's
        # wording as a float. Refused as unparseable, exactly as the writer
        # refuses it, so neither side ever treats it as a value.
        return ["the order file holds a number that is not finite"]
    missing = [f for f in ORDER_REQUIRED_FIELDS if f not in value]
    if missing:
        problems.append("missing field(s): " + ", ".join(missing))
    extra = sorted(k for k in value if k not in ORDER_REQUIRED_FIELDS)
    if extra:
        problems.append("unknown field(s): " + ", ".join(extra))
    if "schema" in value and value["schema"] != ORDER_SCHEMA:
        problems.append(f"schema is {value['schema']!r}, not {ORDER_SCHEMA!r}")
    entries = value.get("entries")
    if entries is None:
        return problems
    if not isinstance(entries, list):
        problems.append("entries is not an array")
        return problems
    seen: set[int] = set()
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            problems.append(f"entry {index} is not an object")
            continue
        gap = [f for f in ORDER_ENTRY_FIELDS if f not in entry]
        if gap:
            problems.append(f"entry {index} is missing field(s): " + ", ".join(gap))
        junk = sorted(k for k in entry if k not in ORDER_ENTRY_FIELDS)
        if junk:
            problems.append(f"entry {index} has unknown field(s): " + ", ".join(junk))
        issue = entry.get("issue")
        if "issue" in entry:
            if not isinstance(issue, int) or isinstance(issue, bool) or issue < 1:
                problems.append(f"entry {index} issue {issue!r} is not a positive integer")
            elif issue in seen:
                problems.append(f"issue {issue} appears more than once")
            else:
                seen.add(issue)
        decision = entry.get("decision")
        if "decision" in entry and decision is not None \
                and not (isinstance(decision, str) and decision.strip()):
            problems.append(f"entry {index} decision is neither a record id nor null")
        confirmed = entry.get("confirmed")
        if "confirmed" in entry and (not isinstance(confirmed, str)
                                     or parse_iso(confirmed) is None):
            problems.append(f"entry {index} confirmed {confirmed!r} is not a UTC timestamp")
    return problems


def _load_json_strict(raw: bytes) -> object:
    """The value ``raw`` holds, refusing everything a noni writer would not emit.

    The census's own copy of the reading half of the ordering contract (the
    writer's copy is ``orderschema.refuse_constant`` plus
    ``orderschema.holds_non_finite``): ``parse_constant`` refuses the three bare
    tokens json accepts by default — ``NaN``, ``Infinity``, ``-Infinity``, which
    are not JSON at all — and :func:`_holds_non_finite` walks the parsed value
    for the legal literal that overflows to the same value with no token to stop
    it (``1e400``). Without both, a JSON literal that no writer can name is read
    in as a float, the entry that carries it is reported by one class alone, and
    every other class calls the file clean.

    Raises ValueError on any of them; the caller turns that into the row its own
    class owns. Decoding happens here too, so a non-UTF-8 file raises
    UnicodeDecodeError rather than reaching json.
    """
    value = json.loads(raw.decode("utf-8"), parse_constant=_refuse_constant)
    if _holds_non_finite(value):
        raise ValueError("non-finite number")
    return value


def _refuse_constant(token: str) -> float:
    """The reader's answer to ``NaN``/``Infinity``/``-Infinity``: refuse the token.

    Raising is how ``parse_constant`` refuses; the ValueError travels the same
    except arm as a malformed document, so no token from an untrusted file is
    named back in a row.
    """
    raise ValueError(f"not a JSON number: {token}")


def _holds_non_finite(value: object) -> bool:
    """Whether ``value`` holds a float json read in that is not finite.

    The census's copy of ``orderschema.holds_non_finite``: the census reads the
    artifact, the session register and the ledger without importing the writer's
    helpers, so the walk lives with the reader that needs it. A bool is a bool,
    never a number, so an artifact every writer emits still parses.
    """
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_holds_non_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_holds_non_finite(item) for item in value)
    return False


def _load_order(order: Path, file_kind, bounded, parse_iso
                ) -> tuple[list[dict] | None, str | None]:
    """The order's entries, or (None, the reason it is not an order).

    Absent is not a problem: the ordering layer is optional, so no file means no
    ordering rows at all (contrast the ledger, whose absence is its own warn
    class). Anything else at the path that the census cannot read — a symlink it
    will not follow, a directory, unparseable bytes, a non-finite number, a wrong
    schema — is the ``ordering-malformed`` finding, because the artifact is there
    and is not the artifact.

    The bytes go through :func:`_load_json_strict`, so what this arbiter can read
    is exactly what ``order.py`` can write: an artifact the writer refuses is
    never one the census calls clean under the classes the operator gates on.
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
        value = _load_json_strict(raw)
    except UnicodeDecodeError:
        # The exception text carries the offending bytes, which are untrusted
        # file content; the fixed wording names the class without echoing them.
        return None, "the order file is not valid UTF-8"
    except (json.JSONDecodeError, ValueError):
        # ValueError is the non-finite refusal; its text names a token read from
        # the file, so the fixed wording below names the class instead.
        return None, "the order file is not valid JSON"
    problems = _order_problems(value, parse_iso)
    if problems:
        return None, "; ".join(problems)
    return list(value["entries"]), None


class _IssueState(NamedTuple):
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


def _load_issue_state(path: Path | None, file_kind, bounded) -> _IssueState:
    """The ``--issue-state`` map (issue -> open|closed), with its state.

    A file the operator or an adapter produced that does not parse, or whose
    values are not the two states it may name, is reported as
    ``ordering-malformed`` by the caller: a typo in the state file must stop the
    closed check from reading "no row" as "nothing is closed".
    """
    if path is None:
        return _IssueState(None, None, False)
    kind, problem = file_kind(path)
    if kind != "regular":
        return _IssueState(None, (f"the --issue-state file ({bounded(str(path))}) is not a "
                                  f"readable regular file: {problem}"), True)
    try:
        raw = path.read_bytes()
    except OSError as e:
        return _IssueState(None, (f"the --issue-state file ({bounded(str(path))}) is "
                                  f"unreadable: {bounded(str(e))}"), True)
    try:
        value = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return _IssueState(None, (f"the --issue-state file ({bounded(str(path))}) is not "
                                  f"valid UTF-8"), True)
    except json.JSONDecodeError:
        return _IssueState(None, (f"the --issue-state file ({bounded(str(path))}) is not "
                                  f"valid JSON"), True)
    if not isinstance(value, dict):
        return _IssueState(None, (f"the --issue-state file ({bounded(str(path))}) is not a "
                                  "JSON object mapping issue numbers to open or closed"), True)
    state: dict[str, str] = {}
    bad: list[str] = []
    for key, item in value.items():
        if not isinstance(key, str) or not key.isdigit():
            bad.append(f"key {key!r} is not an issue number")
            continue
        if item not in (ISSUE_STATE_OPEN, ISSUE_STATE_CLOSED):
            bad.append(f"issue {key} state {item!r} is not {ISSUE_STATE_OPEN!r} or "
                       f"{ISSUE_STATE_CLOSED!r}")
            continue
        state[key] = item
    if bad:
        return _IssueState(None, (f"the --issue-state file ({bounded(str(path))}) is "
                                  "malformed: " + "; ".join(sorted(bad)[:4])), True)
    return _IssueState(state, None, True)


def _ledger_records(
    ledger: Path, file_kind,
) -> tuple[dict[str, dict], bool, set[str]]:
    """The records the ledger holds, keyed by filename stem, plus whether it read
    and which names it could not read.

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

    The second element says whether the listing itself failed — a ledger that
    could not be listed answers nothing, so the caller must not report every
    entry's decision as matching no file.
    """
    kind, _problem = file_kind(ledger, kind="dir")
    if kind != "regular":
        # An absent ledger is a readable answer ('no records'), not a fault:
        # ordering does not re-report what ledger-empty already owns.
        return {}, kind == "absent", set()
    try:
        paths = sorted(ledger.glob("*.json"))
    except OSError:
        return {}, False, set()
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
            value = _load_json_strict(raw)
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            records[stem] = value
    return records, True, unreadable


def _decision_problem(stem: str, records: dict[str, dict],
                      unreadable: set[str] | frozenset[str] = frozenset()) -> str | None:
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
    """
    if stem in unreadable:
        return (f"decision {stem!r} is a record file this run could not read: the ledger "
                "holds it, but it is not a readable regular file, so whether the citation "
                "stands cannot be answered")
    if stem not in records:
        return f"decision {stem!r} matches no record file in the ledger"
    record = records[stem]
    status = record.get("status")
    if status not in RECORD_STATUSES:
        return (f"decision {stem!r} carries status {status!r}, not one of "
                + ", ".join(RECORD_STATUSES))
    if status != STATUS_SUPERSEDED:
        return None
    successors = sorted(rid for rid, other in records.items()
                        if other.get("supersedes") == stem
                        and other.get("status") != STATUS_SUPERSEDED
                        and isinstance(rid, str) and RECORD_ID_RE.fullmatch(rid))
    if successors:
        return (f"decision {stem!r} is {STATUS_SUPERSEDED} by {successors[-1]}, so its "
                "order no longer stands")
    return f"decision {stem!r} is {STATUS_SUPERSEDED}, so its order no longer stands"


def check_ordering(
    order: Path, ledger: Path, root: Path, now: datetime, ordering_stale_after: timedelta,
    issue_state: _IssueState, strict: bool, findings: list[dict], *,
    row: Callable[..., dict], rel_to_root: Callable[[Path, Path], str], file_kind,
    bounded: Callable[[str], str], parse_iso,
) -> None:
    """Check the ordering artifact; append its findings to ``findings``.

    Three classes, one read. ``ordering-malformed`` (fail 15) is the artifact
    that is there and is not the artifact; ``ordering-stale`` (warn 45) is an
    entry nobody confirmed within the threshold, measured against --now alone
    so two runs with one --now emit one byte-stream; ``ordering-closed`` (warn
    46) is an entry whose issue the --issue-state map says is closed, plus the
    cannot-tell rows for the issues that map does not mention.

    An absent order file adds no row: the ordering layer is optional. Closed
    state reaches the census only through --issue-state, which an adapter or the
    operator produces — the census never contacts a tracker — so without the
    flag the closed question is not asked and the run says so once rather than
    reading as a clean closed check.

    The row factory and the four path/text primitives it needs come in as
    arguments rather than being imported: ``census.py`` owns the row shape and
    the bounded wording of a foreign message, and a copy here would be a second
    contract for the same row.
    """
    # The readers below take the census's own path and message primitives as
    # arguments: this module must not carry a second definition of what a
    # readable path or a bounded foreign message means.
    def add(check: str, subject: str, artifact: str, message: str,
            severity: str | None = None, whole_artifact: bool = False) -> None:
        """Append one row of this group.

        ``whole_artifact`` marks a row that reports a fault of the read the
        whole group shares — the artifact, its ``--issue-state`` file, or its
        ledger — rather than a defect of one entry, which is what keeps it
        through the group's --only filter (see ``_row`` in census.py). The
        ordering classes share one read, so a fault of that read belongs to the
        group and not to a class the caller may or may not have named.
        """
        findings.append(row(check, strict, subject, artifact, message, root,
                            severity=severity, whole_artifact=whole_artifact))

    entries, problem = _load_order(order, file_kind, bounded, parse_iso)
    state_map = issue_state.map
    if issue_state.given and issue_state.problem is not None:
        # The flag was given and its file does not answer: reported as a
        # malformed ordering input, never swallowed into "no closed issues".
        # The row is added even when the artifact itself is malformed, so a
        # caller who filtered to one class still sees the half they asked about,
        # and it is marked whole_artifact so the group's row filter cannot drop
        # it for naming a class the caller did not.
        add("ordering-malformed", ISSUE_STATE_SUBJECT, ISSUE_STATE_SUBJECT,
            issue_state.problem, whole_artifact=True)
    if problem is not None:
        # Same for the artifact's own fault: it is the group's answer to "could
        # you read the order", which no --only set may silence into a clean run.
        add("ordering-malformed", ORDER_DEFAULT_SUBJECT, rel_to_root(root, order), problem,
            whole_artifact=True)
        return

    records, ledger_readable, unreadable_records = _ledger_records(ledger, file_kind)
    for index, entry in enumerate(entries or [], 1):
        issue = entry.get("issue")
        # The subject is the issue the entry names, so a caller can join a row
        # to the entry it is about; an entry too broken to name one is reported
        # by the malformed pass as a whole-file finding, not entry by entry.
        subject = f"#{issue}" if isinstance(issue, int) else f"entry {index}"

        decision = entry.get("decision")
        if isinstance(decision, str) and ledger_readable:
            why = _decision_problem(decision, records, unreadable_records)
            if why is not None:
                # The subject here is the entry, but the fault is the group's:
                # the citation depends on a ledger read every entry of this run
                # shares, so it is a whole-artifact row (see the whole_artifact
                # paragraph of _row's docstring in census.py). Whatever the
                # --only set names, a run that could not check the citation must
                # not report nothing.
                add("ordering-malformed", subject, rel_to_root(root, order),
                    f"{why} ({rel_to_root(root, ledger)})", whole_artifact=True)

        confirmed = parse_iso(entry.get("confirmed")) if isinstance(
            entry.get("confirmed"), str) else None
        if confirmed is not None:
            age = now - confirmed
            if age > ordering_stale_after:
                add("ordering-stale", subject, rel_to_root(root, order),
                    f"stale: confirmed {entry['confirmed']} is {age.days} day(s) before "
                    f"--now, past the {ordering_stale_after} threshold")

        if state_map is None:
            continue
        key = str(issue) if isinstance(issue, int) else None
        state = state_map.get(key) if key is not None else None
        if state == ISSUE_STATE_CLOSED:
            add("ordering-closed", subject, rel_to_root(root, order),
                f"closed: issue {issue} is {ISSUE_STATE_CLOSED} in --issue-state, so it is "
                "not work to do next")
        elif state is None:
            # The map was given and does not mention this issue: the closed
            # question is genuinely unanswered for this entry, so it gets a row
            # rather than silence (probe honesty). The row belongs to
            # ordering-closed because that is the question it could not answer.
            add("ordering-closed", subject, rel_to_root(root, order),
                f"cannot-tell: --issue-state does not say whether issue {issue} is open or "
                "closed, so the closed check cannot answer for this entry",
                severity="warn")
