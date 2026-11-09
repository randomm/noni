"""``item-reference-unresolved`` (55), the order's half: an entry whose ``item`` names nothing.

The class has two halves and they read two artifacts. An item's ``decision`` names a
record under ``noni/decisions/`` and is checked in ``tests/test_census_items_group.py``;
an entry of ``noni.order/2`` names an idea under ``noni/items/`` and is checked here.
Both are the same defect -- a reference that resolves to nothing -- reported by one
class, so the operator can fix the reference however it was written.

Three rules run through the file, one per way this half could be got wrong:

- **A dangling citation is a verdict, not a shrug.** The ordering group's
  ``--issue-state`` arm emits ``cannot-tell`` for an issue the map does not mention,
  and this half is *never* routed through it: a ``/2`` entry names no issue, so that
  arm has nothing to be silent about, and the store holds no such file, which is a
  finding at 55 with the class's own severity.
- **The run's own blindness is still a warn.** An order this run could not open, or a
  store it could not list, answers nothing: the row says ``cannot-tell``, and
  ``--strict`` promotes it like any other.
- **One class per defect, and both halves report.** A dropped idea the queue still
  cites is 53; an idea nobody ever filed is 55; one queue holding both earns two rows.

Builders and the launch are ``tests/census_items_group_support.py``, shared with the
other two suites so all three run the census the same way.
"""
from __future__ import annotations

from census_items_group_support import STORE
from census_items_group_support import commit as census_commit
from census_items_group_support import findings as _findings
from census_items_group_support import item as _item
from census_items_group_support import launch as _launch
from census_items_group_support import one as _one
from census_items_group_support import order as _order
from items_fixtures import BASELINE_ID, repo
from items_shapes import FRESH

ORDER_REL = "noni/direction/order.json"

ITEM_CLASSES_55 = ("--only", "item-reference-unresolved")


def _item_entry(item_id: str) -> dict:
    """One ``/2`` entry that cites an idea and names no issue.

    The shape ``order.py add --item`` writes: the two fields every entry has always
    carried, and ``item`` where an issue entry carries ``issue``. An entry that held
    both would be ``ordering-malformed`` and the dangling citation would never be
    reached, so the fixture has to be the one the writer produces.
    """
    return {"item": item_id, "decision": BASELINE_ID, "confirmed": FRESH}


def _issue_entry(issue: int = 7) -> dict:
    """One entry of either version that names an issue and cites nothing else."""
    return {"issue": issue, "decision": BASELINE_ID, "confirmed": FRESH}


def _state_file(tree, mapping: dict[int, str]):
    """An ``--issue-state`` map, as the flag expects it.

    Passing the flag is what makes the closed check's cannot-tell arm reachable at
    all: a test that omitted it would see no ``ordering-closed`` row for a reason
    unrelated to the entry under test, and would pass without having asked the
    question it exists to ask.
    """
    target = tree / "issue-state.json"
    target.write_text(
        "{\n" + "".join(f'  "{issue}": "{state}",\n'
                        for issue, state in mapping.items()) + "}\n",
        encoding="utf-8")
    return target


# --------------------------------------------------------------------------
# The finding: an entry whose item names no file
# --------------------------------------------------------------------------


def test_an_order_entry_whose_item_names_no_file_is_reported(tmp_path):
    """The queue cites an idea the store has never held.

    A reference that resolves to nothing is the same defect whether it sits in an
    item's ``decision`` or in an order entry's ``item``, and one class reporting both
    is what lets the operator fix the reference whichever artifact holds it.
    """
    tree = repo(tmp_path, "dangling-order-item")
    _item(tree, item_id="idea-0002")
    _order(tree, [_item_entry("ghost-idea")], schema="noni.order/2")
    census_commit(tree, "items and order")
    row = _one(tree, "item-reference-unresolved", *ITEM_CLASSES_55)
    assert row["code"] == 55
    assert row["severity"] == "fail", (
        "a dangling item is a verdict on the project, not this run's blindness: "
        f"{row}")
    assert "cannot-tell" not in row["message"].lower(), row["message"]
    assert "ghost-idea" in row["message"], row["message"]
    assert STORE in row["message"], row["message"]
    assert _launch(tree, *ITEM_CLASSES_55)[0] == 55, \
        "a dangling order citation moves the exit code on its own"


