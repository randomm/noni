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
- ``item-dropped-in-order`` (fail 53): an order entry that cites an item the store
  has dropped.
- ``item-promoted-without-issue`` (fail 54): a ``promoted`` item that names no issue,
  or one whose issue no entry of the order holds.
- ``item-reference-unresolved`` (fail 55): an item whose ``decision`` names no live
  record.
- ``item-stale`` (warn 56): a candidate aged past the threshold from its ``created``
  stamp against ``--now``.
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

# The citation half of the group, split out for the size limit along the seam the two
# already had (shape here, references there). Imported last and after the constants it
# reads, which is why it sits below the module's own declarations rather than beside
# the package imports above.
from .census_items_citations import _check_citations, _field
from .census_items_names import (
    ITEM_CHECKS,
    ITEM_DROPPED_IN_ORDER,
    ITEM_MALFORMED,
    ITEM_PROMOTED_WITHOUT_ISSUE,
    ITEM_REFERENCE_UNRESOLVED,
    ITEM_STALE,
    ITEM_UNLISTABLE,
    STATUS_CANDIDATE,
    STATUS_DROPPED,
    STATUS_PROMOTED,
    STORE_SUBJECT,
)

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
        # A run that could not open part of the store has no standing to certify the
        # rest, so the two questions that are asked *of the store as a whole* are not
        # answered: does each citation resolve to a live record, and does the order
        # still hold each promoted item. Both ask a question whose answer depends on
        # an artifact this run did not fully read, and answering them from a partial
        # store is how "the ledger holds that record" gets said about a ledger this
        # run never opened.
        #
        # What is *not* gated is the per-file work: a file this run read in full has
        # a known status, a known age and a known issue, and one hand-made file in the
        # store must not hide the finding sitting in the file beside it. The ordering
        # group makes the same split for the same reason -- its ``ordering-stale`` and
        # ``ordering-closed`` rows are added whatever the ledger listing answered,
        # while the citation check is refused when the listing faulted.
        _check_status_and_issue(scan.bodies, None, add, rel_store,
                                file_kind=file_kind, read_record=read_record,
                                load_json_strict=load_json_strict, clipped=clipped)
        _check_stale(scan.bodies, now, item_stale_after, add, rel_store)
        return
    _check_citations(scan.bodies, ledger, ledger_names, add, rel_store,
                     read_record=read_record, load_json_strict=load_json_strict,
                     clipped=clipped)
    _check_status_and_issue(scan.bodies, order, add, rel_store,
                            file_kind=file_kind, read_record=read_record,
                            load_json_strict=load_json_strict, clipped=clipped)
    _check_stale(scan.bodies, now, item_stale_after, add, rel_store)

