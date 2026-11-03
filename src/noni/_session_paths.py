"""The one check that keeps a session write inside the state root it was named.

The four session writers (``register``, ``claim``, ``close``, ``release``) read
and replace one file under ``noni/sessions/``, and the commit primitive they all
share reads the tree before it stages. Each asks the two questions answered here
before it reads or writes anything, so a caller that skipped its own guard cannot
drive the commit primitive through a link either.

Both questions are the lstat one ``decide.py`` already uses for its supersede
target (:func:`noni.gitwrite.path_kind`), asked of the three paths a session write
touches: the session file itself, the ``noni/sessions`` directory the file is
written into, and the ``noni`` directory that holds it. ``is_file()`` is never
asked -- it follows a link, so a symlinked session file reads as present and the
writer's ``os.replace`` lands on the link's target, replacing somebody's link with
a session file holding the bytes this run composed. A symlinked ``noni/sessions``,
or a symlinked ``noni`` above it, is the same fault one or two levels up: the file
lands outside the tree and git then refuses a path "beyond a symbolic link", which
is git's words for a shape the writer saw before it wrote. The third path is not
optional: ``lstat`` resolves every intermediate component and leaves only the last,
so a link at ``noni`` makes both of the other two answer "directory" and "regular
file" and the write passes through untouched.

The two answers differ in what they allow through, and that difference is the
contract: a session FILE must be absent or a regular file, because those are the
two states a writer writes; any other kind, a link included, is refused. A session
DIRECTORY must be absent or a directory, so a plain file, socket or device at that
position is refused too -- :func:`noni.gitwrite.path_kind` alone cannot tell a
directory from a device, so the directory question reads ``S_IFMT`` itself and
shares ``path_kind``'s wording for the rest.

The refusal stops at the state root. :func:`noni._session_git.linked_state_root`
owns that refusal and looks at only the ``--repo`` component itself, because a
project *reached through* a link is the layout the quickstart sells and must stay a
normal run. Every path here is derived from that root and sits under it, so nothing
resolves an ancestor of the root: the walk up from the session file stops at the
root, and an ancestor above it is never a refusal.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from . import gitwrite

# A one-way import pair: ``_session_git`` imports this module for the refusal in
# :func:`stage_and_commit`, so nothing here may import it at module scope -- hence
# the local import inside :func:`_answer`. ``gitwrite`` is the far safer neighbour:
# it imports only gitenv and targetschema.

# The word every refusal here carries, and the word the tests assert is present:
# one spelling shared with the state-root refusal, so either message tells the
# operator the same thing about the path.
SYMLINK_WORD = "symlink"

# The one wording pair for a refused session-file path. ``{path}`` is the path
# the writer would have read or replaced and ``{kind}`` is the verdict the lstat
# returned, so the sentence names the shape actually found rather than guessing
# at a link that may be a device.
FILE_REFUSAL = ("{path} {kind} at its path: the session writers never read or "
                "write through a " + SYMLINK_WORD + ", so this run writes nothing")
FILE_REFUSAL_HINT = ("replace {path} with a regular session file, or remove it "
                     "and re-run the writer")

# The one wording pair for a refused directory on the way to a session file: the
# sessions directory itself and every directory above it down to the state root.
# The phrase is a description of the position, not a hard-coded name: the same
# sentence serves a link at ``noni/sessions`` and one at the ``noni`` above it, and
# a tree whose sessions live deeper is answered in the same words.
DIR_REFUSAL = ("{path} {kind} on the way to this writer's session file: the "
               "session writers never read or write through a link")
DIR_REFUSAL_HINT = ("replace {path} with a real directory, or remove it and let "
                    "the writer create it")


def _directory_kind(path: Path) -> str | None:
    """Why ``path`` is not a directory this writer may write into, or None.

    The kind is read from ``S_IFMT``, never from :func:`noni.gitwrite.path_kind`:
    that helper answers "is not a regular file" for a directory as well as for a
    device, and this question must let the first case through -- ``noni/sessions``
    being a directory is the state every writer works in. A link is refused by
    ``S_ISLNK`` before the directory question is asked, so a dangling link counts
    too (lstat, never ``is_file()``, is what makes a broken link a refusal rather
    than a missing directory). Anything that is neither a directory nor a link --
    a plain file, socket or device -- is refused as one. An absent path is None:
    that is the state the first ``register`` on a fresh repository writes into.
    """
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return None
    if stat.S_ISLNK(mode):
        return "is a symlink"
    return None if stat.S_ISDIR(mode) else "is not a directory"


def _answer(path: Path, kind: str, headline: str, hint: str) -> tuple[str, str]:
    """One refusal pair, with the caller's path and the lstat verdict filled in.

    Both fields carry a path the command line or a marker supplied, and this pair
    goes straight to stderr, so the path is sanitised on its way in and once for
    both sentences -- the same rule the writers' name refusals follow.
    """
    text = _sanitize(str(path))
    return (_sanitize(headline.format(path=text, kind=kind)),
            _sanitize(hint.format(path=text)))


def _sanitize(text: str) -> str:
    """One printed line's worth of text, control bytes dropped and tail bounded.

    Imported where it is used rather than at module scope: :mod:`noni._session_git`
    imports *this* module for its commit guard, and a module-scope import back would
    be taken while one of the two is still running its own import.
    """
    from . import _session_git
    return _session_git.safe_text(text)


def file_refusal(path: Path) -> tuple[str, str] | None:
    """The ``(headline, hint)`` pair when ``path`` is no file this writer may write.

    The question a writer asks of its session file after the name has been
    derived and before ``is_file()``, the read, or
    :func:`noni._session_git.atomic_write`. Absent and regular both answer None;
    a link, dangling or not, and any other non-regular path are refused.
    """
    kind = gitwrite.path_kind(path)
    if kind is None:
        return None
    return _answer(path, kind, FILE_REFUSAL, FILE_REFUSAL_HINT)


def directory_refusal(path: Path) -> tuple[str, str] | None:
    """The ``(headline, hint)`` pair when ``path`` is no directory this writer may use.

    The question a writer asks of every directory between the state root and the
    session file -- ``noni/sessions`` and the ``noni`` above it -- before its
    ``mkdir`` or its first write. A link, a plain file, a socket or a device is
    refused; an absent path is None, because creating the directory is what a first
    registration does.
    """
    kind = _directory_kind(path)
    if kind is None:
        return None
    return _answer(path, kind, DIR_REFUSAL, DIR_REFUSAL_HINT)


def write_refusal(repo: Path, rel: str) -> tuple[str, str] | None:
    """The refusal for the session file ``rel`` and the ``noni`` tree above it, or None.

    The one call every writer and the commit primitive makes, in the order the
    questions are asked: the sessions directory first, because a link there is the
    fault that puts the file outside the tree at all, then the ``noni`` directory
    that holds it, then the file itself. The middle question is the sessions one
    again -- it is the same judgement :func:`_directory_kind` makes, never a
    special case for one name -- so the question is asked of every directory between
    ``.git`` and the file, and a tree that holds sessions under any other name is
    refused on the same contract. It is not decoration: ``lstat`` resolves every
    component but the last, so a link at ``noni`` makes the other two answer
    "directory" and "regular file" and the write lands outside the state clone.
    Asked after the name has been derived and before ``is_file()``, any read, or
    :func:`noni._session_git.atomic_write`.

    Nothing here resolves an ancestor of ``repo``: :func:`noni._session_git
    .linked_state_root` owns the state-root question precisely because a project
    reached *through* a link must stay a normal run, so this helper takes the state
    root as given and examines only the paths beneath it -- every directory between
    the root and the file it would write, and the file itself.
    """
    rel_path = Path(rel)
    session_file = repo / rel_path
    path = session_file.parent
    while path != repo:
        refused = directory_refusal(path)
        if refused is not None:
            return refused
        path = path.parent
    return file_refusal(session_file)