def test_the_row_names_the_order_and_not_an_item_file(tmp_path):
    """The row is about the artifact that holds the bad reference.

    A row keyed to a nonexistent item file would send the operator to look for a file
    that is not there; the order is what has to change, and the row says so in its
    subject, its artifact and its prose.
    """
    tree = repo(tmp_path, "dangling-row-shape")
    _item(tree, item_id="idea-0002")
    _order(tree, [_item_entry("ghost-idea")], schema="noni.order/2")
    census_commit(tree, "items and order")
    row = _one(tree, "item-reference-unresolved", *ITEM_CLASSES_55)
    assert row["subject"] == ORDER_REL, row
    assert row["artifact"] == ORDER_REL, row
    assert ORDER_REL in row["message"], row["message"]


def test_a_dangling_citation_is_never_a_cannot_tell_row(tmp_path):
    """The rule the acceptance criterion states outright, pinned as an absence.

    The ``--issue-state`` cannot-tell arm answers for tracker issues and only for the
    issues the map was asked about. With the flag given and one issue entry present,
    a run that also reported the item entry through that arm would produce an
    ``ordering-closed`` row here; it produces none, and its one row is a fail.
    """
    tree = repo(tmp_path, "dangling-not-cannot-tell")
    _item(tree, item_id="idea-0002")
    _order(tree, [_item_entry("ghost-idea"), _issue_entry()],
           schema="noni.order/2")
    census_commit(tree, "items and order")
    rows = _findings(tree, "--only", "item-reference-unresolved",
                     "--only", "ordering-closed", "--issue-state",
                     str(_state_file(tree, {7: "open"})))
    dangling = [row for row in rows if row["check"] == "item-reference-unresolved"]
    assert len(dangling) == 1, rows
    assert dangling[0]["severity"] == "fail", dangling[0]
    # The closed check ran (it was given a map) and answered for the issue entry; it
    # stayed silent on the entry that names an item, which is the whole rule.
    assert [row["check"] for row in rows if row["check"] == "ordering-closed"] == [], (
        f"the item entry was routed through the issue-state arm: {rows}")


def test_a_live_item_cited_by_an_order_earns_no_reference_row(tmp_path):
    """The citation resolves, so the class says nothing about it.

    Pinned beside the finding so the two cannot be collapsed: the run held the order's
    bytes and the store's listing and found the file, which is a different answer from
    the one above and earns a different verdict.
    """
    tree = repo(tmp_path, "order-cites-live-item")
    _item(tree, item_id="idea-0002")
    _order(tree, [_item_entry("idea-0002")], schema="noni.order/2")
    census_commit(tree, "items and order")
    assert _findings(tree, *ITEM_CLASSES_55) == []


def test_a_noni_order_1_file_can_cite_no_item_so_the_class_is_silent(tmp_path):
    """The version the queue had before items is not a dangling reference.

    Every entry of ``/1`` names an issue and a decision and nothing else, so the scan
    meets no ``item`` key and the honest answer about that file is silence -- which is
    why the class reads the field rather than requiring it.
    """
    tree = repo(tmp_path, "v1-cites-nothing")
    _item(tree, item_id="idea-0002")
    _order(tree, [_issue_entry()])
    census_commit(tree, "items and order")
    assert _findings(tree, *ITEM_CLASSES_55) == []


# --------------------------------------------------------------------------
# The blindness: this run could not look
# --------------------------------------------------------------------------


def test_a_dangling_citation_against_an_unreadable_store_reports_no_verdict(tmp_path):
    """The order says an entry cites an idea and this run could not look in the store.

    Reporting the citation as dangling would be a verdict built out of this run's own
    inability -- the inversion the group's blindness rule exists to prevent. The store
    has one blindness class of its own and it is the group's whole answer for a store
    it could not list: ``item-unlistable``, a warn that ``--strict`` promotes and that
    moves no exit code on its own. Class 55 adds no second row for the same unreadable
    directory, and never the fail the citation alone would earn.
    """
    tree = repo(tmp_path, "dangling-store-unreadable")
    _item(tree, item_id="idea-0002")
    _order(tree, [_item_entry("ghost-idea")], schema="noni.order/2")
    census_commit(tree, "items and order")
    (tree / STORE).chmod(0o000)
    try:
        rows = _findings(tree, *ITEM_CLASSES_55, commit_before=False)
        assert [row["check"] for row in rows] == ["item-unlistable"], rows
        assert rows[0]["severity"] == "warn", rows[0]
        assert _launch(tree, *ITEM_CLASSES_55)[0] == 0, \
            "the run's own blindness moves no code on its own"
        strict = _launch(tree, *ITEM_CLASSES_55, "--strict")
        assert strict[0] == 57, (strict[0], strict[1])
    finally:
        (tree / STORE).chmod(0o755)


