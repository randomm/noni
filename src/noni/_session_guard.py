"""The session writers' path guards, each refusing in its own voice.

:mod:`noni._session_paths` answers the questions a session write must ask -- is
this session file a path this writer may read or replace, and is every directory
from the state root down to it (``noni/sessions`` and the ``noni`` above it) a
directory it may write into. This module adds the printing: the writer hands in its
failure printer and its exit code for a wrong path (2 for register, 4 for the other
three) and gets back the int to return, or None when the path may be written. A call
site is therefore two statements in a writer whose module is already at the size
limit.

The writer's printer is passed rather than duplicated here on purpose. Every session
writer prints a refusal the same way -- ``label: headline``, then ``label: fix:
hint``, then the code back -- so printing through the caller's own printer keeps the
prefix, the shape and any side effect that printer has (counting, capturing) with the
command the operator ran. Only the wording of the two lines is
:mod:`noni._session_paths`'s.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import _session_paths

# The shape every session writer's failure printer has: the code it wants back, the
# headline, the fix hint. Positional so a writer can pass its own ``_fail`` directly.
Printer = Callable[[int, str, str], int]


def session_write(printer: Printer, code: int, sessions_dir: Path | None,
                  session_file: Path | None = None) -> int | None:
    """The exit code for a session write this run may not make, or None.

    The one call a writer makes: the chain of directories from the state root down
    to ``sessions_dir`` (its last component is the sessions directory itself,
    because a link there is the fault that puts the file outside the state root at
    all), then ``session_file`` when the writer has already derived its name. The
    directories above the sessions one are not decoration: ``lstat`` resolves
    intermediate components, so a linked ``noni`` reads to the question below it as
    the ordinary directory and file beneath it. All answers are None in the ordinary
    case -- an absent directory (creating it is what a first registration does) and
    an absent or regular file -- so the writer's own 'register file not found' stays
    the verdict for a name that really is missing.

    Pass ``None`` for either path to skip its question. That is how the three
    writers which never create the directory ask both at once (``sessions_dir`` is
    their session file's own parent, and its parent is ``noni``), and how
    ``register`` asks them apart: it creates ``noni/sessions``, so an absent
    directory is its ordinary case and not a refusal, and it asks the file only after
    it has derived the name to write.
    """
    refused = _directory_chain(sessions_dir) if sessions_dir is not None else None
    if refused is None and session_file is not None:
        refused = _session_paths.file_refusal(session_file)
    return _report(printer, code, refused)


def _directory_chain(sessions_dir: Path) -> tuple[str, str] | None:
    """The first directory from the state root down to ``sessions_dir`` that is no
    directory, or None.

    :func:`noni._session_paths.write_refusal` walks the same chain for the commit
    primitive; this is that walk for a writer that hands in the directory it is
    about to write into instead of a name to derive. The path a writer hands in is
    always derived from its own state root, so the walk asks the same question of
    every component between the root and that directory rather than of the last one
    alone: a link anywhere on that way sends the write outside the clone, and
    ``lstat`` cannot see it through the component below it.

    The walk ends at the state root, which is the boundary
    :func:`noni._session_git.linked_state_root` owns: no ancestor of the root is
    examined here, so a project reached *through* a link stays a normal run.
    """
    path = sessions_dir
    while str(path) != str(path.parent):
        refused = _session_paths.directory_refusal(path)
        if refused is not None:
            return refused
        path = path.parent
    return None


def _report(printer: Printer, code: int,
            refused: tuple[str, str] | None) -> int | None:
    """One refusal through the writer's printer, or None when there was nothing to say.

    The printer is the writer's, so its prefix, its two-line shape and anything else
    it does (counting, capturing) stay with the command the operator ran.
    """
    if refused is None:
        return None
    return printer(code, *refused)
