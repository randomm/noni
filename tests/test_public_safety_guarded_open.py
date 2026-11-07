"""The guarded open of ``public_safety``, on its own.

The open-and-classify step (``_open_regular``) is the seam every file read in the
package goes through, and it answers five distinct questions about one path. They are
asserted here, one per case, rather than only through the FIFO suite: a change to the
answers must say which question it changed.

The answers are the triple of ``_read_text_lenient`` in miniature -- a descriptor, no
finding, or a finding naming the fault -- so the cases below name the state they plant as
well as the answer they expect. A bare "no row" is also what a scan that never reached the
path reports, which is why each case asserts the state first.
"""
from __future__ import annotations

import errno
import os
import socket
from pathlib import Path

import pytest
from _harness import SRC, _git, _init_repo, subprocess_env

from noni import public_safety

# The bound for one child run: long enough for a git listing and an open, short enough
# that a read of a pipe shows up as a failure of this test rather than a hung session.
BOUND_SECONDS = 25


# The verdict is the shape ``_open_regular`` answers with, flattened for JSON:
# ``[kind, class, errno_words]`` where kind is "fd" (a descriptor the caller must close),
# "skip" (nothing to report) or "fault" (the finding #91 swallowed), and the two fault
# fields are absent on the two kinds that carry none.
def _open_in_time(path: Path) -> list:
    """``_open_regular`` on ``path`` in a child, with its answer flattened to JSON.

    The child keeps a bent or blocked seam out of the parent's next test, and the
    ``timeout=`` bounds a read that should never have been attempted.
    """
    import subprocess
    import sys

    script = (
        "import json, sys; sys.path.insert(0, {src!r})\n"
        "from pathlib import Path\n"
        "from noni import public_safety\n"
        "fd, fault = public_safety._open_regular(Path({path!r}))\n"
        "if fd is not None and fd >= 0:\n"
        "    public_safety.os.close(fd)\n"
        "kind = 'fd' if fd is not None and fd >= 0 else ('skip' if fault is None"
        " else 'fault')\n"
        "print('OPEN::' + json.dumps([kind] + (fault and list(fault) or [])))\n"
    ).format(src=str(SRC), path=str(path))
    proc = subprocess.run([sys.executable, "-B", "-c", script],
                          capture_output=True, text=True,
                          env=subprocess_env(), timeout=BOUND_SECONDS)
    assert proc.returncode == 0, f"the open faulted: {proc.stderr}"
    line = next((ln for ln in proc.stdout.splitlines()
                 if ln.startswith("OPEN::")), "")
    assert line, f"the open returned no verdict: {proc.stderr!r}"
    return json_loads(line[len("OPEN::"):])


def json_loads(text: str) -> list:
    """Parse the child's verdict (kept separate so the script stays one expression)."""
    import json
    return json.loads(text)


def _mkfifo_available() -> bool:
    return hasattr(os, "mkfifo")


needs_fifo = pytest.mark.skipif(not _mkfifo_available(),
                                reason="os.mkfifo is POSIX-only")


def _regular(tmp_path: Path, name: str = "file.md", body: str = "text\n") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _fd_answer() -> list:
    """The verdict for a path the scan may read: a descriptor, no fault."""
    return ["fd"]


def _skip_answer() -> list:
    """The verdict for a path there is nothing to report about."""
    return ["skip"]


def test_a_regular_file_comes_back_as_a_descriptor_the_caller_closes(tmp_path):
    """A plain file is the one answer that hands back a descriptor.

    The caller's obligation is the point: every other answer means nothing is left to
    close, because ``_open_regular`` closes what it opened. The precondition names the
    file as regular and readable, since a missing path would also answer "no fault".
    """
    path = _regular(tmp_path)
    assert path.is_file() and os.access(path, os.R_OK), "the fixture is not a readable file"

    assert _open_in_time(path) == _fd_answer()


def test_an_absent_path_is_a_silent_skip(tmp_path):
    """ENOENT is a path that vanished after the listing, not a file refused."""
    missing = tmp_path / "gone.md"
    assert not missing.exists(), "the fixture must plant nothing"

    assert _open_in_time(missing) == _skip_answer()


