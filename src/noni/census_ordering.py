"""The census's ordering group: the three classes over ``noni/direction/order.json``.

Split from ``census.py`` so each file stays the size one responsibility is
worth: ``census.py`` owns the CLI, the exit-code table, the row shape and the
group wiring, and this module owns the ordering classes and their verdicts over
what the reads return. The reads themselves live in ``census_ordering_readers.py``
beside this file (and the strict JSON rule that module obeys in
``census_json.py``); all three are loaded by path from ``census.py`` — the census
never puts a directory on ``sys.path``, where a lookalike earlier on the path
could be trusted as its ordering checks — and the two row mechanics this group
needs (``_row`` and ``_rel_to_root``) are handed in at the call, so the census
keeps its single owner of the row shape.

Three classes, one read of the artifact:

- ``ordering-malformed`` (fail 15): the artifact exists and is not the artifact.
- ``ordering-stale`` (warn 45): an entry nobody confirmed within the threshold.
- ``ordering-closed`` (warn 46): an entry whose issue the ``--issue-state`` map
  says is closed, plus the ``cannot-tell`` rows for the issues it does not name.

Nothing here prints or exits: every answer is appended to the caller's
``findings`` list through the ``row`` factory it supplies.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

# The artifact's shape, the census's side of the contract order.py writes to.
ORDER_SCHEMA = "noni.order/1"
ORDER_REQUIRED_FIELDS = ("schema", "entries")
ORDER_ENTRY_FIELDS = ("issue", "decision", "confirmed")

# The two states an --issue-state map answers for one issue, plus the third
# state a map cannot answer at all: an issue the file does not mention. The
# words are the census's own, never a value read from the file's contents.
ISSUE_STATE_OPEN = "open"
ISSUE_STATE_CLOSED = "closed"
ISSUE_STATE_STATES = (ISSUE_STATE_OPEN, ISSUE_STATE_CLOSED)

# The three status words a decision record may hold. A chain analysis reads
# them everywhere a verdict about 'does this record still stand' is made; the
# same words in the same set are what ordering's decision lookup answers for,
# so a hand-edited status outside this set decides nothing about an order.
RECORD_STATUSES = ("decided", "open", "superseded")
STATUS_SUPERSEDED = "superseded"

# The two subjects the ordering class uses for the rows that are not about one
# entry: a whole-file malformation, and the --issue-state file that did not
# parse. Like hygiene's `deny-list` / `hygiene scan` subjects, they are the
# machine-readable discriminator between whole-artifact and per-entry rows.
ORDER_DEFAULT_SUBJECT = "noni/direction/order.json"
ISSUE_STATE_SUBJECT = "issue-state"


def order_problems(value: object, parse_iso, names_zone) -> list[str]:
    """Why ``value`` is not an order the census can read; [] when it is.

    The rules of ``noni.order/1`` as one list, so the row the class reports and
    the refusal order.py applies before writing cannot drift apart: the writer
    refuses what this census would report, which is what keeps a writer run from
    producing an artifact this arbiter calls malformed. The census reads with the
    strict reader (``census_json.load_json_strict``), so the two answer the same
    document alike, and a non-finite number is refused here as the backstop for
    a parsed value that came from anywhere but that reader.

    A blank ``decision`` is a defect, not a string: it matches no record file, so
    the census's own mirror of the writer's rule asks for more than ``isinstance(
    decision, str)`` — otherwise a hand-repaired artifact could stay clean here
    while the writer refuses to touch it.

    A ``confirmed`` with no UTC offset is refused too, as the writer's
    ``orderschema.parse_confirmed`` refuses it: the census's own ``_parse_iso``
    reads a bare time as UTC, and an entry judged stale or fresh against a minute
    nobody chose is a verdict on a time the file does not state.

    An empty ``entries`` list with the right schema is clean, not a finding: an
    operator who wants nothing ordered next has said so, and the census reports
    no ordering rows for it.
    """
    if not isinstance(value, dict):
        return ["the order file is not a JSON object"]
    problems: list[str] = []
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
    _entry_problems(entries, problems, parse_iso, names_zone)
    return problems


def _entry_problems(entries: list, problems: list[str], parse_iso, names_zone) -> None:
    """Append why one entry list is not a list of entries the census can read.

    Split from :func:`order_problems` so each half reads as one rule set: the
    document's own fields, then the entries' fields. A duplicate ``issue`` is
    reported once per repeat, and a non-integer is not also counted as a
    duplicate: a caller who fixes the type gets a second answer rather than a
    surprise.
    """
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
                                     or parse_iso(confirmed) is None
                                     or not names_zone(confirmed)):
            problems.append(f"entry {index} confirmed {confirmed!r} is not a UTC timestamp")


def check_ordering(
    order: Path, ledger: Path, root: Path, now: datetime, ordering_stale_after: timedelta,
    issue_state, strict: bool, findings: list[dict], *,
    row: Callable[..., dict], rel_to_root: Callable[[Path, Path], str], file_kind,
    bounded: Callable[[str], str], parse_iso, readers, names_zone,
    load_json_strict: Callable[[bytes], object], clipped: Callable[[str], str],
    ledger_name: Callable[[str], str],
    names: tuple[str, ...] | None = None,
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

    The row factory, the four path/text primitives it needs, the ``readers``
    module (with its ``names_zone`` stamp rule) and ``load_json_strict`` — the
    census's strict JSON reader — come in as arguments rather than being
    imported: ``census.py`` owns the row shape and the bounded wording of a
    foreign message, neither module carries a sys.path entry of its own, and a
    copy of any of them here would be a second contract for the same row.

    ``ledger_name`` is the census's one rule for naming a ledger a run could not
    read (``census_ledger.ledger_name``), and it is required: every place this
    group names the ledger in a row -- the listing-fault row and the per-entry
    citation row -- takes the identifier from it rather than interpolating the
    root-relative path itself. An out-of-tree ``--ledger`` override cannot be
    rooted, so that path is a machine-local directory, and a default that handed
    back the path unchanged would print it for any caller that forgot the
    argument. Both groups' rows for one ledger then name it identically, and the
    scrubber is left to its safety-net job on foreign text instead of being asked
    to redact a path this census wrote and still leave it identifiable.

    ``names`` is the run's one ledger listing — the names the census's probe
    read — and it goes straight to the readers, which is what keeps the whole
    run to a single readdir of the ledger. It defaults to None, which asks the
    readers to list: that is the seam a test faults to plant a fault in this
    group's read alone (see ``_listing_faults`` in
    ``tests/test_census_ordering.py``), and a direct caller that has no probe
    gets a listing of its own rather than nothing.
    """
    # The readers take the census's own path and message primitives as
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

    entries, problem = readers.load_order(order, file_kind, bounded, parse_iso,
                                          lambda value: order_problems(value, parse_iso,
                                                                       names_zone),
                                          load_json_strict, clipped)
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

    rel_ledger = rel_to_root(root, ledger)
    records, ledger_readable, unreadable_records, listed, listing_fault = \
        readers.ledger_records(ledger, file_kind, load_json_strict, names)
    if not ledger_readable and listed and any(isinstance(entry.get("decision"), str)
                                             for entry in entries or []):
        # The listing itself faulted on a directory that is there, so this run
        # checked no citation at all — and a run that checked nothing must not
        # report the artifact clean. One row for the group (the read is shared),
        # marked whole_artifact so no --only set can silence it. Unlike the
        # not-a-directory case, where the listing never ran and the ledger group
        # owns the report, an I/O fault of the listing is visible only here: no
        # other class of this run sees it.
        add("ordering-malformed", ORDER_DEFAULT_SUBJECT, rel_to_root(root, order),
            # The whole composed sentence is clipped, not just the fault text
            # inside it: the row's length is a property of the row, and a fault
            # whose strerror runs to thousands of characters is otherwise a row
            # past the bound every other row of the report keeps. ``clipped`` and
            # not ``bounded`` because the sentence names the ledger by a path the
            # row must keep; the fault text itself still goes through ``bounded``.
            # The ledger is named by ``ledger_name``, the identifier the ledger
            # group's own row for this same fault uses, so the two rows agree on
            # which directory they could not read -- and the fault text carries no
            # filename at all (``census_ordering_readers`` builds it with
            # ``census_text.fault_text``), so the ``bounded`` here is a net over
            # text that should need none.
            clipped(f"the decision ledger ({bounded(ledger_name(rel_ledger))}) could not be listed"
                    f"{'' if listing_fault is None else ': ' + bounded(listing_fault)}, "
                    "so no entry's decision citation could be checked against the records "
                    "the ledger holds"), whole_artifact=True)
    for index, entry in enumerate(entries or [], 1):
        issue = entry.get("issue")
        # The subject is the issue the entry names, so a caller can join a row
        # to the entry it is about; an entry too broken to name one is reported
        # by the malformed pass as a whole-file finding, not entry by entry.
        subject = f"#{issue}" if isinstance(issue, int) else f"entry {index}"

        decision = entry.get("decision")
        if isinstance(decision, str) and ledger_readable:
            why = readers.decision_problem(decision, records, unreadable_records,
                                           RECORD_STATUSES, STATUS_SUPERSEDED)
            if why is not None:
                # The subject here is the entry, but the fault is the group's:
                # the citation depends on a ledger read every entry of this run
                # shares, so it is a whole-artifact row (see the whole_artifact
                # paragraph of _row's docstring in census.py). Whatever the
                # --only set names, a run that could not check the citation must
                # not report nothing.
                # Clipped as a whole because ``why`` quotes the entry's own
                # decision text, read from the artifact: a value of any length is
                # a row of at most the bound, as every other row of the report is.
                add("ordering-malformed", subject, rel_to_root(root, order),
                    # The ledger is named by ``ledger_name`` for the same reason
                    # the listing-fault row above is: an out-of-tree ``--ledger``
                    # makes this path a host directory, and the row only needs to
                    # say which ledger it means.
                    clipped(f"{why} ({ledger_name(rel_ledger)})"), whole_artifact=True)

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
