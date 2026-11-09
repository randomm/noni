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
publishes it; ``report`` is that writer's own printer, so a refusal reads as coming from
the command that ran. ``move`` is the one plan that reads state for itself: it resolves
the record it is told to cite against ``noni/decisions/`` before it places anything, on
the same lookup and the same codes ``add`` uses for a new entry's citation.

Why the plan is built before any write and never after: a reorder restamps the moved
entry (the operator confirming it again), so a plan computed from entries the writer had
already restamped would not be a plan anybody approved -- and the freshness guard later
compares the bytes of exactly this plan against what git holds.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from . import labels, orderschema, orderstate

# The rationale's key, read from the artifact's schema: a move keeps the field, so the
# plan asks for it by the name the writer and the censuses both use.
WHY_FIELD = orderschema.WHY_FIELD


# The usage line, spelled once and handed to argparse as ``usage=``. argparse composes a
# usage line as ``optionals + positionals`` unconditionally, so with ``--repo`` required
# and five flags declared before the verbs, ``order.py --help`` rendered ``...
# [--no-commit] subcommand [issue]`` and buried the one word the caller has to choose --
# while the docstring's ``Usage:`` block and ``skills/direction/SKILL.md`` both spell the
# verb first, and a help line that contradicts the two texts a reader copies from is the
# bug (issue #77). A literal is the only public way to put the verb first: a formatter
# subclass used to derive the line from argparse's private ``_format_usage`` and
# ``_format_actions_usage``, and 3.14 removed the second, so every usage print died with an
# ``AttributeError`` (issue #98). A literal keeps the rendering inside argparse, which
# still prepends ``usage:`` and wraps at ``COLUMNS``. The flag block is the parser's own
# declaration, in declaration order, with the metavar argparse prints for each, and it is
# compared against that declaration by ``tests/test_order_writer_usage.py`` and the
# flag-set parity of ``tests/test_order_writer_docs.py``: a flag added to the parser
# belongs here too.
USAGE = (f"{labels.ORDER} --repo REPO subcommand [issue]"
          " [--at N] [--to N] [--decision ID] [--item ID] [--why REASON]"
          " [--now ISO-8601] [--no-commit] [-h]")

# The missing-positional message argparse composes for a required positional, and the
# line argparse prints above it. argparse turns this refusal into usage-plus-error itself,
# so the verbs are added to *that* pair rather than to the message text: a subclass that
# re-raised it would print its own usage instead, and ``first_usage_line`` reads the
# ``usage:`` line out of the refusal.
def build_parser(parser_class: type, usage: str, prog: str,
                 description: str) -> object:
    """The parser of the order writer, built by the module that owns ``add``.

    The writer hands over its own parser class rather than this module importing one:
    the class is the answer to a *missing* verb and lives with the writer's other usage
    refusals, and a module that reached for it would be reaching back into the file that
    calls it. ``prog``, ``usage`` and ``description`` travel the same way so the
    three strings a reader copies from stay in the file whose docstring publishes them.
    """
    return parser_class(prog=prog, description=description, usage=usage)


class Planned(NamedTuple):
    """The entries a verb writes, the word the run is named by, or a refusal.

    ``refusal`` carries the code the caller returns unchanged and is set only when the
    other two are empty, because the check that failed has already printed its two lines
    and chosen between the environment's code and the order's own.
    """

    entries: list
    verb: str
    refusal: int | None


