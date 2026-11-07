"""The census's items group: the six classes over ``noni/items/``.

Split from ``census.py`` the way the ordering group was: ``census.py`` owns the CLI,
the row shape and the group wiring, ``census_report.py`` owns the class table, and
this module owns the six classes, their codes and severities, and the verdicts built
from what the reads return. The reads themselves live in
``census_items_readers.py`` beside this file (and the strict JSON rule that module
obeys lives in ``census_json.py``); all three are ordinary package imports, and the
row mechanics this group needs are handed in at the call, so the census keeps its
single owner of the row shape.

Six classes, one read of the store. Three of them are findings about the project and
two are this run's own blindness, kept apart by the read itself rather than by a
caller's flag:

- ``item-malformed`` (fail 52): a file the run read in full that is not an item.
- ``item-dangling-link`` (fail 53): an item whose ``decision`` names no live record.
- ``item-issue-mismatch`` (fail 54): a status and an ``issue`` that contradict each
  other, or a promoted item whose issue the order no longer holds.
- ``item-stale`` (warn 55): a candidate aged past the threshold from its ``created``
  stamp against ``--now``.
- ``item-unreadable`` (warn 56): a file the run was told to read and could not.
- ``item-unlistable`` (warn 57): a store that exists and cannot be listed.

The two blindness classes say *this run could not look*, and every class that counts,
ages or resolves asks the read whether it saw everything before it answers. A run
that read part of the store reports what it could not read and says nothing about the
rest, because the alternative is the clean verdict of a project that never filed an
idea. A store that could not be listed at all answers nothing to any class: one row
says so, and it survives every filter (see ``WHOLE_ARTIFACT_KEY``).

Absence is not a finding: a project that has never filed an idea has no
``noni/items/`` at all and earns no row of any class, exactly as a project that has
never ordered anything earns no ordering rows. A store that exists but holds nothing
is the same state, and earns nothing either.

Nothing here prints or exits: every answer is appended to the caller's ``findings``
list through the ``row`` factory the census supplies.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from . import itemschema, orderschema

# The six ids, spelled once each so the group's set, every row's class and the
# tests' expected ids all read one declaration. ``census_report.CHECKS`` carries the
# codes and severities beside them; a name typed twice is how a class comes to
# report a code its table does not carry.
ITEM_MALFORMED = "item-malformed"
ITEM_REFERENCE_UNRESOLVED = "item-reference-unresolved"
ITEM_PROMOTED_WITHOUT_ISSUE = "item-promoted-without-issue"
ITEM_DROPPED_IN_ORDER = "item-dropped-in-order"
ITEM_STALE = "item-stale"
ITEM_UNLISTABLE = "item-unlistable"

ITEM_CHECKS = frozenset({ITEM_MALFORMED, ITEM_REFERENCE_UNRESOLVED,
                         ITEM_PROMOTED_WITHOUT_ISSUE, ITEM_DROPPED_IN_ORDER,
                         ITEM_STALE, ITEM_UNLISTABLE})

# The subject of a row that is about the store rather than one item in it, the way
# hygiene's ``hygiene scan`` and ordering's ``issue-state`` are machine-readable
# discriminators: a consumer branches on ``subject``, not on message prose.
STORE_SUBJECT = "noni/items"

# The three status words, read from the schema rather than restated: a status the
# writer can produce and this group did not name would be reported as nothing.
STATUS_CANDIDATE = itemschema.STATUS_CANDIDATE
STATUS_PROMOTED = itemschema.STATUS_PROMOTED
STATUS_DROPPED = itemschema.STATUS_DROPPED

# The record states that answer "does this decision still stand". A record whose
# status is anything else decides nothing, so a citation to it is answered like a
# citation to no file at all — the same rule the order group and the writer apply.
RECORD_STATUSES = ("decided", "open", "superseded")
STATUS_SUPERSEDED = "superseded"

# How far the successor search will walk a supersede chain before it stops and names
# no heir. A chain this long is not a chain; the census is read-only and must not
# spin on a hand-made ledger, and the loop itself is ``ledger-chain``'s finding, not
# this group's.
_CHAIN_STEPS = 32

# The ledger and order paths, spelled from the modules that own them so a row names
# the artifact by the same string its own group names it by.
LEDGER_REL = "noni/decisions"

# The six rows of the check contract, declared here beside the classes they describe
# and merged into ``census_report.CHECKS``. One declaration carries the id, the code,
# the default severity and the fix hint, so the group's set and the table's rows are
# two views of one list rather than two lists: ``ITEM_CHECKS`` is derived from these
# keys, and a class whose row is missing is a ``KeyError`` at import rather than a
# class that renders no code and cannot be documented.
#
# The codes sit in one contiguous band above every existing class, so the
# lowest-wins rule of the exit-code choice never buries an item finding under an
# older class's number. Within the band the four findings sit below the two
# blindnesses for the same reason in reverse: a row that says "the project is
# wrong" outranks a row that says "this run could not read it", so a store that is
# both broken and unreadable reports the defect rather than the census's own limits.
ITEM_ROWS: dict[str, tuple[int, str, str]] = {
    ITEM_MALFORMED: (
        52, "fail",
        "repair noni/items/<id>.json to the noni.item/1 shape (schema, the id as its "
        "own name, a one-line title, one of candidate/promoted/dropped, a UTC "
        "created stamp, and issue/decision/why only where that status owes them), or "
        "write it with item.py, which refuses the shapes this class reports",
    ),
    ITEM_DROPPED_IN_ORDER: (
        53, "fail",
        "the order and the store disagree about one idea: drop it from the order with "
        "order.py remove ISSUE, or file the idea again under its own id with item.py "
        "add if the order really does still hold it",
    ),
    ITEM_PROMOTED_WITHOUT_ISSUE: (
        54, "fail",
        "make the status and the issue agree: only a promoted item names an issue, "
        "and a promoted item names one the order holds (order.py puts it there); "
        "repair with item.py rather than by hand, which refuses every shape this "
        "class reports",
    ),
    ITEM_REFERENCE_UNRESOLVED: (
        55, "fail",
        "cite a record the ledger holds and has not superseded (item.py drop ID "
        "--decision <id> --why REASON), or repair the ledger: the point of a dropped "
        "item is the decision that killed it, so a citation to nothing is the record "
        "the kill list exists to carry",
    ),
    ITEM_STALE: (
        56, "warn",
        "move the candidate or let it go: promote it with item.py promote ID "
        "--issue N, or drop it with item.py drop ID --decision <id> --why REASON; "
        "an unclaimed idea past --stale-after is the operator's last word on the "
        "store only as far back as that",
    ),
    ITEM_UNLISTABLE: (
        57, "warn",
        "restore noni/items/ as a readable directory, or pass the --items of the "
        "clone that holds the store: a store this run could not list is reported by "
        "this class and never as the empty store of a project that filed no idea",
    ),
}

assert ITEM_CHECKS == frozenset(ITEM_ROWS), (
    "the items group's set and its check-contract rows must name one set of ids")


def check_items(
    items: Path, ledger: Path, order: Path, root: Path, now: datetime,
    item_stale_after: timedelta, strict: bool, findings: list[dict], *,
    listed: tuple[Path, ...] | None, fault: str | None,
    ledger_names: tuple[str, ...] | None,
    row: Callable[..., dict], rel_to_root: Callable[[Path, Path], str],
    file_kind: Callable[..., tuple[str, str | None]],
    read_record: Callable[[Path], tuple[bytes | None, OSError | None]],
    bounded: Callable[..., str], clipped: Callable[[str], str],
    load_json_strict: Callable[[bytes], object], readers,
) -> None:
    """Check the item store; append its findings to ``findings``.

    One read of the store (``listed`` and ``fault``, the two answers of the run's
    one probe readdir, read through the readers module), one ledger listing
    (``ledger_names``, the same probe's names — the group never walks
    ``noni/decisions/`` for itself), and one read of the order, asked only when a
    class needs the answer.

    ``item_stale_after`` is this run's item threshold: ``--stale-after`` when the
    caller named one, the group's own default when it did not (see
    ``ITEM_STALE_AFTER_DEFAULT`` in ``census_report.py``). Age is measured from the
    item's ``created`` stamp against ``--now`` and the boundary is exclusive, the
    same shape the ordering group gives its own default: an item aged exactly the
    threshold has not passed it.

    ``row``, ``rel_to_root``, ``file_kind``, ``bounded``, ``clipped``,
    ``load_json_strict`` and ``readers`` are the census's own and arrive as
    arguments rather than being imported: the row shape, the machine-local-path
    rule, the classifier, the bound on a foreign message and the store's read each
    keep their single owner, no module of this group puts a directory on
    ``sys.path``, and a seam a test puts on one of them is the seam this group uses.
    """
    def add(check: str, subject: str, artifact: str, message: str, *,
            severity: str | None = None, whole_artifact: bool = False) -> None:
        """Append one row of this group, worded by the caller.

        One factory for all six classes so no class composes a row of its own
        devising: ``whole_artifact`` marks a row about a read the group shares
        rather than one item inside it, which is what keeps it through the run's
        ``--only`` filter (see ``_row`` and ``WHOLE_ARTIFACT_KEY`` in
        ``census.py``).
        """
        findings.append(row(check, strict, subject, artifact, message, root,
                            severity=severity, whole_artifact=whole_artifact))

    rel_store = rel_to_root(root, items)

    if fault is not None:
        # The store exists and could not be listed: one row, marked whole-artifact,
        # because a run that read nothing must not report the clean verdict of a
        # project that filed nothing, and no other class of this group may answer a
        # question about a store it never opened. The fault is foreign text, so it
        # goes through ``bounded``; the sentence around it is this group's own, so
        # the finished row goes through ``clipped``.
        add(ITEM_UNLISTABLE, STORE_SUBJECT, rel_store,
            clipped(f"cannot-tell: the item store ({bounded(rel_store)}) exists "
                    f"but could not be listed ({bounded(fault)}), so no item of "
                    "this store was checked"),
            severity="warn", whole_artifact=True)
        return

    scan = readers.items_scan(items, listed, file_kind=file_kind,
                              read_record=read_record,
                              load_json=load_json_strict, bounded=bounded)

    for stem, why in scan.unreadable:
        # A file this run was told to read and could not: a symlink (never followed),
        # a directory or device, bytes that are not UTF-8, a document the strict reader
        # refused, or a name the listing gave that was gone by the read. The ruling
        # gives the group no blindness class of its own, so it is reported as the one
        # finding the file does support -- this store holds no item at that path -- and
        # the row says so in those words rather than quoting a defect the run did not
        # establish. It is a fail row of a fail class: the whole-artifact marker keeps
        # it through a filter that named none of these classes, so a store that cannot
        # be read never reports the clean verdict of a store that holds nothing.
        add(ITEM_MALFORMED, stem, f"{rel_store}/{stem}.json",
            clipped(f"malformed: {why}, so no item was read at this path"),
            whole_artifact=True)
    for stem, problems in scan.not_items:
        add(ITEM_MALFORMED, stem, f"{rel_store}/{stem}.json",
            clipped("malformed: " + "; ".join(problems)))
    for stem, why in scan.id_mismatch:
        # The stem is the item's name and the ``id`` field restates it, so a file
        # whose two disagree is one item named two ways: the census keys the store by
        # the stem, and the writer refuses to write over the mismatch. Asked whatever
        # else this run could or could not read, because the disagreement lives in
        # bytes this run held, so one broken file in the store does not hide a second
        # file that names another item.
        add(ITEM_MALFORMED, stem, f"{rel_store}/{stem}.json",
            clipped(f"malformed: {why}"))
    if scan.blind:
        # Every class below counts, ages or resolves. A run that could not open
        # part of the store has no standing to certify the rest, and the rows above
        # already say what it could not read, so the answers a partial store would
        # have produced are not produced.
        return

    _check_citations(scan.bodies, ledger, ledger_names, add, rel_store,
                     read_record=read_record, load_json_strict=load_json_strict,
                     clipped=clipped)
    _check_status_and_issue(scan.bodies, order, add, rel_store,
                            file_kind=file_kind, read_record=read_record,
                            load_json_strict=load_json_strict, clipped=clipped)
    _check_stale(scan.bodies, now, item_stale_after, add, rel_store)


def _ledger_status(ledger: Path, names: tuple[str, ...] | None, *,
                   read_record, load_json_strict) -> dict[str, str | None]:
    """Each record id of the ledger, mapped to the state this run could answer for it.

    The run's one ledger listing (``names``) read once, so the citation question is
    answered without walking the directory a second time (see
    ``census_ledger.LedgerProbe.names``). A name maps to its record's ``status``
    word when this run read the record and it carried a status the group knows; it
    maps to ``None`` when the run could not read it or it stated nothing the group
    recognises, which is blindness the citation class words as a cannot-tell and
    never as a verdict.

    ``names`` arriving as ``None`` means the caller had no probe to hand and the
    directory is listed here — the seam a test faults for this group's read alone,
    the same shape the ordering group accepts.
    """
    paths = (sorted(ledger.glob("*.json")) if names is None
             else [ledger / name for name in names if name.endswith(".json")])
    records: dict[str, str | None] = {}
    for path in paths:
        record_id = path.name[: -len(".json")]
        raw, fault = read_record(path)
        if fault is not None or raw is None:
            records[record_id] = None
            continue
        try:
            value = load_json_strict(raw)
        except (UnicodeDecodeError, ValueError, RecursionError):
            records[record_id] = None
            continue
        status = value.get("status") if isinstance(value, dict) else None
        records[record_id] = status if status in RECORD_STATUSES else None
    return records


def _check_citations(bodies, ledger: Path, ledger_names, add, rel_store: str, *,
                     read_record, load_json_strict, clipped) -> None:
    """``item-dangling-link``: an item whose ``decision`` names no live record.

    Asked of every item that cites a record, in any status: a dropped item's link is
    the record that killed it and a promoted item's is the record that ordered it, so
    a citation resolving to nothing leaves the kill list untraceable. Three answers,
    three shapes — the record is not there (a finding), the record is there and
    superseded (a finding, which names its successor when the ledger holds one), and
    the run could not tell (a cannot-tell, never a verdict).

    The successor is read from the ledger the run already listed, the same question
    ``order.py`` asks before it accepts a citation, so the row can name the record
    the operator should cite instead of only saying the citation is dead.
    """
    records = _ledger_status(ledger, ledger_names, read_record=read_record,
                             load_json_strict=load_json_strict)
    for stem, body in bodies:
        decision = body["decision"]
        if decision is None:
            continue
        if decision not in records:
            add(ITEM_REFERENCE_UNRESOLVED, stem, f"{rel_store}/{stem}.json",
                f"unresolved: the item cites decision {decision}, which no file "
                f"under {LEDGER_REL}/ carries")
            continue
        state = records[decision]
        if state is None:
            # The record's file is there and this run could not read it, so whether
            # the citation stands is an answer the run does not hold. The class is a
            # fail class, so the row carries the cannot-tell severity override
            # explicitly (see ``_row``): the run's own blindness is never a verdict on
            # the project, and --strict still promotes it like any other cannot-tell.
            add(ITEM_REFERENCE_UNRESOLVED, stem, f"{rel_store}/{stem}.json",
                clipped(f"cannot-tell: the record {decision} the item cites could "
                        "not be read, so whether it stands was not answered"),
                severity="warn", whole_artifact=True)
        elif state == STATUS_SUPERSEDED:
            heir = _successor(ledger, ledger_names, decision,
                              read_record=read_record,
                              load_json_strict=load_json_strict)
            add(ITEM_REFERENCE_UNRESOLVED, stem, f"{rel_store}/{stem}.json",
                f"unresolved: the item cites decision {decision}, which is "
                f"superseded{'' if heir is None else f' by {heir}'}")


def _successor(ledger: Path, names, decision: str, *, read_record,
               load_json_strict) -> str | None:
    """The live record that supersedes ``decision``, when this run read one.

    A scan over the listing the run already took, so no second readdir of the
    ledger: the newest record whose ``supersedes`` names ``decision`` and whose own
    status is not superseded answers. A chain of supersedes is a ledger group
    question (``ledger-chain`` owns it); this group only wants the heir to name in
    the row, so a chain whose first link was itself superseded is followed to the
    live record rather than stopped at the first link it met. None means the chain
    has no live link this run could see, and the row says only that the citation is
    superseded — which is still the finding, and the ledger group is the arbiter of
    the chain itself.
    """
    paths = (sorted(ledger.glob("*.json")) if names is None
             else [ledger / name for name in names if name.endswith(".json")])
    live: dict[str, str] = {}
    for path in paths:
        raw, fault = read_record(path)
        if fault is not None or raw is None:
            continue
        try:
            value = load_json_strict(raw)
        except (UnicodeDecodeError, ValueError, RecursionError):
            continue
        if not isinstance(value, dict):
            continue
        if value.get("status") == STATUS_SUPERSEDED:
            continue
        heir = value.get("id")
        cites = value.get("supersedes")
        if isinstance(heir, str) and isinstance(cites, str):
            live.setdefault(cites, heir)
    # Walk the chain from the cited record, taking the greatest heir at each step
    # (ids are dated, so the greatest name is the newest link). The step bound is a
    # guard against a cycle: a ledger with a loop in it is the ledger group's
    # finding, and this group stops rather than spinning.
    best: str | None = None
    cursor = decision
    for _step in range(_CHAIN_STEPS):
        heirs = [heir for cites, heir in live.items() if cites == cursor]
        if not heirs:
            return best
        cursor = best = max(heirs)
    return best


def _check_status_and_issue(bodies, order: Path, add, rel_store: str, *,
                            file_kind, read_record, load_json_strict,
                            clipped) -> None:
    """``item-promoted-without-issue`` and ``item-dropped-in-order``.

    Two classes, because two questions are asked and the PM ruling gives each its own
    id, its own code and its own severity:

    - ``item-promoted-without-issue`` (54) asks a question of the item file alone: a
      ``promoted`` item that carries no issue was promoted to nothing, and any other
      status that carries an issue names an issue it never became. The ruling puts the
      status checks on item files only, which is what makes them answerable now.
    - ``item-dropped-in-order`` (53) is the one class that reads the order as well as
      the store, and asks the order-side question the ruling declares here and tests
      against item files only: an order entry that cites an idea the store has
      dropped. The item entries sub-issue 2 adds to ``noni.order/2`` are what fill
      this class in; against a ``noni.order/1`` file, whose entries name an issue and
      a decision and nothing else, no entry can cite an item, so the class is declared,
      documented and tested (its shape is pinned in
      ``tests/test_census_items_group.py``) and reports nothing on a /1 order.

    The order question is asked only when the order can be read at all. An order the
    run could not read belongs to ``ordering-malformed`` (its own group reports it) and
    this group says nothing about it, rather than promoting an empty list into "the
    order cites no item" -- the inversion the group's blindness rule exists to prevent.
    """
    for stem, body in bodies:
        status, issue = body["status"], body["issue"]
        if status == STATUS_PROMOTED and issue is None:
            add(ITEM_PROMOTED_WITHOUT_ISSUE, stem, f"{rel_store}/{stem}.json",
                "promoted without an issue: the item is promoted and names no "
                "issue, so it was promoted to nothing")
        elif status != STATUS_PROMOTED and issue is not None:
            add(ITEM_PROMOTED_WITHOUT_ISSUE, stem, f"{rel_store}/{stem}.json",
                f"promoted without an issue: the item is {status} and names issue "
                f"{issue}, which only a promoted item does")

    cited = _order_item_citations(order, file_kind=file_kind,
                                  read_record=read_record,
                                  load_json_strict=load_json_strict)
    if cited is None:
        return
    dropped = {stem for stem, body in bodies
               if body["status"] == STATUS_DROPPED}
    for stem in sorted(cited & dropped):
        add(ITEM_DROPPED_IN_ORDER, stem, f"{rel_store}/{stem}.json",
            clipped(f"dropped in the order: an entry of "
                    f"{orderschema.ORDER_REL} cites item {stem}, which the store "
                    "has dropped"))


def _order_item_citations(order: Path, *, file_kind, read_record,
                          load_json_strict) -> set[str] | None:
    """The item ids the order cites, or None when this run could not read the order.

    Reads the ``item`` field an ``noni.order/2`` entry carries, which a
    ``noni.order/1`` entry does not: the set is then honestly empty rather than
    unknown, because the file this run read cites no item and said so. None is the
    blindness answer (no readable artifact at all), which the caller reads as "not
    asked" and never as "the order cites nothing" -- an entry naming an item this run
    never saw is exactly the finding this class exists to make, so it cannot be
    inferred from a read that failed.
    """
    kind, _problem = file_kind(order)
    if kind == "absent":
        return set()
    if kind != "regular":
        return None
    raw, fault = read_record(order)
    if fault is not None or raw is None:
        return None
    try:
        value = load_json_strict(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(value, dict):
        return None
    entries = value.get("entries")
    if not isinstance(entries, list):
        return None
    return {entry["item"] for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("item"), str)}


def _check_stale(bodies, now: datetime, item_stale_after: timedelta, add,
                 rel_store: str) -> None:
    """``item-stale``: a candidate nobody has moved in longer than the threshold.

    Aged from ``created`` against ``--now``, boundary exclusive: an item aged
    exactly the threshold has not passed it, which is the same rule the ordering
    group's stale class states and the reason both take their threshold as an
    argument rather than comparing against a literal. The row names the threshold it
    compared against, so a reader can tell a default run from a prompted one.

    Only a candidate is aged. A promoted or dropped item has an answer recorded, and
    an answer that has sat unmoved for a month is a decision rather than a stalled
    idea: a census that reported it as stale would be asking the operator to
    re-litigate a choice the ledger already holds.
    """
    for stem, body in bodies:
        if body["status"] != STATUS_CANDIDATE:
            continue
        created = itemschema.parse_timestamp(body["created"])
        if created is None:  # the malformed class already reported it
            continue
        age = now - created
        if age > item_stale_after:
            add(ITEM_STALE, stem, f"{rel_store}/{stem}.json",
                f"stale: created {body['created']} is {age.days} day(s) before "
                f"--now, past the {item_stale_after} threshold")
