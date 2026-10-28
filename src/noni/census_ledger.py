"""The census's ledger probe: one classification of ``noni/decisions/``, read once.

Split from ``census.py`` so each file stays the size one responsibility is
worth: ``census.py`` owns the CLI, the exit-code table, the row shape and the
group wiring, and this module owns the probe that reads the ledger directory and
the one row the group adds for a listing that faulted. The probe is a sibling
module rather than more code in the census because the census is the largest
file in the package and the probe is the only reader of the ledger's own
existence: it answers a question about a directory and nothing else.

The probe is reached through three callables the census hands in at the call —
``file_kind`` (the same classifier every other reader of this filesystem uses),
``row`` (the census's one row factory) and ``bounded`` (its one scrubbing and
clipping rule for foreign text) — so the row shape, the state vocabulary and the
bound on a message keep their single owner in ``census.py`` and this module
cannot compose a row of its own devising.

Nothing here prints or exits: every answer is a ``LedgerProbe`` or an entry
appended to the caller's ``findings`` list.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class LedgerProbe:
    """The ledger path's classification, answered once by :func:`probe_ledger`.

    ``state`` is a key of LEDGER_EMPTY_MESSAGES; ``problem`` is the OSError
    text when a filesystem fault forced that state, or None when the state is
    what the tree actually is. Carrying both keeps the probe honest (an I/O
    error is never reported as a symlink that is not there) and lets
    ``_check_ledger`` hand one answer to every reporter instead of letting each
    re-classify the same path and drift.

    ``listing_fault`` is the one fault no state word may carry: the OSError text
    of a ``decisions/`` directory that exists, stats as a directory, and cannot
    be listed. The read answered nothing, so no word of LEDGER_EMPTY_MESSAGES
    describes it — those four name states of the tree, and "unlistable" is a
    fault of this run's read. ``state`` keeps "empty" so the git-backed deletion
    question is still put when git can answer it (the probe's inability to list
    is not git's inability to answer), while ``_check_ledger`` renders the fault
    as a `ledger-edited` cannot-tell row and stays silent on the empty class —
    which is why the text travels beside ``problem`` instead of inside it.
    """

    state: str
    problem: str | None = None
    listing_fault: str | None = None


def probe_ledger(ledger: Path, file_kind: Callable[..., tuple[str, str | None]]) -> LedgerProbe:
    """Classify ``ledger`` once; see :class:`LedgerProbe` for the fields.

    One ``file_kind`` classification per path — the ledger itself and its parent
    (``noni/``) — mapped to a state word, so the vocabulary is derived once and
    never disagrees with the other readers of the same filesystem facts:
    "symlink" — either level is a symlink (refused, never followed; a link is
    never read through even when its target holds records); "not a directory"
    — ``noni/`` exists but is not a directory, so no ledger can live under it
    (or the ledger entry itself is not a directory); "absent" — there is no
    noni/ at all (which is what "no noni/" means for the ledger checks);
    "empty" — noni/ is present and there is no record to arbitrate: no
    ``noni/decisions`` directory at all, or one that holds no *.json record;
    "ok" — a real ledger directory that holds at least one *.json record (the
    recordless directory is "empty" above, not "ok": operator decision on
    issue #33, which reverses the exit-10 ruling of issue #23).

    The child is classified before the parent: ``noni`` committed as a plain
    file must read as "not a directory", not "absent".

    The listing is an explicit ``Path.iterdir``, never ``Path.glob``: glob
    swallows the OSError that readdir raises and yields nothing, so a
    directory that exists and cannot be read would read as the recordless
    "empty" tree — a warn the operator could dismiss as a project that has
    not steered anything yet. ``iterdir`` raises, and the text goes out on
    ``listing_fault`` for ``_check_ledger`` to report as a cannot-tell.
    """
    kind, problem = file_kind(ledger, kind="dir")
    if kind == "symlink":
        return LedgerProbe("symlink")
    parent_kind, parent_problem = file_kind(ledger.parent, kind="dir")
    if parent_kind == "symlink":
        return LedgerProbe("symlink")
    if parent_kind == "nonregular":
        # noni/ exists but is not a directory (a plain file, a fifo), so no
        # ledger can live under it. A fault on the parent keeps its text; "no
        # noni/ at all" is "absent" below, the ledger being absent together
        # with its parent.
        return LedgerProbe("not a directory", parent_problem)
    # A filesystem fault keeps its OSError text (a genuine I/O fault must not
    # be reported under a state word that did not occur) and is rendered under
    # the closest documented state word, so the row's word always comes from
    # LEDGER_EMPTY_MESSAGES.
    if kind == "nonregular":
        return LedgerProbe("not a directory", problem)
    if parent_kind == "absent":
        return LedgerProbe("absent")
    if kind == "absent":
        # noni/ is there and decisions/ is not: no record can be censusable
        # under it, the same finding as a recordless decisions/ directory.
        return LedgerProbe("empty")
    try:
        names = [p.name for p in ledger.iterdir() if p.suffix == ".json"]
    except OSError as e:
        # A directory that exists and stats fine but cannot be listed (a mount
        # or permission fault on readdir) is not a ledger the census can read,
        # and it is not one of the states LEDGER_EMPTY_MESSAGES words. The text
        # travels on its own field so no reporter can mistake it for a state.
        return LedgerProbe("empty", listing_fault=str(e))
    if not names:
        # A decisions/ directory that exists and holds no *.json record: the
        # census exits 0 here so a freshly attached project is not permanently
        # red. The git-backed deletion check still runs and reports how the
        # ledger got empty (operator decision, issue #33).
        return LedgerProbe("empty")
    return LedgerProbe("ok")


def listing_fault(ledger: Path,
                  file_kind: Callable[..., tuple[str, str | None]]) -> str | None:
    """The OSError text of a ledger listing this run cannot make, or None.

    The one question ``main`` must answer before it decides whether to run the
    ledger group at all: the group's ``--only`` filter is a contract about
    classes, and a probe that could not read its input is not a class — it is
    the run losing the ability to answer anything. The row is produced once
    the group runs; this answers only whether the group has to run even when
    the filter named none of its classes.

    A probe that raises something other than ``OSError`` is a bug in the census,
    not a fault of the tree, and is left to propagate: swallowing it here would
    be the very silence the probe-honesty rule forbids.
    """
    return probe_ledger(ledger, file_kind).listing_fault


def append_listing_fault(ledger: Path, root: Path, findings: list[dict],
                         strict: bool, fault: str, *,
                         row: Callable[..., dict],
                         rel_to_root: Callable[[Path, Path], str],
                         bounded: Callable[[str], str]) -> None:
    """The row for a ledger directory this run could not list.

    A probe that read nothing reports it, under the probe-honesty rule: the
    alternative is the run calling an unreadable ledger an empty one, which is
    the verdict a project that has never steered anything also earns. Built
    with ``row`` and an explicit ``severity="warn"`` rather than through the
    census's ``_append_cannot_tell``, because the row must name the ledger it
    could not read in both ``subject`` and ``artifact`` — the helper names its
    check — and because ``_check_sessions_deleted`` shares that helper and must
    not have its shape changed for this case. The OSError text is foreign and
    passes through ``bounded``; the root-relative path is the census's own
    wording and does not, so a machine-local path can only enter through the
    fault.

    ``check`` is ``ledger-edited`` exactly: ``main`` filters the ledger group
    against that id plus ``ledger-empty``, and a row under any other id would
    be dropped by an ``--only``/``--skip`` run rather than reported by it. The
    row is also marked whole-artifact, which is what keeps it in front of the
    operator under a filter that named none of the ledger classes: a run that
    could not read its input must say so whatever the filter asks for (see
    ``keep`` and the census's module docstring).
    """
    path = rel_to_root(root, ledger)
    findings.append(
        row("ledger-edited", strict, path, path,
            f"cannot-tell: the ledger directory ({path}) exists but could not be "
            f"listed ({bounded(fault)}), so whether a committed record was deleted "
            "or edited cannot be answered", root, severity="warn", whole_artifact=True))
