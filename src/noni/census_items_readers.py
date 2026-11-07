"""The items group's reads: the store's listing, and the items it holds.

Split from ``census_items.py`` the way ``census_ordering_readers`` was split from
``census_ordering``: that module owns the six classes, their rows and the verdicts
over what these reads return, and this module owns the reads themselves. Nothing
here prints, exits or composes a row: each answer travels back as a value and the
caller words the finding its own class owns.

Two reads and one standard:

- :func:`items_listing` — the one readdir of ``noni/items/`` a run performs. It is
  an explicit ``Path.iterdir`` and never ``Path.glob``: ``glob`` swallows the
  ``OSError`` a faulted readdir raises and yields nothing, so a store the run
  could not read would earn the same clean verdict as a project that never filed
  an idea. The probe carries the fault's text instead, and both the run's gate and
  the group's rows read that one answer.
- :func:`items_scan` — the items behind that listing, each read through the
  census's open-time rules and parsed with the strict reader handed in at the call.

Every parse goes through ``load_json``, which the census passes as its own
``census_json.load_json_strict``, so what this arbiter can read is exactly what
``item.py`` can write, and a third copy of the strict reader's four refusals is
never born here. The reader arrives as an argument for the same reason the path
classifier and the message bounder do: a bare-name import would let any module
named ``census_json`` earlier on ``sys.path`` be trusted as the census's reader.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import itemschema
from .census_text import fault_text, path_is_known_missing


@dataclass(frozen=True)
class ItemsProbe:
    """The store directory's listing, answered once by :func:`items_listing`.

    Exactly one field is set, so "listed" and "did not list" are distinguishable by
    construction rather than by a convention the reporter must remember: ``names``
    is the ``*.json`` listing this run took (the empty tuple for a directory it
    listed and found nothing in — a read that answered "no items"), or ``fault`` is
    the text of the ``OSError`` that stopped the listing of a directory that
    exists, stats as a directory and cannot be read. A probe that could mean both
    is how an unlistable store reports the clean verdict of a project that never
    filed an idea.

    It is the sessions probe's shape (see ``census_sessions_probe.SessionsProbe``)
    and the ledger probe's minus their ``state`` fields: this group words no
    states, so there is no state word here for a fault to be mistaken for.

    ``fault`` comes from ``census_text.fault_text``, which reads the exception's
    class and its ``strerror`` and never its ``filename``: the path a read failed
    on is the one part of an ``OSError`` no row may carry. It is never the empty
    string, so the run's gate and the reporter's cannot diverge over one.
    """

    names: tuple[Path, ...] | None = None
    fault: str | None = None

    def __post_init__(self) -> None:
        if (self.names is None) == (self.fault is None):
            raise ValueError(
                "ItemsProbe answers one readdir: set names (the listing, () for "
                "a directory listed and found empty) or fault (the text of the "
                "OSError that stopped the listing), never both and neither")
        if self.names is not None and (
                not isinstance(self.names, tuple)
                or not all(isinstance(n, Path) for n in self.names)):
            raise TypeError(
                "ItemsProbe.names is the listing: a tuple of Path, not a "
                f"{type(self.names).__name__} of whatever it was handed")
        if self.fault is not None and not isinstance(self.fault, str):
            raise TypeError(
                "ItemsProbe.fault is the text of the OSError that stopped the "
                f"listing, not a {type(self.fault).__name__}")


def items_listing(items: Path) -> ItemsProbe:
    """List the store once; the whole census performs no other readdir of it.

    The one readdir of a run, taken by ``census_run._run`` before the group is
    gated on its answer, so the gate and the rows are the same read and cannot
    disagree about whether it happened.

    "A directory that is not there is not a fault" is the rule, and the honest way
    to hold it is to ask the filesystem rather than to read the exception: an
    ``OSError`` is the whole family, so it covers the store that cannot be *opened*
    (no permission, a name too long, a parent whose traversal is refused) as much as
    the one that is not there, and the two deserve different rows. The classifier is
    the census's own ``path_is_known_missing``, the one that separates "missing" from
    "the filesystem would not say": it answers False for an ``ENOENT``/``ENOTDIR``,
    which is the state of a project that never filed an idea and earns the empty
    listing and no row; it answers True for a path that exists and still could not be
    opened, which is this run's blindness and earns ``item-unlistable``; and a
    declined ``lstat`` raises out of it into the same blindness row, which is the
    honest third answer. ``_file_kind`` is not used here: its ``absent`` half reads a
    declined stat as absence, which is the misreading this probe must not make about
    the store it is reporting on.

    ``Path.iterdir`` and never ``Path.glob`` (see the module docstring for the
    swallowed ``OSError`` that decides it), and the fault's text goes out on
    ``fault`` rather than being read as an empty listing. The tuple is sorted
    because the group's reporters print sorted, and one order per run is what
    keeps two rows naming one file the same way.

    A directory that is not there at all is not a fault: it lists as empty, which
    is the state of a project that has never filed an idea, and the group adds no
    row for it. Only a directory that exists and cannot be listed faults -- and
    "cannot be listed" is read from the raised ``OSError``, not from a guess about
    what kind of path was expected. A plain file where the store should be raises
    ``NotADirectoryError``, which is not an ``ENOENT``/``ENOTDIR`` about the path's
    own existence, so it is a fault: the caller named a path (or the default names
    one) that holds something that is not the store, and an empty listing there
    would be the census certifying a store it never opened.
    """
    try:
        return ItemsProbe(names=tuple(sorted(
            p for p in items.iterdir() if p.suffix == ".json")))
    except OSError as exc:
        # ``NotADirectoryError`` is an ``ENOTDIR``, which the classifier below reads
        # as "this path is known not to be there". For the store that answer is wrong
        # in the dangerous direction: the path *is* there, it is just not a directory,
        # and "no such directory" and "not a directory" are two different things an
        # operator can be told. The two families are kept apart by which of them the
        # kernel raised about the path itself.
        #
        # A declined lstat reaches the same arm and must not escape: the classifier
        # raises on ``EACCES`` by design (that is how it refuses to call an
        # untraversable tree "absent"), and an escaping exception would end the whole
        # census with a traceback instead of the honest cannot-tell row. The raised
        # error is itself the evidence -- a path that was genuinely absent raised
        # ``ENOENT``/``ENOTDIR``, so anything else is a store this run was told to look
        # in and cannot, which is exactly what ``item-unlistable`` reports.
        if not isinstance(exc, NotADirectoryError):
            try:
                known_missing = path_is_known_missing(items)
            except OSError:
                return ItemsProbe(fault=fault_text(exc) or type(exc).__name__)
            if known_missing is False:
                return ItemsProbe(names=())
        return ItemsProbe(fault=fault_text(exc) or type(exc).__name__)


@dataclass(frozen=True)
class ItemScan:
    """What one run's single read of the store answered, per file.

    Three buckets, because the six classes ask three different questions of the
    same read and the answers must not be collapsed into one list of "bad files":

    - ``bodies`` holds the ``(stem, body)`` of every file this run read and
      recognised as an item, the store as this run saw it (a row's artifact is
      spelled by the caller from the store path it was handed, so no rooting is
      done here and no path of the caller's is composed from a listing);
    - ``unreadable`` holds the ``(stem, reason)`` of every file it was told to
      read and could not — a symlink (never followed), a directory or device, a
      file whose bytes could not be read, bytes that are not UTF-8, or a document
      the strict reader refused (a non-finite literal, a repeated key, a nesting
      past the depth bound);
    - ``not_items`` holds the ``(stem, problems)`` of every file it read in full
      and found was not an item the store describes;
    - ``id_mismatch`` holds the ``(stem, problem)`` of every file this run read as a
      complete item document whose ``id`` field names something other than its own
      stem — a defect of a file the group can still describe, so its body stays in
      ``bodies`` and its age and citations stay checkable.

    The distinction between the last two is the whole of the probe-honesty rule
    for this group: a file the run could not read and a file it read and found wrong
    stay distinct buckets, because the first is a warning about this run and the second
    a failure about the project; they agree only on the consequence, which is that the
    group stops short of the store-wide questions. The ruling gives the group one
    blindness class of its own (``item-unlistable``, for the store it could not open)
    and no class for a single file it could not open: such a file is reported as
    ``item-malformed`` with the reason this run could not read it, which is the one
    finding the file does support -- no item was read at that path.
    """

    bodies: tuple[tuple[str, dict], ...] = ()
    unreadable: tuple[tuple[str, str], ...] = ()
    not_items: tuple[tuple[str, tuple[str, ...]], ...] = ()
    id_mismatch: tuple[tuple[str, str], ...] = ()

    @property
    def blind(self) -> bool:
        """Whether this run read less than the store holds.

        The one test every class that counts, ages or resolves asks before it
        answers, and it is asked of the read rather than of a flag a caller sets:
        a run that could not open three files has no standing to say the other
        forty are in order.

        A file this run opened, read in full and found to be no item at all belongs
        to that test beside the files it could not open. The classes below ask
        questions of the store as a whole — does any live record answer this
        citation, which issues does the order hold — and one hand-made file is one
        item whose status, age and citations are unknown, so a run that certified the
        rest of that store would report the verdict of a store it did not read. The
        malformed rows it earned are still reported. Blindness (``unreadable``) and a
        defect (``not_items``) stay distinct buckets, because the first is a warning
        about this run and the second a failure about the project; they agree only on
        the consequence, which is that the group stops short of the store-wide
        questions.
        """
        return bool(self.unreadable or self.not_items)


def items_scan(items: Path, names: tuple[Path, ...], *,
               file_kind: Callable[..., tuple[str, str | None]],
               read_record: Callable[[Path], tuple[bytes | None, OSError | None]],
               load_json: Callable[[bytes], object],
               bounded: Callable[..., str]) -> ItemScan:
    """Read every ``*.json`` of ``names`` and sort the answers into the three buckets.

    ``names`` is the run's one listing, handed down from the probe: this function
    never lists the directory for itself, which is what keeps the gate's answer and
    the rows' answer the same read.

    Each file is classified with the census's own ``file_kind`` (so a symlink, a
    directory or a device is refused before it is opened) and then opened through
    ``read_record`` — the census's one open-time-safe reader (``O_NOFOLLOW``,
    ``O_NONBLOCK`` and an ``fstat`` on the descriptor). The classifier's verdict is
    asked *and* the open refuses again: classify-then-open leaves an interval in
    which a file can be swapped for a link, and it is the flags on the open, not
    the earlier stat, that close it.

    The fault text of every refusal is this run's own fixed sentence for the shape
    it met, with one exception: the ``OSError`` a read or an open raised goes
    through ``bounded``, because that text is foreign and can carry a host path.
    A file's own contents are never quoted, so a malformed item cannot put its own
    bytes into a report.
    """
    bodies: list[tuple[str, dict]] = []
    unreadable: list[tuple[str, str]] = []
    not_items: list[tuple[str, tuple[str, ...]]] = []
    id_mismatch: list[tuple[str, str]] = []
    for path in names:
        stem = path.stem
        kind, problem = file_kind(path)
        if kind == "absent":
            # The listing named a file that is no longer there. That is the race a
            # read-only census runs into by design, and it says nothing about the
            # project: reported as this run's blindness rather than as a defect.
            unreadable.append((stem, "the file the store listed was gone when "
                                     "this run reached it"))
            continue
        if kind != "regular":
            unreadable.append((stem, _shape_words(kind, problem)))
            continue
        raw, fault = read_record(path)
        if fault is not None:
            unreadable.append((stem, f"the file could not be opened "
                                f"({bounded(fault_text(fault))})"))
            continue
        if raw is None:  # pragma: no cover - read_record answers one or the other
            unreadable.append((stem, "the file could not be opened"))
            continue
        verdict = _classify(raw, load_json)
        if isinstance(verdict, str):
            unreadable.append((stem, verdict))
            continue
        problems = itemschema.problems(verdict)
        # The id check is split out of the rest of the schema. An ``id`` that is not
        # the file's stem is a defect of a document this run *can* describe: its
        # status, its age and its citations are all known, so the age and citation
        # classes keep their standing and ``id_mismatch`` reports the disagreement
        # beside them. Every other problem leaves those three unknown, which is the
        # state that stops the group at its malformed rows.
        id_lines = itemschema.id_problems(verdict, stem)
        if id_lines:
            id_mismatch.append((stem, id_lines[0]))
        if problems:
            not_items.append((stem, tuple(problems)))
            continue
        bodies.append((stem, itemschema.body_of(verdict)))
    return ItemScan(bodies=tuple(bodies), unreadable=tuple(unreadable),
                    not_items=tuple(not_items), id_mismatch=tuple(id_mismatch))


def _shape_words(kind: str, problem: str | None) -> str:
    """Why the census will not open the path, in this file's own words.

    The classifier's problem half is never quoted: for the two states that reach a
    row it is a fixed sentence this module wrote, so a row carries no ``OSError``
    text (which can name a host path and run to any length), no bare ``None`` from
    a classifier that named no problem, and no verdict word a classifier might gain
    later. The finding is that this run could not say, not what the filesystem said
    about it.
    """
    if kind == "symlink":
        return "the path is a symlink and the census does not read through links"
    return ("the path is not a regular file, or the census could not say what "
            "stands there")


def _classify(raw: bytes, load_json: Callable[[bytes], object]) -> dict | str:
    """The parsed document, or the fixed sentence saying this run could not read it.

    Two faults and one answer, kept apart by type rather than by sentinel: a
    ``str`` return is this run's blindness (bytes that are not UTF-8, a document
    the strict reader refuses) and a ``dict`` is a document read in full, which the
    caller then judges against the item shape. A non-finite literal, a repeated key
    or a nesting past the depth bound all arrive as the reader's own ``ValueError``
    and get one content-free sentence; ``RecursionError`` is named because it is no
    kind of ``ValueError`` — the bound answers for a document short of the
    interpreter's ceiling, past which the decoder raises this one first, so the arm
    is reachable and not decorative.
    """
    try:
        value = load_json(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return "the file is not JSON the census can read"
    return value if isinstance(value, dict) else "the file is not a JSON object"
