"""The ``move``, ``remove`` and ``confirm`` plans, and the command line they parse from.

``order.py`` owns the verbs, the exit codes, the probe and the commit; this module owns
the three verbs that rearrange the list the operator was shown. ``add`` -- the one verb
with two kinds of subject -- lives in :mod:`noni.order_add`; the four sit in two modules
because the two questions are different ones. ``add`` asks whether a subject exists and
where a new entry goes; these three ask which entry of the list is meant and what
happens to it, and all three refuse the same way when the list holds no such entry.

The usage line and the parser of the verb slot are here too -- both are decisions about
what the caller typed rather than about the order, and both were moved out of
``order.py`` for the file-size limit, which is the same seam ``item.py`` used for its own
command line (:mod:`noni.item_cli`). The parser holds no exit code and no verb list of
its own: both arrive as arguments, so the one table of codes and the one verb tuple stay
with the writer whose docstring publishes them.

The list they hand back is the list the writer renders, and the ``verb`` is the sentence
the run prints and commits under (``move 7 to 2``, ``remove 7``, ``confirm all``), which
is why both come back together: the digest in the commit subject is taken over the plan,
and a run that printed one plan and committed another would name bytes it did not show.

Nothing here prints or exits, apart from the parser's own usage refusals -- which print
argparse's usage line and this writer's exit code only because both were handed in. The
exit codes arrive as arguments the way ``orderstate``
takes them, so the one table of codes stays in ``order.py``, where the docstring
publishes it; ``fail`` is that writer's own printer, so a refusal reads as coming from
the command that ran.

Why the plan is built before any write and never after: a reorder restamps the moved
entry (the operator confirming it again), so a plan computed from entries the writer had
already restamped would not be a plan anybody approved -- and the freshness guard later
compares the bytes of exactly this plan against what git holds.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, NamedTuple

from . import labels, orderschema, orderstate

# The usage line, spelled once and handed to argparse as ``usage=``.
#
# argparse composes a usage line as ``optionals + positionals``, unconditionally, so
# with ``--repo`` required and five flags declared before the verbs, ``order.py
# --help`` rendered ``... [--no-commit] subcommand [issue]`` and buried the one word
# the caller has to choose. The docstring's ``Usage:`` block and
# ``skills/direction/SKILL.md`` both spell the verb first, and a help line that
# contradicts the two texts a reader copies from is the bug (issue #77).
#
# A literal is the only public way to put the verb first. A formatter subclass used to
# derive the line from argparse's private ``_format_usage`` and
# ``_format_actions_usage``, and 3.14 removed the second: every usage print then died
# with an ``AttributeError`` (issue #98). A literal keeps the rendering inside
# argparse, which still prepends ``usage:`` and wraps at ``COLUMNS``.
#
# The flag block is the parser's own declaration, in declaration order, with the
# metavar argparse prints for each, and it is compared against that declaration by
# ``tests/test_order_writer_usage.py`` and the flag-set parity of
# ``tests/test_order_writer_docs.py``: a flag added to the parser belongs here too.
USAGE = (f"{labels.ORDER} --repo REPO subcommand [issue]"
         " [--at N] [--to N] [--decision ID] [--item ID] [--why REASON]"
         " [--now ISO-8601] [--no-commit] [-h]")

# The missing-positional message argparse composes for a required positional, and
# the line argparse prints above it. argparse turns this refusal into usage-plus-
# error itself, so the verbs are added to *that* pair rather than to the message
# text: a subclass that re-raised it would print its own usage instead, and
# ``first_usage_line`` reads the ``usage:`` line out of the refusal.
MISSING_SUBCOMMAND = "the following arguments are required: subcommand"


class VerbedParser(argparse.ArgumentParser):
    """The parser of a one-verb writer, naming the verbs when the verb is missing.

    ``order.py --repo R`` with no verb got argparse's own refusal, which names the
    slot (``subcommand``) and not the words that fill it: only an *invalid* verb
    reached the fix line that named them, so the commonest mistake printed the
    least useful answer (issue #98). This parser keeps argparse's own refusal and
    adds the verbs to it, so the usage line, the wording and the exit code are
    unchanged and one more line names the accepted verbs.

    The parser shape is deliberately untouched: ``add_subparsers`` or ``choices=``
    would name the verbs too, but both move the verb out of the usage line and take the
    refusal off the path the pinned wording stands for.

    ``verbs`` arrives from the writer so the unknown-verb refusal, the missing-verb
    hint and the documents cannot be handed three different sets, and ``usage_exit``
    arrives for the same reason as the codes: this module chooses none of them.
    """

    def __init__(self, *args, verbs: tuple[str, ...], usage_exit: int,
                 **kwargs) -> None:
        self._verbs = verbs
        self._usage_exit = usage_exit
        super().__init__(*args, **kwargs)

    def error(self, message: str):
        if MISSING_SUBCOMMAND in message:
            self.print_usage(sys.stderr)
            print(f"{self.prog}: {message}", file=sys.stderr)
            print(f"{self.prog}: fix: choose from: {missing_verb_hint(self._verbs)}",
                  file=sys.stderr)
            raise SystemExit(self._usage_exit)
        super().error(message)


def missing_verb_hint(verbs: tuple[str, ...]) -> str:
    """The verb list the missing-subcommand hint prints.

    Joined with the same "or" the unknown-verb refusal uses, so the two refusals of
    one mistake cannot answer it twice.
    """
    *first, last = verbs
    if len(first) == 1:
        return f"{first[0]} or {last}"
    return f"{', '.join(first)} or {last}"


# The rationale's key, read from the artifact's schema: a move keeps the field, so the
# plan asks for it by the name the writer and the censuses both use.
WHY_FIELD = orderschema.WHY_FIELD


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
              fail: Callable[..., int], exit_usage: int, exit_refusal: int,
              repo: Path | None = None, decision: str | None = None,
              exit_io: int = 0) -> Planned:
    """The list ``move`` writes: the entry taken out and put back at ``--to``.

    A move restamps the entry it moved: reordering the queue is the operator confirming
    the position again, so the entry leaves with a fresh ``confirmed`` rather than the
    one its original placement carried. ``--to`` is a position of the list this run
    produces, which is the same length the entry left behind, so the bound is the current
    count and not that count minus one. Without ``--to`` the entry keeps its place: the
    position it is taken out of is the one it is put back at, which is what makes
    ``--decision`` on its own a run that changes only the citation. A move with neither
    flag places nothing and changes no field, so it is refused at the flag rather than
    left to print a plan that wrote nothing.

    ``decision`` is the id the entry takes over, and it answers to the same live-record
    rule as ``add --decision``, asked of the same
    :func:`noni.orderstate.decision_problems`: exit 3 for a ledger this run could not
    look in, exit 4 for a record that is absent or has been superseded, the hint naming
    the successor. The entry question is asked first, so a subject the queue does not
    hold is refused before any ledger is opened -- there is no entry whose citation a run
    over an absent subject could be settling.

    ``subject`` is an issue number or an item id, and the two never name the same entry:
    a string is looked up among the entries citing an idea and an int among those naming
    an issue, so ``move 7`` can never reach into an item's position by coincidence.
    """
    holds = _holds(entries, subject)
    if not holds:
        return Planned([], "", fail(exit_refusal, _absent(subject), _LIST_FIRST_HINT))
    if decision is not None and repo is not None:
        cited = orderstate.decision_problems(repo, decision, exit_io, exit_refusal)
        if cited is not None:
            # The tuple's first slot is the code the lookup chose -- the environment's
            # for a ledger this run could not look in, the order's for a record that is
            # not there or is superseded -- so it is returned unchanged.
            return Planned([], "", fail(*cited))
    if to is None and decision is None:
        return Planned([], "", fail(exit_usage, "move needs --to N: a move to no "
                                    "position is not a move",
                                    f"pass the 1-based position to move {subject} to, "
                                    "e.g. --to 1"))
    moved = _restamped(_named(entries, subject), subject, stamp, decision)
    if to is None:
        # No position given: the entry is put back where it was found, so the run
        # rewrites the one field it was asked to rewrite and leaves the queue's order
        # exactly as the operator committed it.
        return Planned([moved if _names(entry, subject) else dict(entry)
                        for entry in entries], f"move {subject}", None)
    position, problem = orderstate.parse_index(to, "--to", len(entries))
    if problem is not None:
        return Planned([], "", fail(exit_usage, *problem))
    rest = [entry for entry in entries if not _names(entry, subject)]
    rest.insert(position - 1, moved)
    return Planned(rest, f"move {subject} to {position}", None)


def _restamped(moved: dict, subject: int | str, stamp: str,
               decision: str | None = None) -> dict:
    """``moved`` with a fresh ``confirmed``, in the key order its subject writes.

    Rebuilt from the entry's own ``decision`` and its own ``why`` rather than copied and
    patched, so the moved entry lands in the documented key order and not the order the
    file happened to hold it in -- the bytes the writer renders are the bytes the version
    documents. ``decision`` overrides the citation only when the run handed one: without
    it the entry keeps the record that set its position. The rationale travels with the
    position it explains: a move restamps when the operator confirmed the placement, not
    why they wanted it, and a move that dropped the reason would delete an operator's
    record as a side effect of reordering.
    """
    why = moved.get(WHY_FIELD)
    citation = moved["decision"] if decision is None else decision
    if isinstance(subject, str):
        return orderschema.entry(item=subject, decision=citation,
                                 confirmed=stamp, why=why)
    return orderschema.entry(issue=subject, decision=citation,
                             confirmed=stamp, why=why)


def _named(entries: list, subject: int | str) -> dict:
    """The entry ``subject`` names, once the caller has proved the list holds it.

    The one lookup, shared by the two shapes of ``move``, so neither half can pick a
    different entry than the other did. ``_holds`` gates it: a list with no such entry
    is refused before anyone reaches here.
    """
    return next(entry for entry in entries if _names(entry, subject))


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
                                    _REMOVE_HINT))
    kept = [entry for entry in entries if not _names(entry, subject)]
    return Planned(kept, f"remove {subject}", None)


# The two hints that tell a refused subject what to do next, spelled once each: the verb
# that placed nothing offers the placement, and the verb that drops an entry has nothing
# left to offer.
_LIST_FIRST_HINT = ("list it first with 'order.py add ISSUE --decision ID' or "
                    "'order.py add --item ID --decision ID'")
_REMOVE_HINT = ("there is nothing to remove; the order is left as it is")


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
        return Planned([], "", fail(exit_refusal, _absent(subject), _LIST_FIRST_HINT))
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
