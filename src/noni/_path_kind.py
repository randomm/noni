"""The ``lstat`` question a writer asks before it reads or replaces a path.

:func:`noni.gitwrite.path_kind` is the question ``decide.py`` asks of a supersede
target it is about to write: "is this a plain file I may replace, or is it absent?"
Absent is an acceptable answer there, because the caller is about to create the file.

A writer that is about to READ or REPLACE a tracked file needs the stricter answer.
Only ``ENOENT`` and ``ENOTDIR`` mean "no file here" -- the two errno values a guard may
legitimately read as absence. Every other failure is the filesystem declining to
answer: ``EACCES`` from a parent the operator cannot read (a state clone left owned by
another user), ``ELOOP`` from a chain of links, ``ENAMETOOLONG`` from a name the
filesystem will not name. A guard that reads a declined answer as "absent" prints
"file not found" about a file it never looked at, and the writer that
creates reports success about a position it could not inspect. So
:func:`inspected_file_kind` refuses those, naming the path's verdict and the error,
and every guard asks that question of each path a write touches.

Both questions are asked of the same ``lstat`` exactly once, by :func:`kind_of`, so the
two cannot give two readings of one path.

The third question is the DIRECTION one, and it belongs here for the same reason: it
is the same ``lstat``, read the same way, and it must not give a third reading of one
path. :func:`direction_refusal` asks it of every component of a ``noni/`` directory
under a state root -- ``noni`` itself and the directory below it a writer reads or
writes -- and hands back a ``(headline, hint)`` pair for the caller to print. The
three direction writers (``decide``, ``order``, ``intent``) answer the direction
question here, beside the file
question, in words that name a directory and nothing else.

The fourth question is the STATE-ROOT one: "is this ``--repo`` a noni state root at
all?" It is the same ``lstat`` on ``noni`` itself, and it has its own sentence pair
(:data:`STATE_ROOT_NOT_A_NONI`, :data:`STATE_ROOT_NOT_A_NONI_HINT`) rather than a
reused one, because a directory that holds no ``noni/`` is not the same finding as a
``noni/`` that is a link or a plain file: the first says the caller named the wrong
tree, the second says the tree it named is obstructed. The writers that read state
ask it through :func:`state_root_refusal`; the wording lives here so no writer
composes its own.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

from ._safe_text import safe_path

# The word a refusal uses for a path that is a link. Spelled once, here, because
every guard asks the same question of the same bits.
SYMLINK_WORD = "symlink"

# The two errno values that mean "nothing of mine exists at that path". A refusal of
# any other kind is the filesystem declining to answer, which is not evidence that the
# position is free (see :func:`inspected_file_kind`).
ABSENT_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR})

# The head of the verdict :func:`_declined` renders for an ``lstat`` the filesystem
# refused to answer. One wording, so one declined syscall reads the same way to every
guard in the family.
_DECLINED_PREFIX = "could not be inspected"


def refusal_reason(exc: BaseException) -> str:
    """The words a declined ``lstat`` owes the operator, for either exception type.

    An OSError carries its reason in ``strerror`` ("Permission denied", "Too many
    levels of symbolic links"); a ``ValueError`` has no such attribute and only a
    message, whose first word is the syscall that refused (``"lstat: embedded null
    character in path"``). Both are rendered as what the filesystem said rather than
    an invented cause, with the class name as the tail for an exception that said
    nothing. Shared by :func:`kind_of` and
    :func:`_directory_kind` so the file and the directory
    question describe one declined syscall in one set of words.
    """
    reason = getattr(exc, "strerror", None) or str(exc).split(":")[0]
    return reason.strip() or exc.__class__.__name__


def kind_of(path: Path) -> tuple[str | None, str | None]:
    """The ``(kind, error)`` answer for one ``lstat``: at most one of the two is set.

    ``kind`` is why the path is no plain file -- a link, or something that is not a
    regular file. ``error`` is why the question could not be answered at all. The two
    callers below want different halves of the same syscall, and asking it twice would
    let them disagree about what is at the path.

    ``ValueError`` is caught beside ``OSError``: ``os.lstat`` raises it, and not an
    ``OSError``, for a path carrying a NUL -- which every guard refuses by name
    at its entry point, so catching it here is the last line of defence behind that
    rather than the ordinary route. Both are the same answer to the same question,
    "the filesystem declined to say what is at this path", and a caller that reads
    the declination as absence proceeds to write where it could not look.
    """
    try:
        mode = os.lstat(path).st_mode
    except (OSError, ValueError) as exc:
        if isinstance(exc, OSError) and exc.errno in ABSENT_ERRNOS:
            return None, None
        return None, refusal_reason(exc)
    if stat.S_ISLNK(mode):
        return f"is a {SYMLINK_WORD}", None
    if not stat.S_ISREG(mode):
        return "is not a regular file", None
    return None, None


def _declined(reason: str) -> str:
    """The verdict for an ``lstat`` the filesystem refused to answer.

    One sentence for the three questions: "could not be inspected" plus what the
    syscall said. A declined answer is never read as absence -- see
    :func:`inspected_file_kind`, :func:`direction_refusal` and :func:`has_no_noni`,
    which all refuse it.
    """
    return f"{_DECLINED_PREFIX} ({reason})"


def inspected_file_kind(path: Path) -> str | None:
    """Why ``path`` is no file a writer may read or replace, or None.

    :func:`noni.gitwrite.path_kind` plus one distinction that only matters to a
    reader: a declined ``lstat`` is a refusal rather than an absence. Absent and
    regular answer None; a link, a directory, a socket, a device, and any path whose
    ``lstat`` was declined by something other than ``ENOENT``/``ENOTDIR`` are refused.
    """
    kind, error = kind_of(path)
    if kind is None and error:
        return _declined(error)
    return kind


# The two sentences the direction writers print for one refused directory. The
# position is the writer's (``noni/decisions`` for decide, ``noni/direction`` for
# order and intent, and ``noni`` itself for all three), so the templates name no
# directory of their own: :func:`direction_refusal` fills it. The kind slot carries
# what the ``lstat`` actually saw -- "is a symlink", "is not a directory", or
# "could not be inspected (...)" -- so a device or an unreadable parent is never
# reported as a link the operator should go and remove.
DIRECTION_REFUSAL = "{path} {kind}: noni never reads or writes through it"
DIRECTION_REFUSAL_HINT = "replace {path} with a real directory inside the repository"

# The two sentences for a ``--repo`` that is a directory but holds no ``noni/``: a
# tree the caller named by mistake (a code repository where the state clone was meant,
# or the reverse). Distinct from :data:`DIRECTION_REFUSAL` on purpose -- that pair
# reports an obstruction at a ``noni/`` that IS there, this one reports that nothing
# of noni's lives at the path at all, which is what the pilot's "no decision record
# ... is in the ledger" answer failed to say. Spelled here rather than in a writer so
# the three direction writers and the census print one sentence. The path slot is
# filled with ``--repo`` as the caller spelled it, never a resolved absolute path.
STATE_ROOT_NOT_A_NONI = "{path} is not a noni state root: no noni/ directory is there"
STATE_ROOT_NOT_A_NONI_HINT = (
    "pass --repo naming the state root, the directory that holds (or will hold) "
    "noni/: the project repository itself, or the private state repository of "
    "docs/PRODUCT.md 7")

# The one directory whose presence makes ``--repo`` a state root at all: a tree that
# holds it is a tree noni was told to look in, and the only shape a no-``noni/``
# refusal may be reached through is its absence, which is also the state the sanctioned
# first writers create (:func:`has_no_noni` answers for it and nothing else).
STATE_ROOT_DIR = "noni"

# The two questions this module asks of a directory are both asked by a helper that
# gives the SAME answer for "a directory I may read" and for "nothing of mine is
# here": :func:`_directory_kind` returns None for both, which is all its own callers
# need (either way, do not refuse). The state-root question needs the distinction, so
# it asks :func:`_directory_verdict` instead, which keeps absence and acceptability
# apart. :data:`ABSENT` is that helper's one word for nothing at the path, and the
# verdicts it answers instead name every state the state-root refusal does NOT report
# as a missing ``noni/``: "is a symlink" and "is not a directory" belong to
# :data:`DIRECTION_REFUSAL`, and a verdict beginning :data:`_DECLINED_PREFIX` is the
# filesystem declining to answer. None of them may be collapsed into "no ``noni/``
# directory", which would contradict ``skills/census/SKILL.md`` where each stands as
# its own state.
ABSENT = "absent"


def _directory_verdict(path: Path) -> str | None:
    """Why ``path`` is no usable directory, :data:`ABSENT` when nothing is there, or
    None when it is a real directory.

    Three answers, not two: :data:`ABSENT` for a plain absence, a verdict string for
    every other reason the path is no directory ("is a symlink", "is not a directory",
    or the declined-``lstat`` sentence :func:`_declined` renders), and None for a real
    directory. A caller that reads this as "absent or usable" mis-handles the fault.

    :func:`_directory_kind` plus the distinction its callers never needed: a plain
    absence is reported rather than merged with "directory". Same ``lstat``, same
    bounds -- a link is judged before the directory question, and only
    ``ENOENT``/``ENOTDIR`` count as absence, so a declined answer stays a refusal.
    """
    try:
        mode = os.lstat(path).st_mode
    except (OSError, ValueError) as exc:
        if isinstance(exc, OSError) and exc.errno in ABSENT_ERRNOS:
            return ABSENT
        return _declined(refusal_reason(exc))
    if stat.S_ISLNK(mode):
        return f"is a {SYMLINK_WORD}"
    return None if stat.S_ISDIR(mode) else "is not a directory"


def has_no_noni(root: Path) -> bool:
    """Whether ``root`` holds no ``noni`` entry, so nothing of noni's has been written.

    The creator's test, and the strictest one a first run can be let through on: absence
    and nothing else. An ``noni`` that exists is state, even an empty one -- the census
    gives it its own state word and the readers answer for it (``skills/census/SKILL.md``)
    -- so a verb that creates state is admitted only where the directory is genuinely not
    there. A ``noni`` that is a link, a plain file, a socket or a device answers False
    beside it: those are :func:`direction_refusal`'s finding, and the census names each as
    its own state, so no guard here collapses them into "no ``noni/`` directory". So does
    an ``lstat`` the filesystem declined (``EACCES`` on a ``--repo`` the operator cannot
    traverse): a tree this run could not inspect is not evidence that it holds no state,
    and a guard that read the fault as an absence would admit a write it never looked at.
    """
    return _directory_verdict(
        Path(os.path.normpath(str(root))) / STATE_ROOT_DIR) == ABSENT


def state_root_refusal(root: Path) -> tuple[str, str] | None:
    """The ``(headline, hint)`` pair for a ``--repo`` that is no noni state root.

    The question a writer that only READS asks before its first read, probe or
    ``mkdir``: "does this tree hold any noni state?" It is :func:`has_no_noni`
    plus the two sentences above -- one ``lstat`` of ``<root>/noni``, no listing,
    and it never walks above ``root`` nor follows a link. Only a plain absence
    answers here: a link, a non-directory or a declined ``lstat`` answers None and is
    left to :func:`direction_refusal`, which words each of those states as the fault it
    is. A run whose verb creates
    the state it is about to write does not ask it: the first record, the first
    session, the first order entry and the first intent file all legitimately create
    ``noni/`` (see :func:`noni._writer.allocate_ledger`), so the refusal belongs to
    the readers and the verbs with no sanctioned create path, not to every caller of
    ``--repo``.

    The path in both sentences is the root as the caller spelled it, rendered once
    through :func:`noni._safe_text.safe_path`; nothing is printed, nothing raises, and
    the caller prints the pair through its own failure printer with its own label and
    its own code -- 2 for ``order`` and ``intent``, the code its tool already uses for
    a wrong path (docs/PRODUCT.md 7).
    """
    if not has_no_noni(root):
        return None
    text = safe_path(str(root))
    return (STATE_ROOT_NOT_A_NONI.format(path=text),
            STATE_ROOT_NOT_A_NONI_HINT)


def refuse_state_root(root: Path, creates: bool,
                      guarded: tuple[str, ...]) -> tuple[str, str] | None:
    """The one guard a direction writer runs on its ``--repo``, or None.

    Both ``noni/`` questions in the order that matters, asked of the same ``lstat``:
    first :func:`direction_refusal` over every component of ``guarded`` (a ``noni/``
    that is a link or a plain file is refused, never followed or written through),
    then :func:`state_root_refusal` for a tree holding no ``noni/`` at all.
    The obstruction question comes first so a linked ``noni/`` keeps the sentence that
    names it rather than being reported as a missing one, which is what
    ``skills/census/SKILL.md`` documents as its own state.

    A function that returns a ``(headline, hint)`` pair rather than printing, so each
    writer keeps its own label, its own ``fix:`` shape and its own exit code (2 for
    ``order`` and ``intent``: docs/PRODUCT.md 7), and the guard still runs before any
    read, probe or mkdir in the caller.
    """
    return (direction_refusal(root, guarded)
            or (None if creates else state_root_refusal(root)))


def _directory_kind(path: Path) -> str | None:
    """Why ``path`` is no directory a writer may read or write through, or None.

    The directory half of :func:`kind_of`, which answers only the FILE question and
    calls a directory "not a regular file". A link is judged by ``S_ISLNK`` before
    the directory question is asked, so a dangling link is a refusal rather than an
    absence; anything that is neither a directory nor a link -- a plain file, a
    socket, a device -- is refused as "is not a directory". Absent is the one
    non-answer: ``ENOENT`` and ``ENOTDIR`` are the state a first run creates, and any
    other failure is the filesystem declining to answer (:func:`_declined`), which is
    a refusal and never an absence.
    """
    try:
        mode = os.lstat(path).st_mode
    except (OSError, ValueError) as exc:
        if isinstance(exc, OSError) and exc.errno in ABSENT_ERRNOS:
            return None
        return _declined(refusal_reason(exc))
    if stat.S_ISLNK(mode):
        return f"is a {SYMLINK_WORD}"
    return None if stat.S_ISDIR(mode) else "is not a directory"


def direction_refusal(root: Path, rels) -> tuple[str, str] | None:
    """The ``(headline, hint)`` pair for a ``noni/`` directory this run may not use.

    The question ``decide``, ``order`` and ``intent`` ask of the directories they
    read and write, before their first read, probe or ``mkdir``. ``root`` is the
    state root as ``--repo`` spelled it and ``rels`` the directories beneath it --
    ``noni`` first, then the output directory (``noni/direction`` for the two
    direction writers, ``noni/decisions`` for decide and for the two writers that
    cite a record). The first refusal found is returned; None means every one of
    them is a directory or absent, which is the state the writers work in.

    Every component is asked, not just the last: ``lstat`` resolves every
    intermediate component and leaves only the last, so a link at ``noni`` makes the
    directory beneath it answer "directory" and the writer mkdirs straight through
    it into a tree outside the repository. Checking the leaf alone is the bug this
    walk exists to close.

    Two bounds hold it in place. It never climbs above ``root`` -- the parts of each
    ``rel`` are joined to the normalised root, so ``..``, an absolute name or the
    root itself can name nothing outside it, and no ancestor is ever examined.
    And the path in both sentences is the root as
    the caller spelled it joined to the rel, rendered once here through
    :func:`noni._safe_text.safe_path` -- the finished lines are never run through a
    second renderer, which would double every backslash an operator then copies.
    Nothing is printed and nothing raises: the caller prints the pair through its own
    failure printer, with its own label and its own code.
    """
    normalised = os.path.normpath(str(root))
    for rel in rels:
        parts = Path(os.fsdecode(rel) if isinstance(rel, bytes) else str(rel)).parts
        if not parts or ".." in parts or os.path.isabs(parts[0]):
            # Not a directory under the root, so there is nothing under the root to
            # inspect. The writers pass one of their own constants here; a caller
            # that passed something else gets the same answer an absent path gets
            # rather than a refusal of a path this run never reads or writes.
            continue
        for depth in range(1, len(parts) + 1):
            step = Path(os.path.join(*parts[:depth]))
            candidate = Path(normalised) / step
            kind = _directory_kind(candidate)
            if kind is not None:
                text = safe_path(str(candidate))
                return (DIRECTION_REFUSAL.format(path=text, kind=kind),
                        DIRECTION_REFUSAL_HINT.format(path=text))
    return None
