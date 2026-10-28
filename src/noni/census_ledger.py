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

    ``names`` is the record listing this probe took — the ``*.json`` names of a
    directory it successfully listed (the empty tuple for a directory it listed
    and found no record in, which is a read that answered "nothing"), and None
    for every state in which no such read happened. It exists so the whole
    census reads the ledger once: the record pass and the ordering readers take
    these names instead of walking the directory a second and third time, which
    is both the fewer syscalls and the honest answer to a tree that turns hostile
    between two reads of it. A second readdir that faulted after the probe's
    succeeded used to end the run with an ``OSError`` traceback out of ``main``;
    there is no second readdir to fault now, and the names the run reports are
    the names the run observed.
    """

    state: str
    problem: str | None = None
    listing_fault: str | None = None
    names: tuple[str, ...] | None = None


def _ledger_name(rel: str) -> str:
    """The identifier a row uses for a ledger it could not read.

    The root-relative path when the census could root it (``noni/decisions``).
    An out-of-tree ``--ledger`` override cannot be rooted, and ``rel_to_root``
    hands back the machine-local absolute path it was given; keeping only its
    last segment (``decisions``) still tells the operator which ledger the row
    is about without printing the directory the host keeps it in. A trailing
    separator drops out rather than yielding an empty id.

    A root-relative path is one segment below the repo root (``noni/decisions``
    is two), so that is the test for "rootable": the override's absolute form
    has an empty first segment, and a bare relative fragment has no separator
    at all.
    """
    stripped = rel.rstrip("/")
    parts = stripped.split("/")
    if len(parts) >= 2 and parts[0] and "" not in parts:
        return stripped
    return parts[-1] or "ledger"


def listing_helper(ledger: Path) -> list[str]:
    """The ``*.json`` record names ``ledger`` holds, listed with ``iterdir``.

    The one listing of the ledger the whole census performs, and the one the
    census's tests fault to prove it: every read of the ledger's directory ends
    here, and here alone, so "which files count as a ledger record" has a single
    answer and a single readdir behind it. The probe of :func:`probe_ledger` is
    the only caller; the record pass of ``census.py`` and the ordering readers
    read the names it carries rather than calling this again.

    It is an explicit ``Path.iterdir`` and never ``Path.glob``: ``glob`` swallows
    the ``OSError`` that readdir raises and yields nothing, so a directory that
    exists and cannot be read would report the same verdict as a project that has
    never steered anything. Here the ``OSError`` propagates and the caller decides
    what a fault means — the probe carries its text, and no pass runs behind a
    fault at all.
    """
    return [p.name for p in ledger.iterdir() if p.suffix == ".json"]


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

    The listing is :func:`listing_helper` — an explicit ``Path.iterdir``, never
    ``Path.glob``: ``glob`` swallows the OSError that readdir raises and yields
    nothing, so a directory that exists and cannot be read would read as the
    recordless "empty" tree — a warn the operator could dismiss as a project that
    has not steered anything yet. ``iterdir`` raises, and the text goes out on
    ``listing_fault`` for ``_check_ledger`` to report as a cannot-tell. The names
    a successful listing produced go out on ``names``, because this is the one
    readdir the run performs (see :class:`LedgerProbe`).
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
        # under it, the same finding as a recordless decisions/ directory. The
        # empty tuple, not None: this read did happen and answered "no names",
        # so the passes below may take that answer rather than list again.
        return LedgerProbe("empty", names=())
    try:
        names = listing_helper(ledger)
    except OSError as e:
        # A directory that exists and stats fine but cannot be listed (a mount
        # or permission fault on readdir) is not a ledger the census can read,
        # and it is not one of the states LEDGER_EMPTY_MESSAGES words. The text
        # travels on its own field so no reporter can mistake it for a state,
        # and ``names`` stays None: the read answered nothing, so no downstream
        # pass may borrow a listing it never got.
        #
        # ``str(e)`` is the whole fault, path included: OSError appends the path
        # it failed on (``[Errno 2] No such file or directory: '/home/x/decisions'``)
        # and ``e.filename`` holds it outright. It is foreign text, so every row
        # that renders it passes it through the census's scrub-and-bound, which
        # is where the machine-local path is removed -- not here, where raising
        # would turn the one row about an unreadable ledger into a traceback.
        return LedgerProbe("empty", listing_fault=str(e))
    # A decisions/ directory that holds no *.json record is "empty", not "ok":
    # the census exits 0 here so a freshly attached project is not permanently
    # red, and the git-backed deletion check still reports how the ledger got
    # empty (operator decision, issue #33). A directory that holds a record is
    # "ok". Both carry the names they listed, because both read them.
    if not names:
        return LedgerProbe("empty", names=())
    return LedgerProbe("ok", names=tuple(names))


def append_listing_fault(ledger: Path, root: Path, findings: list[dict],
                         strict: bool, fault: str, *,
                         row: Callable[..., dict],
                         rel_to_root: Callable[[Path, Path], str],
                         bounded: Callable[[str], str],
                         clipped: Callable[[str], str]) -> None:
    """The row for a ledger directory this run could not list.

    A probe that read nothing reports it, under the probe-honesty rule: the
    alternative is the run calling an unreadable ledger an empty one, which is
    the verdict a project that has never steered anything also earns. Built
    with ``row`` and an explicit ``severity="warn"`` rather than through the
    census's ``_append_cannot_tell``, because the row must name the ledger it
    could not read in both ``subject`` and ``artifact`` — the helper names its
    check — and because ``_check_sessions_deleted`` shares that helper and must
    not have its shape changed for this case.

    Every piece of foreign text the row carries comes from outside this census
    and passes through ``bounded``: the OSError text, whose ``str(e)`` appends
    the path the readdir failed on, and the ledger path itself. That is the same
    rule the ordering group's equivalent row follows (``census_ordering``
    composes its listing-fault sentence with the fault text passed through
    ``bounded``), and it is what makes the row safe for an out-of-tree
    ``--ledger`` override: ``rel_to_root`` cannot root a path that lies outside
    the audited tree, so it hands back the machine-local absolute path it was
    given, and a row that quoted that raw would print a host path in a report
    that promises never to print one.

    The path is scrubbed wherever it is *narrated* — in the message's "the
    ledger directory (…)" clause — and left as ``rel_to_root`` answered it in
    ``subject``/``artifact``, which is the row's identifier, not its prose: the
    census's own rows name the ledger root-relative there (a
    ``ledger-empty`` row's subject is ``noni/decisions``), and scrubbing the
    identifier would collapse the one field a caller joins on. So an in-repo
    fault reads as the same path in all three fields, and an out-of-tree one
    keeps a non-path identifier (its last segment) rather than a host directory:
    the row says which ledger it could not read without saying where the host
    keeps it. The rooting is asked once, into ``name``, because the three uses
    are one question about one path and a row must not disagree with itself.

    ``check`` is ``ledger-edited`` exactly: ``main`` filters the ledger group
    against that id plus ``ledger-empty``, and a row under any other id would
    be dropped by an ``--only``/``--skip`` run rather than reported by it. The
    row is also marked whole-artifact, which is what keeps it in front of the
    operator under a filter that named none of the ledger classes: a run that
    could not read its input must say so whatever the filter asks for (see
    ``keep`` and the census's module docstring).

    ``clipped`` wraps the finished message, the way the ordering group's
    equivalent row is wrapped (``census_ordering`` clips its listing-fault
    sentence): the bound a report keeps is a property of the row, and a fault
    whose ``strerror`` runs to thousands of characters must not make a row of
    thousands of characters. The scrubbing of the foreign pieces stays
    ``bounded``'s job, applied to each fragment before the sentence is clipped,
    so clipping the whole cannot cut a host path loose at the cut.
    """
    name = rel_to_root(root, ledger)
    subject = _ledger_name(name)
    findings.append(
        row("ledger-edited", strict, subject, subject,
            clipped(f"cannot-tell: the ledger directory ({bounded(name)}) "
                    "exists but could not be "
                    f"listed ({bounded(fault)}), so whether a committed record was deleted "
                    "or edited cannot be answered"), root, severity="warn",
            whole_artifact=True))
