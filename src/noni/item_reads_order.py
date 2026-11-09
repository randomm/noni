"""The order read a promote needs: the citation, and the rewrite it owes.

Split from ``item_reads`` for the file-size limit, along the seam the two halves already
are: ``item_reads`` answers what the item store and a borrowed record say, and this
module answers what ``noni/direction/order.json`` says about one item. The reads still
go through ``orderstate`` and ``orderschema`` rather than a third copy of either, and
nothing here prints, exits or decides an exit code -- each answer travels back as a
value, and the caller words its own refusal.

The one reason these reads are not ``orderstate.read_order`` is stated there and
repeated nowhere else: the writer's read answers "may this run write over the order"
and refuses what it would not itself write, and a promote needs to know what the order
says.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from . import orderschema, orderstate
from .item_reads import _order_entries_if_artifact

# The answers ``promote`` distinguishes, in one NamedTuple each, so the verb branches on
# names rather than on the position of a slot in a pair.


class CitedOrder(NamedTuple):
    """What promote needs from the order when an entry cites the item it promotes.

    ``entries`` are the artifact's entries with the citing one rewritten to name the
    issue the item became, and ``before`` the bytes this run read them from -- what the
    freshness guard compares HEAD, the file and the index against before a byte of the
    two-path commit is staged. ``None`` in the first slot means no entry cited the item
    and there is nothing to rewrite, so the promote stays the single-path commit it was.

    ``refused_code`` is the exit code the caller returned for this answer, and it is
    meaningful only when the read refused: the printer that words a refusal takes the
    code as an argument and gives no answer back, so the reader hands the number out
    here instead of leaving the verb to guess which of its two codes applied.
    """

    entries: list[dict] | None
    before: bytes | None
    refused_code: int | None = None


class DuplicateIssue(Exception):
    """The rewrite ``promote`` was asked for would name one issue twice.

    Raised by :func:`rewrite_citation` rather than answered with a code: this module
    prints nothing and chooses no exit code, so the number belongs to the writer that
    publishes the table. The caller turns it into the same exit-4 refusal ``order.py``
    gives "issue N is already in the order".

    It is raised only of a list that owes a rewrite, because a list nothing cites would
    duplicate nothing: the exception answers "the rewrite is impossible", never "this
    issue happens to be in the order".
    """

    def __init__(self, issue: int) -> None:
        super().__init__(f"issue {issue} is already in the order")
        self.issue = issue


def order_for_promote(repo: Path, item_id: str, issue: int, report, exit_io: int,
                      exit_refusal: int) -> CitedOrder | None:
    """The order rewrite ``promote`` owes a citing entry, or None when nothing cites it.

    ``None`` is no answer at all: the read printed its refusal, in the order writer's
    words, and hands its code back through :attr:`CitedOrder.refused_code` of the pair
    this returns beside it. That is the shape a caller branches on -- a refusal carries
    the code that reader chose (3 for a path it could not open, 4 for bytes that are not
    the artifact) and a real answer carries none -- and it exists because a verb that
    printed a refusal and then exited 0 is the one outcome worse than either code.
    The one whose ``entries`` is ``None`` is the case the order has nothing to do: no
    artifact at all, or one that cites something else, and the promote writes only the
    item, which is the single-path commit the writer promised before the order carried
    items.

    When an entry does cite the item, this returns the whole entry list with that
    entry's ``item`` key replaced by the ``issue`` the item became. The caller renders
    it through the order's own renderer and commits it beside the item file in one
    commit, because promoting an item the order still cites -- leaving a promoted item
    whose position rests on an idea that no longer needs ordering -- is the disagreement
    the item census classes exist to report.

    The two faults that stop it keep the codes ``order.py`` gives the same states.
    """
    read = _read_order_entries(repo, report, exit_io, exit_refusal)
    if isinstance(read, tuple) and len(read) == 2 and read[0] is None:
        # The refusal's code came back in the second slot of the reader's pair: the
        # printer words the two lines and returns the number, which is the only way a
        # code survives a read whose printer is a callback. Exiting 0 over a printed
        # refusal is the one outcome the writer may not produce, so no branch here
        # returns without one.
        return CitedOrder(None, None, read[1])
    if read is None:
        return CitedOrder(None, None, exit_io)
    entries, before = read
    rewritten = rewrite_citation(entries, item_id, issue)
    if rewritten is None:
        return CitedOrder(None, before)
    return CitedOrder(rewritten, before)


def _read_order_entries(repo: Path, report, exit_io: int,
                        exit_refusal: int) -> tuple[list[dict], bytes | None] \
    | tuple[None, int] | None:
    """The artifact's entries and the bytes they came from, or a printed refusal.

    Each fault calls ``report`` with the code ``order.py`` gives the same state -- the
    caller's I/O code for a path it could not open, its refusal code for bytes that are
    not the artifact -- and ``report`` returns that code, which :func:`order_for_promote`
    carries out in :attr:`CitedOrder.refused_code` rather than dropping it: a verb that
    printed a refusal and then exited 0 is the one answer worse than either.

    Absence is an answer rather than a fault, and it is the answer "nothing cites
    this item": the caller gets an empty list and a ``None`` before, which is what
    the freshness guard reads as "no file, and still no file".
    """
    path = repo / orderschema.ORDER_REL
    kind, why = orderstate.file_kind(path)
    if kind == "absent":
        return [], None
    if kind != "regular":
        return None, report(exit_io, f"{orderschema.ORDER_REL} is not a readable "
                           f"regular file: "
               f"{why or 'not a regular file'}",
               f"repair or remove {orderschema.ORDER_REL}, then re-run the item "
               "writer")
    try:
        raw = path.read_bytes()
    except OSError:
        return None, report(exit_io, f"{orderschema.ORDER_REL} could not be read, so "
                          "whether an "
               "order entry cites this item cannot be answered",
               f"repair or remove {orderschema.ORDER_REL}, then re-run the item "
               "writer")
    entries = _order_entries_if_artifact(raw)
    if entries is None:
        # The artifact's own defect, and the code ``order.py`` gives the same bytes:
        # not "could not be read" (the file was read) and not a citation (no entry was
        # vouched for). The order is what has to change, so the hint says so.
        return None, report(exit_refusal,
               f"{orderschema.ORDER_REL} is not an order this reader can check, so "
               "whether an entry cites this item cannot be answered",
               f"repair {orderschema.ORDER_REL} to the documented shape "
               f"({' or '.join(repr(name) for name in orderschema.ORDER_SCHEMAS)}) "
               "with the order writer, then re-run the item writer")
    return [dict(entry) for entry in entries], raw


def rewrite_citation(entries: list[dict], item_id: str,
                     issue: int) -> list[dict] | None:
    """The entries with the one citing ``item_id`` turned into an issue entry, or None.

    ``item`` is removed and ``issue`` set, so the entry keeps the two fields it always
    had and swaps only its subject; the keys the renderer emits afterwards are the
    documented order of the version the rewritten list belongs to. ``None`` is "no
    entry cites it", which is the caller's signal to commit one path rather than two.

    :raises DuplicateIssue: only when a rewrite is owed, that is, when some entry does
    cite ``item_id`` *and* another entry already names the issue the citing one would
    take. That is the duplicate ``order.py add`` refuses and the census calls malformed
    -- an artifact the writer could emit once and never rewrite again. An order that
    lists the issue but cites nothing answers ``None`` like any other order with nothing
    to do, because a promote that rewrites no entry cannot duplicate anything.
    """
    cited = False
    rewritten: list[dict] = []
    for entry in entries:
        if entry.get(orderschema.ITEM_FIELD) == item_id:
            cited = True
            entry = {key: value for key, value in entry.items()
                     if key != orderschema.ITEM_FIELD}
            entry["issue"] = issue
        elif cited and orderschema.entry_issue(entry) == issue:
            # The queue already holds this issue, so the rewrite would put one issue at
            # two positions -- the duplicate the writer's own ``add`` refuses and the
            # census reports as malformed. Refused here, at the read that would build it,
            # so no byte is written and the item keeps its ``candidate`` status: a
            # promoted item whose order still cites it is the half state this verb exists
            # to prevent, and an artifact no verb can open again is worse than a refusal.
            raise DuplicateIssue(issue)
        rewritten.append(dict(entry))
    return rewritten if cited else None
