"""The item group's citation and successor checks over the run's ledger reads.

The three classes here all answer a question about a *decision record*: whether an item's
``decision`` names a record that stands, whether a promoted item cites one at all, and
whether the promotion the item claims was ever ordered. Each of those questions belongs to
one record in ``noni/decisions/``, and the ledger group has already read every one of them
to answer its own. This module asks nothing a prior read answered, and takes no read the
store's own items did not ask for: it reads the ledger through the map the census passes
in, so the citation classes are linear in the store, not the product of the store and the
ledger.

The census's strict reader is handed in at the call, as it is everywhere the census reads
a committed file: what this arbiter can read is exactly what the ledger's writer can
write, and a second copy of the reader's refusals is never born here.

One rule of this class reads the queue rather than the ledger: an entry of
``noni.order/2`` whose ``item`` names no file under the store. It sits here because it is
the same defect as an unresolvable ``decision`` -- a reference that resolves to nothing --
seen from the artifact that holds it, and one class reporting both is what lets an
operator fix the reference however it was written (:func:`_dangling_order_items`).
"""

from __future__ import annotations

from pathlib import Path

from .census_items_names import (
    _CHAIN_STEPS,
    ITEM_REFERENCE_UNRESOLVED,
    LEDGER_REL,
    RECORD_STATUSES,
    STATUS_SUPERSEDED,
    STORE_SUBJECT,
)

# The subject and the artifact of a row about the *order's* side of class 55. A row
# about one item file is keyed by the item's stem and rooted into the store; a row
# about an entry of the order is about the order, so it names the order artifact and
# takes the order's path as its subject, the way the ordering group's whole-artifact
# rows name ``noni/direction/order.json``. Spelled here rather than imported from
# ``census_ordering``: this package's groups never import each other, and the shared
# shape table holds the two spellings to one string.
ORDER_SUBJECT = "noni/direction/order.json"
ORDER_ARTIFACT = ORDER_SUBJECT

# One field of this module's own making, kept beside the two words the ledger holds. It
# says whether the run opened the file and read them, or was handed the answer by a prior
# pass. A word the run did not read is never stated as absent: the chain walk has to tell
# an unread ``supersedes`` from a record that genuinely names nothing, and an invented
# null would silently stop a chain that was only unseen.
_READ_KEY = "read"


def _field(body: dict, field: str):
    """``body``'s ``field`` when the document holds it, else None.

    The citation classes ask one word of each item and one word of each record, and none of
    them may raise on the shape a malformed document presents: a body that is not a mapping
    is the store group's finding, and this group reads no word from a body that is not a
    mapping rather than failing on it.
    """
    if not isinstance(body, dict):
        return None
    return body.get(field)


def _cited_ids(bodies) -> set[str]:
    """The record ids the items of this store cite, and nothing else.

    The set that decides which ledger files a run has to open at all: a record no item
    names holds no answer this group needs, so it costs no read. The class therefore pays
    for the ledger the items asked about plus the chains those citations lead through,
    which is linear in the store and the records it cites -- not in the product of the two,
    which is what a run that re-walked the directory per citing item came to.
    """
    cited = {_field(body, "decision") for _stem, body in bodies}
    cited.discard(None)
    return {record_id for record_id in cited if isinstance(record_id, str)}


def _listed_ids(ledger_names) -> set[str] | None:
    """The ledger's own listing as ids, or ``None`` when the caller had no probe.

    ``None`` means "no listing was handed in" and the reader lists the directory itself;
    an empty set is the listing that answered "no records", which is an answer and must not
    be read as the same absence.
    """
    if ledger_names is None:
        return None
    return {name[: -len(".json")] for name in ledger_names
            if name.endswith(".json")}


