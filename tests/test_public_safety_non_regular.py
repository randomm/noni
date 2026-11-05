"""Every non-regular kind the hygiene scan refuses at the open, and how it refuses.

Issue #91. The scan of a tree holding a named pipe blocked in ``open`` forever:
no row, no traceback, no exit, because a blocked read raises nothing and the
module's only timeout sits on the ``git ls-files`` call the scan had already
returned from. The guard is the open itself -- ``os.open(O_RDONLY | O_NONBLOCK)``
then ``stat.S_ISREG(os.fstat(fd))`` on that descriptor -- so this file asserts
both halves of it:

- **The kinds.** A fifo, a unix socket, a directory, a dangling link, a link to a
  pipe and an unreadable path are each refused with nothing read. A character
  device is deliberately *not* among them: opening one returns EOF immediately
  with or without the guard, so a device test would pass green and prove nothing
  about the class. The behavioural cases therefore run in child processes under a
  ``timeout=`` (the shape ``tests/test_session_walk_bounded.py`` uses), since an
  in-process hang takes the pytest worker with it.
- **The structure.** The flag ordering no fixture can plant: a regular file
  swapped for a pipe between a check and the open, and the flags on the one
  ``os.open`` that guards the read. Pinned at the syntax tree, as
  ``tests/test_census_intent_record_reader.py`` pins the intent reader's open.

The fixture builder is the repo's one FIFO helper (``tests/harness_faults.py``)
shared with the scrub, census and gate-CLI levels, so the four cannot drift into
four different ideas of what "a tracked pipe" means.

The FIFO cases skip where ``os.mkfifo`` is unavailable (``O_NOFOLLOW`` aside, a
non-POSIX host has no pipes to plant, and the suite's offline-determinism rule
says such a host skips rather than errors).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from _harness import SRC, _init_repo
from fifo_ast_support import (
    call_line,
    function_source,
    public_safety_module,
    public_safety_text,
)

# Generous against a refusal that costs microseconds, short enough that a
# regression reports itself in seconds instead of inheriting the suite's absence
# of any timeout at all (there is no pytest-timeout in this project).
BOUND_SECONDS = 15

posix_only = pytest.mark.skipif(
    not hasattr(os, "mkfifo"),
    reason="os.mkfifo is POSIX-only, so this host cannot plant a named pipe",
)


def _scan_in_time(repo: Path) -> list[str]:
    """The scan over ``repo`` in a child that cannot stall the suite.

    The child prints the violations on a marker line so "no violations" is
    distinguishable from "no answer": the second is the hang, and it is the
    finding, not an artefact.
    """
    script = (
        "import json, sys; sys.path.insert(0, {src!r})\n"
        "from pathlib import Path\n"
        "from noni import public_safety\n"
        "found, _s, _d = public_safety.scrub_tracked_files(Path({repo!r}))\n"
        "print('FOUND::' + json.dumps(found))\n"
    ).format(src=str(SRC), repo=str(repo))
    started = time.monotonic()
    proc = subprocess.run([sys.executable, "-B", "-c", script],
                          capture_output=True, text=True, timeout=BOUND_SECONDS)
    elapsed = time.monotonic() - started
    assert proc.returncode == 0, f"the scan faulted rather than skipping: {proc.stderr}"
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("FOUND::")), "")
    assert line, f"the scan returned no verdict: {proc.stderr!r}"
    assert elapsed < BOUND_SECONDS, f"the scan took {elapsed:.1f}s"
    return json.loads(line[len("FOUND::"):])


def _read_in_time(path: Path) -> object:
    """The lines ``_read_text_lenient`` returns for ``path``, in a child.

    The function's answer is now a triple (lines, fault) or None for a skip, which
    a caller reads; this helper answers the one question the non-regular cases ask
    -- what lines did the read hand back -- so ``None`` means "skipped" and a list
    means "read", exactly as before the unreadable-file finding was added.
    """
    script = (
        "import json, sys; sys.path.insert(0, {src!r})\n"
        "from pathlib import Path\n"
        "from noni import public_safety\n"
        "value = public_safety._read_text_lenient(Path({path!r}))\n"
        "lines = None if value is None else value[0]\n"
        "print('KIND::' + json.dumps(lines))\n"
    ).format(src=str(SRC), path=str(path))
    started = time.monotonic()
    proc = subprocess.run([sys.executable, "-B", "-c", script],
                          capture_output=True, text=True, timeout=BOUND_SECONDS)
    elapsed = time.monotonic() - started
    assert proc.returncode == 0, f"the read faulted: {proc.stderr}"
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("KIND::")), "")
    assert line, f"the read returned no verdict: {proc.stderr!r}"
    assert elapsed < BOUND_SECONDS, f"the read took {elapsed:.1f}s"
    return json.loads(line[len("KIND::"):])


# --- The kinds refused, one per case ------------------------------------------


@posix_only
def test_a_fifo_yields_no_lines_and_no_wait(tmp_path):
    """A pipe with no writer is refused at the open, not waited on.

    No writer is started on purpose: the unbounded ``open`` of a pipe with no
    writer is the hang, so the non-hanging return while none exists IS the
    assertion. The result must be ``None`` (skipped) and never ``[]``, which is
    what reading the pipe's immediate EOF would have handed back as a false clean.
    """
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    assert _read_in_time(fifo) is None, "the fifo was read rather than skipped"


@posix_only
def test_a_socket_yields_no_lines_and_no_wait(tmp_path):
    """The class, not the one fixture: a bound unix socket is refused too.

    A socket, like a pipe, holds no stored content and answers no EOF, and it is
    the kind a ``S_ISREG`` check catches for the same reason a pipe does.
    """
    sock = tmp_path / "sock"
    socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).bind(str(sock))
    assert _read_in_time(sock) is None, "the socket was read rather than skipped"


def test_a_directory_yields_no_lines(tmp_path):
    """A tracked path that became a directory is skipped, not EISDIR-raised.

    The pre-fix ``read_text`` reached ``open`` on a directory and faulted; the
    guard answers None before any read, which is the same skip every other
    non-regular kind gets.
    """
    directory = tmp_path / "dir"
    directory.mkdir()
    assert _read_in_time(directory) is None


def test_a_dangling_symlink_yields_no_lines(tmp_path):
    """A tracked link whose target is gone is a skip, not a traceback.

    The link is followed (no ``O_NOFOLLOW``), so this is the open faulting with
    ENOENT -- the one non-regular shape where the fault is the answer rather than
    a hang, and the guard still has to turn it into a skip.
    """
    link = tmp_path / "dangling"
    link.symlink_to("nowhere-at-all")
    assert _read_in_time(link) is None


@posix_only
def test_a_symlink_to_a_fifo_yields_no_lines_and_no_wait(tmp_path):
    """The case a pre-open ``lstat`` skip misses, at the read level.

    ``lstat`` of the link answers ``S_ISLNK``, so a top-level regular check skips
    the path and never learns what it pointed at; the scan's own ``read_text``
    follows the link and blocks. Only the ``fstat`` of the descriptor actually
    opened refuses it, so this case is what separates the two designs AC2 offers.
    """
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    link = tmp_path / "link"
    link.symlink_to(fifo.name)
    assert _read_in_time(link) is None, "the link was followed into a read of the pipe"


def test_a_regular_file_through_a_symlink_is_read(tmp_path):
    """The control that says the refusal is about the kind, not about links.

    ``O_NOFOLLOW`` would make this case a silent skip, which is why it exists: a
    tracked link onto ordinary content is scanned and its lines come back.
    """
    body = "the only line\n"
    target = tmp_path / "target.md"
    target.write_text(body, encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(target.name)
    assert _read_in_time(link) == body.splitlines()


def test_an_unreadable_path_yields_no_lines(tmp_path):
    """A path that is no file the scan could read is a skip, the lenient contract.

    A missing path and a link loop must both answer None: the census's honesty
    about a scan that ran is built on the scan never crashing, and each faults the
    open in its own way (ENOENT, ELOOP) on a path the listing named.

    A 000-mode ``regular`` file is deliberately NOT one of these cases any more:
    an unreadable tracked file is a finding, and the row it earns is asserted in
    ``tests/test_public_safety_unreadable.py``. A non-regular sealed path still
    skips, which is what the directory arm below pins for its whole family.
    """
    assert _read_in_time(tmp_path / "absent") is None
    loop_a = tmp_path / "loop-a"
    loop_a.symlink_to("loop-b")
    (tmp_path / "loop-b").symlink_to(loop_a)
    assert _read_in_time(loop_a) is None, "a link loop was not a skip"
    sealed_dir = tmp_path / "sealed-dir"
    sealed_dir.mkdir()
    sealed_dir.chmod(0o000)
    assert _read_in_time(sealed_dir) is None, "an unreadable directory was not skipped"


@posix_only
def test_the_scan_reports_violations_for_regular_files_of_a_tree_holding_every_kind(tmp_path):
    """A tree of refusals is still scanned: the guard is narrow, not a stop.

    Every non-regular kind is planted beside two regular files, one of them
    carrying a violation, and the scan must return the violation and nothing for
    the pipes, sockets, directories and links. This is the case a guard that bailed
    out of the whole scan on the first odd path would pass.
    """
    from harness_faults import _secret_violation

    repo = _init_repo(tmp_path / "kinds")
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    _git_add_commit(repo, "README.md")
    os.mkfifo(repo / "pipe.md")
    socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).bind(str(repo / "sock"))
    (repo / "dir").mkdir()
    (repo / "dangling").symlink_to("nowhere")
    (repo / "note.md").write_text(_secret_violation() + "\n", encoding="utf-8")
    _git_add_commit(repo, "note.md")

    violations = _scan_in_time(repo)
    assert any(v.startswith("note.md:1:") for v in violations), violations
    odd = ("pipe.md", "sock", "dir", "dangling")
    assert not any(any(o in v for o in odd) for v in violations), violations


def _git_add_commit(repo: Path, *rels: str) -> None:
    """Track ``rels`` and commit them, harness identity and all."""
    from _harness import _git

    _git(repo, "add", "--", *rels)
    _git(repo, "commit", "-q", "-m", "fixture")


# --- The structure no fixture can plant ---------------------------------------


def test_the_guarded_open_inspects_the_descriptor_it_opened():
    """``open`` before ``fstat``, in that order, in the one function that guards.

    A ``stat``/``lstat`` of the path and a later ``open`` leave an interval in
    which the path is swapped for a pipe after the check and is opened anyway; the
    promise holds only while the mode is read from the descriptor the scan itself
    opened. Pinned at the tree because no fixture can plant that swap in the
    process under test -- the reason ``tests/test_census_intent_record_reader.py``
    pins the intent reader the same way.
    """
    tree = public_safety_module(public_safety_text())
    opened = call_line(tree, "open_regular", "open")
    inspected = call_line(tree, "open_regular", "fstat")
    assert opened < inspected, (
        "the scan no longer inspects the descriptor it opened, so a path swapped "
        "for a fifo after the check is read and blocks the census forever"
    )


def test_the_guarded_open_carries_both_flags_and_neither_extra():
    """``O_NONBLOCK`` and ``S_ISREG`` present, ``O_NOFOLLOW`` absent, in the guard.

    Each half is a different bug, and the behavioural tests above each carry the one that
    belongs to it: dropping the flag makes the pipe cases hang, dropping the check makes a
    pipe scan as the empty file that is not there, and adding ``O_NOFOLLOW`` makes a
    tracked symlink's content vanish silently -- the last one a green publishing gate over
    bytes nobody read. The flags travel with the open, so the pin reads the guard's whole
    the flags are read off the code itself: ``getattr`` resolves ``"O_NONBLOCK"`` at
    import time and the flag constant is absent on a host without it, so the pin asserts
    the spelling is in the executable text and ``O_NOFOLLOW`` is not.
    """
    import ast

    import noni.public_safety_io

    tree = ast.parse(Path(noni.public_safety_io.__file__).read_text(encoding="utf-8"))
    # Comments are gone with the parse; the docstrings are dropped here. The guard's own
    # docstring spends a paragraph on why O_NOFOLLOW is absent, and a pin that read prose
    # would fail on the sentence that justifies the design.
    for _node in ast.walk(tree):
        if isinstance(_node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)) and _node.body:
            first = _node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                _node.body = _node.body[1:] or [ast.Pass()]
    body = ast.unparse(tree)
    assert "O_NONBLOCK" in body, (
        "the scan's open lost O_NONBLOCK, so a pipe with no writer blocks the open"
    )
    assert "S_ISREG" in body, (
        "the scan lost the descriptor check, so a non-regular path is read as the "
        "empty file that O_NONBLOCK's immediate EOF hands back"
    )
    assert "O_NOFOLLOW" not in body, (
        "O_NOFOLLOW on the scan's open raises ELOOP on a tracked symlink and skips "
        "legitimate tracked content silently"
    )


def test_the_denylist_read_shares_the_guarded_open():
    """The second blocking open is guarded by the same call, not a copy of it.

    ``load_denylist`` used ``path.is_file()`` and ``read_text``: ``is_file()``
    follows links and answers True for a pipe, so a deny-list path that was a pipe
    hung the whole scan before its tracked-file loop started. The pin is that the
    function reaches the guarded opener, so a refactor that reintroduces a bare
    ``read_text`` there re-opens the hang and fails here rather than in the field.
    """
    source = public_safety_text()
    tree = public_safety_module(source)
    call_line(tree, "load_denylist", "_open_regular")
    body = function_source("load_denylist", source)
    assert "read_text" not in body, (
        "load_denylist reads the deny-list with read_text again, which follows a "
        "link and waits on a pipe: is_file() is not a guard"
    )