def test_an_unreadable_order_earns_the_items_group_no_verdict(tmp_path):
    """A file this run could not open answers nothing, and 53 and 55 both hold their tongues.

    The ordering group owns the only row a malformed or unreadable order earns
    (``ordering-malformed``, on its own read of the same path). This group promoting
    an empty entry list into "the queue cites no dropped idea" is the inversion the
    blindness rule refuses, and the run's exit code is the ordering group's, not one
    of the items group's.
    """
    tree = repo(tmp_path, "order-unreadable-items")
    _item(tree, item_id="idea-0002", status="dropped", decision=BASELINE_ID,
          why="out of scope")
    _order(tree, [_item_entry("idea-0002")], schema="noni.order/2")
    census_commit(tree, "items and order")
    order = tree / ORDER_REL
    order.chmod(0o000)
    try:
        assert _findings(tree, "--only", "item-dropped-in-order",
                         *ITEM_CLASSES_55, commit_before=False) == []
    finally:
        order.chmod(0o644)


# --------------------------------------------------------------------------
# The two halves of the queue's contract, side by side
# --------------------------------------------------------------------------


def test_a_dangling_citation_and_a_dropped_one_are_two_rows_of_their_own(tmp_path):
    """Two defects in one queue, each reported under its own class.

    Both read the same artifact and both are fails, so a group that answered them as
    one class would leave the operator one repair short of a clean run -- and the two
    repairs differ: one idea has to be re-filed, the other has to come out of the
    order.
    """
    tree = repo(tmp_path, "dangling-and-dropped")
    _item(tree, item_id="idea-0001", status="dropped", decision=BASELINE_ID,
          why="out of scope")
    _order(tree, [_item_entry("idea-0001"), _item_entry("ghost-idea")],
           schema="noni.order/2")
    census_commit(tree, "items and order")
    exit_code, rows, out, err = _launch(tree)
    found = sorted((row["check"], row["subject"]) for row in rows
                   if row["check"].startswith("item-"))
    assert found == [("item-dropped-in-order", "idea-0001"),
                     ("item-reference-unresolved", ORDER_REL)], (found, out, err)
    # The lowest code wins, and 53 sits below 55: a defect outranks another defect.
    assert exit_code == 53, (exit_code, rows)


def test_a_promoted_item_the_order_cites_by_item_is_not_dropped_and_not_dangling(tmp_path):
    """One read of one artifact, and the entries that are right earn nothing.

    The queue holds a live idea and the store agrees it is promoted with an issue the
    same order holds, so neither order-reading class has a finding to make. Pinned
    because both classes read the same entries and a scan that mistook their subjects
    would report this queue twice.
    """
    tree = repo(tmp_path, "promoted-cited-clean")
    _item(tree, item_id="idea-0002", status="promoted", issue=7)
    _order(tree, [_item_entry("idea-0002")], schema="noni.order/2")
    census_commit(tree, "items and order")
    assert _findings(tree, "--only", "item-dropped-in-order",
                     *ITEM_CLASSES_55) == []


def test_an_unreadable_store_file_earns_the_order_citation_no_verdict(tmp_path):
    """One file the group could not open is enough to stop the order-side verdict.

    The citation is answered against the store's listing, so a run that read part of
    the store has no standing to call an idea absent from it: the malformed row for
    the unreadable file is reported (that is a finding about the project) and the
    citation class says nothing, which is the same split the store's own classes make.
    """
    tree = repo(tmp_path, "dangling-one-unreadable-file")
    _item(tree, item_id="idea-0002")
    (tree / STORE / "unreadable.json").write_text("{ not json", encoding="utf-8")
    _order(tree, [_item_entry("ghost-idea")], schema="noni.order/2")
    census_commit(tree, "items and order")
    rows = _findings(tree, *ITEM_CLASSES_55)
    assert [row["check"] for row in rows] == ["item-malformed"], rows


