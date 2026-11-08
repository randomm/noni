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
import re
from pathlib import Path

from . import itemschema, labels, orderschema, orderstate
from ._safe_text import safe_text


def order_cites_item(repo: Path, item_id: str) -> tuple[bool, str]:
    """(cited, answer): whether an order entry cites ``item_id``, and what reading
    stands behind that answer.

    ``answer`` is ``"read"`` when this run holds the order's entries (``cited`` is then
    a verdict, ``False`` meaning "no entry cites it"), ``"absent"`` when the artifact is
    simply not there (the same verdict, from a project that never ordered anything), and
    ``"io"`` or ``"malformed"`` when no reading was made -- the first for a path this run
    could not open (a symlink, a directory, a device, an unreadable file), the second for
    bytes that are not the artifact. The caller gives the two faults the two codes
    ``order.py`` already gives them, and treats the first two answers alike: neither is a
    refusal.

    The entry's own key is asked with ``.get`` because the item field of the order is
    sub-issue 2's: a ``noni.order/1`` entry carries ``issue``, ``decision`` and
    ``confirmed`` and nothing else, so today nothing cites an item and the honest
    answer is the empty scan. The day the order gains the field, the scan already
    asks the right question and only the order's schema changes.

    The path is classified with ``orderstate.file_kind`` first, the way every other
    read of this family asks, and only the one state "no file" answers "no entry cites
    it": a plain file, a directory or a file whose bytes this run cannot read is no
    reading at all, never the empty list that would stand for "the order cites nothing".
    A promote answered on such a list is a run that read nothing agreeing with a run
    that read an order citing nothing, which is the failure this read exists to make
    impossible. The three states are therefore named here one at a time.

    Reads are lenient about one thing a *writer* is not, and the leniency is the whole
    reason this is a read of its own rather than a call to ``orderstate.read_order``: an
    entry carrying the ``item`` key the current entry schema does not name is read, not
    skipped. That key arrives with sub-issue 2's order artifact, and a scan that applied
    today's entry rules would report "no entry cites it" for the very entries whose
    citation this refusal exists to catch -- a clean exit through an entry the reader
    silently dropped. ``_order_bytes_are_artifact`` says exactly how far that leniency
    reaches.
    """
    path = repo / orderschema.ORDER_REL
    kind, _why = orderstate.file_kind(path)
    if kind == "absent":
        return False, "absent"
    if kind != "regular":
        return False, "io"
    try:
        raw = path.read_bytes()
    except OSError:
        return False, "io"
    if not _order_bytes_are_artifact(raw):
        return False, "malformed"
    entries = _order_entries_from(raw)
    if entries is None:
        return False, "malformed"
    return (any(entry.get("item") == item_id for entry in entries), "read")


