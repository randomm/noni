"""The sessions register's probe: one listing of ``noni/sessions/``, read once.

Split from ``census.py`` so each file stays the size one responsibility is
worth: ``census.py`` owns the CLI, the exit-code table, the row shape and the
group wiring, and this module owns the probe that lists the session register
and the one row the group adds for a listing that faulted. The probe is a
sibling module rather than more code in the census because the census is the
largest file in the package and the probe is the only reader of the register's
own existence: it answers a question about a directory and nothing else.

The probe is reached through the callables the census hands in at the call —
``row`` (the census's one row factory), ``rel_to_root`` (its one root-relative
identifier), ``bounded`` and ``clipped`` (its scrubbing and clipping rules for
foreign text) — so the row shape and the bound on a message keep their single
owner in ``census.py`` and this module cannot compose a row of its own devising.
The row itself is composed by ``census_ledger.append_listing_fault``, shared
with the ledger group, so the two cannot-tells of one faulted read cannot drift
apart in shape.

Nothing here prints or exits: every answer is a ``SessionsProbe`` or an entry
appended to the caller's ``findings`` list.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import census_ledger as _ledger
from . import census_text as _text


# The probe and its one listing are declared above the reporter that annotates
# them, the way ``census_ledger`` declares ``LedgerProbe`` above its reporters:
# a reader meeting ``probe: SessionsProbe`` should not have to scroll to learn
# what the type promises.
@dataclass(frozen=True)
class SessionsProbe:
    """The register directory's listing, answered once by :func:`sessions_listing`.

    Exactly one field is set, and that one field is the answer of one readdir:
    ``names`` is the ``*.md`` listing this run took (the empty tuple for a
    directory it listed and found no register file in, a read that answered
    "nothing"), or ``fault`` is the text of the ``OSError`` a directory that
    exists, stats as a directory and cannot be listed raised. "Listed" and "did
    not list" are therefore distinguishable by construction rather than by a
    convention the reporter has to remember: a probe that could mean both would
    let the group ask the deletion question about a register it never opened,
    which is the silent clean this ticket exists to close.

    It is the ledger probe's shape (see ``census_ledger.LedgerProbe``) minus its
    ``state`` field: the sessions group words no states, so there is no state
    word here for a fault to be mistaken for.

    ``fault`` is built by ``census_text.fault_text``, which reads the
    exception's class and its ``strerror`` and never its ``filename``: the path a
    read failed on is the one part of an ``OSError`` no row may carry. It is
    ``None`` or a non-empty string, never the empty string, and it is the one
    field both ``main``'s gate and :func:`_check_sessions` read (see
    :func:`sessions_listing` for where a blank errno text is replaced).

    The one read is also the one answer: a register that starts faulting *after*
    this listing succeeded reports the listing it got and earns no fault row,
    because there is no second readdir left to change its mind (the same
    trade-off ``census_ledger.LedgerProbe`` documents).
    """

    names: tuple[Path, ...] | None = None
    fault: str | None = None

    def __post_init__(self) -> None:
        if (self.names is None) == (self.fault is None):
            raise ValueError(
                "SessionsProbe answers one readdir: set names (the listing, "
                "() for a directory listed and found empty) or fault (the text "
                "of the OSError that stopped the listing), never both and neither")
        if self.names is not None and (
                not isinstance(self.names, tuple)
                or not all(isinstance(n, Path) for n in self.names)):
            raise TypeError(
                "SessionsProbe.names is the listing: a tuple of Path, not a "
                f"{type(self.names).__name__} of whatever it was handed")
        if self.fault is not None and not isinstance(self.fault, str):
            raise TypeError(
                "SessionsProbe.fault is the text of the OSError that stopped "
                f"the listing, not a {type(self.fault).__name__}")


def sessions_listing(sessions: Path) -> SessionsProbe:
    """List the register once; the whole census performs no other readdir of it.

    The body of the census's ``_sessions_listing``, the one readdir of a run:
    this module never lists the register for itself, and the census keeps the
    caller's name so its own pins -- "the register is listed once" and the
    ``iterdir``/no-``glob`` rule below, which reads this function by name --
    still have exactly one definition to scope to.

    The read is an explicit ``Path.iterdir`` and never ``Path.glob``: ``glob``
    swallows the ``OSError`` a faulted readdir raises and yields nothing, so a
    register the run could not read would earn the same clean verdict as a
    project that never opened a session. Here the ``OSError`` propagates and the
    probe carries its text instead.

    Both answers come from this call, so the group's file loop and ``main``'s
    gate are the same read: ``_check_sessions`` reports from the names and
    ``main`` opens the group on the fault. The tuple is sorted because the
    register's reporters print sorted, and one order per run is what keeps two
    of them naming one file the same way.

    The fault field is never empty: an ``OSError`` whose ``strerror`` came back
    blank or whitespace answers with the exception's class name, so a probe that
    says a read faulted always carries a diagnosis, and the gate's test and the
    reporter's cannot diverge over an empty string.
    """
    try:
        return SessionsProbe(names=tuple(sorted(
            p for p in sessions.iterdir() if p.suffix == ".md")))
    except OSError as e:
        return SessionsProbe(fault=_text.fault_text(e) or type(e).__name__)


def append_sessions_listing_fault(
    sessions: Path, root: Path, strict: bool, findings: list[dict], fault: str, *,
    row: Callable[..., dict],
    rel_to_root: Callable[[Path, Path], str],
    bounded: Callable[..., str],
    clipped: Callable[[str], str],
) -> None:
    """The row for a sessions register this run could not list.

    The sessions call of ``census_ledger.append_listing_fault``, which owns this
    row's shape: one row naming the register in ``subject`` and ``artifact``,
    foreign text through ``bounded``, the finished sentence through ``clipped``,
    ``severity="warn"`` with the ``--strict`` promotion, and the whole-artifact
    marker that keeps it visible under a filter that named no session class.
    Read that function for why the row is built that way. What differs here is
    only the two things it takes as arguments: the class, ``session-deleted``
    (what the deletion check already uses for its cannot-tells, so a run filtered
    to that class reports the fault instead of the silent clean of a group that
    read nothing), and the question the faulted read took away. No ``probe`` row
    accompanies it: one fault earning rows of two classes reads as two problems
    found where there was one read.

    The row mechanics are handed in at the call — ``row``, ``rel_to_root``,
    ``bounded`` and ``clipped`` are the census's own, the same ones every other
    group passes to ``append_listing_fault`` — so this module composes no row of
    its own devising and the row shape keeps its single owner in ``census.py``.
    """
    _ledger.append_listing_fault(
        sessions, root, findings, strict, fault,
        check="session-deleted", noun="the sessions register",
        unknown="so which session files are registered, and whether a committed "
                "register file was deleted, cannot be answered",
        row=row, rel_to_root=rel_to_root, bounded=bounded, clipped=clipped)
