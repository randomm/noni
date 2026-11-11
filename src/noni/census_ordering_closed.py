"""The one rule for the census's "closed state was never checked" row.

``census_ordering_closed.append`` below is the only writer of the row, and
``census_ordering.check_ordering`` is its only caller: it asks once per run, after the
artifact read it shares with the rest of the group. The row is worth its own module
because it is the whole of issue #148: a class that skipped itself said so in a
``note:`` line and nowhere else, so a CI step gating on the exit code stayed green for
days over an order whose issues had all been closed. A note is a sentence; a verdict is
a row, and only a row carries a code.

The row is ``warn``, and ``--strict`` gives it the class's own 46 -- the same
promotion ``census_render._promote`` applies to every warn row, asked of the row factory
rather than spelled out here. It carries no issue number: its subject and its artifact
are both the ordering artifact's fixed root-relative id, because the fact is about the
run and not about any one ordered issue. The artifact is that id rather than a spelling
of the path this run read, because a path helper hands back what it was given whenever
it cannot ground one -- an out-of-root ``--ordering``, a symlinked parent -- and a row
that carried it would put a machine-local path in the report. The id is the same one the
rest of the group uses for its whole-artifact rows, so the group and this row name one
file alike.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

CLOSED_STATE_UNASKED = (
    "closed state not checked: the order holds entries and no --issue-state FILE was "
    "given, so no entry's closed state was asked and a dead order reads as a live one "
    "(the census never contacts a tracker: produce the map with an adapter, or pass "
    "--issue-state)"
)


def owed(entries: list[dict] | None) -> bool:
    """Whether the artifact this run read leaves the closed question genuinely unasked.

    Three states owe nothing, because a run never invents a finding where the reader has
    nothing to repair. ``None`` means the artifact faulted: the group already appended its
    fail-class ``ordering-malformed`` row and a warn must not second-guess it. An empty
    list, which is also what an absent artifact answers, is a project that never ordered
    anything -- the ordering layer is optional, and an operator who wants nothing worked
    next has said so. Entries that name no issue leave no closed state unstated, and an
    order of blanks is answered by the malformed class, not here.

    "Names an issue" is the entry arbiter's test, ``isinstance(x, int)`` with the boolean
    case refused: JSON spells ``true`` as a value and Python answers ``isinstance(True,
    int)``, so a reader that asked only the first half would count a JSON ``true`` as an
    issue number and owe this row, and a code under ``--strict``, for an order that names
    none. The same document must not read as an order here and as a defect there.

    The run's class filter is not consulted: that is ``census_run.keep``, which every row
    of every group obeys, and it is applied there rather than copied here. This module
    decides only what the tree says, never what the caller asked to see -- a second copy
    of the filter would be a second rule for one row, and the two would disagree the first
    time the run's filter gained a case.
    """
    return bool(entries) and any(
        isinstance(entry.get("issue"), int) and not isinstance(entry.get("issue"), bool)
        for entry in entries)


def append(entries: list[dict] | None, root: Path, strict: bool, findings: list[dict], *,
           row: Callable[..., dict], check: str, whole_artifact_subject: str) -> None:
    """Append the run's one not-evaluated row, if :func:`owed` says it owes one.

    ``entries`` is what this run's one read of the artifact answered -- the pair
    ``check_ordering`` got from ``readers.load_order`` -- and is never re-read here: a
    second read would double the cost and let this part of the group answer from a later
    view of the tree than the rows above it. ``strict`` goes to the row factory and
    nowhere else, so its severity is the one rule the whole report reads; the fix hint is
    the class table's, because a row this run raises never words its own remedy.

    The row names itself by ``whole_artifact_subject`` for both its subject and its
    artifact, the fixed root-relative id the group gives its whole-artifact rows. The
    artifact field is not ``relative_artifact=False`` either: the id is already a root-
    relative path, so rooting it is the identity, and a caller that handed in a foreign
    spelling would then be rooted or refused rather than printed.

    The row is deliberately **not** marked ``whole_artifact``, whatever its subject looks
    like. That marker is the probe-honesty exemption: it keeps a row through ``--only``
    and ``--skip`` because a group that could not read its input must say so even under a
    filter that named none of its classes (``census_run.keep``). This row reports a
    question the run chose not to ask, not a read that failed, so it is an ordinary
    finding of its class and the run's filter drops it whenever that class was not named
    -- which is what makes ``--skip ordering-closed`` mean no row, and ``--only hygiene``
    print nothing about the closed order.
    """
    if not owed(entries):
        return
    findings.append(row(check, strict, whole_artifact_subject,
                        whole_artifact_subject, CLOSED_STATE_UNASKED, root))