def _order_bytes_are_artifact(raw: bytes) -> bool:
    """Whether ``raw`` holds an order this run can vouch for, byte for byte.

    Three questions, each asked of the owner that already answers it: the strict reader
    for the bytes no noni writer emits (non-finite numbers, a duplicate key, a nesting
    past the bound), ``orderschema.problems`` for the document's shape, and
    ``orderstate.render`` for the canonical form. All three because ``promote`` owes the
    same codes ``order.py`` owes for the same defects, and asked of the reader's own
    path rather than a shared strictness flag: "not the artifact" and "no artifact" are
    two codes and a reader must not collapse them.

    One rule is read with the entry schema's leniency rather than the writer's strictness:
    the ``item`` key. It is the field sub-issue 2 adds to ``noni.order/2``, and the whole
    point of this scan is that an entry carrying it today is still scanned, not dropped
    (see :func:`order_cites_item`). So the entry-level check is ``problems`` minus that
    one report; every other complaint the entry schema makes still refuses the file. The
    canonical comparison is made against the bytes of *this* document, entries and all,
    rather than of the writer's projection: ``orderschema.order_bytes`` drops ``item``
    on its way to the bytes, so a citing entry compared against that projection is never
    canonical and every ``/2`` order would be refused as malformed.
    """
    try:
        value = orderschema.load_json_checked(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return False
    if not isinstance(value, dict):
        return False
    found = orderschema.problems(value)
    if [problem for problem in found
            if not _is_item_field_report(problem)]:
        return False
    rendered = orderstate.render({"schema": value["schema"],
                                  "entries": _entry_projections(raw)})
    return not isinstance(rendered, orderstate.RenderRefused) \
        and _canonical_bytes_match(rendered, raw)


# The two shapes one citing entry makes of the artifact, and the two questions they are
# the answer to.
#
# ``orderschema.order_bytes`` renders an entry as its three fields and nothing else, so
# the bytes of an entry that also carries ``item`` are never the bytes that renderer
# produces. Both halves of that fact have to be handled together or ``/2`` is simply
# unreadable: the shape rule has to forgive the one complaint about that key, and the
# byte comparison has to be made against the artifact *with* the key restored rather than
# against the projection it renders.
_ITEM_FIELD_REPORT = re.compile(r"^entry \d+ has unknown field\(s\): ")


def _is_item_field_report(problem: str) -> bool:
    """Whether ``problem`` is the entry schema's complaint about the ``item`` key alone.

    Asked of the report's text and matched to the field name, so the leniency covers one
    key and nothing else: an entry with two unknown fields, one of them ``item``, still
    refuses the file. The shape is ``orderschema``'s own wording for that report; a
    second unknown field lands in the same joined list and fails this match.
    """
    match = _ITEM_FIELD_REPORT.match(problem)
    return bool(match) and problem[match.end():] == orderschema.ITEM_FIELD


def _canonical_bytes_match(rendered: bytes, raw: bytes) -> bool:
    """Whether ``raw`` is the canonical text of the document ``rendered`` came from.

    A file is canonical when its bytes are what the writer would have written for the
    document it holds -- with one allowance: the ``item`` key, which sits where the
    writer puts nothing because today's artifact has no such field. So the comparison is
    made after that key is taken back out of the file's bytes, and only an entry that
    carries it alone accounts for the difference. A file whose bytes differ any other way
    (key order, indent, spacing, an added or dropped key that is not ``item``) is not
    canonical and is refused: a promote must not rewrite an item on the strength of an
    order no writer produced.
    """
    if rendered == raw:
        return True
    return _strip_item_field(raw) == rendered


def _strip_item_field(raw: bytes) -> bytes:
    """``raw`` with a lone ``item`` key removed from each entry, leaving the rest.

    Not a re-render: the point is to ask whether the file's *own* bytes are canonical
    once the one key the writer cannot write is set aside, so a file that also has a bad
    indent or a reordered key stays different from what the writer produces and is
    refused. Text surgery rather than a parse-and-dump for the same reason: a parse
    cannot tell "canonical bytes" from "any bytes of the same value".
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return b""
    stripped = re.sub(r",\s*\"item\"\s*:\s*(?:\"[^\"\\]*(?:\\.[^\"\\]*)*\"|"
                      r"null|true|false|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", "", text)
    return stripped.encode("utf-8")


def _entry_projections(raw: bytes) -> list:
    """Each entry of ``raw`` reduced to the three fields the order writer writes.

    A projection of the document the file holds, taken field by field with ``.get`` so
    an entry missing one of the three renders as ``null`` (and is refused by
    ``orderschema.problems`` a line earlier) instead of raising here: the reader answers
    with a code and never with an exception. An entry carrying a key outside the three
    is reduced to them, because the entry-level check is the artifact's rules minus the
    item field this scan exists to read.
    """
    entries = _order_entries_from(raw) or []
    return [{field: entry.get(field)
             for field in ("issue", "decision", "confirmed")} for entry in entries]


def _order_entries_from(raw: bytes) -> list | None:
    """The entry list of a document already proven to be the artifact, or None."""
    try:
        value = orderschema.load_json_checked(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return None
    entries = value.get("entries") if isinstance(value, dict) else None
    if not isinstance(entries, list):
        return None
    return [dict(entry) for entry in entries if isinstance(entry, dict)]


def store_listing(repo: Path, report, exit_io: int) -> tuple[list[Path] | None, int | None]:
    """The store's one listing, or the refusal code a faulted read earned.

    ``(paths, None)`` is a listing this run holds (the empty list for a store that is
    not there, which is an answer and not a fault) and ``(None, code)`` is the refusal
    the caller returns unchanged. The code travels in the **second** slot for the same
    reason :func:`read_item` puts it there and not in the first: every caller of this
    read unpacks ``(paths, code)``, guards on ``code is not None`` and then iterates
    ``paths``, so a code in the first slot is an ``int`` handed to a ``for`` --
    ``TypeError: 'int' object is not iterable`` on the terminal instead of exit 3 and
    the two lines that name the path to repair. ``tests/test_item_writer_store_faults.py``
    drives each faulting shape through every verb and asserts the code, the two lines
    and the absence of a traceback.

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
        return None, report(exit_io, f"{itemschema.ITEM_DIR} could not be listed: "
                            f"{why or 'not a readable directory'}",
                             f"restore {itemschema.ITEM_DIR} as a directory, then "
                             f"re-run {labels.ITEM}")
    try:
        return sorted(store.iterdir()), None
    except OSError as exc:
        return None, report(exit_io, f"{itemschema.ITEM_DIR} could not be listed "
                            f"({exc.__class__.__name__}: {exc.strerror or exc})",
                             f"check that {itemschema.ITEM_DIR} is readable, then "
                             f"re-run {labels.ITEM}")


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


def store_is_readable(repo: Path, report, exit_io: int) -> int | None:
    """The exit-3 refusal for a store this run may not list, or None.

    The question ``drop`` and ``promote`` owe before they touch an item: a verb that
    reads one file inside ``noni/items/`` has no standing to change it while the
    directory that holds it cannot be opened. ``read_item`` answers for one path and
    cannot see this -- an item file is perfectly readable through a store directory
    whose *listing* is refused (a 000 directory keeps execute permission out of the
    read bit ``iterdir`` needs), and ``file_kind`` reads a declined ``lstat`` as
    absence, so an unreadable store would otherwise answer "no such item" (exit 4) or,
    one step later, write a new record into a store nobody could enumerate. The
    duplicate-title scan reaches the same refusal a moment afterwards on these verbs;
    asking it first is what keeps the run from rewriting an item on the strength of a
    store it never opened. ``tests/test_item_writer_store_faults.py`` pins both verbs.
    """
    _paths, code = store_listing(repo, report, exit_io)
    return code


def listing_line(body: dict) -> str:
    """One line of ``list``, in the bytes the contract of #124 states.

    ``<id> <status> issue=<n|-> decision=<id|-> created=<stamp> <title>``: five fixed
    fields in that order, so a reader can cut the line by field number, and a field
    the item does not carry prints as ``-`` rather than dropping out (a row that
    shifted its columns when an optional key was missing would make every reader
    guess). The title comes last and unlabelled because it is the one field that may
    hold a space, and the title is what goes through the package's one renderer: an
    operator's text, so a control character cannot split a line and a length cannot
    crowd the row out. The two bounds are the schema's own, so a row is never longer
    than the widest item the store can hold.
    """
    # ``.get`` rather than ``[]``: a document that omits an optional key it does not
    # owe is well-formed (``itemschema.problems`` accepts it, and it is the shape an
    # ``add`` writes), and a listing that walked into a KeyError over one would turn
    # the store's own readability on whether a writer happened to print the key.
    issue = body.get("issue")
    decision = body.get("decision")
    return (f"{body['id']} {body['status']} "
            f"issue={issue if issue is not None else '-'} "
            f"decision={decision if decision is not None else '-'} "
            f"created={body['created']} "
            f"{safe_text(body['title'], itemschema.TITLE_MAX)}")


def read_item(path: Path, item_id: str, report, exit_io: int, exit_refusal: int):
    """The item at ``path``, or the refusal code with its line already printed.

    ``(None, code)`` is a refusal the caller returns unchanged; ``(None, None)`` is
    absence, which the caller decides the meaning of: an absent item is the "no such
    item" refusal of drop and promote, and the empty store a first ``add`` extends. A
    file that is there and is not the artifact is refused rather than overwritten,
    because destroying a record the operator committed is worse than refusing the run.

    The code travels in the **second** slot, which is the only shape that keeps the two
    answers apart: a refusal in the first slot is an ``int``, and the callers that read
    ``existing["status"]`` straight after a ``code is not None`` test would walk into
    ``TypeError: 'int' object is not subscriptable`` on the very file this function
    exists to refuse. ``tests/test_item_writer_artifact.py`` drives every refused shape
    through a caller and asserts exit 4 with the file intact.
    """
    rel = itemschema.item_rel(item_id)
    kind, why = orderstate.file_kind(path)
    if kind == "absent":
        return None, None
    if kind != "regular":
        return None, report(exit_io, f"{rel} is not a readable regular file: "
                   f"{why or 'not a regular file'}",
                             "remove that path or point --repo at the tree that holds "
                             f"the item, then re-run {labels.ITEM}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, report(exit_io, f"{rel} could not be read "
                   f"({exc.__class__.__name__}: {exc.strerror or exc})",
                            f"check that {rel} is readable, then re-run "
                            f"{labels.ITEM}")
    try:
        value = orderschema.load_json_checked(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        # The package's one strict reader, so the writer and the census answer one
        # document alike. The wording is fixed and names none of the bytes: they are
        # content this writer did not write, and a refusal that quotes them prints
        # them. RecursionError is no kind of ValueError -- the depth bound answers
        # short of the interpreter's own ceiling, past which the decoder raises it
        # first, so the arm is reachable and not decorative.
        return None, report(exit_refusal,
                       f"{rel} is not valid JSON this writer can extend",
                       f"repair the file (it must hold {itemschema.ITEM_SCHEMA}) or "
                       f"remove it and re-file the idea with {labels.ITEM} add")
    found = itemschema.problems(value)
    if found:
        return None, report(exit_refusal,
                       f"{rel} is not an item this writer writes: "
                       + "; ".join(found),
                       f"repair the file to the documented shape "
                       f"({itemschema.ITEM_SCHEMA}) or remove it and re-file the idea "
                       f"with {labels.ITEM} add")
    if value["id"] != item_id:
        return None, report(exit_refusal,
                       f"{rel} carries id {value['id']!r}, which is not the item's "
                       "own name",
                       "the id and the file's stem are the same name: repair one of "
                       "them, or remove the file and re-file the idea with "
                       f"{labels.ITEM} add")
    if itemschema.item_bytes(itemschema.body_of(value)) != raw:
        return None, report(exit_refusal,
                       f"{rel} is not in the canonical form this writer writes "
                       "(its keys, their order or its indent)",
                       f"have {labels.ITEM} write it, or repair and commit it in that "
                       f"form, then re-run {labels.ITEM}")
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
    cited, answer = order_cites_item(repo, item_id)
    if answer in ("read", "absent") and not cited:
        return None
    if answer == "io":
        return report(exit_io, f"{orderschema.ORDER_REL} could not be read, so "
                     "whether an order entry cites this item cannot be answered",
                       f"repair or remove {orderschema.ORDER_REL}, then re-run the "
                       "item writer")
    if answer == "malformed":
        # The artifact's own defect, and the code ``order.py`` gives the same bytes:
        # not "could not be read" (the file was read) and not a citation (no entry was
        # vouched for). The order is what has to change, so the hint says so.
        return report(exit_refusal,
                      f"{orderschema.ORDER_REL} is not an order this reader can "
                      "check, so whether an entry cites this item cannot be answered",
                      f"repair {orderschema.ORDER_REL} to the documented shape "
                      f"({orderschema.ORDER_SCHEMA}) with the order writer, then "
                      "re-run the item writer")
    return report(exit_refusal,
                  f"{orderschema.ORDER_REL} has an entry that cites item {item_id}, "
                  "so promoting the item alone would leave the order out of step",
                  f"the order is what has to change: correct that entry in "
                  f"{orderschema.ORDER_REL} with the order writer in the same commit "
                  "as the promotion; until the order carries items, remove it and "
                  "re-run promote")