def test_a_directory_is_a_skip_and_not_read(tmp_path):
    """A tracked directory entry is a skip: it opened, and it is not a file."""
    directory = tmp_path / "dir"
    directory.mkdir()

    assert _open_in_time(directory) == _skip_answer()


@needs_fifo
def test_a_named_pipe_is_refused_on_the_open_and_never_read(tmp_path):
    """The #91 fault: a pipe with no writer must be refused, not opened-and-read.

    The pipe is still a pipe afterwards, which is the assertion that nothing read it --
    an EOF-then-empty read would have consumed it into the empty string.
    """
    pipe = tmp_path / "pipe.md"
    os.mkfifo(pipe)

    assert _open_in_time(pipe) == _skip_answer()
    assert pipe.exists() and not pipe.is_file(), "the scan consumed the pipe it skipped"


def test_a_bound_socket_is_a_skip_and_not_a_finding(tmp_path):
    """ENXIO on the open is the kind's refusal, so a socket earns no violation row.

    On Linux the kernel refuses the open of a bound AF_UNIX socket rather than hand back
    a descriptor, so the refusal arrives as a fault and must not be mistaken for the
    filesystem declining to hand over a regular file.
    """
    sock = tmp_path / "sock"
    if sock.exists():
        sock.unlink()
    socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).bind(str(sock))

    assert _open_in_time(sock) == _skip_answer()


def test_a_file_the_open_refused_is_a_finding_naming_the_fault(tmp_path):
    """EACCES on a regular tracked file is the finding #91 swallowed as a skip.

    The verdict names the fault's class and its errno words, and not the path the kernel
    put in the exception's message: a public-safety row that carried the path would leak
    the machine the scan ran on. Skipped where the host's euid ignores the mode bits.
    """
    path = _regular(tmp_path, "sealed.md", "content nobody may read\n")
    path.chmod(0o000)
    if os.access(path, os.R_OK):  # pragma: no cover - root reads anything
        path.chmod(0o644)
        pytest.skip("root reads anything, so the 000-mode file cannot be planted")

    assert _open_in_time(path) == ["fault", "PermissionError", "Permission denied"]
    path.chmod(0o644)


def test_the_fault_pair_never_carries_the_path_the_message_holds(tmp_path):
    """``_fault_pair`` reads the two structured fields and nothing else.

    ``str(OSError)`` is "class: words - filename", so a row built from the message would
    carry the host path. The words are asserted as well as the absence: a row that named
    no reason would read like every other skip.
    """
    host = "/home/someone/private/denylist"
    fault = PermissionError(errno.EACCES, "Permission denied", host)

    pair = public_safety._fault_pair(fault)

    assert pair == ("PermissionError", "Permission denied"), pair
    assert host not in str(pair)


def test_a_scan_reports_the_refused_file_at_line_zero_and_nothing_else(tmp_path):
    """End to end: one row, at line 0, naming the fault; the neighbour stays clean.

    Line 0 is the file rather than a line of it, and the clean neighbour is the control
    that says the scan flagged the file it could not read and not every path it saw.
    """
    repo = _init_repo(tmp_path / "sealed-tree")
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "--", "README.md")
    _git(repo, "commit", "-q", "-m", "clean file")
    sealed = _regular(repo, "sealed.md", "secret-shaped content\n")
    _git(repo, "add", "--", "sealed.md")
    _git(repo, "commit", "-q", "-m", "a file to seal")
    sealed.chmod(0o000)
    if os.access(sealed, os.R_OK):  # pragma: no cover - root reads anything
        sealed.chmod(0o644)
        pytest.skip("root reads anything, so the 000-mode file cannot be planted")
    assert "sealed.md" in _git(repo, "ls-files").stdout.split(), "git must still list it"
    try:
        found, _source, _denylist, _allowlist = public_safety.scrub_tracked_files(repo)
    finally:
        sealed.chmod(0o644)

    assert any(v.startswith("sealed.md:0:") for v in found), found
    assert not any(v.startswith("README.md") for v in found), found
