"""The ``promote`` verb of ``item.py``: a candidate becomes the issue it became.

Split from ``item.py`` for the file-size limit, along the seam the verb itself makes:
``add``, ``list`` and ``drop`` each write one item file and finish, while ``promote`` is
the one verb that reaches outside the item store -- it reads the order, may rewrite an
entry of it, and needs the order writer's freshness guard and a two-path commit to do
that honestly. Everything a promote prints, exits or refuses is spelled here with the
codes the writer hands in, and the mechanics it calls are ``item_reads`` (its two reads)
and :mod:`noni.item_promote` (the two-path commit), with the order read itself in
:mod:`noni.item_reads_order`.

Nothing here declares an exit code: the three a refusal can carry arrive as arguments
the way ``orderstate`` takes them, so the one table of codes stays in ``item.py``, where
the docstring publishes it and the other three verbs use it. ``fail`` is the writer's own
printer, so a promote's refusal is printed in the item writer's voice and under its name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import item_promote, item_reads, item_reads_order, itemschema, labels, orderschema
from . import order_gitwrite as orderwrite

# The answer the order read gives when it refused the run: it printed its own two lines
# and chose its own code, which comes back beside this sentinel rather than in place of
# the entries, because a caller that read a refusal as "nothing cites it" would promote
# an item out from under an order it never opened. Distinguished from the two real
# answers by type -- this string where they carry ``None`` or a list.
REFUSED = "refused"


def promote(repo: Path, item_id: str, issue: int | None, raw_issue: str | None,
            no_commit: bool,
            fail: Callable[..., int], write, digests, exit_ok: int, exit_io: int,
            exit_usage: int, exit_refusal: int) -> int:
    """``promote``: mark a candidate as the issue it became, and rewrite the order.

    An order entry that cites the item is rewritten from ``item`` to the ``issue`` the
    idea became, in the same commit as the item file: half a promote would leave the
    queue pointing at an idea that no longer needs ordering. An order that cites nothing
    is left alone and the run stays the single-path commit it always was, so a project
    that never ordered its ideas sees no change from this verb.

    ``created`` is carried over, never restamped: promoting an idea does not make it
    younger.

    ``fail``, ``write`` and ``digests`` are the writer's own refusal printer, its
    single-path write and its commit-subject digest, handed in rather than imported so
    the voice, the ``--no-commit`` line and the code table stay in the one file that
    publishes them.
    """
    refused = _refuse_issue(issue, raw_issue, fail, exit_usage)
    if refused is not None:
        return refused
    assert issue is not None
    # The store before the item, for the reason ``drop`` gives in the writer: this verb
    # rewrites a record of a store this run may have to refuse to open.
    unlistable = item_reads.store_is_readable(repo, fail, exit_io)
    if unlistable is not None:
        return unlistable
    existing, code = item_reads.read_item(repo / itemschema.item_rel(item_id),
                                          item_id, fail, exit_io, exit_refusal)
    if code is not None:
        return code
    if existing is None:
        return fail(exit_refusal, f"no item {item_id} is filed under "
                    f"{itemschema.ITEM_DIR}/",
                    "file it first with 'item.py add ID --title TITLE'")
    if existing["status"] in itemschema.TERMINAL_STATUSES:
        return fail(exit_refusal, f"item {item_id} is already "
                    f"{existing['status']}, so there is nothing to promote",
                    "a promoted item is ordered with order.py, not re-promoted")
    try:
        entries, before = _refuse_cited_order(repo, item_id, issue, fail, exit_io,
                                              exit_refusal)
    except item_reads_order.DuplicateIssue as clash:
        # The queue already holds the issue this idea became, so the rewrite would name
        # one issue at two positions -- the duplicate ``order.py add`` refuses and the
        # arbiter reports as malformed. Refused before any byte is written: the item
        # stays a candidate and the order keeps the entry that still describes it.
        return fail(exit_refusal, f"issue {clash.issue} is already in the order, so "
                    f"promoting {item_id} to it would list that issue twice",
                    "remove the entry that holds it with 'order.py remove "
                    f"{clash.issue}', or promote the item to the issue it became")
    if entries is REFUSED:
        # The order refused the run and chose the code: exit 3 for a path it could not
        # read, exit 4 for bytes that are not an order. Nothing here is written.
        return before
    body = itemschema.entry(item_id, existing["title"], itemschema.STATUS_PROMOTED,
                            existing["created"], issue)
    if entries is None:
        return write(repo, body, f"promote {item_id}", no_commit)
    return _with_order(repo, body, entries, before, item_id, no_commit, fail, digests,
                       exit_ok, exit_io, exit_refusal)


def _refuse_issue(issue: int | None, raw: str | None, fail: Callable[..., int],
                  exit_usage: int) -> int | None:
    """The usage refusal for the ``--issue`` the verb was handed, or None.

    Two states and one code: a token that is not a positive integer (the caller spelled
    it, so the fix is to spell it again, and the sentence quotes the token it was
    given), and no token at all -- a promoted item is one that became an issue, and the
    schema refuses a ``promoted`` item carrying none, so a verb that wrote one would
    leave a file the next ``add`` refuses to write over and a census row the operator
    cannot repair by re-running anything. Refused at the verb that owes the field, the
    same way ``drop`` owes ``--decision`` and ``--why``.

    ``raw`` is the token as the operator typed it: ``issue`` arrives already parsed, so
    without the text a bad token and no token at all would answer one sentence and the
    operator would be told to pass what they just passed.
    """
    if raw is None:
        return fail(exit_usage, "promote needs --issue N: a promoted item is one "
                    "that became an issue, and one that names none was promoted to "
                    "nothing", "name the issue it became, e.g. --issue 42, or leave "
                    "it a candidate until an issue is filed for it")
    if issue is None:
        return fail(exit_usage, f"issue {raw!r} is not a positive integer",
                    "name the issue by its number, e.g. --issue 42")
    return None


def _refuse_cited_order(repo: Path, item_id: str, issue: int,
                        fail: Callable[..., int], exit_io: int, exit_refusal: int):
    """What ``promote`` asks the order, in the three answers the writer must tell apart.

    ``(REFUSED, code)`` is a refusal whose code the read chose (3 for a path it could not
    open, 4 for bytes that are not the artifact) and whose two lines it already printed;
    ``(None, before)`` is an order that cites nothing and needs no rewrite, and
    ``(entries, before)`` is the entry list with the citing entry turned into an issue
    entry. ``before`` is the bytes this run read, which is what the freshness guard
    compares HEAD, the file and the index against before either byte is staged, and
    ``None`` for a promote that read no artifact at all.

    A fourth answer is exceptional and travels as an exception rather than a slot: when
    the rewrite would duplicate an issue the queue already holds,
    :func:`noni.item_reads_order.rewrite_citation` raises
    :class:`noni.item_reads_order.DuplicateIssue` through here and the verb answers it.
    It is raised only of a list that owes a rewrite, so an order that merely lists the
    issue still gets the single-path answer above.

    The code travels in the second slot beside the sentinel because the reader keeps the
    wording of every refusal and leaves the code to the writer -- one table of codes, in
    the file that publishes them -- and a printer that only prints cannot hand a number
    back to its caller. See :func:`noni.item_reads_order.order_for_promote` for the read.
    """
    asked = item_reads_order.order_for_promote(repo, item_id, issue, fail, exit_io,
                                         exit_refusal)
    if asked is None or asked.entries is None and asked.refused_code is not None:
        # The read refused: it printed its two lines and handed back the code it chose.
        # A pair with no entries and no code is the ordinary "nothing cites this item"
        # answer and falls through, which is what keeps a project that never ordered its
        # ideas on the single-path commit it always had.
        return REFUSED, asked.refused_code if asked is not None else exit_io
    return asked.entries, asked.before




def _with_order(repo: Path, body: dict, entries: list, before: bytes | None,
                item_id: str, no_commit: bool, fail: Callable[..., int], digests,
                exit_ok: int, exit_io: int, exit_refusal: int) -> int:
    """The promote that rewrites the order: both renderings, one commit, or neither.

    Every check of both artifacts has passed by the time this runs, so the two renderings
    are the only work left, and the freshness guard is the last thing that can refuse: it
    is asked of the order before a byte is written or staged, which is the same ordering
    ``order.py`` gives its own lost-update check. The mechanics all live in
    ``item_promote``, which reuses the ledger writer's two-path staging and rollback and
    the order writer's probe rather than opening a third set of git steps; what stays
    here is the voice, the codes and the order the five steps run in.
    """
    try:
        pair = item_promote.plan(body, entries, itemschema.item_rel(item_id), before)
    except item_promote.Refused as refused:
        return fail(exit_refusal, refused.headline, refused.hint)
    verb = f"promote {item_id}"
    if not no_commit:
        refused = item_promote.guard(repo, pair, verb, str(repo), exit_io,
                                     exit_refusal)
        if refused is not None:
            return refused
    if item_promote.unchanged(repo, pair):
        print(f"{labels.ITEM}: {pair.item_rel} and {pair.order_rel} are unchanged; "
              "nothing to commit")
        return exit_ok
    seen: dict = {}
    try:
        item_promote.write(repo, pair, seen)
    except OSError as exc:
        # The undo runs before a word of this is printed: ``item_promote.write`` writes
        # the item first and lets the OSError out of whichever path failed, and the
        # handler's job is to put the tree back rather than report a half promote. The
        # headline is the order writer's own wording of an OSError, which is the module
        # that owns ``written``; the undo is handed what ``write`` saw at the item path
        # (through ``seen``, because a write that raised never got to return it) so it
        # never deletes a record this run did not create. ``seen`` is empty only when the
        # fault came before that observation, which means nothing was written and the one
        # arm of the undo that removes a file has nothing it is entitled to remove.
        unredone = (None if not seen else
                    item_promote.rollback(repo, pair,
                                          bool(seen["item_existed"])))
        headline = unredone or orderwrite.written(
            exc, "the promoted item and its order entry could not be written")
        return fail(exit_io, headline,
                    f"check that {itemschema.ITEM_DIR} and "
                    f"{orderschema.ORDER_DIR} are writable, then re-run "
                    f"{labels.ITEM}")
    print(f"{labels.ITEM}: {item_id} is {body['status']} ({verb})")
    if no_commit:
        return _left_uncommitted(repo, pair)
    digest = digests(pair.item_bytes + pair.order_bytes)
    refusal = item_promote.commit(labels.ITEM, repo, pair, f"items: {verb} [{digest}]")
    if refusal is not None:
        return fail(exit_io, *refusal)
    print(f"{labels.ITEM}: committed {repo / pair.item_rel} and "
          f"{repo / pair.order_rel} ({verb})")
    return exit_ok


def _left_uncommitted(repo: Path, pair: item_promote.Pair) -> int:
    """The ``--no-commit`` report of a two-path promote: both paths, neither committed.

    Spelled beside the single-path verb's own line rather than shared with it, because
    the two runs leave different numbers of files for the caller to commit and the census
    reads the working tree: a reader has to learn which paths to commit from the run that
    made them.
    """
    print(f"{labels.ITEM}: wrote {repo / pair.item_rel} and "
          f"{repo / pair.order_rel}; left uncommitted: commit these paths before "
          "running the census")
    return 0
