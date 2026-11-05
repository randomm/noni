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

:func:`allocate` and :func:`taken_refusal` are the one question only ``register``
asks: an allocated name that is already spoken. They print through the same printer
and take the same code, so a name collision reads in register's own voice and on the
code it already uses for a wrong path.
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


def taken_refusal(repo: Path, rel: str) -> tuple[str, str] | None:
    """The ``(headline, hint)`` pair for the allocated name ``rel``, or None if free.

    The question without the printing, for a caller that wants to ask it in a loop
    and decide what to do about a yes itself (:func:`allocate` does exactly that).

    Like every guard in this family it answers, never raises: the name is joined
    through :func:`noni._session_paths.taken_name_refusal`, which decodes a bytes
    name and stringifies an odd one the way the walk does, so a shape no writer
    passes still gets a sentence rather than a traceback.
    """
    if not _session_paths.name_taken(_session_paths.allocation_target(repo, rel)):
        return None
    return _session_paths.taken_name_refusal(repo, rel)


def allocate(printer: Printer, code: int, name: Callable[[], str],
             to_rel: Callable[[str], str], repo: Path, retries: int) -> tuple[str, str] | int:
    """``(id, rel)`` for one allocation, or the exit code of the refusal that stopped it.

    The retry loop ``register``'s allocating route needs, in the module that owns the
    questions it asks: mint an id, derive the name, ask the path question then the
    taken-name question, and mint again on a name that is spoken -- at most
    ``retries`` times. A name the *name* guard refuses (see the writer's own
    ``writer_name``) is not retried: a bad id is not made better by another mint, so
    it comes back as the refusal its caller prints on the code for a bad argument.
    Only a name the filesystem has taken is re-minted, which is why a happy-path run
    costs exactly one call to ``name``.

    ``retries`` is floored at zero: a bound below that would never enter the loop and
    so would report a refusal about a name it never minted. A run that mints no name
    has no taken name to report, so it asks once.
    """
    for _ in range(max(0, retries) + 1):
        session_id = name()
        rel = to_rel(session_id)
        if not rel:
            # Not a name at all: the caller refuses it as an argument, so return the
            # id and the empty name rather than deciding that code here.
            return session_id, rel
        if (refused := session_write(printer, code, repo, rel, creates=True)):
            return refused
        if (refused := taken_refusal(repo, rel)):
            # Spoken: another mint, until the bound runs out.
            continue
        return session_id, rel
    return _report(printer, code, _session_paths.all_taken_refusal(repo, rel,
                                                                    max(0, retries)))


def _report(printer: Printer, code: int,
            refused: tuple[str, str] | None) -> int | None:
    """One refusal through the writer's printer, or None when there was nothing to say.

    The printer is the writer's, so its prefix, its two-line shape and anything else
    it does (counting, capturing) stay with the command the operator ran.
    """
    if refused is None:
        return None
    return printer(code, *refused)
