"""The ONE walk a session write must pass, and the name questions that precede it.

Split from :mod:`noni._session_paths` along the seam its own docstring names: that
module answers the two ``lstat`` questions (is this a directory I may write into, is
this a file I may replace) and owns the wording of every refusal; THIS module walks a
name down from the state root asking them, and refuses by name the shapes no ``lstat``
question is about. One loop exists in the pair, and it is here.

Three entry points, all re-exported from :mod:`noni._session_paths` so callers keep
one import:

:func:`_normalise_name`
    The one decoding and the one "that is not a name" verdict: bytes decoded by
    :func:`os.fsdecode`, a name that is blank after ``strip()`` or carries a control
    character refused as a name rather than walked.
:func:`outside_root_refusal`
    The position question the walk cannot answer: an empty name, ``.``, an absolute
    path, a home reference, or one that walks out of the root with ``..``.
:func:`walk_refusal`
    The walk itself, plus the two thin wrappers the callers actually use --
    :func:`write_refusal` (the commit primitive) and :func:`session_file_refusal`
    (the four writers).

The boundary the walk never crosses is the state root:
:func:`noni._session_git.linked_state_root` owns that question and a project reached
*through* a link must stay a normal run. The bound is structural rather than a loop
condition -- the name is normalised, made relative to the root, and iterated by PARTS
-- so no shape of ``rel`` (``.``, ``..``, an absolute path, a deep one, a root spelled
with a trailing slash) can make it run past the root or past the file.
"""

from __future__ import annotations

import os
from pathlib import Path

from ._safe_text import is_control_char
from ._session_paths import (
    OUTSIDE_REFUSAL,
    OUTSIDE_REFUSAL_HINT,
    _answer,
    directory_refusal,
    file_refusal,
)


def _outside_refusal(name: object) -> tuple[str, str]:
    """The refusal pair for a name that is no file inside the root, from the one pair.

    The name goes in as the caller spelled it and comes out rendered exactly once,
    by :func:`noni._session_paths._answer`. Every name refusal the walk makes goes
    through here.
    """
    return _answer(Path(str(name)), "", OUTSIDE_REFUSAL, OUTSIDE_REFUSAL_HINT)


def _refused_text(rel: object) -> str:
    """``rel`` as text, with bytes decoded once at the entry point.

    :func:`os.fsdecode` rather than ``str``: a bytes name is a perfectly good path
    on every POSIX system, and ``str(b"x")`` reads it as the four characters
    ``b'x'``, so the guard would have inspected a path nobody named and pronounced
    the real one free.
    """
    return os.fsdecode(rel) if isinstance(rel, bytes) else str(rel)


def _normalise_name(rel: object) -> tuple[str, tuple[str, str] | None]:
    """The entry point's one normalisation: ``(text, refusal)``, and never a raise.

    The public entry points call this once, at :func:`walk_refusal`, before any
    ``lstat``, so the normalisation sits at the single point every walk passes
    through and a name cannot be judged one way by the name question and another
    way by the walk. Text arrives via :func:`_refused_text`, so the two questions
    cannot read one name in two decodings.

    A name that is empty after ``strip()``, or that carries any control character
    (:func:`noni._safe_text.is_control_char`), is refused rather than walked. The
    renderer drops control bytes from the sentence it prints and ``str.strip()``
    leaves them in, so ``"\x01"`` used to reach the walk, answer "absent" at every
    component and be admitted as the ordinary file a writer may replace; a name of
    spaces used to reach it as one odd filename. Neither is a session file, and a
    name no argv element can carry is no session file either.

    The refusal is the ``OUTSIDE_REFUSAL`` pair: neither shape is a link or a
    non-directory, so neither gets a path-kind sentence and neither is lstat'ed.
    The answer is always a ``(headline, hint)`` tuple -- never ``None``, never a
    raise -- whatever the caller passed in.
    """
    text = _refused_text(rel)
    if not text.strip():
        # The one sentence for "no name at all", which covers the empty string, the
        # root spelled ``.``, a run of whitespace and anything that becomes one.
        return text, _outside_refusal(rel)
    if any(is_control_char(ch) for ch in text):
        # This sentence enumerates what it refuses, so the name it quotes must name
        # the category-C character rather than print nothing where it stood.
        return text, _outside_refusal(f"{text!r}")
    return text, None


def walk_refusal(repo: Path, rel: str, *, creates: bool = False,
                 asks_last_as_directory: bool = False) -> tuple[str, str] | None:
    """The refusal for the session file ``rel`` and the tree above it, or None.

    The ONE walk, and the only loop in the guard pair. It takes the state root as
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
    not by ``lstat``: :data:`noni._session_paths.OUTSIDE_REFUSAL` in words that
    describe a NAME, because a ``..`` is neither a symlink nor a non-directory and
    the link wording would blame the wrong thing.

    ``creates`` goes to :func:`noni._session_paths.directory_refusal` (see there):
    True only for ``register``, which mkdirs the sessions directory.

    ``asks_last_as_directory`` is the one knob, and it exists for one caller:
    ``register`` asks the question of the sessions DIRECTORY it is about to create,
    so its last component is a directory question and not a file question. A
    directory name handed to the file question would be refused as "not a regular
    file", which is both the wrong verdict and the wrong advice.

    The name is normalised first, at this one entry point
    (:func:`_normalise_name`): bytes decoded, a name that is blank or carries a
    control character refused as a name, so neither question below is ever asked of
    a string no argv element could carry. A refusal renders its path once, in
    :func:`noni._session_paths._answer`, and the templates are composed with plain
    :func:`noni._safe_text.safe_path` rather than a second pass over the finished
    line: see the backslash case in ``tests/test_session_symlink_docs.py``.
    """
    text, refused = _normalise_name(rel)
    if refused is not None:
        return refused
    refused = outside_root_refusal(repo, text)
    if refused is not None:
        return refused
    normalised = os.path.normpath(str(repo))
    parts = Path(os.path.normpath(os.path.join(
        normalised, *Path(os.path.normpath(str(text))).parts))).relative_to(
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
    rather than folded away, and they are taken from the text :func:`_refused_text`
    produced -- the one decoding the walk inspects, so the two questions cannot
    disagree about what the name was. A name may answer "a file under the root" after
    normalisation and still make the walk lstat a directory the operator never named
    (``noni/sessions/../../outside.md`` reads as ``outside.md``, two levels up, once
    the ``..`` is resolved), and the walk then reports "no problem" about a path
    outside the tree. Refusing the component, not the resolved answer, is what keeps
    the position the guard inspected and the position the writer writes the same
    position. ``.`` components are not refused: they name no move, and the walk's
    path is built by JOINING the parts of the normalised answer, so the check and
    the walk cannot read one component two different ways.

    The name has already been normalised by :func:`_normalise_name`, which owns the
    bytes, whitespace-only and control-character cases; this is the position question.
    """
    normalised = os.path.normpath(str(repo))
    parts = Path(_refused_text(rel)).parts
    if not rel or _refused_text(rel) == "." or os.path.isabs(rel) or not parts \
            or ".." in parts or parts[0].startswith("~"):
        return _outside_refusal(rel)
    joined = os.path.normpath(os.path.join(normalised, *parts))
    try:
        Path(joined).relative_to(normalised)
    except ValueError:
        return _outside_refusal(rel)
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
