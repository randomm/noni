"""The ``move``, ``remove`` and ``confirm`` plans: what the entries become.

``order.py`` owns the verbs, the exit codes, the probe and the commit; this module owns
the three verbs that rearrange the list the operator was shown. ``add`` -- the one verb
with two kinds of subject -- lives in :mod:`noni.order_add`; the four sit in two modules
because the two questions are different ones. ``add`` asks whether a subject exists and
where a new entry goes; these three ask which entry of the list is meant and what
happens to it, and all three refuse the same way when the list holds no such entry.

The list they hand back is the list the writer renders, and the ``verb`` is the sentence
the run prints and commits under (``move 7 to 2``, ``remove 7``, ``confirm all``), which
is why both come back together: the digest in the commit subject is taken over the plan,
and a run that printed one plan and committed another would name bytes it did not show.

Nothing here prints or exits. The exit codes arrive as arguments the way ``orderstate``
takes them, so the one table of codes stays in ``order.py``, where the docstring
publishes it; ``fail`` is that writer's own printer, so a refusal reads as coming from
the command that ran.

Why the plan is built before any write and never after: a reorder restamps the moved
entry (the operator confirming it again), so a plan computed from entries the writer had
already restamped would not be a plan anybody approved -- and the freshness guard later
compares the bytes of exactly this plan against what git holds.
"""

from __future__ import annotations

from typing import Callable, NamedTuple

from . import orderschema, orderstate


class Planned(NamedTuple):
    """The entries a verb writes, the word the run is named by, or a refusal.

    ``refusal`` carries the code the caller returns unchanged and is set only when the
    other two are empty, because the check that failed has already printed its two lines
    and chosen between the environment's code and the order's own.
    """

    entries: list
    verb: str
    refusal: int | None


def plan_move(entries: list, subject: int | str, to: str | None, stamp: str,
              fail: Callable[..., int], exit_usage: int,
              exit_refusal: int) -> Planned:
    """The list ``move`` writes: the entry taken out and put back at ``--to``.

    A move restamps the entry it moved: reordering the queue is the operator confirming
    the position again, so the entry leaves with a fresh ``confirmed`` rather than the
    one its original placement carried. ``--to`` is a position of the list this run
    produces, which is the same length the entry left behind, so the bound is the current
    count and not that count minus one.

    ``subject`` is an issue number or an item id, and the two never name the same entry:
    a string is looked up among the entries citing an idea and an int among those naming
    an issue, so ``move 7`` can never reach into an item's position by coincidence.
    """
    if not _holds(entries, subject):
        return Planned([], "", fail(exit_refusal, _absent(subject),
                                    "list it first with 'order.py add ISSUE "
                                    "--decision ID' or 'order.py add --item ID "
                                    "--decision ID'"))
    if to is None:
        return Planned([], "", fail(exit_usage, "move needs --to N: a move to no "
                                    "position is not a move",
                                    f"pass the 1-based position to move {subject} to, "
                                    "e.g. --to 1"))
    position, problem = orderstate.parse_index(to, "--to", len(entries))
    if problem is not None:
        return Planned([], "", fail(exit_usage, *problem))
    moved = next(entry for entry in entries if _names(entry, subject))
    moved = _restamped(moved, subject, stamp)
    rest = [entry for entry in entries if not _names(entry, subject)]
    rest.insert(position - 1, moved)
    return Planned(rest, f"move {subject} to {position}", None)


def _restamped(moved: dict, subject: int | str, stamp: str) -> dict:
    """``moved`` with a fresh ``confirmed``, in the key order its subject writes.

    Rebuilt from the entry's own ``decision`` rather than copied and patched, so the
    moved entry lands in the documented key order and not the order the file happened to
    hold it in -- the bytes the writer renders are the bytes the version documents.
    """
    if isinstance(subject, str):
        return orderschema.entry(item=subject, decision=moved["decision"],
                                 confirmed=stamp)
    return orderschema.entry(issue=subject, decision=moved["decision"], confirmed=stamp)


def _holds(entries: list, subject: int | str) -> bool:
    """Whether the list holds an entry naming ``subject``."""
    return any(_names(entry, subject) for entry in entries
               if isinstance(entry, dict))


def _names(entry: dict, subject: int | str) -> bool:
    """Whether ``entry`` is the one ``subject`` names, by the type of the subject.

    The one place the two kinds of subject are told apart for these three verbs, so a
    lookup written wrong is wrong once. A dict that is not an entry at all never matches:
    the shape rules have already refused the document, and a plan built from a list the
    caller still holds must not reach into a value that has no subject to compare.
    """
    if not isinstance(entry, dict):
        return False
    if isinstance(subject, str):
        return orderschema.entry_item(entry) == subject
    return orderschema.entry_issue(entry) == subject


def _absent(subject: int | str) -> str:
    """The refusal for a subject the queue does not hold, worded for its kind."""
    if isinstance(subject, str):
        return f"item {subject} is not in the order"
    return f"issue {subject} is not in the order"


def plan_remove(entries: list, subject: int | str, fail: Callable[..., int],
                exit_refusal: int) -> Planned:
    """The list ``remove`` writes: every entry but the one naming ``subject``.

    The only verb that shortens the list, and the only one whose refusal tells the
    operator nothing to do: a subject that is not in the queue is already not in it, and
    the artifact is left exactly as it was rather than rewritten to say so. An item
    removed from the queue keeps its record under ``noni/items/``: this verb drops a
    position, never an idea.
    """
    if not _holds(entries, subject):
        return Planned([], "", fail(exit_refusal, _absent(subject),
                                    "there is nothing to remove; the order is left as "
                                    "it is"))
    kept = [entry for entry in entries if not _names(entry, subject)]
    return Planned(kept, f"remove {subject}", None)


def plan_confirm(entries: list, subject: int | str | None, stamp: str,
                 fail: Callable[..., int],
                 exit_refusal: int) -> Planned:
    """The list ``confirm`` writes: the same entries, with ``confirmed`` restamped.

    With a subject, the one entry naming it; without one, every entry, which is how "the
    whole queue still stands" is said. The list is the same length and the same order in
    both cases -- a confirm places nothing and drops nothing -- and a subject the list does
    not hold is refused rather than confirmed into silence, because a run that reported
    success for an entry nobody can find would be reporting a confirmation that never
    happened.
    """
    if subject is not None and not _holds(entries, subject):
        return Planned([], "", fail(exit_refusal, _absent(subject),
                                    "add it first with 'order.py add ISSUE "
                                    "--decision ID' or 'order.py add --item ID "
                                    "--decision ID'"))
    confirmed = []
    for entry in entries:
        # A copy either way: the caller keeps the list it read for the lost-update
        # comparison, so a verb that restamped in place would move the very bytes the
        # guard later compares against HEAD. The identity test that a naive ``in`` gives
        # is not enough either -- two entries can be equal dicts naming different issues
        # -- so the choice is re-made from the subject rather than from identity.
        copy = dict(entry)
        if subject is None or _names(copy, subject):
            copy["confirmed"] = stamp
        confirmed.append(copy)
    name = "all" if subject is None else str(subject)
    return Planned(confirmed, f"confirm {name}", None)