def _check_status_and_issue(bodies, order: Path | None, add, rel_store: str, *,
                            file_kind, read_record, load_json_strict,
                            clipped) -> None:
    """``item-promoted-without-issue`` and ``item-dropped-in-order``.


    Two classes, because two questions are asked and the PM ruling gives each its own
    id, its own code and its own severity:


    - ``item-promoted-without-issue`` (54) asks the one status question the artifact's
      own rules leave open: a ``promoted`` item that carries no issue was promoted to
      nothing. The other half of the pairing -- a status that carries an issue it never
      became -- is not asked here because the schema already refuses it
      (``itemschema._dropped_problems`` reports a dropped item that still names an
      issue, and a candidate's or promoted item's ``issue`` is checked by
      ``_citation_problems``), so a file that carried it would already be reported
      ``item-malformed`` by the pass above. Two classes claiming one defect is how a
      store starts reporting the same file twice under two codes.
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
    # One read of the order answers both of its questions, and the run either holds
    # that read or asks neither. ``order is None`` is the caller's way of saying a file
    # of the store itself could not be opened: with the store unreadable this run has
    # no standing to answer what the order owes it, so the two order questions are
    # refused and the per-file question (was anything promoted to nothing) is still
    # answered from the bodies this run did read.
    held = None if order is None else _order_entries(
        order, file_kind=file_kind, read_record=read_record,
        load_json_strict=load_json_strict)
    ordered: set[int] = set()
    cited: set[str] = set()
    if held is not None:
        entries, readable = held
        if not readable:
            return
        ordered, cited = _held_issues(entries), _held_item_citations(entries)
    for stem, body in bodies:
        status, issue = _field(body, "status"), _field(body, "issue")
        if status == STATUS_PROMOTED and issue is None:
            add(ITEM_PROMOTED_WITHOUT_ISSUE, stem, f"{rel_store}/{stem}.json",
                "promoted without an issue: the item is promoted and names no "
                "issue, so it was promoted to nothing")
        elif (status == STATUS_PROMOTED and issue is not None and held is not None
              and issue not in ordered):
            add(ITEM_PROMOTED_WITHOUT_ISSUE, stem, f"{rel_store}/{stem}.json",
                clipped(f"promoted without an issue: the item is promoted to "
                        f"issue {issue}, which no entry of "
                        f"{orderschema.ORDER_REL} holds"))
    dropped = {stem for stem, body in bodies
               if _field(body, "status") == STATUS_DROPPED}
    for stem in sorted(cited & dropped):
        add(ITEM_DROPPED_IN_ORDER, stem, f"{rel_store}/{stem}.json",
            clipped(f"dropped in the order: an entry of "
                    f"{orderschema.ORDER_REL} cites item {stem}, which the store "
                    "has dropped"))


def _order_entries(order: Path, *, file_kind, read_record,
                   load_json_strict) -> tuple[list[dict], bool]:
    """The order's entries, and whether this run holds them.
    One read answers both questions this group asks of the order, which is the point
    of the single reader: two readers of one path is how a run comes to ask the second
    question of a file the first refused. ``(entries, True)`` is a read this run holds
    (an absent artifact reads as an empty list, because a file that is not there
    carries no entries); ``(anything, False)`` is blindness -- a path this run could
    not open, or a document that is not an order at all -- and the caller answers
    nothing from it.
    The ``issue`` numbers and the ``item`` names are taken from the same entry list the
    ordering group holds under its own classes, and a malformed entry is skipped rather
    than fatal: an entry too broken to name an issue is the ordering group's
    ``ordering-malformed`` row, not this group's, and the rest of the list still says
    what the order holds.
    """
    kind, _problem = file_kind(order)
    if kind == "absent":
        return [], True
    if kind != "regular":
        return [], False
    raw, fault = read_record(order)
    if fault is not None or raw is None:
        return [], False
    try:
        value = load_json_strict(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return [], False
    if not isinstance(value, dict):
        return [], False
    entries = value.get("entries")
    if not isinstance(entries, list):
        return [], False
    return [entry for entry in entries if isinstance(entry, dict)], True


def _held_issues(entries: list[dict]) -> set[int]:
    """The issue numbers the entries hold, ignoring the ones too broken to name one."""
    return {entry["issue"] for entry in entries
            if isinstance(entry.get("issue"), int)
            and not isinstance(entry.get("issue"), bool)}


def _held_item_citations(entries: list[dict]) -> set[str]:
    """The item ids the entries cite.
    Only ``noni.order/2`` gives an entry an ``item`` field, which is why a
    ``noni.order/1`` file answers the empty set: the artifact this run read cites no
    item and said so, and an empty set is the honest report about it rather than the
    blindness answer. The class that reads this fills in when sub-issue 2 adds the
    field, and its shape is pinned in ``tests/test_census_items_group.py`` so it is not
    invented then.
    """
    return {entry["item"] for entry in entries
            if isinstance(entry.get("item"), str)}


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
        if _field(body, "status") != STATUS_CANDIDATE:
            continue
        created_text = _field(body, "created")
        if not isinstance(created_text, str):
            continue  # the malformed class already reported it
        created = itemschema.parse_timestamp(created_text)
        if created is None:  # the malformed class already reported it
            continue
        age = now - created
        if age > item_stale_after:
            add(ITEM_STALE, stem, f"{rel_store}/{stem}.json",
                f"stale: created {created_text} is {age.days} day(s) before "
                f"--now, past the {item_stale_after} threshold")
