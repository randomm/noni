"""The citations an item makes, and the ones the order makes to it.

Split out of ``census_items.py`` for the size limit, along the seam the two halves
already had: that module owns what a store file *is* (its shape, its status, its age),
this one owns what it *points at* -- an item's ``decision`` against the ledger, and an
order entry's ``issue``/``item`` against the store. Both directions are read-only
questions over the same three artifacts, and the two groups of classes ask them of the
same one read each, which is what keeps a citation and its target from being judged by
two different readings of one file.

Nothing here prints or exits, and nothing here opens a file: the reads are handed in
at the call (``read_record``, ``load_json_strict``, ``file_kind``) exactly as the group
hands them in, so the census keeps its single owner of the row shape and of every
fault the filesystem can raise.
"""

from __future__ import annotations

from pathlib import Path

from .census_items_names import (
    _CHAIN_STEPS,
    ITEM_REFERENCE_UNRESOLVED,
    LEDGER_REL,
    RECORD_STATUSES,
    STATUS_SUPERSEDED,
)


def _field(body: dict, field: str):
    """One field of an item the group is allowed to read, or ``None`` for no answer.

    ``itemschema.body_of`` keeps only the eight known fields, so a document the scan
    accepted always carries all eight and could be indexed directly. The defensive read
    is for the path a caller other than the reader takes: a hand-made document that
    skipped a key is still a mapping that parsed, and a census that indexed it blindly
    would end the whole run with a ``KeyError`` on one bad file. The census is read-only
    and must answer, not crash, so a field that is not there is read as the state every
    class already treats as "this run holds no answer for it".
    """
    return body.get(field)


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
    """``item-reference-unresolved``: an item whose ``decision`` names no live record.
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
        decision = _field(body, "decision")
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
