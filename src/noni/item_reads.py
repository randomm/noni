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

    The entry's own key is asked with ``.get``: a ``noni.order/1`` entry carries
    ``issue``, ``decision`` and ``confirmed`` and nothing else, so a ``/1`` file
    answers the empty scan and that is the honest answer about a document that cites
    no item, not the blindness answer. A ``noni.order/2`` entry carries ``item`` and
    is scanned by the same line.
    The path is classified with ``orderstate.file_kind`` first, the way every other
    read of this family asks, and only the one state "no file" answers "no entry cites
    it": a plain file, a directory or a file whose bytes this run cannot read is no
    reading at all, never the empty list that would stand for "the order cites nothing".
    A promote answered on such a list is a run that read nothing agreeing with a run
    that read an order citing nothing, which is the failure this read exists to make
    impossible. The three states are therefore named here one at a time.

    This is a read of its own rather than a call to ``orderstate.read_order`` because
    the two answer different questions: the writer's read answers "may this run write
    over the order" and refuses what it would not itself write, while this one answers
    "does any entry cite this item", and the states it has to keep apart (absent,
    unreadable, not the artifact) are three answers to *that* question rather than two
    to the writer's.
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
    entries = _order_entries_if_artifact(raw)
    if entries is None:
        return False, "malformed"
    return (any(entry.get("item") == item_id for entry in entries), "read")


def _order_entries_if_artifact(raw: bytes) -> list | None:
    """The entries of ``raw``, or None unless it is the artifact in canonical form.

    Three questions, each asked of the owner that already answers it: the strict reader
    for the bytes no noni writer emits (non-finite numbers, a duplicate key, a nesting
    past the bound), ``orderschema.problems`` for the document's shape, and
    ``orderstate.render`` for the canonical form. All three because ``promote`` owes the
    same codes ``order.py`` owes for the same defects, and none of them relaxed here. An
    entry that carries the ``item`` field of ``noni.order/2`` inside a ``noni.order/1``
    document is not the artifact either version describes, so it is refused as a
    malformed order naming the order path, exactly as ``order.py`` refuses those bytes;
    a ``/2`` document whose entries hold the field is read, and is what a promote rewrites.
    """
    try:
        value = orderschema.load_json_checked(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(value, dict) or orderschema.problems(value):
        return None
    entries = [dict(entry) for entry in value["entries"]
               if isinstance(entry, dict)]
    # The version the document itself states, handed to the renderer rather than a
    # default: ``body_of`` keeps the marker precisely so a ``/2`` file is compared
    # against ``/2`` bytes, and asking for ``/1`` bytes here would make every citing
    # order a permanent refusal.
    rendered = orderstate.render({"schema": value["schema"], "entries": value["entries"]})
    if isinstance(rendered, orderstate.RenderRefused) or rendered != raw:
        return None
    return entries


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


