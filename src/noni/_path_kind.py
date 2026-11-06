"""The ``lstat`` question a writer asks before it reads or replaces a path.

:func:`noni.gitwrite.path_kind` is the question ``decide.py`` asks of a supersede
target it is about to write: "is this a plain file I may replace, or is it absent?"
Absent is an acceptable answer there, because the caller is about to create the file.

A writer that is about to READ or REPLACE a session file needs the stricter answer.
Only ``ENOENT`` and ``ENOTDIR`` mean "no file here" -- the two errno values a guard may
legitimately read as absence. Every other failure is the filesystem declining to
answer: ``EACCES`` from a parent the operator cannot read (a state clone left owned by
another user), ``ELOOP`` from a chain of links, ``ENAMETOOLONG`` from a name the
filesystem will not name. A guard that reads a declined answer as "absent" prints
"register file not found" about a session it never looked at, and the writer that
creates reports success about a position it could not inspect. So
:func:`inspected_file_kind` refuses those, naming the path's verdict and the error,
and the session guard asks that question of every path a write touches.

Both questions are asked of the same ``lstat`` exactly once, by :func:`kind_of`, so the
two cannot give two readings of one path.

The third question is the DIRECTION one, and it belongs here for the same reason: it
is the same ``lstat``, read the same way, and it must not give a third reading of one
path. :func:`direction_refusal` asks it of every component of a ``noni/`` directory
under a state root -- ``noni`` itself and the directory below it a writer reads or
writes -- and hands back a ``(headline, hint)`` pair for the caller to print. The
three direction writers (``decide``, ``order``, ``intent``) have no session guard to
borrow: :mod:`noni._session_paths`' sentences are about a session file and stay the
session writers', so the direction question is answered here, beside the file
question, in words that name a directory and nothing else.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

from ._safe_text import safe_path

# The word a refusal uses for a path that is a link. Spelled once, here and in
# :mod:`noni._session_paths`, because both ask the same question of the same bits.
SYMLINK_WORD = "symlink"

# The two errno values that mean "nothing of mine exists at that path". A refusal of
# any other kind is the filesystem declining to answer, which is not evidence that the
# position is free (see :func:`inspected_file_kind`).
ABSENT_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR})


def refusal_reason(exc: BaseException) -> str:
    """The words a declined ``lstat`` owes the operator, for either exception type.

    An OSError carries its reason in ``strerror`` ("Permission denied", "Too many
    levels of symbolic links"); a ``ValueError`` has no such attribute and only a
    message, whose first word is the syscall that refused (``"lstat: embedded null
    character in path"``). Both are rendered as what the filesystem said rather than
    an invented cause, with the class name as the tail for an exception that said
    nothing. Shared by :func:`kind_of` and
    :func:`noni._session_paths._directory_kind` so the file and the directory
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
    ``OSError``, for a path carrying a NUL -- which the session guard refuses by name
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

    One sentence for the two questions: "could not be inspected" plus what the
    syscall said. A declined answer is never read as absence -- see
    :func:`inspected_file_kind` and :func:`direction_refusal`, which both refuse it.
    """
    return f"could not be inspected ({reason})"


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
    root itself can name nothing outside it, and no ancestor is ever examined: a
    project *reached through* a link stays a normal run, which
    :func:`noni._session_git.linked_state_root` keeps as its own separate refusal of
    a ``--repo`` that is itself a link. And the path in both sentences is the root as
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
