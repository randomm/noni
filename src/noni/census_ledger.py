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

from .census_text import fault_text


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

    Both fault fields are built by ``census_text.fault_text``, which reads the
    exception's class and its ``strerror`` and never its filename: the path a
    read failed on is the one part of an ``OSError`` no row may carry, and the
    row names the ledger by the census's own identifier in any case.

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


def ledger_name(rel: str) -> str:
    """The identifier a row uses for a directory it could not read.

    The root-relative path when the census could root it: a plain path below the
    repo root (``noni/decisions``, ``noni/sessions``) -- two or more segments, a
    real name in each (no empty segment, no ``.`` or ``..``, nothing longer than a
    directory is ever named), the first not opening with ``~``. That is the only
    form the census wrote itself, and it is the form a caller joins on, so it is
    kept whole.

    Everything else is a path the caller spelled out of its own cwd or home, which
    ``rel_to_root`` could not root and handed back unchanged: an absolute path, a
    ``~user`` form, a relative walk out of the tree. None of those may be printed
    -- the report promises no machine-local path, and an identifier field cannot go
    through the scrubber because a marker there is not a name anybody can join on.
    So the identifier is that path's last segment, with a dot segment (which names
    no directory) dropped in favour of the generic word, and no path shape puts a
    location in the two fields the row is joined on.

    It is the census's one answer to "which directory did this run fail to read",
    shared by the ledger, sessions and ordering rows for the same fault.
    """
    parts = rel.rstrip("/").split("/")
    if any(p in ("", ".", "..") or len(p) > _ROOT_SEGMENT_MAX for p in parts):
        # Not a plain path below the repo root, so not a name the census wrote.
        # The last segment alone is all the row may print; a segment that names no
        # directory (a dot, or a run of them) names nothing at all.
        return parts[-1].strip(".") or "ledger"
    if len(parts) >= 2 and not parts[0].startswith("~"):
        return "/".join(parts)
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
        # ``fault_text`` is the whole fault minus its path: OSError appends the
        # path it failed on (``[Errno 2] No such file or directory:
        # '/home/x/decisions'``) and ``e.filename`` holds it outright, so the row
        # is built from the exception's class and its ``strerror`` instead of
        # being scrubbed after the fact. The scrubber stays a safety net for text
        # whose shape nobody knows; it is no longer the thing standing between a
        # host directory and a published report.
        return LedgerProbe("empty", listing_fault=fault_text(e))
    # A decisions/ directory that holds no *.json record is "empty", not "ok":
    # the census exits 0 here so a freshly attached project is not permanently
    # red, and the git-backed deletion check still reports how the ledger got
    # empty (operator decision, issue #33). A directory that holds a record is
    # "ok". Both carry the names they listed, because both read them.
    if not names:
        return LedgerProbe("empty", names=())
    return LedgerProbe("ok", names=tuple(names))


# The bound a finished row keeps: ``census_text._clipped``'s own default, named
# here because the fault's budget is computed against it.
ROW_BOUND = 300

# The floor under a fault's budget. The row's own sentence is what it is, and a
# group whose prose already fills the bound must still be able to name the fault
# that refused it -- a cannot-tell whose parentheses are empty says "a read
# happened" and nothing about why it did not.
_MIN_FAULT_BOUND = 24

# The longest segment a directory inside the audited tree is ever named with. A
# path holding a longer one is not a name the census wrote: it is a fragment a
# caller walked out of its own cwd, and a repository directory is not a 240-
# character run of one letter. The identifier rule treats such a path as the
# caller's own and keeps its last segment, so no path shape puts a location -- or
# an unbounded run of someone else's characters -- into the two fields the row is
# joined on, and the row's bound stays arithmetic the builder can trust.
_ROOT_SEGMENT_MAX = 80


def append_listing_fault(dir_: Path, root: Path, findings: list[dict],
                         strict: bool, fault: str, *,
                         check: str, noun: str, unknown: str,
                         row: Callable[..., dict],
                         rel_to_root: Callable[[Path, Path], str],
                         bounded: Callable[..., str],
                         clipped: Callable[[str], str]) -> None:
    """The row for a directory this run could not list.

    The one composition of this row, shared by the ledger group and (for its
    register) the sessions group: two copies is how two rows that mean the same
    thing come to disagree about shape, bound or severity. It is built on the
    probe-honesty rule -- the alternative to saying so is calling an unreadable
    directory an empty one, the verdict a project that has never steered anything
    also earns.

    ``row`` builds it with an explicit ``severity="warn"`` (so ``--strict`` still
    promotes it through the row factory) and ``whole_artifact=True``: the row is
    about the directory the group was asked to read, not one file inside it, which
    is what keeps it visible under a filter that named none of the group's
    classes. ``check``, ``noun`` and ``unknown`` are required and come from the
    caller -- the class, the wording, and the question the faulted read took away
    are the group's own, and a shared builder must not quietly speak one group's
    vocabulary for the other.

    The directory is named by ``ledger_name(rel_to_root(root, dir_))`` in all
    three rendered fields (``subject``, ``artifact`` and the prose clause), so the
    row cannot disagree with itself about which directory it could not read. That
    identifier is either the root-relative path or the last segment of a path the
    caller spelled, so it holds no machine-local location and needs no scrub: the
    fault text is the only foreign thing the row carries, and the only thing that
    goes through ``bounded``.

    The row's budget is computed from the sentence, not passed in. The fault gets
    everything the census's own prose does not spend, up to ``ROW_BOUND`` and
    never below ``_MIN_FAULT_BOUND``: the sentence around the fault is what the
    group wrote, so the sentence is what pays, and the clause the census wrote is
    never what ``clipped`` cuts. A group that lengthens its own wording pays for it
    out of the fault's slack rather than out of the bound every other row of the
    report keeps, and no caller passes a number that could go stale.
    """
    # The identifier is the one answer to "which directory", asked of one rooting
    # so that ``subject``, ``artifact`` and the clause the row narrates cannot
    # disagree: the root-relative path where the census could root it, the last
    # segment of the path where it could not. Nothing here runs the raw path
    # through the scrubber: a scrubbed identifier is a marker, and a marker is not
    # a name a caller can join on or an operator can act on.
    name = ledger_name(rel_to_root(root, dir_))

    def compose(with_fault: str) -> str:
        """The finished message, with ``with_fault`` in the fault's parentheses.

        One composition, used twice: once with the fault empty to measure what the
        sentence itself costs, once with the fault's own words in it. Measuring the
        sentence this row actually builds is what makes the budget a bound and not
        an estimate -- a number a caller had guessed would have to be recomputed
        every time a group reworded its clause.
        """
        return (f"cannot-tell: {noun} ({name}) exists but could not be listed "
                f"({with_fault}), {unknown}")

    # The budget is what the sentence leaves over, floored so a group whose prose
    # already fills the bound still names the fault that refused it.
    fault_bound = max(ROW_BOUND - len(compose("")), _MIN_FAULT_BOUND)
    findings.append(
        row(check, strict, name, name,
            clipped(compose(bounded(fault, fault_bound))), root,
            severity="warn", whole_artifact=True))
