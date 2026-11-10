"""The ``add`` plan: the subject the verb accepts and the entry it puts in the list.

``order.py`` owns the verbs, the exit codes and the commit; this module owns the one
verb that places a new entry rather than rearranging the ones the operator was shown.
``add`` asks whether the issue is already in the queue, where the new entry goes, and
what the operator's one line of reason for the position is; the three rearranging verbs
live in :mod:`noni.order_plan`.

Nothing here prints or exits: each answer is a value, and the exit codes travel in as
arguments the way ``orderstate`` takes them, so the one table of codes stays in the
writer that publishes it.

Why the checks land here and not later: the decision an entry cites is looked up before
anything is written, so a run that would place a position on the strength of a record the
ledger does not hold is refused without touching a byte.
"""

from __future__ import annotations

from pathlib import Path

from . import (
    order_plan,
    orderschema,
    orderstate,
)
from .order_plan import Planned

# The rationale's key, read from the artifact's schema so the flag's refusal names the
# field the censuses name rather than a string this module spells.
WHY_FIELD = orderschema.WHY_FIELD


def misplaced_flag(subcommand: str, at: str | None, to: str | None,
                   decision: str | None,
                   why: str | None) -> tuple[str, str] | None:
    """The (headline, hint) refusal for a flag the verb does not own, or None.

    The owners, stated once: ``--at`` and ``--why`` belong to ``add``, ``--to`` to
    ``move``, and ``--decision`` to both -- ``add`` sets the record a new position rests
    on and ``move`` re-cites the record an entry rests on. Each arm says who does own the
    flag, because the caller's mistake is a reasonable one and the fix is to name the verb
    that answers it. A run whose only flag the verb does own is not a hint this writer may
    quietly drop: the operator typed it, and dropping it loses what they typed.
    """
    if subcommand != "add" and at is not None:
        return (f"--at belongs to add, not {subcommand}",
                f"to place an entry with {subcommand} pass --to N")
    if subcommand != "move" and to is not None:
        return (f"--to belongs to move, not {subcommand}",
                "--to is only how move names a position")
    if decision is not None and subcommand not in ("add", "move"):
        return (f"--decision belongs to add, not {subcommand}",
                "add and move own a decision: add sets the record a new position rests "
                "on and move re-cites the record an entry rests on, while confirm "
                "restamps what is there")
    if why is not None and subcommand != "add":
        return (f"--why belongs to add, not {subcommand}",
                "only add records a reason; the other verbs answer to an entry that "
                "already carries one")
    return None


def unknown_verb(subcommand: str, label: str) -> tuple[str, str]:
    """The (headline, hint) refusal for a verb this writer does not own.

    The two sentences name the set the writer accepts and give one line of the form to
    copy, which is the same pair of answers the missing-verb hint gives; both live here
    beside the verb list so neither can name a set the parser does not accept.
    """
    return (f"subcommand {subcommand!r} is not one of "
            "add, move, remove or confirm",
            f"{label} --repo REPO add ISSUE --decision ID | "
            "move ISSUE [--to N] [--decision ID] | remove ISSUE | confirm [ISSUE]")


def plan_add(repo: Path, entries: list, issue: int | None,
             decision: str, at: str | None, stamp: str, report, exit_io: int,
             exit_usage: int, exit_refusal: int,
             why: str | None = None) -> Planned:
    """The entries ``add`` writes, or the refusal naming why it writes none.

    Every question the verb owes is asked here, in the order whose remedies differ:
    the subject's own place in the queue (an issue already listed), then the decision
    the position rests on, then the position itself -- because ``--at N`` is a position
    *of the list this run produces*, so it cannot be parsed until the count is settled,
    and a run that refused a bad position first would tell the operator about a position
    they were never going to fill.

    ``why`` is the rationale the run may carry, and it is refused for its shape before
    anything is read: a reason that is blank, multi-line or past the bound is the
    caller's mistake and takes the usage code. It
    defaults to None because a run that names no reason writes the entry it always
    wrote.

    ``entries`` is copied rather than mutated: the caller keeps the list it read for
    the lost-update comparison, and a plan that reached into it would move the very
    bytes the guard later compares.
    """
    if why is not None:
        refused = _why_refusal(why, report, exit_usage)
        if refused is not None:
            return Planned([], "", refused)
    listed = [entry for entry in entries]
    refusal = _already_listed(listed, issue, report, exit_refusal)
    if refusal is not None:
        return Planned([], "", refusal)
    assert issue is not None
    cited = orderstate.decision_problems(repo, decision, exit_io, exit_refusal)
    if cited is not None:
        # The tuple's first slot is the code the lookup chose -- the environment's for
        # a ledger this run could not look in, the order's for a record that is not
        # there or is superseded -- so it is returned unchanged, not re-picked here.
        return Planned([], "", report(*cited))
    position, problem = _position(at, len(listed) + 1, report, exit_usage)
    if problem is not None:
        return Planned([], "", problem)
    listed.insert(position - 1, _new_entry(issue, decision, stamp, why))
    return Planned(listed, f"add {issue}", None)


def _why_refusal(why: str, report, exit_usage: int) -> int | None:
    """The exit-2 refusal for a ``--why`` that is not one bounded line, or None.

    The ledger's rule, asked through the artifact's own schema (which is the ledger's
    module read from this side): the same shape and the same bound a decision record's
    rationale answers to, so one line of reason is one line wherever it is written and
    the number keeps one owner. The problem string names the field, which is what both
    censuses' rows name too.
    """
    problems = orderschema.why_problems({WHY_FIELD: why})
    if not problems:
        return None
    headline = problems[0]
    if "characters" in headline:
        hint = f"shorten --why to at most {orderschema.why_max()} characters"
    else:
        hint = ("--why is one line of text: pass it without a newline and with "
                "something in it")
    return report(exit_usage, f"--why {why!r} is not a usable reason: {headline}", hint)


def _new_entry(subject: int, decision: str, stamp: str,
               why: str | None = None) -> dict:
    """The entry ``add`` places, built through the artifact's one entry builder.

    ``why`` rides through unchanged: absent is the three-field entry the writer produced
    before the field existed.

    The same builder serves ``move --decision``, which rebuilds the entry it re-cites
    rather than patching the one it read: two verbs spelling an entry from a subject is
    two chances to write an entry the schema refuses.
    """
    return order_plan.entry_for(subject, decision, stamp, why)


def _already_listed(entries: list, issue: int | None, report,
                    exit_refusal: int) -> int | None:
    """The refusal for an issue the queue already holds, or None when it does not.

    A position for an issue that already has one is the operator's second word on the
    same issue, and the writer has no way to tell it from a mistake, so it is refused
    and the hint names the verbs that do answer the two real questions: move it, or
    restamp it.
    """
    if issue is None or issue not in orderschema.listed_issues(entries):
        return None
    position = next(i for i, entry in enumerate(entries, 1)
                    if orderschema.entry_issue(entry) == issue)
    return report(exit_refusal,
                  f"issue {issue} is already in the order at position "
                  f"{position}",
                  f"move it with 'order.py move {issue} --to N', or "
                  "restamp it with 'order.py confirm'")


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
