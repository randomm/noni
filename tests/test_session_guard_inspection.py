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
with :data:`noni._path_kind.ABSENT_ERRNOS`); every other ``OSError`` is a refusal that
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

from noni import _path_kind, _session_guard, _session_paths

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


def test_a_declined_lstat_that_is_not_an_errno_is_a_refusal(tmp_path, monkeypatch):
    """A refused ``lstat`` is a refusal, and only ``ENOENT``/``ENOTDIR`` are absence.

    Every test above reaches the declination through the filesystem (a mode-000
    parent, a link loop). This one reaches it through the syscall itself, because the
    real bug the adversarial review found was invisible to all of them: mutating
    ``ABSENT_ERRNOS`` membership to answer "absent" for every errno passed the whole
    suite. With ``os.lstat`` raising ``EIO`` -- a disk fault, a failing network mount,
    a parent that cannot be read for a reason no test plants -- there is no fact of the
    matter about what sits at the path, and a guard that says "nothing is there" is a
    guard that hands a writer permission to create over something it never saw.

    The assertion is the refusal and its words: the path is refused on both questions,
    named, and said in the "could not be inspected" form rather than the absent one.
    """
    root = tmp_path / "eio"
    sessions = root / "noni" / "sessions"
    sessions.mkdir(parents=True)
    session_file = sessions / f"{SID}.md"
    session_file.write_text("- status: active\n", encoding="utf-8")

    def refusing_lstat(path, *args, **kwargs):
        raise OSError(errno.EIO, "Input/output error", str(path))

    monkeypatch.setattr(_path_kind.os, "lstat", refusing_lstat)

    refused = _session_paths.file_refusal(session_file)
    assert refused is not None, "a declined lstat was read as an absent session file"
    assert "could not be inspected" in refused[0].lower(), refused[0]
    assert str(session_file) in refused[0], refused[0]
    assert "symlink" not in refused[0].lower(), refused[0]

    refused = _session_paths.directory_refusal(sessions)
    assert refused is not None, "a declined lstat was read as an absent directory"
    assert "could not be inspected" in refused[0].lower(), refused[0]
    assert str(sessions) in refused[0], refused[0]

    # The walk, not just the two questions: this is the call the writers make.
    refused = _session_paths.session_file_refusal(root, "noni/sessions/" + f"{SID}.md")
    assert refused is not None, "the walk read a declined lstat as an ordinary tree"

    # A refusal, so nothing was written and the session's bytes are untouched.
    assert session_file.read_text(encoding="utf-8") == "- status: active\n"


def test_a_value_error_from_lstat_is_the_same_refusal(tmp_path, monkeypatch):
    """``ValueError`` is the NUL case, and it folds into the same words.

    ``os.lstat`` raises ``ValueError`` rather than ``OSError`` for a path carrying an
    embedded NUL, so a guard that catches only ``OSError`` turns the one shape it
    cannot inspect into a traceback over the sentence the operator was meant to read.
    The session guard refuses such a name by name before the walk (see
    ``test_a_name_carrying_a_control_character_is_refused_by_name``), so this pins the
    last line of defence behind that guard: the same "could not be inspected" refusal
    the filesystem's own declinations get, from both questions.
    """
    root = tmp_path / "value-error"
    sessions = root / "noni" / "sessions"
    sessions.mkdir(parents=True)
    target = sessions / "s.md"

    def refusing_lstat(path, *args, **kwargs):
        raise ValueError("lstat: embedded null character in path")

    monkeypatch.setattr(_path_kind.os, "lstat", refusing_lstat)

    for refused, label in ((_session_paths.file_refusal(target), "file"),
                           (_session_paths.directory_refusal(sessions), "directory")):
        assert refused is not None, f"a ValueError was read as absence: {label}"
        assert "could not be inspected" in refused[0].lower(), refused[0]
        assert "symlink" not in refused[0].lower(), refused[0]


def test_a_name_carrying_a_control_character_is_refused_by_name(tmp_path):
    """The entry point's normalisation, which is the only thing that says "no name".

    ``lstat`` on a name of whitespace answers ENOENT, which the guard reads as absent,
    so before the normalisation a name of spaces -- or one carrying a control
    character -- walked the whole chain, found nothing at every component, and was
    admitted as the ordinary file a writer may replace. The renderer then dropped the
    control bytes from the sentence about it, so even the refusal printed a name that
    was not the name refused.

    Each shape below therefore comes back as a refusal tuple and not ``None``, and
    never raises: the guard's promise to its callers is a pair of strings or nothing,
    whatever a caller hands it. The name the refusal quotes is the name as the caller
    spelled it, with its control byte named rather than silently dropped.
    """
    root = tmp_path / "normalised"
    (root / "noni" / "sessions").mkdir(parents=True)
    good = "noni/sessions/2026-10-01-cccccc.md"
    assert _session_paths.write_refusal(root, good) is None, "the good name must pass"

    refused_names = (b"", " ", "   ", chr(9), " \n ", chr(2), "a" + chr(2) + "b.md",
                     "noni/sessions/a" + chr(27) + "[31mred.md",
                     "noni/sessions/a" + chr(0) + "b.md",
                     "noni/sessions/a" + chr(0x202e) + "b.md")
    for rel in refused_names:
        refused = _session_paths.write_refusal(root, rel)
        assert refused is not None, f"{rel!r} was admitted as a session file"
        headline, hint = refused
        assert isinstance(headline, str) and isinstance(hint, str), rel
        assert headline and hint, f"{rel!r}: a refusal needs both lines"
        low = headline.lower()
        assert "not a session file inside the state root" in low, f"{rel!r}: {headline}"
        assert "symlink" not in low, f"{rel!r} blamed a link: {headline}"

    # Bytes are a path, not the four characters of its repr: fsdecode is what makes
    # the name the guard inspects the name the caller named.
    refused = _session_paths.write_refusal(root, b"noni/sessions/../outside.md")
    assert refused is not None, "a bytes name that walks out was admitted"
    assert "not a session file inside the state root" in refused[0].lower(), refused[0]
    # The repr of a bytes object carries a leading b and quotes; a refusal that
    # rendered those had stringified instead of decoding.
    assert "b'" not in refused[0], f"the refusal quoted a bytes repr: {refused[0]}"

    # A bytes name that IS a session file inside the root is not a refusal, which is
    # the half that keeps the decoding from becoming a blanket rejection.
    assert _session_paths.write_refusal(root, good.encode()) is None


def test_no_input_shape_raises_out_of_the_guard(tmp_path):
    """Whatever a caller hands the guard, it answers: a tuple or None, never an excuse.

    The writers call this before they have written anything and print the answer
    straight to stderr, so a raise is a traceback where an operator should have read a
    fix. The shapes here are the ones a caller can actually produce -- bytes, a Path, a
    number, None, a name no codec carries -- driven through every entry point that
    takes a name, the allocating route's two questions included.
    """
    root = tmp_path / "never-raises"
    (root / "noni" / "sessions").mkdir(parents=True)
    for rel in (b"", b"\xff\xfe", "", " ", chr(0), "a" + chr(1) + "b", ".", "..",
                "/", "~", "noni/sessions/x.md", chr(0xd800), 12, None,
                Path("noni/sessions/x.md"), ["not", "a", "name"]):
        for call in (_session_paths.write_refusal, _session_paths.session_file_refusal,
                     _session_guard.taken_refusal):
            refused = call(root, rel)
            assert refused is None or (isinstance(refused, tuple)
                                        and len(refused) == 2
                                        and all(isinstance(x, str) and x
                                                for x in refused)), (
                f"{call.__name__}({rel!r}) answered {refused!r}")
