"""The session writers' path guards, each refusing in its own voice.

:mod:`noni._session_paths` answers the questions a session write must ask -- is
this session file a path this writer may read or replace, and is every directory
from the state root down to it (``noni/sessions`` and the ``noni`` above it) a
directory it may write into -- in ONE walk over the parts of the name, so there is
no second walk here and no ancestor of the state root is ever examined. This module
adds the printing: the writer hands in its failure printer and its exit code for a
wrong path (2 for register, 4 for the other three) and gets back the int to return,
or None when the path may be written. A call site is therefore two statements in a
writer whose module is already at the size limit.

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


def session_write(printer: Printer, code: int, repo: Path | None,
                  rel: str | None, *, creates: bool = False,
                  directory_only: bool = False) -> int | None:
    """The exit code for a session write this run may not make, or None.

    The one call a writer makes: :func:`noni._session_paths.walk_refusal` takes the
    state root and the name inside it, asks the directory question of every
    directory strictly below that root and down to ``rel`` (the last of them is the
    sessions directory itself, because a link there is the fault that puts the file
    outside the state root at all), then the file question of ``rel`` itself. The
    directories above the sessions one are not decoration: ``lstat`` resolves
    intermediate components, so a linked ``noni`` reads to the question below it as
    the ordinary directory and file beneath it. All answers are None in the ordinary
    case -- an absent directory (creating it is what a first registration does) and
    an absent or regular file -- so the writer's own 'register file not found' stays
    the verdict for a name that really is missing.

    The writers pass the state root and the ONE name they derived
    (:func:`noni._session_git.writer_name`, or :func:`noni._session_git.session_id_rel`
    for the directory ``register`` creates), never a ``Path`` they joined themselves:
    four joins and two walks became one, and the guard's root and the writer's write
    location cannot then be two different directories.

    Pass ``None`` for either argument to skip the whole question. ``creates`` says
    whether this writer mkdirs the sessions directory (only ``register`` does), which
    decides the hint a refused directory gets: the other three never create it, so
    their hint must not tell the operator to remove a link and let the writer
    create it.
    """
    if repo is None or rel is None:
        return None
    return _report(printer, code, _session_paths.session_file_refusal(
        repo, rel, creates=creates, directory_only=directory_only))


def _report(printer: Printer, code: int,
            refused: tuple[str, str] | None) -> int | None:
    """One refusal through the writer's printer, or None when there was nothing to say.

    The printer is the writer's, so its prefix, its two-line shape and anything else
    it does (counting, capturing) stay with the command the operator ran.
    """
    if refused is None:
        return None
    return printer(code, *refused)
