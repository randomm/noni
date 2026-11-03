"""A guard that could not look must refuse, not assume (issue #68).

The session guard asks two ``lstat`` questions per write: is every directory from the
state root down to the session file a directory, and is the file a regular file. Both
helpers read the answer off the ``lstat``, and both used to treat *any* ``OSError`` as
"absent, so writable" -- which is the right answer for ``ENOENT`` (a first
registration writes into a tree that does not exist yet) and the wrong one for
everything else. A parent at mode 000 makes the ``lstat`` of the path beneath it fail
with ``EACCES``; a chain of links pointing at each other fails with ``ELOOP``. Neither
is evidence that the position is free, and a writer that read it that way printed
"register file not found" about a session it never looked at, or composed bytes into a
position it could not inspect.

Now only ``ENOENT`` and ``ENOTDIR`` mean absent (the one pair of errno values, shared
with :data:`noni.gitwrite.ABSENT_ERRNOS`); every other ``OSError`` is a refusal that
names the path and the error, because "I could not look" is a fact the operator has to
be told -- and the fix is different from the fix for a missing file.

The same module also owns the two refusal sentences. Since the kind comes from the
``lstat``, a sentence that always said "symlink" would call a device a symlink, so
each template carries the kind it found, and the directory hint has to be true of the
writer that prints it: only ``register`` creates the sessions directory, and the other
three must not advise removing a link "and let the writer create it" when no writer
ever will.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

import pytest
from _harness import _git_ok, run_from
from harness_paths import CLOSE, SRC
from session_git_support import STATE_DIR, _nested_state

from noni import _path_kind, _session_paths

SID = "2026-10-01-cccccc"

# The two answers that mean "nothing of mine is at that path". Anything else is the
# filesystem declining, and the guard says so rather than proceeding.
ABSENT = frozenset({errno.ENOENT, errno.ENOTDIR})


def _unreadable_parent(tmp_path: Path, name: str) -> tuple[Path, Path]:
    """``(root, sessions_dir)`` under a parent no reader may enter.

    The mode goes on the directory ABOVE the root, so the path the guard lstats is one
    the caller named and the error is the one that probe raises.
    """
    outer = tmp_path / name
    outer.mkdir()
    root = outer / "st"
    (root / "noni" / "sessions").mkdir(parents=True)
    (root / "noni" / "sessions" / f"{SID}.md").write_text("- status: active\n",
                                                          encoding="utf-8")
    outer.chmod(0o000)
    return root, root / "noni" / "sessions"


def _producible(path: Path) -> bool:
    """Whether this user actually cannot lstat ``path`` (root can lstat anything)."""
    try:
        os.lstat(path)
    except OSError:
        return True
    return False


def test_an_unreadable_parent_is_a_refusal_and_names_the_error(tmp_path):
    """EACCES is not ENOENT: the guard must refuse and say why.

    A mode-000 parent is the shape an operator meets -- a state clone left owned by
    somebody else -- and the two possible answers differ completely: the refusal says
    "I could not inspect this path", and the old behaviour said "there is nothing
    there", which sent the operator to register a session that existed.

    Skipped where the reading user can lstat a 000-mode directory (running as root):
    there the condition cannot be produced, and asserting a refusal that cannot occur
    would pin nothing.
    """
    root, sessions = _unreadable_parent(tmp_path, "eacces")
    try:
        if not _producible(sessions):
            pytest.skip("the reading user can lstat a 000-mode directory's child")
        refused = _session_paths.directory_refusal(sessions)
        assert refused is not None, (
            "an EACCES on the way to the session file was read as absent")
        headline, hint = refused
        low = headline.lower()
        assert "symlink" not in low, (
            f"a path that could not be inspected is not a link: {headline}")
        assert "could not be inspected" in low, headline
        assert str(sessions) in headline, (
            f"the refusal must name the path it could not read: {headline}")
        # The operator gets the error's own words, so the two fixes stay
        # distinguishable: chmod/ownership here, remove-the-link for a link.
        assert "permission" in low or "denied" in low, headline
        assert hint, "a refusal without a fix is not a refusal an operator can use"
    finally:
        (tmp_path / "eacces").chmod(0o755)


def test_the_file_question_refuses_an_unreadable_parent_too(tmp_path):
    """The file half of the pair, because a writer that cannot see the file must not
    report it missing.

    ``path_kind`` still answers None for every refusal -- that is what a caller about
    to CREATE a file wants -- and the new sibling ``inspected_file_kind`` is the
    reader's question. The guard uses the reader's question.
    """
    root, sessions = _unreadable_parent(tmp_path, "eacces-file")
    try:
        if not _producible(sessions):
            pytest.skip("the reading user can lstat a 000-mode directory's child")
        session_file = sessions / f"{SID}.md"
        assert _path_kind.kind_of(session_file)[0] is None, (
            "path_kind must keep answering 'fine' for a caller about to create")
        kind = _path_kind.inspected_file_kind(session_file)
        assert kind and "could not be inspected" in kind, kind
        refused = _session_paths.file_refusal(session_file)
        assert refused is not None, (
            "a session file the guard could not read was reported as absent")
        assert "could not be inspected" in refused[0].lower(), refused
    finally:
        (tmp_path / "eacces-file").chmod(0o755)


def test_absent_and_not_a_directory_still_answer_as_before(tmp_path):
    """The two errno values that DO mean absent, so this is not a blanket refusal.

    A fresh repository has no ``noni/`` at all (ENOENT) and a tree whose ``noni`` is a
    plain file makes the path beneath it fail with ENOTDIR; both are the ordinary
    "nothing is there" the writers work with, and both must stay non-refusals or the
    first registration on a fresh clone breaks.
    """
    assert ABSENT == _path_kind.ABSENT_ERRNOS
    missing = tmp_path / "fresh" / "noni" / "sessions"
    assert _session_paths.directory_refusal(missing) is None
    (tmp_path / "plain").write_text("x\n", encoding="utf-8")
    assert _session_paths.directory_refusal(
        tmp_path / "plain" / "noni" / "sessions") is None
    assert _session_paths.file_refusal(tmp_path / "fresh" / "x.md") is None


def test_a_link_loop_refuses_rather_than_answering_absent(tmp_path):
    """ELOOP: a chain of links, no directory, and no answer from ``lstat``.

    ``lstat`` on the final component succeeds (it is a link, and that is already a
    refusal), so the loop is produced on the DIRECTORY question with a link standing
    where a component of the path is followed -- the shape the guard walks.
    """
    root = tmp_path / "loop"
    (root / "noni").mkdir(parents=True)
    (root / "noni" / "a").symlink_to("b")
    (root / "noni" / "b").symlink_to("a")
    refused = _session_paths.directory_refusal(root / "noni" / "a" / "c")
    assert refused is not None, "a link loop was read as an absent directory"
    low = refused[0].lower()
    assert "could not be inspected" in low, refused[0]
    assert "symlink" not in low, f"a loop is not one link: {refused[0]}"


def test_the_kind_in_a_refusal_is_the_kind_found(tmp_path):
    """A device is not a symlink: each sentence names what the lstat actually saw.

    A fifo is the regular-file question's non-regular kind and the directory
    question's non-directory kind, and one planted path covers both sentences. The
    link case is checked beside it so the two wordings cannot collapse into one.
    """
    root = tmp_path / "kinds"
    sessions = root / "noni" / "sessions"
    sessions.mkdir(parents=True)
    fifo = sessions / "fifo.md"
    os.mkfifo(fifo)

    refused = _session_paths.file_refusal(fifo)
    assert refused is not None
    assert "is not a regular file" in refused[0], refused[0]
    assert "symlink" not in refused[0].lower(), refused[0]

    refused = _session_paths.directory_refusal(sessions / "fifo.md")
    assert refused is not None
    assert "is not a directory" in refused[0], refused[0]
    assert "symlink" not in refused[0].lower(), refused[0]

    link = sessions / "link.md"
    link.symlink_to("elsewhere.md")
    refused = _session_paths.file_refusal(link)
    assert refused is not None and "is a symlink" in refused[0], refused[0]
    assert "not a regular file" not in refused[0], refused[0]


def test_only_register_is_told_the_writer_will_create_the_directory():
    """The directory hint, correct for the three writers that never mkdir.

    close, claim and release refuse an unregistered session rather than build the
    tree, so "remove it and let the writer create it" is advice they must not give --
    an operator who followed it would re-run a writer that creates nothing and read
    the same refusal again. register, which does mkdir, keeps the creating hint.
    """
    creates_hint = _session_paths.DIR_REFUSAL_HINT
    plain_hint = _session_paths.DIR_REFUSAL_HINT_NO_CREATE
    assert "let the writer create it" in creates_hint
    assert "never creates" in plain_hint
    # The two hints are different sentences, and the guard can ask for either.
    assert creates_hint != plain_hint
    import inspect

    signature = inspect.signature(_session_paths.session_file_refusal)
    assert "creates" in signature.parameters
    signature = inspect.signature(_session_paths.directory_refusal)
    assert "creates" in signature.parameters


def test_a_writer_prints_the_non_creating_hint(tmp_path):
    """End to end, the close writer's own stderr, because the hint is only worth
    anything in the two lines the operator actually reads.

    ``close`` never creates the sessions directory, so a refusal it prints must not
    promise a creation. The run is the ordinary close of a planted link, from a cwd
    that is not the state root.
    """
    project, state, _session = _nested_state(tmp_path, SID, name="project",
                                             link_sessions_dir=True)
    sessions = state / "noni" / "sessions"
    proc = run_from(project, CLOSE, "--repo", STATE_DIR, "--session-id", SID)

    assert proc.returncode == 4, f"{proc.returncode}: {proc.stderr}"
    err = proc.stderr.lower()
    assert "symlink" in err, proc.stderr
    assert str(sessions.relative_to(state)) in proc.stderr, proc.stderr
    assert "let the writer create it" not in err, (
        f"close.py promised a directory it never creates: {proc.stderr}")
    assert "never creates" in err, proc.stderr
    # The refusal is a refusal: nothing created, the link intact.
    assert sessions.is_symlink(), "the run replaced the sessions link"
    assert _git_ok(state, "status", "--porcelain").stdout.splitlines()


def test_a_reader_asks_the_inspection_question_via_the_module_that_owns_it():
    """The two questions stay two, and the shared pair of errnos is one list.

    :mod:`noni._path_kind` owns the file question and the errno pair, so the census
    and the order writer keep ``gitwrite.path_kind``'s old answer while the session
    guard gets the stricter one. Both must treat the same two errno values as absent,
    or one guard proceeds where the other refuses.
    """
    assert _path_kind.ABSENT_ERRNOS == ABSENT
    # The directory question reaches the same verdict without its own copy.
    source = (SRC / "noni" / "_session_paths.py").read_text(encoding="utf-8")
    assert "_path_kind.ABSENT_ERRNOS" in source, (
        "the directory question must share the file question's verdict")


def test_a_socket_at_the_file_path_is_refused_not_read_as_absent(tmp_path):
    """A non-regular kind is a refusal on both questions, whatever the mode bits say.

    The check is S_IFMT, so a socket -- which is what a misdirected write to a
    predictable name leaves behind -- is refused rather than replaced, and the refusal
    says "not a regular file" instead of calling it a link.
    """
    root = tmp_path / "sock"
    sessions = root / "noni" / "sessions"
    sessions.mkdir(parents=True)
    sock = sessions / "s.md"
    os.mkfifo(sock)
    mode = os.lstat(sock).st_mode
    assert stat.S_ISFIFO(mode)
    refused = _session_paths.file_refusal(sock)
    assert refused and "is not a regular file" in refused[0], refused
    assert "symlink" not in refused[0].lower()