def test_a_store_that_holds_a_malformed_item_still_answers_the_citation(tmp_path):
    """A file the group read in full and found wrong still names an item.

    The store's key is the file's name, so a listing of files this run held answers
    the question "does any file carry this name" whatever their contents say. A
    citation to one of them is not dangling, and the defect in the file is reported
    by ``item-malformed`` rather than here.
    """
    tree = repo(tmp_path, "citation-to-malformed-file")
    _item(tree, item_id="idea-0002", status="nope")
    _order(tree, [_item_entry("idea-0002")], schema="noni.order/2")
    census_commit(tree, "items and order")
    rows = _findings(tree, *ITEM_CLASSES_55)
    assert rows == [], rows


def test_an_order_with_no_citing_entry_earns_no_reference_row(tmp_path):
    """The class reads the field rather than requiring it.

    A ``/2`` document whose entries all name issues is a queue in which the last item
    entry was promoted away, and the writer leaves the version marker alone until a
    run rewrites it. No entry cites an idea, so there is no citation to resolve and
    the store is never opened for it.
    """
    tree = repo(tmp_path, "v2-no-item-entry")
    _item(tree, item_id="idea-0002")
    _order(tree, [_issue_entry(7), _issue_entry(9)], schema="noni.order/2")
    census_commit(tree, "items and order")
    assert _findings(tree, *ITEM_CLASSES_55) == []


def test_two_entries_citing_the_same_absent_item_are_one_row(tmp_path):
    """One missing idea, one row.

    The subject of a row is the thing the caller joins on, and two rows naming one
    absent file would read as two defects to repair. The pair is also the shape a
    hand-edited order reaches, so the class folds the citation set before it asks the
    store, and the row is capped rather than repeated.
    """
    tree = repo(tmp_path, "same-dangling-twice")
    _item(tree, item_id="idea-0002")
    _order(tree, [_item_entry("ghost-idea"), _item_entry("ghost-idea")],
           schema="noni.order/2")
    census_commit(tree, "items and order")
    rows = [row for row in _findings(tree, *ITEM_CLASSES_55)
            if row["check"] == "item-reference-unresolved"]
    assert len(rows) == 1, rows


# --------------------------------------------------------------------------
# The read the two order classes share, on its own
# --------------------------------------------------------------------------


def _scan(tree, *extra):
    """The group's own read of the order artifact, asked directly.

    The run gives these classes one answer and words the row itself, so the states a
    subprocess cannot plant (a path whose classification the census's own classifier
    refuses, a document whose entry list is not a list) are asked of the reader here.
    The run-level tests above pin what the classes do with each answer.
    """
    from noni import census
    from noni.census_items_readers import order_scan
    from noni.census_json import load_json_strict

    return order_scan(tree / ORDER_REL, file_kind=census._file_kind,
                      read_record=_read_record, load_json=load_json_strict,
                      bounded=census._bounded)


def _read_record(path):
    from noni.census_intent_readers import read_record

    return read_record(path)


def test_a_directory_at_the_order_path_is_blindness_not_an_empty_queue(tmp_path):
    """A directory is not "an order holding nothing", and the reader says so.

    The two classes refuse to answer on this answer at all. Read as an empty entry
    list it would mean "this queue cites no idea and no dropped one", which is the
    clean verdict of a project that ordered nothing, reached without opening a file.
    """
    tree = repo(tmp_path, "scan-directory")
    (tree / ORDER_REL).parent.mkdir(parents=True, exist_ok=True)
    (tree / ORDER_REL).mkdir()
    scan = _scan(tree)
    assert scan.entries == () and scan.blind is not None, scan


def test_a_document_whose_entries_is_not_a_list_is_blindness(tmp_path):
    """A file this run read in full and cannot use still answers nothing.

    ``entries`` is the only part of the artifact either class asks, and a document
    that holds a number there has no queue to describe. The row that names the defect
    belongs to ``ordering-malformed``; this group's two classes hold their tongues.
    """
    tree = repo(tmp_path, "scan-entries-not-a-list")
    _order(tree, None, schema="noni.order/2")
    (tree / ORDER_REL).write_text('{"schema": "noni.order/2", "entries": 3}\n',
                                  encoding="utf-8")
    scan = _scan(tree)
    assert scan.entries == () and "entry list" in scan.blind, scan


def test_an_absent_order_reads_as_an_empty_queue_not_blindness(tmp_path):
    """No file is an answer: the ordering layer is optional.

    The two classes then find no citation and report nothing, which is the honest
    verdict about a project that never ordered an idea -- and it is kept apart from
    the states above by the reader rather than by a convention the reporter has to
    remember.
    """
    tree = repo(tmp_path, "scan-absent")
    scan = _scan(tree)
    assert scan.entries == () and scan.blind is None, scan