def plan_move(repo: Path, entries: list, subject: int | str, to: str | None,
              stamp: str, decision: str | None, report,
              exit_io: int, exit_usage: int, exit_refusal: int) -> Planned:
    """The list ``move`` writes, or the refusal naming why it writes none.

    Two reads before any placement, in the order whose remedies differ: the record the
    entry will cite, then the entry itself. The lookup is the half the writer used to
    carry; it lives here so the run that re-cites an entry asks the ledger in the one
    module that asks it for a new one, and so the writer stays the file that owns verbs
    and codes rather than a reader of ``noni/decisions/``. Its answer is reported on the
    codes ``add --decision`` already uses for the same three states -- the environment's
    for a ledger this run could not look in, the order's for a record that is not there
    or has been superseded -- which is what makes a bad record read alike whichever verb
    named it.

    A move restamps the entry it moved: reordering the queue is the operator confirming
    the position again, so the entry leaves with a fresh ``confirmed`` rather than the
    one its original placement carried. ``--to`` is a position of the list this run
    produces, which is the same length the entry left behind, so the bound is the current
    count and not that count minus one.

    ``decision`` is the record the entry cites once this run is done, and it is what
    makes ``--to`` optional: a run that names a new record and no position changes only
    the citation, because the reason for a priority changed while the priority itself
    stood. A run that names neither is refused: a move of nothing is not a move.

    ``subject`` is an issue number or an item id, and the two never name the same entry:
    a string is looked up among the entries citing an idea and an int among those naming
    an issue, so ``move 7`` can never reach into an item's position by coincidence.
    """
    if decision is not None:
        cited = orderstate.decision_problems(repo, decision, exit_io, exit_refusal)
        if cited is not None:
            # The tuple's first slot is the code the lookup chose, so it is handed to the
            # printer unchanged -- the same reading ``plan_add`` gives a new entry's
            # citation, and the reason a move and an add answer a bad record alike.
            return Planned([], "", report(*cited))
    if not _holds(entries, subject):
        return Planned([], "", report(
            exit_refusal, _absent(subject),
            "list it first with 'order.py add ISSUE --decision ID' or "
            "'order.py add --item ID --decision ID'"))
    if to is None and decision is None:
        return Planned([], "", report(
            exit_usage, "move needs --to N: a move to no position is not a move",
            f"pass the 1-based position to move {subject} to, e.g. --to 1, or "
            "--decision ID to re-cite the record it rests on"))
    rest = [entry for entry in entries if not _names(entry, subject)]
    if to is None:
        # No position named: the entry stays where it stands, so the list this run
        # writes is the read list with the one entry rebuilt in place.
        position = next(i for i, entry in enumerate(entries, 1)
                        if _names(entry, subject))
    else:
        position, problem = orderstate.parse_index(to, "--to", len(entries))
        if problem is not None:
            return Planned([], "", report(exit_usage, *problem))
    moved = next(entry for entry in entries if _names(entry, subject))
    moved = _restamped(moved, subject, stamp, decision)
    rest.insert(position - 1, moved)
    return Planned(rest, _move_name(subject, position, to, decision), None)


def _move_name(subject: int | str, position: int, to: str | None,
               decision: str | None) -> str:
    """The sentence a move run is printed and committed under.

    It names what the run actually did, because it is the line ``git log`` offers a
    reader who was not there: a run that re-cited as well as moved says so, and a run
    that only re-cited does not claim a position it never took.
    """
    if decision is None:
        return f"move {subject} to {position}"
    if to is None:
        return f"move {subject} to decision {decision}"
    return f"move {subject} to {position} with decision {decision}"


def _restamped(moved: dict, subject: int | str, stamp: str,
               decision: str | None = None) -> dict:
    """``moved`` with a fresh ``confirmed`` (and a new decision when one was given),
    in the key order its subject writes.

    Rebuilt from the entry's own ``decision`` and its own ``why`` rather than copied and
    patched, so the moved entry lands in the documented key order and not the order the
    file happened to hold it in -- the bytes the writer renders are the bytes the version
    documents. The rationale travels with the position it explains: a move restamps when
    the operator confirmed the placement, not why they wanted it, and a move that dropped
    the reason would delete an operator's record as a side effect of reordering.

    ``decision`` is the record the entry cites after this run, or None to keep the one it
    carries. It arrives already resolved against the ledger by the caller, so the only
    question left here is which of the two ids to write.
    """
    why = moved.get(WHY_FIELD)
    cited = moved["decision"] if decision is None else decision
    return entry_for(subject, cited, stamp, why)


def entry_for(subject: int | str, decision: str, confirmed: str,
              why: str | None) -> dict:
    """One entry for ``subject``, spelled from the type the caller handed it.

    The one place this module chooses an entry's subject key, so the verb that rebuilds a
    moved entry and the verb that places a new one cannot spell the same entry two ways:
    ``add`` reaches it through :func:`noni.order_add._new_entry` and ``move`` through
    :func:`_restamped`, and both arrive at :func:`noni.orderschema.entry` here. The
    rationale is written last and only when the caller was given one, which is what lets a
    rebuilt entry hold the bytes the artifact held before the field existed.
    """
    if isinstance(subject, str):
        return orderschema.entry(item=subject, decision=decision,
                                 confirmed=confirmed, why=why)
    return orderschema.entry(issue=subject, decision=decision,
                             confirmed=confirmed, why=why)


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


def plan_remove(entries: list, subject: int | str, report,
                exit_refusal: int) -> Planned:
    """The list ``remove`` writes: every entry but the one naming ``subject``.

    The only verb that shortens the list, and the only one whose refusal tells the
    operator nothing to do: a subject that is not in the queue is already not in it, and
    the artifact is left exactly as it was rather than rewritten to say so. An item
    removed from the queue keeps its record under ``noni/items/``: this verb drops a
    position, never an idea.
    """
    if not _holds(entries, subject):
        return Planned([], "", report(exit_refusal, _absent(subject),
                                      "there is nothing to remove; the order is left "
                                      "as it is"))
    kept = [entry for entry in entries if not _names(entry, subject)]
    return Planned(kept, f"remove {subject}", None)


def plan_confirm(entries: list, subject: int | str | None, stamp: str, report,
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
        return Planned([], "", report(exit_refusal, _absent(subject),
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