def _read_record_fields(ledger: Path, record_id: str, *, read_record,
                        load_json_strict):
    """One record's two words, from one open of its file.

    Returns the map (``status``, ``supersedes`` and ``_READ_KEY`` true) or ``None`` when
    this run could not read the file or the document was not a mapping -- the blindness the
    citation class words as a cannot-tell and never as a verdict. Only the two words are
    kept, never the raw value: the ledger belongs to the ledger group, this group needs two
    words out of it, and a map of whole records would be a second copy of the directory in
    memory for a question about two keys.

    The status is kept exactly as the document states it, including a word the group does
    not know: the ledger group's own pass is what refuses a record for that, and a class
    that folded an unrecognised word into ``None`` would report its own uncertainty where
    the ledger has already reported the project's. ``supersedes`` is the exception -- the
    chain walk compares it against a name, and only a string can be that name.
    """
    raw, fault = read_record(ledger / (record_id + ".json"))
    if fault is not None or raw is None:
        return None
    try:
        value = load_json_strict(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(value, dict):
        return None
    supersedes = value.get("supersedes")
    return {
        "status": value.get("status"),
        "supersedes": supersedes if isinstance(supersedes, str) else None,
        _READ_KEY: True,
    }


def _record_fields(ledger: Path, record_id: str, *, ledger_names, records,
                   read_record, load_json_strict):
    """One record's two words, taken from the run's read or taken once.

    ``records`` is the map the census built from the ledger group's own validation pass --
    every record that pass parsed, already carrying its words. A record in it is answered
    from it and costs no open, which is the whole point of the map: the citation class asks
    the ledger two questions the ledger group asked first.

    A record the map does not hold has two causes and the listing tells them apart: a name
    the probe listed is a record the ledger group did not read (unreadable, malformed, or a
    pass that never ran) and is opened here exactly once; a name the listing does not carry
    is a record that is not there, and the answer is the absence, not a read. Either result
    is written back into ``records``, so the next item asking the same question is answered
    from the map rather than the disk -- which is what keeps the class's cost at one open
    per record rather than one per item.
    """
    if record_id in records:
        return records[record_id]
    if ledger_names is not None and (record_id + ".json") not in ledger_names:
        return None
    fields = _read_record_fields(ledger, record_id,
                                 read_record=read_record,
                                 load_json_strict=load_json_strict)
    records[record_id] = fields
    return fields


def _successor(ledger: Path, cited: str, *, ledger_names, records,
               read_record, load_json_strict) -> str | None:
    """The live record the operator should cite in place of the dead record ``cited``.

    The ledger stores the chain in one direction only -- a record's ``supersedes`` names
    the decision *it* replaced -- so nothing points forwards from a dead record to its
    replacement. The replacement is found by the question that can be asked of every
    record: who says they replaced this one. That is :func:`_heir_of`, and it is the same
    question ``orderstate._successor`` asks before it accepts a citation, which is the
    point of the row: the census names the id the writer would have named.

    The answer is then followed, and the following is what makes a two-step chain answer
    at all. A record that replaced the cited one may itself have been replaced, in which
    case a third record names *it*, and the id the operator wants is the last of those --
    the first record in the run that is live. So each step asks who replaced the record the
    last step reached, and the walk stops at the first live answer. Stopping at the first
    answer instead would name a record that is itself superseded and send the operator to
    cite a decision the ledger has already buried.

    ``None`` where no live record ever answers: the row then says only that the citation is
    superseded, and a chain this run cannot see is not a chain it may name. A record the
    run could not read is skipped rather than crashed on -- the class names a successor
    when it can and never guesses one.

    The cost is the bound this class exists to set. Each step reads only what the shared
    map does not already hold, so a walk of a chain N links deep opens N records and never
    the ledger N times; the whole walk runs once per *distinct cited record* for the run
    (``_check_citations`` memoises the answer per id, so twenty items citing one dead record
    pay for one walk); and the step count is capped at ``_CHAIN_STEPS``, the number the
    ledger group puts on its own chain check, so a ``supersedes`` loop is that class's
    finding and never this one's hang. Where several live records name the same decision the
    greatest name wins, ids being dated -- ``ledger-chain`` calls that duplication a finding
    of its own.
    """
    current = cited
    for _step in range(_CHAIN_STEPS):
        heir = _heir_of(ledger, current, ledger_names=ledger_names, records=records,
                        read_record=read_record, load_json_strict=load_json_strict)
        if heir is None:
            return None
        fields = records.get(heir) or {}
        if fields.get("status") not in (None, STATUS_SUPERSEDED):
            return heir
        if heir == current:
            # A record naming itself: the walk cannot move and the ledger group owns the
            # finding, so this one stops rather than spinning.
            return None
        current = heir
    return None


def _heir_of(ledger: Path, replaced: str, *, ledger_names, records,
             read_record, load_json_strict) -> str | None:
    """The newest record that says it replaced ``replaced``, live or not.

    Only a record's own body says which decision it replaced, so answering this means
    asking every record in the listing -- the one pass of the ledger the successor question
    costs, and the same pass the ledger group's chain check makes. A record whose status the
    run could not read is not an answer; a *superseded* one is still reported, because the
    walk in :func:`_successor` is what decides whether a link is the last word or a step.

    Both functions read through :func:`_record_fields`, so a record one step opened is
    answered from the map for the next step and for the ledger group afterwards.
    """
    heirs = []
    for name in _ledger_json_names(ledger, ledger_names):
        other = name[: -len(".json")]
        fields = _record_fields(ledger, other, ledger_names=ledger_names,
                                records=records, read_record=read_record,
                                load_json_strict=load_json_strict)
        if fields is None or fields.get("status") not in RECORD_STATUSES:
            continue
        if fields.get("supersedes") == replaced:
            heirs.append(other)
    return max(heirs) if heirs else None


def _ledger_json_names(ledger: Path, ledger_names) -> list[str]:
    """The ledger's ``*.json`` names: the run's listing when it has one, else a listing.

    The single place this module reaches the directory, so the one rule that decides
    whether the census walks ``noni/decisions/`` for itself -- ``None`` means no probe was
    handed down and the group must answer for itself -- is stated once rather than copied
    into every loop.
    """
    if ledger_names is not None:
        return [name for name in ledger_names if name.endswith(".json")]
    return sorted(path.name for path in ledger.glob("*.json"))


def _store_names(store: Path, *, file_kind, read_record, load_json_strict) -> set[str] | None:
    """The ids the item store names, or ``None`` when this run cannot tell.

    ``None`` is the blindness answer, and it is the only answer a run that could not
    list ``noni/items/`` may give: a citation checked against a partial listing reports
    a live idea as a reference to nothing, which is a verdict built out of this run's
    own inability. A store that is simply not there answers the empty set -- that is a
    project that filed no idea, which is a fact about the project and not a fault --
    and an entry citing any id is then dangling.

    ``file_kind`` is the census's classifier, asked of the directory as a directory
    and of each file as a file; ``read_record`` is the census's open-time-safe reader
    and the store is listed with ``Path.iterdir``, never ``glob`` (which swallows the
    ``OSError`` a faulted readdir raises and would hand back the empty set -- the
    verdict of a project that filed no idea -- for a store nobody could open). Every
    document is parsed with the strict reader the whole group obeys.
    """
    kind, _problem = file_kind(store, "dir")
    if kind == "absent":
        return set()
    if kind != "regular":
        return None
    try:
        names = sorted(path for path in store.iterdir()
                       if path.suffix == ".json")
    except OSError:
        # Any refusal to list a store that is there is blindness: the group may not
        # answer "no such item" about a directory it could not open. The class object
        # is named only so the except binds nothing unused.
        return None
    for path in names:
        kind, _why = file_kind(path)
        if kind != "regular":
            return None
        raw, fault = read_record(path)
        if fault is not None or raw is None:
            return None
        try:
            value = load_json_strict(raw)
        except (UnicodeDecodeError, ValueError, RecursionError):
            return None
        if not isinstance(value, dict):
            return None
        if not isinstance(value.get("id"), str):
            return None
    return {path.stem for path in names}


def _dangling_order_items(store: Path, entries, add, *,
                          file_kind, read_record, load_json_strict,
                          clipped) -> None:
    """``item-reference-unresolved`` for an order entry whose ``item`` names no file.

    The other half of class 55. The item file's ``decision`` is answered by
    :func:`_check_citations`; this answers the order's side of the same contract -- a
    citation must name something that exists -- and it belongs to the same class
    because it is the same defect seen from the queue rather than the store: the
    artifact holds a reference that resolves to nothing.

    It is emphatically **not** routed through the ordering group's ``--issue-state``
    cannot-tell arm. That arm answers for tracker issues, and only for issues the map
    was asked about: a ``/2`` entry naming an item names no issue at all, so the
    closed check has nothing to be silent about here, and the row is emitted from this
    module with no severity override at all -- class 55's own severity, which is a
    fail. A dangling item is not "the census could not tell whether this is work":
    the store holds no such file, and that is a verdict the run reached by looking.
    The one cannot-tell this function may emit is about its own reads (an order or a
    store it could not open), and it is marked as such.

    One entry may cite nothing (an issue entry): its ``item`` is asked with ``.get``,
    so a ``/1`` file contributes no candidate and the class stays silent on it.
    """
    if not entries:
        return
    cited = {entry["item"] for entry in entries
             if isinstance(entry.get("item"), str)}
    if not cited:
        return
    held = _store_names(store, file_kind=file_kind, read_record=read_record,
                        load_json_strict=load_json_strict)
    if held is None:
        # The order says an entry cites an idea and this run could not look in the
        # store to say whether the idea is there: this run's blindness, a warn that
        # --strict promotes, never a verdict on the project.
        add(ITEM_REFERENCE_UNRESOLVED, ORDER_SUBJECT, ORDER_ARTIFACT,
            clipped(f"cannot-tell: {ORDER_ARTIFACT} cites "
                    f"{len(cited)} item(s) and the item store could not be read, "
                    "so whether the citations name a file was not answered"),
            severity="warn", whole_artifact=True)
        return
    for item_id in sorted(cited - held):
        add(ITEM_REFERENCE_UNRESOLVED, ORDER_SUBJECT, ORDER_ARTIFACT,
            clipped(f"unresolved: an entry of {ORDER_ARTIFACT} cites item "
                    f"{item_id}, which no file under {STORE_SUBJECT}/ names"))


def _check_citations(bodies, ledger: Path, ledger_names, add, rel_store: str, *,
                     read_record, load_json_strict, clipped,
                     records: dict[str, dict | None] | None) -> None:
    """``item-reference-unresolved``: an item whose ``decision`` names no live record.
    Asked of every item that cites a record, in any status: a dropped item's link is
    the record that killed it and a promoted item's is the record that ordered it, so
    a citation resolving to nothing leaves the kill list untraceable. Three answers,
    three shapes -- the record is not there (a finding), the record is there and
    superseded (a finding, which names its successor when the ledger holds one), and
    the run could not tell (a cannot-tell, never a verdict).

    The cost is bounded by what the store asks. Each cited record is answered from the
    census's ``records`` map when the ledger group's validation pass read it, and by one
    open otherwise -- never once per item, because the map is shared across the loop. A
    citation whose record is *superseded* costs one walk of the ledger to name the heir,
    and that walk is memoised per record id in ``_successor_cache``, so twenty items citing
    one dead record pay for the walk once. The successor question is the same one
    ``order.py`` asks before it accepts a citation, so the row can name the record the
    operator should cite instead of only saying the citation is dead.
    """
    listed = _listed_ids(ledger_names)
    # The census hands the map the ledger group built straight to this loop, and this
    # class writes its own reads back into it: a record opened for one item is answered
    # from the map for every later item and for every chain that walks through it. A
    # caller with no map to share passes None, and the run then holds its own -- still
    # one open per record for this run, which is the bound that matters.
    if records is None:
        records = {}
    # One entry per distinct citation: the successor a record answered once is the
    # successor every later item citing it is told about, without a second walk.
    cache: dict[str, str | None] = {}
    for stem, body in bodies:
        decision = _field(body, "decision")
        if decision is None:
            continue
        if listed is not None and decision not in listed:
            add(ITEM_REFERENCE_UNRESOLVED, stem, f"{rel_store}/{stem}.json",
                f"unresolved: the item cites decision {decision}, which no file "
                f"under {LEDGER_REL}/ carries")
            continue
        fields = _record_fields(ledger, decision, ledger_names=ledger_names,
                                records=records, read_record=read_record,
                                load_json_strict=load_json_strict)
        if fields is None:
            # Either the record is not there (no listing, so the probe cannot say) or this
            # run could not read it. The listing already answered "not there" above, so
            # what is left is blindness, and the run's own blindness is never a verdict on
            # the project: the row carries the cannot-tell severity override explicitly
            # (see ``_row``) and --strict still promotes it like any other cannot-tell.
            add(ITEM_REFERENCE_UNRESOLVED, stem, f"{rel_store}/{stem}.json",
                clipped(f"cannot-tell: the record {decision} the item cites could "
                        "not be read, so whether it stands was not answered"),
                severity="warn", whole_artifact=True)
            continue
        state = fields["status"]
        if state not in RECORD_STATUSES:
            # Either the record states no status or states one outside the set; both are
            # the ledger group's finding (``ledger-record``), and this class has no answer
            # of its own to give. It is a cannot-tell and not a verdict: the row carries
            # the override explicitly (see ``_row``) and --strict promotes it like any
            # other cannot-tell.
            add(ITEM_REFERENCE_UNRESOLVED, stem, f"{rel_store}/{stem}.json",
                clipped(f"cannot-tell: the record {decision} the item cites carries "
                        "no status this census can read, so whether it stands was not "
                        "answered"),
                severity="warn", whole_artifact=True)
        elif state == STATUS_SUPERSEDED:
            if decision not in cache:
                cache[decision] = _successor(
                    ledger, decision, ledger_names=ledger_names, records=records,
                    read_record=read_record, load_json_strict=load_json_strict)
            heir = cache[decision]
            add(ITEM_REFERENCE_UNRESOLVED, stem, f"{rel_store}/{stem}.json",
                f"unresolved: the item cites decision {decision}, which is "
                f"superseded{'' if heir is None else f' by {heir}'}")
