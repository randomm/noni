"""The working copy's session marker: where it lives, what it says, and undoing one.

``register.py`` allocates a session and records the fact twice: once in the
committed file under ``noni/sessions/``, and once in a marker inside this
working copy's own git directory, which is how the next run of the same command
finds the session it already owns. The marker is uncommitted local state, which
makes it the one thing a failed run can leave pointing at a session nobody
committed -- so this module holds both halves: reading and writing it, and
putting it back when the commit that was supposed to justify it did not happen
(``marker_path`` is the one place the path rule is stated).

The path is built from ``--repo`` alone, never through ``git rev-parse``,
``GIT_DIR`` or ``GIT_WORK_TREE``, so an inherited environment cannot move a
working copy's marker into somebody else's tree.
"""

from __future__ import annotations

from pathlib import Path

from noni import _session_git

MARKER_NAME = "noni-session"


def marker_path(repo: Path) -> Path | None:
    """Where this working copy's marker lives, or None when it cannot be resolved.

    The path is built as a literal from ``--repo`` — never through ``git
    rev-parse``, GIT_DIR or GIT_WORK_TREE — so the marker belongs to the tree
    the operator named, whatever environment the caller inherited.

    ``<repo>/.git`` as a directory is the plain clone: the marker sits inside
    it. ``<repo>/.git`` as a file is a linked worktree, and the ``gitdir:`` line
    inside that file names the directory that holds this worktree's own state,
    so each worktree marks itself and two worktrees of one repository never
    share a session. Anything else (no ``.git``, a ``gitdir:`` line that is
    blank, malformed, or names a directory that does not exist) resolves to
    None: the caller mints a new session, writes no marker, and says so.
    """
    dot_git = repo / ".git"
    if dot_git.is_dir():
        return dot_git / MARKER_NAME
    try:
        text = dot_git.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("gitdir:"):
            continue
        named = line.split(":", 1)[1].strip()
        if not named:
            return None
        gitdir = Path(named)
        if not gitdir.is_absolute():
            gitdir = repo / gitdir
        return gitdir / MARKER_NAME if gitdir.is_dir() else None
    return None


def read_marker(marker: Path | None) -> str | None:
    """The session id the marker names, or None when there is nothing to read.

    The first line is the id; a marker that cannot be read, is empty, or whose
    first line is blank answers nothing (the caller allocates afresh), because a
    marker this run cannot trust is no evidence of a session at all. A file whose
    bytes are not UTF-8 is unreadable in exactly the way an OSError makes one --
    the run cannot trust it either -- so it answers nothing here too rather than
    raising out of the run that only came to look up its own session.
    """
    if marker is None:
        return None
    try:
        text = marker.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    first = text.split("\n", 1)[0].strip()
    return first or None


def write_marker(marker: Path | None, session_id: str) -> bool:
    """Record that this working copy owns ``session_id``; True when it landed.

    Written only after the session file itself was written, so a working copy
    never wakes up marked for a session whose file is not on disk.
    """
    if marker is None:
        return False
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        _session_git.atomic_write(marker, session_id + "\n")
    except OSError:
        return False
    return True


def read_marker_raw(marker: Path | None) -> str | None:
    """The marker's exact bytes, or None when this run created the marker.

    :func:`restore_marker` writes these bytes back verbatim, so the marker keeps
    the form the earlier run gave it (a trailing newline, an odd one, even an
    unreadable one) rather than the one value :func:`read_marker` reports. None
    is the caller's signal that there was nothing here to put back, so it is
    answered by absence alone: a marker that exists and reads as empty is
    reported as ``""`` and restored as an empty file, because a run does not
    delete bytes it could not read -- and an empty marker somebody had left
    standing is a fact about the tree, not this run's to undo.
    """
    if marker is None:
        return None
    try:
        return marker.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError:
        # Unreadable-but-present is still not this run's creation: restore the
        # empty bytes rather than delete what this run never saw.
        return "" if marker.exists() else None


def restore_marker(marker: Path | None, previous: str | None) -> bool:
    """Put the working copy's marker back to the bytes it held before this run.

    Called when a run wrote the marker and then could not commit its file: the
    marker is the evidence a later run reads to find this working copy's
    session, and a marker naming a session whose file never landed would make
    that run continue (or refuse to overwrite) a session nobody committed.
    'Back' means the previous bytes, including no marker at all when this run
    created one, so a first registration that fails leaves the tree exactly as
    it found it.

    Returns True when the tree is back where it was (nothing to restore counts
    as restored), False when the restore could not land. A failed restore is
    never raised into the caller -- the commit's own refusal is the fault the
    operator reads, and this runs inside that failure path -- but it is not
    silent either: the caller says the marker may still name a session git never
    received, which is the one state this function exists to prevent.
    """
    if marker is None:
        return True
    try:
        if previous is None:
            if marker.exists():
                marker.unlink()
        else:
            marker.parent.mkdir(parents=True, exist_ok=True)
            _session_git.atomic_write(marker, previous)
    except (OSError, UnicodeError):
        # UnicodeError as well as OSError: read_marker_raw reads with
        # surrogateescape, so a marker holding bytes that are not UTF-8 comes
        # back as lone surrogates, and the UTF-8 write below cannot encode them.
        # That is a restore that cannot land, not a reason to trace back over
        # the operator's failure message.
        return False
    return True
