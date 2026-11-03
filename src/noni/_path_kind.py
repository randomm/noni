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
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

# The word a refusal uses for a path that is a link. Spelled once, here and in
# :mod:`noni._session_paths`, because both ask the same question of the same bits.
SYMLINK_WORD = "symlink"

# The two errno values that mean "nothing of mine exists at that path". A refusal of
# any other kind is the filesystem declining to answer, which is not evidence that the
# position is free (see :func:`inspected_file_kind`).
ABSENT_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR})


def kind_of(path: Path) -> tuple[str | None, str | None]:
    """The ``(kind, error)`` answer for one ``lstat``: at most one of the two is set.

    ``kind`` is why the path is no plain file -- a link, or something that is not a
    regular file. ``error`` is why the question could not be answered at all. The two
    callers below want different halves of the same syscall, and asking it twice would
    let them disagree about what is at the path.
    """
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        if exc.errno in ABSENT_ERRNOS:
            return None, None
        return None, exc.strerror or exc.__class__.__name__
    if stat.S_ISLNK(mode):
        return f"is a {SYMLINK_WORD}", None
    if not stat.S_ISREG(mode):
        return "is not a regular file", None
    return None, None


def inspected_file_kind(path: Path) -> str | None:
    """Why ``path`` is no file a writer may read or replace, or None.

    :func:`noni.gitwrite.path_kind` plus one distinction that only matters to a
    reader: a declined ``lstat`` is a refusal rather than an absence. Absent and
    regular answer None; a link, a directory, a socket, a device, and any path whose
    ``lstat`` was declined by something other than ``ENOENT``/``ENOTDIR`` are refused.
    """
    kind, error = kind_of(path)
    if kind is None and error:
        return f"could not be inspected ({error})"
    return kind
