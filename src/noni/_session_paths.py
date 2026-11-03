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
resolves an ancestor of the root. That boundary is now structural rather than a
loop condition: :func:`walk_refusal` walks the ``relative_to`` parts of the name it
was given, so there is no walk upward at all and no ancestor can be examined
however the root was spelled. The name is refused before it is walked, and the two
refusals are separate sentences with separate fixes: a name that is empty, ``.``,
absolute, or one that walks out of the root with a ``..`` is not a file inside the
root in the first place, so :data:`OUTSIDE_REFUSAL` answers it and never reaches the
``lstat`` questions that produced the "through a link" wording for decades of shapes
it was never about.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from . import _path_kind

# A one-way import pair: ``_session_git`` imports this module for the refusal in
# :func:`stage_and_commit`, so nothing here may import it at module scope -- hence
# the local import inside :func:`_answer`. ``gitwrite`` is the far safer neighbour:
# it imports only gitenv and targetschema.

# The word every refusal here carries, and the word the tests assert is present:
# one spelling shared with the state-root refusal, so either message tells the
# operator the same thing about the path.
SYMLINK_WORD = "symlink"

# The one wording pair for a name that is not a file inside the state root at all:
# empty, ``.``, absolute, or a ``..`` that walks out. The walk below has no answer
# for such a name -- there is no chain of directories under the root to inspect --
# so it is refused by name, before anything is lstat'ed, in words that describe a
# NAME rather than a path kind.
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
    of the same question.
    """
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        if exc.errno in _path_kind.ABSENT_ERRNOS:
            return None
        return f"could not be inspected ({exc.strerror or exc.__class__.__name__})"
    if stat.S_ISLNK(mode):
        return f"is a {SYMLINK_WORD}"
    return None if stat.S_ISDIR(mode) else "is not a directory"


def _answer(path: Path, kind: str, headline: str, hint: str) -> tuple[str, str]:
    """One refusal pair, with the caller's path and the lstat verdict filled in.

    Both fields carry a path the command line or a marker supplied, and this pair
    goes straight to stderr, so the path is sanitised on its way in and once for
    both sentences -- the same rule the writers' name refusals follow.
    """
    text = _sanitize(str(path))
    return (_sanitize(headline.format(path=text, kind=kind)),
            _sanitize(hint.format(path=text, directory=_sessions_rel())))


def _sanitize(text: str) -> str:
    """One printed line's worth of text, control bytes dropped and tail bounded.

    :mod:`noni._session_git` imports *this* module for its commit guard, so the
    renderer is imported where it is used rather than at module scope: a module-scope
    import of that module back would be taken while one of the two is still running
    its own import. :mod:`noni._safe_text` sits below both and could be imported at
    the top, but one call site keeps the pair honest about which renderer a refusal
    uses: :func:`noni._safe_text.safe_path`, which escapes newline and carriage
    return so no path can add lines to the two-line refusal.
    """
    from ._safe_text import safe_path
    return safe_path(text)


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


def walk_refusal(repo: Path, rel: str, *, creates: bool = False,
                 asks_last_as_directory: bool = False) -> tuple[str, str] | None:
    """The refusal for the session file ``rel`` and the tree above it, or None.

    The ONE walk, and the only loop in this module. It takes the state root as
    given, asks the directory question of every directory STRICTLY below that root
    and down to the target (``noni/sessions``, the ``noni`` above it, anything
    deeper), and then the file question of the file itself -- never an ancestor of
    the root, because :func:`noni._session_git.linked_state_root` owns that
    question and a project reached *through* a link must stay a normal run.

    The bound is structural rather than a loop condition: the name is normalised on
    both sides with ``os.path.normpath``, made relative to the root, and the walk
    iterates over the parts of that answer. There is no ``while`` and no parent step,
    so no shape of ``rel`` -- ``.``, ``..``, an absolute path, a deep one, a root
    spelled with a trailing slash -- can make it run past the root or past the file.

    A name that is not a file under the root is refused BEFORE the walk, by name and
    not by ``lstat``: :data:`OUTSIDE_REFUSAL` in words that describe a name, because
    a ``..`` is neither a symlink nor a non-directory and the link wording would
    blame the wrong thing.

    ``creates`` goes to :func:`directory_refusal` (see there): True only for
    ``register``, which mkdirs the sessions directory.

    ``asks_last_as_directory`` is the one knob, and it exists for one caller:
    ``register`` asks the question of the sessions DIRECTORY it is about to create,
    so its last component is a directory question and not a file question. A
    directory name handed to the file question would be refused as "not a regular
    file", which is both the wrong verdict and the wrong advice.
    """
    refused = outside_root_refusal(repo, rel)
    if refused is not None:
        return refused
    normalised = os.path.normpath(str(repo))
    parts = Path(os.path.normpath(os.path.join(
        normalised, *Path(os.path.normpath(str(rel))).parts))).relative_to(
        normalised).parts
    path = Path(normalised)
    steps = parts if asks_last_as_directory else parts[:-1]
    for part in steps:
        path = path / part
        refused = directory_refusal(path, creates=creates)
        if refused is not None:
            return refused
    if asks_last_as_directory:
        return None
    return file_refusal(path / parts[-1] if parts else path)


def outside_root_refusal(repo: Path, rel: str) -> tuple[str, str] | None:
    """The refusal for a ``rel`` that names no file inside ``repo``, or None.

    The question the walk cannot answer, asked first: an empty name, ``.``, an
    absolute path, a home reference, or one that lands outside the state root has no
    chain of directories under the root to inspect, so the walk would have nothing
    honest to say about it. Both sides are normalised and compared by PARTS: the
    name's own components are taken BEFORE normalisation, so any ``..`` is refused
    rather than folded away. A name may answer "a file under the root" after
    normalisation and still make the walk lstat a directory the operator never named
    (``noni/sessions/../../outside.md`` reads as ``outside.md``, two levels up, once
    the ``..`` is resolved), and the walk then reports "no problem" about a path
    outside the tree. Refusing the component, not the resolved answer, is what keeps
    the position the guard inspected and the position the writer writes the same
    position. ``.`` components are not refused: they name no move, and the walk's
    path is built by JOINING the parts of the normalised answer, so the check and
    the walk cannot read one component two different ways.
    """
    normalised = os.path.normpath(str(repo))
    parts = Path(str(rel)).parts
    if not rel or rel == "." or os.path.isabs(rel) or not parts \
            or ".." in parts or parts[0].startswith("~"):
        return _answer(Path(rel), "", OUTSIDE_REFUSAL, OUTSIDE_REFUSAL_HINT)
    joined = os.path.normpath(os.path.join(normalised, *parts))
    try:
        Path(joined).relative_to(normalised)
    except ValueError:
        return _answer(Path(rel), "", OUTSIDE_REFUSAL, OUTSIDE_REFUSAL_HINT)
    return None


def write_refusal(repo: Path, rel: str) -> tuple[str, str] | None:
    """The one call the commit primitive makes; see :func:`walk_refusal`.

    The primitive never creates a directory, so the hint it gets for a refused
    directory is the one that does not promise a ``mkdir``.
    """
    return walk_refusal(repo, rel)


def session_file_refusal(repo: Path, rel: str, *, creates: bool = False,
                         directory_only: bool = False) -> tuple[str, str] | None:
    """The one call the writers make: the same walk, in the writer's own terms.

    The writers derive ``rel`` themselves (:func:`noni._session_git.writer_name`,
    or ``register``'s ``noni/sessions/<sid>.md``), so a name that is not one inside
    the root has already been refused by the writer's own name guard. Asking again
    here costs one normalisation and keeps the walk in one place: a writer whose
    guard was skipped cannot drive a link, or a name outside the root, through the
    same helper the primitive uses.

    ``directory_only`` says the name is a DIRECTORY the writer is about to create
    (``register``, before its ``mkdir``): every component down to and including the
    last is then asked as a directory, and the file question is not asked at all.
    """
    return walk_refusal(repo, rel, creates=creates,
                        asks_last_as_directory=directory_only)
