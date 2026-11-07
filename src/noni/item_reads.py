"""The two reads ``item.py`` borrows from the direction layer: the order and a record.

Mechanics, not the writer's contract. ``item.py`` owns the verbs, the exit codes and
the commit; ``orderstate.py`` owns the reads of the order artifact and the ledger as
*the order writer* needs them, with the refusal wording that writer prints. A promote
needs a different answer from the same file -- not "may this run write over the
order" but "does any entry cite this item" -- and asking the first question to get
the second is how a run that read nothing comes back agreeing with a run that read
an order citing nothing. So the two reads a *reader* of that state needs live here,
beside the module they read through, and reach the artifact's rules through
``orderstate`` and ``orderschema`` rather than a third copy of either.

Nothing here prints, exits or decides an exit code: each answer travels back as a
value, and the caller words its own refusal.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import itemschema, labels, orderschema, orderstate
from ._safe_text import safe_text


def read_order_entries_or_fault(path: Path) -> list[dict] | None:
    """The entries of a canonical ``noni.order/1`` file, or None when it is not one.

    The order read a reader asks. Unlike :func:`noni.orderstate.read_order` it
    refuses nothing, because a caller that only wants to know whether an entry cites
    something gets an honest answer from an absent file (an empty list) and no answer
    at all from a file it could not read (``None``). The distinction is the caller's
    to word; this function's whole job is to keep it from collapsing silently into
    "no entry cites it", which would let a promote through on an order the run never
    read.

    Returns ``None`` for every state in which no reading was made: the path is not a
    readable regular file, the bytes do not parse, the shape is not the artifact, or
    the bytes are not the canonical form the order family writes. Returns ``[]`` for
    the one state that is an answer rather than a fault: no file at all, which is the
    state of a project that has never ordered anything.

    The strict reader and the shape rules are the ones ``orderstate`` and
    ``orderschema`` already own, reached as package imports -- the writer's reads and
    the arbiter's reads of one file must be one definition, and the ``RecursionError``
    arm is named because it is no kind of ``ValueError``: the depth bound answers for
    a document short of the interpreter's own ceiling, past which the decoder raises
    this one first.
    """
    kind, _why = orderstate.file_kind(path)
    if kind == "absent":
        return []
    if kind != "regular":
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        value = orderschema.load_json_checked(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(value, dict) or orderschema.problems(value):
        return None
    if orderstate.render(orderstate.body_of(value)) != raw:
        # The canonical comparison, asked of the same renderer the order writer
        # compares against: a file the writer would refuse is a file whose entries
        # this run cannot vouch for, so it answers nothing rather than something.
        return None
    return [dict(item) for item in value["entries"]]


def order_cites_item(repo: Path, item_id: str) -> tuple[bool, bool]:
    """(cited, answered): whether an order entry cites ``item_id``, and whether that
    question could be answered at all.

    The one question ``item.py promote`` asks of the direction layer, and the two
    answers it must not confuse: ``False`` with ``answered`` True is the order this
    run read and found no citation in, and ``False`` with ``answered`` False is no
    reading at all -- which the caller refuses rather than promotes through.

    The entry's own key is asked with ``.get`` because the item field of the order is
    sub-issue 2's: a ``noni.order/1`` entry carries ``issue``, ``decision`` and
    ``confirmed`` and nothing else, so today nothing cites an item and the honest
    answer is the empty scan. The day the order gains the field, the scan already
    asks the right question and only the order's schema changes.
    """
    entries = read_order_entries_or_fault(repo / orderschema.ORDER_REL)
    if entries is None:
        return False, False
    return any(entry.get("item") == item_id for entry in entries), True


def store_listing(repo: Path, report, exit_io: int) -> tuple[list[Path] | None, int | None]:
    """The store's one listing, or the refusal code a faulted read earned.

    ``report`` is the caller's own refusal printer (code, headline, hint) — this
    module prints nothing and chooses no code, so the writer's voice stays in the
    writer and the reader's answers travel back as values.

    One ``iterdir``, never ``glob``: a store the run could not list must stop the add
    rather than read as a store holding nothing, which is how a duplicate title would
    slip past a scan handed an empty listing. The fault is an environment one (the
    caller's exit-3 code) because nothing about the item being filed is wrong. The
    listing is taken once per run and handed to whichever scan needs it, so the gate
    and the scan cannot disagree about what the store holds.
    """
    store = repo / itemschema.ITEM_DIR
    kind, why = orderstate.file_kind(store)
    if kind == "absent":
        # The state before the first add: an honest answer to the duplicate scan
        # ('no dropped item carries that title'), never a fault to report.
        return [], None
    if kind != "dir":
        return report(exit_io, f"{itemschema.ITEM_DIR} could not be listed: "
                    f"{why or 'not a readable directory'}",
                       f"restore {itemschema.ITEM_DIR} as a directory, then re-run "
                       f"{labels.ITEM}"), None
    try:
        return sorted(store.iterdir()), None
    except OSError as exc:
        return report(exit_io, f"{itemschema.ITEM_DIR} could not be listed "
                    f"({exc.__class__.__name__}: {exc.strerror or exc})",
                       f"check that {itemschema.ITEM_DIR} is readable, then re-run "
                       f"{labels.ITEM}"), None


def scan_item(path: Path) -> dict | None:
    """One file of the store's listing, read as far as a scan needs. None is "skip".

    Not a regular file, unreadable, unparseable, or not an item this shape describes:
    the scan is not the census and reports nothing. The probe-honesty rule of the
    census must not leak into the writer's success path, so a broken file never holds
    up an add -- it is simply a file this scan saw nothing about.
    """
    kind, _why = orderstate.file_kind(path)
    if kind != "regular":
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        value = orderschema.load_json_checked(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(value, dict) or itemschema.problems(value):
        return None
    return itemschema.body_of(value)


def listing_bodies(repo: Path, report, exit_io: int) -> tuple[list[dict] | None,
                                                              int | None]:
    """Every item the store holds, for ``list``, or the refusal code it earned.

    Same one-listing rule as the duplicate scan, same skip-don't-fail rule about
    individual files: an item nobody can read is the census's to report, and a listing
    that died on one broken file would tell the operator nothing about the store they
    asked to see. A file whose contents name another item is left out, because the
    listing prints what an item is, not what a stray file says.
    """
    paths, code = store_listing(repo, report, exit_io)
    if code is not None:
        return None, code
    bodies: list[dict] = []
    for path in paths or []:
        if path.suffix != ".json":
            continue
        body = scan_item(path)
        if body is not None and path.stem == body["id"]:
            bodies.append(body)
    return bodies, None


def listing_line(body: dict) -> str:
    """One line of ``list``: the id, its status, its title, then what it cites.

    Every free text goes through the package's one renderer before it reaches the
    terminal, because a title and a reason are operator input: a value carrying a
    control character cannot split a line of the listing, and a value of any length
    cannot make a row longer than the bound.
    """
    detail = [f"created={body['created']}"]
    if body["issue"] is not None:
        detail.append(f"issue=#{body['issue']}")
    if body["decision"] is not None:
        detail.append(f"decision={body['decision']}")
    if body["why"] is not None:
        detail.append(f"why={safe_text(body['why'])}")
    return (f"  {body['id']} [{body['status']}] {safe_text(body['title'])} "
            + " ".join(detail))


def read_item(path: Path, item_id: str, report, exit_io: int, exit_refusal: int):
    """The item at ``path``, or the refusal code with its line already printed.

    ``(None, None)`` is absence, which the caller decides the meaning of: an absent
    item is the "no such item" refusal of drop and promote, and the empty store a
    first ``add`` extends. A file that is there and is not the artifact is refused
    rather than overwritten, because destroying a record the operator committed is
    worse than refusing the run.
    """
    rel = itemschema.item_rel(item_id)
    kind, why = orderstate.file_kind(path)
    if kind == "absent":
        return None, None
    if kind != "regular":
        return report(exit_io, f"{rel} is not a readable regular file: "
                   f"{why or 'not a regular file'}",
                       "remove that path or point --repo at the tree that holds the "
                       f"item, then re-run {labels.ITEM}"), None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return report(exit_io, f"{rel} could not be read "
                   f"({exc.__class__.__name__}: {exc.strerror or exc})",
                       f"check that {rel} is readable, then re-run {labels.ITEM}"), None
    try:
        value = orderschema.load_json_checked(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        # The package's one strict reader, so the writer and the census answer one
        # document alike. The wording is fixed and names none of the bytes: they are
        # content this writer did not write, and a refusal that quotes them prints
        # them. RecursionError is no kind of ValueError -- the depth bound answers
        # short of the interpreter's own ceiling, past which the decoder raises it
        # first, so the arm is reachable and not decorative.
        return report(exit_refusal,
                       f"{rel} is not valid JSON this writer can extend",
                       f"repair the file (it must hold {itemschema.ITEM_SCHEMA}) or "
                       f"remove it and re-file the idea with {labels.ITEM} add"), None
    found = itemschema.problems(value)
    if found:
        return report(exit_refusal,
                       f"{rel} is not an item this writer writes: "
                       + "; ".join(found),
                       f"repair the file to the documented shape "
                       f"({itemschema.ITEM_SCHEMA}) or remove it and re-file the idea "
                       f"with {labels.ITEM} add"), None
    if value["id"] != item_id:
        return report(exit_refusal,
                       f"{rel} carries id {value['id']!r}, which is not the item's "
                       "own name",
                       "the id and the file's stem are the same name: repair one of "
                       "them, or remove the file and re-file the idea with "
                       f"{labels.ITEM} add"), None
    if itemschema.item_bytes(itemschema.body_of(value)) != raw:
        return report(exit_refusal,
                       f"{rel} is not in the canonical form this writer writes "
                       "(its keys, their order or its indent)",
                       f"have {labels.ITEM} write it, or repair and commit it in that "
                       f"form, then re-run {labels.ITEM}"), None
    return itemschema.body_of(value), None


def dropped_title_taken(repo: Path, title: str, report, exit_io: int,
                        exit_refusal: int) -> int | None:
    """The exit-4 refusal for a title a dropped item already carries, or None.

    An idea already killed is recorded as killed: re-filing its title verbatim is the
    operator asking for that record again, so the add refuses and names the item that
    holds the reason. A file the scan could not read is skipped rather than fatal, so
    the run still exits 0 when the matching dropped file is itself unreadable and
    therefore unable to have matched -- the census's honesty belongs to the census.
    """
    paths, code = store_listing(repo, report, exit_io)
    if code is not None:
        return code
    for path in paths or []:
        if path.suffix != ".json":
            continue
        body = scan_item(path)
        if (body is None or body["status"] != itemschema.STATUS_DROPPED
                or body["title"] != title):
            continue
        return report(exit_refusal,
                       f"an item titled {title!r} was already dropped as {path.stem}",
                       "the record of why it was dropped is the answer: file the idea "
                       "under a different title, or restore that item by its id")
    return None


def refuse_cited_order(repo: Path, item_id: str, report, exit_io: int,
                       exit_refusal: int) -> int | None:
    """The refusal ``promote`` owes an order that cites this item, or None.

    Promote is item-only in this sub-issue, so an order that already cites the item
    is refused rather than left pointing at a newly promoted item the same commit did
    not rewrite. The question is answered by :func:`order_cites_item` beside this
    function, which distinguishes "no entry cites it" from "the order could not be
    read", and the two get different codes: the first is no refusal at all, the second
    is the caller's environment code naming the order path, because a run that read
    nothing may not promote on the strength of not having read it. Sub-issue 2 replaces
    this refusal with the same-commit order rewrite.

    The two refusals are built here and printed through the caller's ``report``, the
    way every other read in this module hands its answer back: the reader keeps the
    question and the wording of its answer, and the writer keeps its codes, its voice
    and the choice of when the question is asked at all.
    """
    cited, answered = order_cites_item(repo, item_id)
    if answered and not cited:
        return None
    if not answered:
        return report(exit_io, f"{orderschema.ORDER_REL} could not be read, so "
                     "whether an order entry cites this item cannot be answered",
                       f"repair or remove {orderschema.ORDER_REL}, then re-run the "
                       "item writer")
    return report(exit_refusal,
                  f"{orderschema.ORDER_REL} has an entry that cites item {item_id}, "
                  "so promoting the item alone would leave the order out of step",
                  f"the order is what has to change: correct that entry in "
                  f"{orderschema.ORDER_REL} with the order writer in the same commit "
                  "as the promotion; until the order carries items, remove it and "
                  "re-run promote")
