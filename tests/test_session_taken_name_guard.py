"""The allocating route's own question: is this minted name already spoken (issue #103).

``register`` is the only session writer that mints its own path, so it is the only one
that can land a fresh allocation on a name somebody else holds. ``file_refusal`` cannot
answer that question -- it answers None for BOTH an absent path and a regular file,
because those are the two states a writer writes -- and for an allocated name the
regular file already there is exactly the victim ``os.replace`` would take. So
:func:`noni._session_paths.name_taken` asks a different question of the same
``lstat``: does anything sit here.

The two guards must stay two. A single existence check would answer "already exists"
about a directory, a fifo or a dangling link, and send the operator off to delete a
file that is a link; the ``_session_guard`` family's walk answers those shapes with the
kind it actually found (pinned in ``test_session_guard_inspection.py`` and
``test_register_taken_name_refusal.py``), and this file pins the taken-name half.

Two invariants this question carries that the file question does not, and both are
pinned here:

Fail closed. A declined ``lstat`` is not evidence that the name is free -- a writer
that read it that way would ``os.replace`` over a file it never saw.
Never leave the root. The position this guard inspects is the position the writer
writes, so an absolute name or one that walks out with ``..`` is rebased under the
root rather than reported as somebody's allocated file.

Like its sibling file, every test here drives the guard directly: a raise is a
traceback where an operator should have read a fix, so the shapes a caller can produce
are driven through the entry points and must answer a tuple or ``None``.
"""

from __future__ import annotations

import errno
import os

from noni import _session_guard, _session_paths

SID = "2026-10-01-cccccc"


def test_an_allocated_name_is_taken_by_anything_lstat_finds(tmp_path):
    """The allocating route's own question, and it is not the file question.

    ``file_refusal`` answers None for a regular file, because a regular file is one of
    the two states a writer writes. For an ALLOCATED name that answer is the bug
    issue #103 fixed: the regular file already there is another session's register,
    and ``os.replace`` would take it. So ``name_taken`` asks lstat's question -- does
    anything sit here -- and the two verdicts must differ on exactly this shape.

    The four kinds are planted in one tree so the pair is compared on each path:
    absent is the only free answer, and a link (dangling included), a directory and
    a fifo all count as taken.
    """
    root = tmp_path / "taken"
    sessions = root / "noni" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "regular.md").write_text("- status: active\n", encoding="utf-8")
    (sessions / "dir.md").mkdir()
    os.mkfifo(sessions / "fifo.md")
    (sessions / "dangling.md").symlink_to("nowhere-at-all")

    # Absent is free, and the file question agrees.
    assert _session_paths.name_taken(sessions / "absent.md") is False
    assert _session_paths.file_refusal(sessions / "absent.md") is None
    for name in ("regular.md", "dir.md", "fifo.md", "dangling.md"):
        assert _session_paths.name_taken(sessions / name) is True, name
    # The pair that pins the difference: a committed register file passes the path
    # guard and fails this one, which is why the writer asks both.
    assert _session_paths.file_refusal(sessions / "regular.md") is None
    assert _session_paths.name_taken(sessions / "regular.md") is True


def test_an_allocated_name_whose_lstat_was_declined_is_taken(tmp_path, monkeypatch):
    """Fail closed: "I could not look" is not evidence that the name is free.

    Both exception types the syscall can raise are the same verdict, matching what
    :func:`noni._path_kind.inspected_file_kind` does for the file question -- a
    writer that read a declined ``lstat`` as absence would ``os.replace`` over a file
    it never saw, which is the fault this question exists to stop.
    """
    root = tmp_path / "declined"
    sessions = root / "noni" / "sessions"
    sessions.mkdir(parents=True)
    target = sessions / "s.md"

    for raise_with in (OSError(errno.EACCES, "Permission denied"),
                       ValueError("lstat: embedded null character in path")):
        def refusing_lstat(path, *args, _exc=raise_with, **kwargs):
            raise _exc

        monkeypatch.setattr(os, "lstat", refusing_lstat)
        assert _session_paths.name_taken(target) is True, raise_with

    monkeypatch.undo()
    refused = _session_guard.taken_refusal(root, "noni/sessions/s.md")
    assert refused is None, "an absent name was reported as taken"
    (sessions / "s.md").write_text("- status: active\n", encoding="utf-8")
    taken = _session_guard.taken_refusal(root, "noni/sessions/s.md")
    assert taken is not None, "a held name answered no refusal"
    assert "s.md" in taken[0] and "already exists" in taken[0].lower(), taken
    assert "noni/sessions" in taken[1], taken


def test_the_taken_name_question_never_leaves_the_state_root(tmp_path):
    """The position this guard inspects is the position ``register`` writes: under the root.

    ``os.replace`` lands where the writer joined the name to the root, so a taken-name
    verdict about a path OUTSIDE it is worse than no verdict: the operator is told a
    file they never allocated already exists, and sent to delete a file no writer here
    touches. An absolute name, or one that walks out with ``..``, is therefore rebased
    under the root before it is ``lstat``'ed -- the same position the walk refuses by
    name, which the caller has already been refused for before this question is asked.
    """
    root = tmp_path / "rebase"
    sessions = root / "noni" / "sessions"
    sessions.mkdir(parents=True)
    outside = tmp_path / "not-mine.md"
    outside.write_text("- status: active\n", encoding="utf-8")

    for rel in (str(outside), "../not-mine.md", "noni/sessions/../../../not-mine.md",
                str(outside).encode()):
        assert _session_guard.taken_refusal(root, rel) is None, (
            f"{rel!r}: a path outside the state root is not this run's allocated name")
        assert outside.is_file(), f"{rel!r}: the guard's verdict named a file it owns"

    # Inside the root the same call still finds the holder, bytes included.
    held = sessions / "held.md"
    held.write_text("- status: active\n", encoding="utf-8")
    for rel in ("noni/sessions/held.md", b"noni/sessions/held.md",
                "noni/../noni/sessions/held.md"):
        refused = _session_guard.taken_refusal(root, rel)
        assert refused is not None, f"{rel!r}: a held name inside the root read as free"
        assert "held.md" in refused[0], refused


def test_allocate_with_a_negative_retry_bound_asks_once(tmp_path):
    """A negative retry bound asks the question once and writes; it never crashes.

    ``range(retries + 1)`` with ``retries`` below zero runs no loop body at all, so the
    code that reports "every name was spoken" would report it about a name the run
    never minted -- an ``UnboundLocalError`` where a refusal belongs. The bound is
    floored at zero: the run mints once, asks once, and writes when the name is free.
    """
    root = tmp_path / "negative-bound"
    (root / "noni" / "sessions").mkdir(parents=True)
    printed = []

    def printer(code, headline, hint):
        printed.append((code, headline, hint))
        return code

    for retries in (-1, -100):
        minted = []

        def name(_minted=minted):
            # Bound as a default so the closure holds THIS round's list, not the
            # variable the loop rebinds (ruff B023).
            _minted.append(SID)
            return SID

        allocated = _session_guard.allocate(printer, 2, name,
                                            lambda sid: f"noni/sessions/{sid}.md",
                                            root, retries)
        assert allocated == (SID, f"noni/sessions/{SID}.md"), (
            f"retries={retries}: {allocated!r}")
        assert len(minted) == 1, f"retries={retries}: minted {len(minted)} names"
    assert printed == [], f"a free name was reported as taken: {printed}"
