"""The one check that keeps a session write inside the state root it was named.

The four session writers (``register``, ``claim``, ``close``, ``release``) read
and replace one file under ``noni/sessions/``, and the commit primitive they all
share reads the tree before it stages. Each asks the two questions answered here
before it reads or writes anything, so a caller that skipped its own guard cannot
drive the commit primitive through a link either.

Both questions are the lstat one ``decide.py`` already uses for its supersede
target (:func:`noni.gitwrite.path_kind`), asked of every directory between the
state root and the session file (``noni/sessions``, the ``noni`` that holds it,
and anything deeper a tree puts in between) and then of the file itself.
``is_file()`` is never asked -- it follows a link, so a symlinked session file
reads as present and the writer's ``os.replace`` lands on the link's target,
replacing somebody's link with a session file holding the bytes this run composed.
A symlinked ``noni/sessions``, or a symlinked ``noni`` above it, is the same fault
one or two levels up: the file lands outside the tree and git then refuses a path
"beyond a symbolic link", which is git's words for a shape the writer saw before it
wrote. The directories are not optional: ``lstat`` resolves every intermediate
component and leaves only the last, so a link at ``noni`` makes both of the other
two answer "directory" and "regular file" and the write passes through untouched.

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
resolves an ancestor of the root.

The walk that enforces that boundary -- and the two name questions asked before it
(``_normalise_name``, ``outside_root_refusal``) -- lives in :mod:`noni._session_walk`,
re-exported from the bottom of this module so callers keep one import. The seam is the
one this docstring has always drawn: the two ``lstat`` questions and every refusal
sentence are here, and the traversal that asks them, the only loop in the pair, is
there. The boundary is structural rather than a loop condition: ``walk_refusal`` walks
the ``relative_to`` parts of the name it was given, so there is no walk upward at all
and no ancestor can be examined however the root was spelled. The name is refused
before it is walked, and the two refusals are separate sentences with separate fixes: a
name that is empty, blank after ``strip()``, carries a control character, is ``.``,
absolute, or one that walks out of the root with a ``..`` is not a file inside the root
in the first place, so :data:`OUTSIDE_REFUSAL` answers it and never reaches the
``lstat`` questions that produced the "through a link" wording for decades of shapes it
was never about. That first question is asked of the text the entry point derives:
bytes decoded by :func:`os.fsdecode`, so the guard and the walk are given one name and
not two readings of it.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from . import _path_kind
from ._safe_text import safe_path

# A one-way import pair: ``_session_git`` imports this module for the refusal in
# :func:`stage_and_commit`, so nothing here may import it at module scope -- hence
# the local import inside :func:`_answer`. ``gitwrite`` is the far safer neighbour:
# it imports only gitenv and targetschema.
#
# The same rule holds the walk off this module's top. The walk asks the two
# questions defined here, so it imports them; were this module to import it back
# at module scope, the pair would be a cycle, and ``python -c "import
# noni._session_walk"`` -- the walk read on its own, which is the shape a reader
# or a traceback lands on -- would fail with "cannot import name ... from a
# partially initialized module". Hence the local import inside :func:`_walk`,
# which is the only statement here that reaches the walk: it runs after both
# modules exist, so either module is importable first.

# The word every refusal here carries, and the word the tests assert is present:
# one spelling shared with the state-root refusal, so either message tells the
# operator the same thing about the path.
SYMLINK_WORD = "symlink"

# The one wording pair for a name that is not a file inside the state root at all:
# empty, whitespace-only, a bare control character, ``.``, an absolute path, or one
# that walks out. The walk below has no answer for such a name -- there is no chain
# of directories under the root to inspect -- so it is refused by name, before
# anything is lstat'ed, in words that describe a NAME rather than a path kind.
OUTSIDE_REFUSAL = ("{path} is not a session file inside the state root: the session "
                   "writers refuse a name that is empty, names the root itself, is "
                   "absolute, or walks out of the root with ..")
OUTSIDE_REFUSAL_HINT = ("pass the session id, so this run derives its own name under "
                        "{directory}, or pass a name beneath that directory without a "
                        ".. in it")

# The one wording pair for a refused session-file path. ``{path}`` is the path
# the writer would have read or replaced and ``{kind}`` is the verdict the lstat
# returned -- "is a symlink", "is not a regular file", or "could not be inspected
# (...)" -- so the sentence names the shape actually found and says "symlink" only of
# a path that is one. The sentence itself stays neutral about the kind: an operator
# reading "never read or write through a symlink" about a device would go looking for
# a link that is not there.
# The two sentences are built from the kind the lstat actually returned, so a device
FILE_REFUSAL = "{path} {kind} at its path: the session writers never read or write through it, so this run writes nothing"
FILE_REFUSAL_HINT = ("replace {path} with a regular session file, or remove it "
                     "and re-run the writer")

# The one wording pair for a refused directory on the way to a session file: the
# sessions directory itself and every directory above it down to the state root.
# The phrase is a description of the position, not a hard-coded name: the same
# sentence serves a link at ``noni/sessions`` and one at the ``noni`` above it, and
# a tree whose sessions live deeper is answered in the same words.
DIR_REFUSAL = ("{path} {kind} on the way to this writer's session file: the session "
               "writers never read or write through it")

# The fix for a refused directory, in two flavours. Three writers only ever READ
# the sessions tree -- they refuse a session that is not registered rather than
# create one -- so for them the remedy is to put a real directory back. ``register``
# is the writer that mkdirs the sessions directory, so telling the operator to
# remove the link and let the writer create it is only true of that one run; it is
# also the reason an absent directory is never a refusal anywhere in this module.
DIR_REFUSAL_HINT = ("replace {path} with a real directory, or remove it and let "
                    "the writer create it")
DIR_REFUSAL_HINT_NO_CREATE = ("replace {path} with a real directory, or remove it; "
                              "this writer never creates that directory")

# The one wording pair for an allocated session name that something already holds.
# ``register`` is the writer that mints its own name, and a minted id can land on a
# path that is occupied -- by a committed session file whose id a second allocator
# happened to repeat, or by anything else a tree put under ``noni/sessions``. The
# sentence names the occupied path and the one action that clears it; the fix is the
# one that is true of both cases, because a run that allocates its own name cannot be
# told to "pick another id" -- the operator chose no id. A refusal here is register's
# usage code (2): the write simply does not happen, which is the same verdict the
# neighbouring path refusals give, and never the git code.
TAKEN_REFUSAL = ("{path} already exists: the session writers never replace a file "
                 "they did not allocate, so this run writes nothing")
TAKEN_REFUSAL_HINT = ("re-run the writer, which mints another session id under "
                      "{directory}, or remove {path} if nothing owns it any more")

# The wording for the rarer verdict: the allocating route re-minted up to its bound and
# every name it produced was spoken. ``{path}`` is the last name it tried (the earlier
# ones are gone, each having sent the run back to the allocator), and the fix says what
# is actually true at that point -- the day's name space is being competed for, so the
# operator reruns the writer or clears the names that hold them.
ALL_TAKEN_REFUSAL = ("every session name this run allocated already exists: the last "
                     "was {path}, and {tries} names found no free one, so this run "
                     "writes nothing")
ALL_TAKEN_REFUSAL_HINT = ("re-run the writer, which mints again, or remove the "
                          "session files under {directory} that nothing owns any more")

# The two errno values that mean "nothing of mine exists at that path" live with
# the file half of the question, in :data:`noni._path_kind.ABSENT_ERRNOS`, so the
# directory and the file answer the declined-``lstat`` case the same way.


def _directory_kind(path: Path) -> str | None:
    """Why ``path`` is not a directory this writer may write into, or None.

    The kind is read from ``S_IFMT``, never from :func:`noni.gitwrite.path_kind`:
    that helper answers "is not a regular file" for a directory as well as for a
    device, and this question must let the first case through -- ``noni/sessions``
    being a directory is the state every writer works in. A link is refused by
    ``S_ISLNK`` before the directory question is asked, so a dangling link counts
    too (lstat, never ``is_file()``, is what makes a broken link a refusal rather
    than a missing directory). Anything that is neither a directory nor a link --
    a plain file, socket or device -- is refused as one.

    Only ``ENOENT`` and ``ENOTDIR`` mean absent, which is the state the first
    ``register`` on a fresh repository writes into. Every other ``OSError`` is
    refused with the path and the error named: an unreadable parent (``EACCES``)
    or a link loop (``ELOOP``) is not evidence that the position is free, and the
    writer that treats it as such composes a file it never saw. The two errno
    values are shared with :func:`noni._path_kind.inspected_file_kind`, the file half
    of the same question, and so is the ``ValueError`` half: ``os.lstat`` raises
    ``ValueError`` for a name carrying an embedded NUL, and the two questions must
    give the same "could not be inspected" verdict for one declined syscall.
    """
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        if exc.errno in _path_kind.ABSENT_ERRNOS:
            return None
        return f"could not be inspected ({exc.strerror or exc.__class__.__name__})"
    except ValueError as exc:
        return f"could not be inspected ({_path_kind.refusal_reason(exc)})"
    if stat.S_ISLNK(mode):
        return f"is a {SYMLINK_WORD}"
    return None if stat.S_ISDIR(mode) else "is not a directory"


def _answer(path: Path, kind: str, headline: str, hint: str) -> tuple[str, str]:
    """One refusal pair, with the caller's path and the lstat verdict filled in.

    Both fields carry a path the command line or a marker supplied, and this pair
    goes straight to stderr, so the path is sanitised BEFORE the interpolation and
    the composed sentences are rendered by plain :func:`safe_path`, not by running
    the finished lines through a second renderer. That ordering is the point: a
    renderer that escapes backslash applied to an already-escaped path doubles every
    backslash in it, so an operator who copies the path from the refusal ends up
    naming a file the guard never inspected. One render, one pass over the caller's
    bytes; the templates hold no caller text of their own.
    """
    text = safe_path(str(path))
    return (headline.format(path=text, kind=kind),
            hint.format(path=text, directory=_sessions_rel()))


def _walk():
    """The walk module, imported at the call: see the import-pair note above.

    :mod:`noni._session_walk` imports this module for the two ``lstat`` questions
    and the refusal templates, so a module-level import here would close the loop.
    Deferring it to the call keeps both modules importable on their own; the four
    names below re-export the walk's entry points through this module's name.
    """
    from . import _session_walk
    return _session_walk


def _sessions_rel() -> str:
    """The sessions directory, for the one hint that names it.

    Read from :mod:`noni._session_git` rather than spelled here: the primitive owns
    the one spelling of ``noni/sessions``, and a second copy in a refusal string is
    a second copy that can go stale. The import is local for the same reason
    :func:`_sanitize`'s is.
    """
    from . import _session_git
    return _session_git.SESSIONS_REL


def file_refusal(path: Path) -> tuple[str, str] | None:
    """The ``(headline, hint)`` pair when ``path`` is no file this writer may write.

    The question a writer asks of its session file after the name has been
    derived and before ``is_file()``, the read, or
    :func:`noni._session_git.atomic_write`. Absent and regular both answer None;
    a link, dangling or not, any other non-regular path, and a path whose
    ``lstat`` was declined are refused (see
    :func:`noni._path_kind.inspected_file_kind` -- a reader must not mistake "I could
    not look" for "there is nothing here").
    """
    kind = _path_kind.inspected_file_kind(path)
    if kind is None:
        return None
    return _answer(path, kind, FILE_REFUSAL, FILE_REFUSAL_HINT)


def directory_refusal(path: Path, *, creates: bool = False) -> tuple[str, str] | None:
    """The ``(headline, hint)`` pair when ``path`` is no directory this writer may use.

    The question a writer asks of every directory between the state root and the
    session file -- ``noni/sessions`` and the ``noni`` above it -- before its
    ``mkdir`` or its first write. A link, a plain file, a socket or a device is
    refused; an absent path is None, because creating the directory is what a first
    registration does.

    ``creates`` selects the hint. It is True only for ``register``, the one writer
    that mkdirs the sessions directory; the other three refuse a session they were
    not registered for rather than build the tree, so their hint must not promise a
    creation that will never happen.
    """
    kind = _directory_kind(path)
    if kind is None:
        return None
    hint = DIR_REFUSAL_HINT if creates else DIR_REFUSAL_HINT_NO_CREATE
    return _answer(path, kind, DIR_REFUSAL, hint)


def _allocation_rel(repo: Path, rel: object) -> str:
    """``rel`` as ONE path under ``repo``, never a path that escapes it.

    The join the taken-name questions share. Two things are normalised here rather
    than left to the caller: bytes are decoded by :func:`os.fsdecode`, the same
    decoding the walk uses for a name (``str(b"x")`` would inspect the four
    characters of its repr instead of the file somebody named), and the answer is
    re-based on the root by PARTS, so an absolute name or one that walks out with
    ``..`` names a position under ``repo`` instead of outside it. A guard that
    reported an outside position as "your allocated name is taken" would send the
    operator to delete a file this writer never allocates; the position checked here
    and the position written (:func:`noni._session_git.atomic_write` joins the same
    name to the same root) are then always the same position.
    """
    text = os.fsdecode(rel) if isinstance(rel, bytes) else str(rel)
    normalised = os.path.normpath(str(repo))
    joined = os.path.normpath(os.path.join(normalised, *text.split(os.sep)))
    try:
        return str(Path(joined).relative_to(normalised))
    except ValueError:
        return os.path.join(*Path(joined).parts[1:])


def allocation_target(repo: Path, rel: object) -> Path:
    """``repo`` joined to the name ``rel``, in the ONE decoding this module uses.

    The path the taken-name questions ``lstat``: the root and the name rebased under
    it by :func:`_allocation_rel`, which is the same join the writer makes from the
    name its allocation produced.
    """
    return Path(os.path.normpath(str(repo))) / _allocation_rel(repo, rel)


def name_taken(path: Path) -> bool:
    """Whether anything at all sits at ``path``, without following a link.

    The question an allocating writer asks of its own minted name, and it is NOT the
    file question the path guards ask. :func:`noni._path_kind.inspected_file_kind`
    answers None for BOTH an absent path and a regular file, because those are the two
    states a writer writes; for this question a regular file that is already there is
    the one answer that matters -- it is the victim the atomic ``os.replace`` would
    overwrite -- so the verdict is ``lstat``'s, not that helper's: does anything sit
    here.

    ``os.lstat``, never ``is_file()``: a dangling symlink is not a free name, because
    ``os.replace`` lands on the link's target and leaves the link where it was (the
    fault ``decide.py`` fixed by asking ``lexists`` of its allocated record path, in
    :func:`noni.decide._path_is_taken`). A declined ``lstat`` answers True: "I could
    not look" is not evidence that the position is free, and the writer that treats it
    as such composes a file over one it never saw.
    """
    try:
        os.lstat(path)
    except OSError as exc:
        return exc.errno not in _path_kind.ABSENT_ERRNOS
    except ValueError:
        # ``os.lstat`` raises ValueError, not OSError, for a name carrying a NUL.
        return True
    return True


def taken_name_refusal(repo: Path, rel: object) -> tuple[str, str]:
    """The ``(headline, hint)`` pair for an allocated name something already holds.

    One call, one rendering of the path, in :func:`_answer`, beside the two path-kind
    refusals: an allocating writer must not compose its own sentence about an occupied
    name any more than it composes one about a linked path. The caller passes the
    root and the name it was handed, not a joined ``Path``: :func:`allocation_target`
    is the only place this module joins them, so the position the guard inspects and
    the position the writer writes cannot come apart on an odd name.
    """
    return _answer(allocation_target(repo, rel), "", TAKEN_REFUSAL,
                   TAKEN_REFUSAL_HINT)


def all_taken_refusal(repo: Path, rel: object, tries: int) -> tuple[str, str]:
    """The ``(headline, hint)`` pair for an allocation whose every name was spoken.

    ``rel`` is the last name the run tried and ``tries`` the bound it ran out of, so
    the sentence says how hard the run looked rather than only what it found. The
    path and the directory are filled in by :func:`_answer`, exactly as the two
    path-kind refusals do, so this wording holds no caller text of its own either --
    which is why ``{tries}`` is filled in first, from a number this module owns, and
    the finished sentence is what :func:`_answer` then renders.
    """
    return _answer(allocation_target(repo, rel), "",
                   ALL_TAKEN_REFUSAL.replace("{tries}", str(tries)),
                   ALL_TAKEN_REFUSAL_HINT)


# The walk lives in :mod:`noni._session_walk`, re-exported here through :func:`_walk`
# so every caller keeps one import for the whole guard: ``_session_git`` asks for
# ``write_refusal`` and the four writers for ``session_file_refusal``, and a test that
# pins the wording still reaches the templates by this module's name. Nothing else may
# import the walk from the other module directly -- the point of the split is one entry
# point, not two -- and each name below is one thin call that forwards every argument
# and returns the walk's answer unchanged, so no caller sees the import and each keeps
# the name the tests and the callers already use.


def walk_refusal(repo: Path, rel: str, *, creates: bool = False,
                 asks_last_as_directory: bool = False):
    """The one walk, by way of :mod:`noni._session_walk` (see there)."""
    return _walk().walk_refusal(repo, rel, creates=creates,
                                asks_last_as_directory=asks_last_as_directory)


def outside_root_refusal(repo: Path, rel: str):
    """The position question, by way of :mod:`noni._session_walk` (see there)."""
    return _walk().outside_root_refusal(repo, rel)


def write_refusal(repo: Path, rel: str):
    """The commit primitive's call, by way of :mod:`noni._session_walk` (see there)."""
    return _walk().write_refusal(repo, rel)


def session_file_refusal(repo: Path, rel: str, *, creates: bool = False,
                         directory_only: bool = False):
    """The writers' call, by way of :mod:`noni._session_walk` (see there)."""
    return _walk().session_file_refusal(repo, rel, creates=creates,
                                        directory_only=directory_only)


