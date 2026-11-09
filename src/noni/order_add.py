"""The ``add`` plan: the subject the verb accepts and the entry it puts in the list.

``order.py`` owns the verbs, the exit codes and the commit; this module owns the one
verb that can name two kinds of subject. The split is the seam the two subjects make:
``add`` used to have one argument to validate and one entry to build, and an item
citation brings a second of each -- a second token at the flag, a second id rule, a
second file to look for before a position is granted to it, and a second "already in
the order" question answered against a different key.

Nothing here prints or exits: each answer is a value, and the exit codes travel in as
arguments the way ``orderstate`` takes them, so the one table of codes stays in the
writer that publishes it.

Why the checks land here and not later: an item id is what a path is built from, so a
token outside the ruled set is refused at the flag and never reaches a filesystem call,
which is the same rule ``orderstate.DECISION_ID_RE`` enforces for a decision id. And
the store is asked before the artifact is planned from, so a run that would order an
idea the store has closed is refused without writing anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, NamedTuple

from . import item_reads, itemschema, orderschema, orderstate


def subject_problems(issue_token: str | None,
                     item_token: str | None) -> tuple[str, str] | None:
    """The (headline, hint) usage refusal for the subject ``add`` was handed, or None.

    ``add`` takes one thing to place: an issue number or an item id. Both is two
    subjects in one entry and neither is a position for nothing, so both are refused
    at the flag rather than left for the artifact to discover. The check runs before
    any read, so a run refused here has opened no file and staged nothing.

    The two-subject half is asked of every verb, not just ``add``: the rearranging verbs
    reach an item entry with ``--item`` too, and a run that named both would have to
    choose between them silently. The "needs a subject" half belongs to ``add`` alone --
    ``confirm`` with none means every entry at once, and move and remove have refusals of
    their own that name the verb.
    """
    if issue_token is not None and item_token is not None:
        return ("one subject per run: an issue number or --item ID, not both",
                "drop one of them: an issue number names an issue's entry and --item "
                "names the entry citing that idea")
    if issue_token is None and item_token is None:
        return ("add needs an issue number or --item ID",
                "name the issue by its number, e.g. 42, or cite an idea the store "
                "holds with --item idea-0001")
    return None


def item_id_refusal(item_token: str, report: Callable[..., int],
                    exit_usage: int) -> int | None:
    """The exit-2 refusal for an ``--item`` token that could never name a file, or None.

    The store's own id rule (:func:`noni.itemschema.is_item_id`), asked before a path
    is built from the token. A name outside the ruled set is not an item that is
    missing, so it takes the caller's usage code rather than the "no such item"
    refusal a well-formed id earns: the fix is to type the name again, not to file it.
    """
    if itemschema.is_item_id(item_token):
        return None
    return report(exit_usage, f"--item {item_token!r} is not an item id",
                  "an item id is lowercase letters, digits, dots, underscores and "
                  "dashes, opens with a letter or a digit, and does not end in .json")


def item_ordering_refusal(repo: Path, item_id: str, report: Callable[..., int],
                          exit_io: int, exit_refusal: int) -> int | None:
    """The refusal for an ``--item`` the order may not hold, or None when it may.

    Three answers, three shapes, the same split ``orderstate.decision_problems`` makes
    for a decision citation. A store this run could not open is the environment's
    ``exit_io``: the order is not what is wrong, and a run that read nothing may not
    grant a position on the strength of not having read it. An id the store does not
    hold is the order's own ``exit_refusal`` -- the operator files the idea with the
    item writer first. A ``dropped`` idea is refused with ``exit_refusal`` too: it is
    recorded as an idea nobody is going to work, so a position in the queue for it is
    the operator asking for that record again, and the hint says which record holds
    the reason rather than offering the item writer, which refuses a terminal item.
    """
    unlistable = item_reads.store_is_readable(repo, report, exit_io)
    if unlistable is not None:
        return unlistable
    path = repo / itemschema.item_rel(item_id)
    body, code = item_reads.read_item(path, item_id, report, exit_io, exit_refusal)
    if code is not None:
        return code
    if body is None:
        return report(exit_refusal, f"no item {item_id} is filed under "
                      f"{itemschema.ITEM_DIR}/",
                      "file it first with 'item.py add ID --title TITLE', then order "
                      "it with 'order.py add --item ID --decision ID'")
    if body["status"] == itemschema.STATUS_DROPPED:
        return report(exit_refusal, f"item {item_id} is dropped, so it is not work to "
                      "order next",
                      "the record of why it was dropped stands: order a live idea, or "
                      "re-file the idea under its own id with 'item.py add' if the "
                      "queue really does hold it again")
    return None


class Planned(NamedTuple):
    """The entry ``add`` puts in the list, or the refusal naming why it puts nothing.

    ``entries`` is the list the writer renders -- the artifact's entries with the new
    one inserted at ``position`` -- and ``verb`` is the word the run prints and commits
    under (``add 7`` or ``add idea-0001``, the subject the entry names). ``refusal``
    carries the code the caller returns unchanged and is set only when the first two
    are empty, because the check that failed has already printed its two lines and
    chosen between the environment's code and the order's own.
    """

    entries: list
    verb: str
    refusal: int | None


def plan_add(repo: Path, entries: list, issue: int | None, item: str | None,
             decision: str, at: str | None, stamp: str, report, exit_io: int,
             exit_usage: int, exit_refusal: int) -> Planned:
    """The entries ``add`` writes, or the refusal naming why it writes none.

    Every question the verb owes is asked here, in the order whose remedies differ:
    the subject's own existence (an issue already listed, an item already listed, an
    item the store has never held or has closed), then the decision the position rests
    on, then the position itself -- because ``--at N`` is a position *of the list this
    run produces*, so it cannot be parsed until the count is settled, and a run that
    refused a bad position first would tell the operator about a position they were
    never going to fill.

    ``entries`` is copied rather than mutated: the caller keeps the list it read for
    the lost-update comparison, and a plan that reached into it would move the very
    bytes the guard later compares.
    """
    listed = [entry for entry in entries]
    subject, refusal = _subject(repo, listed, issue, item, report, exit_io,
                                exit_usage, exit_refusal)
    if refusal is not None:
        return Planned([], "", refusal)
    assert subject is not None
    cited = orderstate.decision_problems(repo, decision, exit_io, exit_refusal)
    if cited is not None:
        # The tuple's first slot is the code the lookup chose -- the environment's for
        # a ledger this run could not look in, the order's for a record that is not
        # there or is superseded -- so it is returned unchanged, not re-picked here.
        return Planned([], "", report(*cited))
    position, problem = _position(at, len(listed) + 1, report, exit_usage)
    if problem is not None:
        return Planned([], "", problem)
    listed.insert(position - 1, _new_entry(subject, decision, stamp))
    return Planned(listed, f"add {subject}", None)


def _new_entry(subject: str | int, decision: str, stamp: str) -> dict:
    """The entry ``add`` places, spelled from its subject's own type.

    An id is a string and an issue number is an int, and that is the whole difference
    between the two shapes: the same call, the key chosen by the type, so a run can never
    write an entry that names both subjects or neither -- the pair the schema refuses.
    """
    if isinstance(subject, str):
        return orderschema.entry(item=subject, decision=decision, confirmed=stamp)
    return orderschema.entry(issue=subject, decision=decision, confirmed=stamp)


def _subject(repo: Path, entries: list, issue: int | None, item: str | None,
             report, exit_io: int, exit_usage: int,
             exit_refusal: int) -> tuple[str | int | None, int | None]:
    """The subject the new entry names, or the refusal naming why there is none.

    The two questions the two subjects ask: is this thing already in the queue (which
    is answered against ``issue`` for an issue and ``item`` for an item, since a
    position for one is not a position for the other), and does the subject exist to
    be placed at all -- a question only the item can answer wrong, because an issue
    number is not something this writer can look up.
    """
    if item is not None:
        bad = item_id_refusal(item, report, exit_usage)
        if bad is not None:
            # A token the store can never name a file for: the usage code, because the
            # fix is to type the name again and not to file the idea. Asked before the
            # store is opened, so a name outside the rule pays no git and no readdir.
            return None, bad
        missing = item_ordering_refusal(repo, item, report, exit_io, exit_refusal)
        if missing is not None:
            return None, missing
        if any(orderschema.entry_item(entry) == item for entry in entries):
            position = next(i for i, entry in enumerate(entries, 1)
                            if orderschema.entry_item(entry) == item)
            return None, report(exit_refusal,
                                f"item {item} is already in the order at position "
                                f"{position}",
                                f"move it with 'order.py move {position} --to N', or "
                                "restamp it with 'order.py confirm'")
        return item, None
    assert issue is not None
    if issue in orderschema.listed_issues(entries):
        position = next(i for i, entry in enumerate(entries, 1)
                        if orderschema.entry_issue(entry) == issue)
        return None, report(exit_refusal,
                            f"issue {issue} is already in the order at position "
                            f"{position}",
                            f"move it with 'order.py move {issue} --to N', or "
                            "restamp it with 'order.py confirm'")
    return issue, None


def _position(at: str | None, count: int, report, exit_usage: int
              ) -> tuple[int, int | None]:
    """The 1-based position to insert at, or the refusal naming why there is none.

    ``--at`` absent is the end of the list, which is why the count arrives already
    including the entry being added; a value outside it is the caller's mistake and
    takes the usage code with the range spelled back to it.
    """
    if at is None:
        return count, None
    position, problem = orderstate.parse_index(at, "--at", count)
    return (position, None) if problem is None else (0, report(exit_usage, *problem))
