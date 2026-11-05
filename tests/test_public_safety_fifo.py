"""The hygiene scan reads a tracked FIFO as a refusal, not as a hang (issue #91).

An adversarial reviewer on PR #87 found the census stalling inside
``public_safety._read_text_lenient`` over a tree whose tracked path held a named
pipe: ``path.read_text`` blocks in ``open`` forever, the ``except OSError`` around
it never runs because a blocked read raises nothing, and the module's only
timeout is on the ``git ls-files`` call the scan had already returned from. The
error surface was zero -- no row, no traceback, no exit.

So this module asserts behaviour, never source text: every scan that could hang
runs in a child process under ``subprocess.run(timeout=...)`` with an elapsed
assertion, the shape ``tests/test_session_walk_bounded.py`` uses. An in-process
scan would take the pytest worker with it, and a test that wedges the suite
reports nothing at all -- the same failure mode as the product bug, one layer up.

The fixtures are the repo's one FIFO builder (``tests/harness_faults.py``):
commit a regular file, unlink it, ``os.mkfifo`` the same path. ``git add`` on a
fresh pipe never lists it, so a fixture that planted the pipe first would leave
the scan looking at an ordinary file and pass green with the hang still in place.

The structural half -- the flag ordering no fixture can plant -- is in
``tests/test_public_safety_non_regular.py``.

The FIFO tests skip where ``os.mkfifo`` is unavailable: it is POSIX-only, and the
suite's offline-determinism rule says a non-POSIX host skips rather than errors.
"""

from __future__ import annotations

import os
from pathlib import Path

import public_safety
import pytest
from _harness import (
    _git,
    _home_path_violation,
    _init_repo,
    _leaked_fds_across,
    _mkfifo_available,
    _plant_fifo,
    _plant_fifo_symlink,
    _plant_untracked_fifo,
    _secret_violation,
)
from fifo_child_runs import (
    load_denylist_in_time,
    read_lenient_bent,
    run_bent_scan,
    scan_with_short_reads,
    scrub_in_time,
)

pytestmark = pytest.mark.skipif(
    not _mkfifo_available(),
    reason="os.mkfifo is POSIX-only, so this host cannot plant a named pipe",
)


@pytest.fixture
def fifo_repo(tmp_path):
    """A throwaway committed repo holding a tracked FIFO and a clean neighbour."""
    repo = _init_repo(tmp_path / "fifo-repo")
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "clean file")
    _plant_fifo(repo, "pipe.md")
    return repo


def test_scrub_skips_a_tracked_fifo_without_reading_or_hanging(fifo_repo):
    """The bug, asserted as behaviour: the scan returns and the pipe is unread.

    Two assertions carry it. The first is the bounded return with no violation row
    -- a pipe holds no stored content, so there is nothing to flag and the scan
    moves on. The second is that the path is still a pipe on disk afterwards: a
    scan that had consumed it would have read it, which is the thing AC1 forbids.
    """
    pipe = fifo_repo / "pipe.md"
    assert os.stat(pipe).st_mode & 0o170000 == 0o010000, "the fixture planted no pipe"

    violations = scrub_in_time(fifo_repo)

    assert violations == [], f"a FIFO is not a violation source: {violations}"
    assert pipe.exists(), "the scan removed the path it was supposed to skip"
    assert os.stat(pipe).st_mode & 0o170000 == 0o010000, "the pipe is no longer a pipe"


def test_scrub_still_reports_a_violation_beside_a_tracked_fifo(tmp_path):
    """The skip is narrow: a real violation in a regular file beside the pipe is
    still named, with path, line and label.

    Without the control, a scan that skipped everything (or read the pipe as the
    empty file ``O_NONBLOCK``'s EOF hands back) would look identical to a scan that
    correctly skipped only the non-regular path.
    """
    repo = _init_repo(tmp_path / "fifo-violation")
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "clean file")
    _plant_fifo(repo, "pipe.md")
    (repo / "note.md").write_text(_secret_violation() + "\n", encoding="utf-8")
    _git(repo, "add", "--", "note.md")
    _git(repo, "commit", "-q", "-m", "plant secret beside the pipe")

    violations = scrub_in_time(repo)

    assert any(v.startswith("note.md:1:") and "token" in v for v in violations), (
        f"the scan stopped at the pipe instead of skipping it: {violations}")
    assert not any("pipe.md" in v for v in violations), violations


def test_scrub_skips_a_tracked_symlink_to_a_fifo(tmp_path):
    """A link to a pipe is skipped without following the link into a read.

    This is the case a pre-open ``lstat`` skip does not cover, and the reason AC2
    names the same-descriptor ``fstat`` as the accepted design: ``lstat`` of the
    link says ``S_ISLNK`` and a top-level check skips the path, while a scan that
    follows it blocks on the pipe. The link is tracked, so the scan must reach it
    and refuse it on the descriptor it opened.
    """
    repo = _init_repo(tmp_path / "fifo-link")
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "clean file")
    _plant_fifo(repo, "pipe.md")
    _plant_fifo_symlink(repo, "link.md", "pipe.md")

    assert scrub_in_time(repo) == []


def test_scrub_scans_a_regular_file_reached_through_a_tracked_symlink(tmp_path):
    """The counterpart the exemption rule needs: a link to a regular file is read.

    ``O_NOFOLLOW`` would raise ELOOP here and skip the content silently, so a
    planted secret reached through a link must still be named. It is the control
    that says the pipe refusal is about the pipe and not about links in general.
    """
    repo = _init_repo(tmp_path / "link-regular")
    (repo / "sub").mkdir()
    (repo / "sub" / "secret.md").write_text(_home_path_violation() + "\n",
                                            encoding="utf-8")
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "--", "sub/secret.md", "README.md")
    _git(repo, "commit", "-q", "-m", "clean and planted")
    (repo / "link.md").symlink_to("sub/secret.md")
    _git(repo, "add", "--", "link.md")
    _git(repo, "commit", "-q", "-m", "track a link to the planted file")

    violations = scrub_in_time(repo)

    assert any(v.startswith("link.md:1:") and "home path" in v for v in violations), (
        f"a tracked symlink's content was not scanned: {violations}")


def test_scrub_never_reaches_an_untracked_fifo_beside_tracked_violations(tmp_path):
    """The untracked pipe is the control that pins the listing, not the guard.

    ``git ls-files`` lists index entries only, so no implementation passes or fails
    this by opening anything: the assertion is that git omits the path and that the
    scan still reports the violation in the regular tracked file beside it. Both
    halves together say the scan reached the file that mattered and not the pipe.
    """
    repo = _init_repo(tmp_path / "fifo-untracked")
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "--", "README.md")
    _git(repo, "commit", "-q", "-m", "clean file")
    _plant_untracked_fifo(repo, "loose-pipe.md")
    (repo / "note.md").write_text(_secret_violation() + "\n", encoding="utf-8")
    _git(repo, "add", "--", "note.md")
    _git(repo, "commit", "-q", "-m", "plant secret beside an untracked pipe")

    listing = _git(repo, "ls-files").stdout.split()
    assert "loose-pipe.md" not in listing, (
        "git lists the untracked pipe, so this case is no longer the control")

    violations = scrub_in_time(repo)
    assert any(v.startswith("note.md:1:") for v in violations), violations
    assert not any("loose-pipe" in v for v in violations), violations


# --- The leak the hang's tests cannot see -------------------------------------
#
# One parametrized case for both of the scan's opens: the descriptor a refused path
# was opened with is closed by the open itself, never handed to a caller. The arms
# differ only in which open they drive, and an implementation that guards one and
# leaks the other fails here -- what a single scan-level test would miss.
#
# This is not the same assertion as the ``leaked == []`` in the read-fault case
# below, and the two cannot replace each other. That one is bent on ``os.close``:
# a seam which appends to a list before delegating, so it cannot tell a real close
# from a never-called ``os.close`` or a swallowed ``os.close(-1)``. What is asserted
# here is the kernel's own descriptor table, counted across the call.

_PIPE_COUNT = 5


def _tree_of_pipes(tmp_path: Path, name: str) -> tuple[Path, list[Path]]:
    """A committed repo with ``_PIPE_COUNT`` tracked pipes and one clean file.

    Several rather than one because a leak is per path: one pipe is one descriptor
    and a table of hundreds will not notice. Five shows a per-path leak as five and
    stays far under any host's ``RLIMIT_NOFILE``, so the assertion that fails is the
    assertion and not the environment.
    """
    repo = _init_repo(tmp_path / name)
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "--", "README.md")
    _git(repo, "commit", "-q", "-m", "clean file")
    return repo, [_plant_fifo(repo, f"pipe{i}.md") for i in range(_PIPE_COUNT)]


def _load_denylist_piped(repo: Path, pipes: list[Path]) -> object:
    """``load_denylist`` with both candidates pointed at pipes, in this process.

    Both candidates, so the load walks the whole list and each open answers for
    itself. The seams are restored in a ``finally`` because the caller measures the
    descriptor table around the call and needs them gone afterwards.
    """
    default_file = public_safety._default_denylist_file
    had_env = os.environ.get(public_safety.DENYLIST_ENV_VAR)
    public_safety._default_denylist_file = lambda _repo: pipes[0]
    os.environ[public_safety.DENYLIST_ENV_VAR] = str(pipes[1])
    try:
        result = public_safety.load_denylist(repo)
    finally:
        public_safety._default_denylist_file = default_file
        if had_env is None:
            os.environ.pop(public_safety.DENYLIST_ENV_VAR, None)
        else:
            os.environ[public_safety.DENYLIST_ENV_VAR] = had_env
    assert result.status == "corrupt", (
        f"a pipe deny-list classified as {result.status}: the load never reached "
        "the open this measurement is about")
    return result


@pytest.mark.parametrize("site", ["scan", "denylist"])
def test_a_refused_pipe_leaves_no_descriptor_open(tmp_path, site):
    """Every pipe the scan refuses gives its descriptor back -- both opens.

    The census scans in-process, so a descriptor left per non-regular path is one
    the whole run holds until it exits: a tree with more pipes than the table allows
    does not hang and does not report clean, it dies with EMFILE on somebody else's
    next open. That is the failure this pins, and it is invisible to every bounded
    hang assertion in this file -- a leaking scan returns promptly and reports
    nothing, which is exactly what those tests accept.
    """
    repo, pipes = _tree_of_pipes(tmp_path, f"leak-{site}")

    def call() -> object:
        return (public_safety.scrub_tracked_files(repo) if site == "scan"
                else _load_denylist_piped(repo, pipes))

    leaked = _leaked_fds_across(call)
    assert leaked == 0, (
        f"the {site} open left {leaked} descriptor(s) open across {_PIPE_COUNT} "
        "refused pipes: the census scans in-process, so a tree of pipes exhausts "
        "the descriptor table and the run dies on the next open")

    # Still pipes: a scan that consumed one read it, and a scan that closed a
    # descriptor it never opened may have closed something else's instead.
    for pipe in pipes:
        assert pipe.exists() and not pipe.is_file(), f"{pipe} is no longer a pipe"


def test_a_fifo_at_the_denylist_path_does_not_stop_the_env_candidate(tmp_path):
    """A pipe at the default path is corrupt, and the walk still continues.

    The corrupt-fallthrough contract predates this issue and the pipe must not
    break it: the scan reaches the env-named deny-list and the class activates
    from it. Before the guard this candidate hung the run before its tracked-file
    loop began, with no row, no exit and no next candidate ever consulted.
    """
    repo = _init_repo(tmp_path / "denylist-fifo")
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "--", "README.md")
    _git(repo, "commit", "-q", "-m", "clean file")
    pipe = tmp_path / "denylist-pipe.txt"
    os.mkfifo(pipe)
    (tmp_path / "env-denylist.txt").write_text("synthetic-env-name\n", encoding="utf-8")

    result = load_denylist_in_time(repo, default=pipe,
                                    env=str(tmp_path / "env-denylist.txt"))
    # The bound and the elapsed assertion live in the runner: a child that reached
    # them would have raised there rather than returned.
    assert result["status"] == "ok", (
        f"the env candidate did not take effect past the pipe: {result}")
    assert result["entries"] == ["synthetic-env-name"], result


def test_load_denylist_reports_a_fifo_only_path_as_corrupt_not_absent(tmp_path):
    """A pipe at the only deny-list path is an inactive class named as unreadable.

    "absent" and "corrupt" are different rows in the census, and a pipe that reads
    as "absent" would tell the operator to go write a deny-list when one is
    sitting at the path, unopenable.
    """
    repo = _init_repo(tmp_path / "denylist-fifo-only")
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "--", "README.md")
    _git(repo, "commit", "-q", "-m", "clean file")
    pipe = tmp_path / "denylist-pipe-only.txt"
    os.mkfifo(pipe)

    result = load_denylist_in_time(repo, default=pipe, env=None)
    assert result["status"] == "corrupt", result
    assert result["source"] == pipe.as_posix(), result


def test_read_text_lenient_refuses_a_socket_without_reading_it(tmp_path):
    """The class, not just the pipe: a socket is refused on the same descriptor.

    A character device would pass this test for the wrong reason -- opening one
    returns EOF immediately, with or without the guard -- so the family is probed
    with a socket, which like a pipe has no stored content and no EOF.
    """
    import socket

    path = tmp_path / "sock"
    socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).bind(str(path))

    assert public_safety._read_text_lenient(path) is None, (
        "a socket was read rather than skipped")


def test_the_read_loop_keeps_a_body_one_syscall_did_not_finish(tmp_path):
    """A short ``os.read`` must not scan half a file as if it were the whole of it.

    ``os.read`` is free to return fewer bytes than were asked for on a regular
    file, and a scanner that kept the first chunk would report clean on bytes
    nobody held -- a violation past the first chunk would go unreported forever.
    The bend is installed in a child, so the seam cannot leak into the next test.
    """
    repo = _init_repo(tmp_path / "short-read")
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "--", "README.md")
    _git(repo, "commit", "-q", "-m", "clean file")
    # The token is written in two halves so neither the fixture nor the seam that
    # cuts the read in half can be read as the source of the miss.
    (repo / "note.md").write_text(_secret_violation() + "\n", encoding="utf-8")
    _git(repo, "add", "--", "note.md")
    _git(repo, "commit", "-q", "-m", "plant a token the first read will not hold")

    violations = scan_with_short_reads(repo)

    assert any(v.startswith("note.md:1:") for v in violations), (
        f"only the first chunk was scanned, and the violation past it was lost: "
        f"{violations}")


def test_the_read_loop_bounds_what_one_file_may_hold(tmp_path):
    """A file past the scan's bound is skipped, not swallowed.

    The bound is what a read of someone else's tree is willing to hold in memory.
    The control beside it -- the clean tracked file the scan still reads -- says
    the run did not simply abort at the big file.
    """
    repo = _init_repo(tmp_path / "oversize")
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    (repo / "big.md").write_text("x" * (public_safety._MAX_SCAN_FILE_BYTES + 4096),
                                 encoding="utf-8")
    _git(repo, "add", "--", "README.md", "big.md")
    _git(repo, "commit", "-q", "-m", "a file past the bound and a clean one")

    assert scrub_in_time(repo) == []


def test_the_read_loop_reads_a_whole_file_under_the_bound(tmp_path):
    """The bound must not cost a legitimate file its content.

    A file just under the cap is scanned in full, so a violation in its last line
    is still named -- the half of the bound that a skip-only implementation gets
    wrong.
    """
    repo = _init_repo(tmp_path / "under-bound")
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    padding = "a" * 64
    lines = (public_safety._MAX_SCAN_FILE_BYTES - 200) // (len(padding) + 1)
    body = "\n".join([padding] * lines) + "\n" + _secret_violation() + "\n"
    assert len(body.encode("utf-8")) < public_safety._MAX_SCAN_FILE_BYTES
    (repo / "long.md").write_text(body, encoding="utf-8")
    _git(repo, "add", "--", "README.md", "long.md")
    _git(repo, "commit", "-q", "-m", "a large file whose last line carries a token")

    violations = scrub_in_time(repo)
    assert any(v.startswith("long.md:") for v in violations), violations


def test_a_read_that_faults_halfway_is_reported_and_the_fd_is_still_closed(tmp_path):
    """A descriptor that faults mid-read is a finding, not a skip and not a crash.

    The read of the tree can fault after the classification succeeded (an I/O
    error, a descriptor revoked underneath the scan). Two promises meet here and
    neither may cost the other: the scan never crashes on a path it cannot read
    (the census's honesty about a scan that ran rests on it), and it never
    certifies bytes it never held -- a faulting read of a tracked regular file is
    a violation row naming that file, not a silent skip. The seam is bent in a
    child so it cannot leak into the next test, and the close count is asserted
    because a leaked descriptor on every faulting file is how a scan dies of
    exhaustion.
    """
    repo = _init_repo(tmp_path / "read-fault")
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "--", "README.md")
    _git(repo, "commit", "-q", "-m", "clean file")
    # The faulting file must be the first path the scan reaches, because the seam faults
    # one read. `git ls-files` sorts by byte with the uppercase block first, so a lowercase
    # name sorts after README.md; the faulting file is therefore the README itself.
    (repo / "README.md").write_text(_secret_violation() + "\n", encoding="utf-8")
    _git(repo, "add", "--", "README.md")
    _git(repo, "commit", "-q", "-m", "a file the read will fault on")
    (repo / "note.md").write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "--", "note.md")
    _git(repo, "commit", "-q", "-m", "the clean neighbour the read must reach")
    listing = _git(repo, "ls-files").stdout.split()
    assert listing[0] == "README.md", f"the fixture must order the faulting file first: {listing}"

    # The scan's own descriptors (the only opens carrying O_NONBLOCK) are all
    # closed: none leaked, including the one whose read faulted.
    found, leaked, closes = run_bent_scan(repo, _READ_FAULT_BENDS)
    assert any(v.startswith("README.md:0:") and "could not be read" in v for v in found), (
        f"a read that faulted on a tracked regular file was skipped, not reported: "
        f"{found}")
    assert not any(v.startswith("note.md") for v in found), (
        f"the clean file beside the faulting read was flagged: {found}")
    assert leaked == [], f"the scan leaked these descriptors: {leaked}"
    assert closes >= 3, f"fewer descriptors closed than the scan opened: {closes}"


# Child source that faults one scan read and reports what happened: the descriptors the
# scan opened (those are the only opens carrying O_NONBLOCK), the ones still open at the
# end, and how many closes it made.
_READ_FAULT_BENDS = (
    "real_read, real_close = os.read, os.close\n"
    "closed = []\n"
    "opened = []\n"
    "faulted = []\n"
    "real_open = os.open\n"
    "def opento(path, flags, *a):\n"
    "    fd = real_open(path, flags, *a)\n"
    "    if flags & os.O_NONBLOCK:\n"
    "        opened.append(fd)\n"
    "    return fd\n"
    "def read(fd, size):\n"
    "    if fd in opened and not faulted:\n"
    "        # Fault the read of the first scan descriptor only: bending every read\n"
    "        # would flag every file in the tree and lose the clean neighbour that\n"
    "        # proves the scan reported the faulting file and not all of them.\n"
    "        faulted.append(fd)\n"
    "        raise OSError(5, 'input/output error')\n"
    "    return real_read(fd, size)\n"
    "def close(fd):\n"
    "    closed.append(fd)\n"
    "    return real_close(fd)\n"
    "public_safety.os.open = opento\n"
    "public_safety.os.read = read\n"
    "public_safety.os.close = close\n"
    "def payload():\n"
    "    return json.dumps([found, [fd for fd in opened if fd not in closed],\n"
    "                       len(closed)])\n"
)


def test_the_guard_falls_back_to_a_skip_when_the_descriptor_cannot_be_asked(tmp_path):
    """An ``fstat`` that faults is a skip, and the descriptor is not leaked.

    No ordinary filesystem state produces it -- the interval is a descriptor closed
    or revoked underneath the scan -- so the seam is bent in a child, as the short-
    read case bends ``os.read``. The assertion is two-sided: the path is skipped
    rather than read, and the fd the scan opened is still closed at the end (an
    unclosed descriptor on every tracked file is how a scan dies of exhaustion).
    """
    path = tmp_path / "regular"
    path.write_text("ordinary content\n", encoding="utf-8")
    skipped, closes = read_lenient_bent(path, _FSTAT_FAULT_BENDS)
    assert skipped == [None, ["OSError", "bad descriptor"]], (
        "a descriptor the scan could not classify was read, or was skipped instead of "
        f"reported: {skipped}")
    assert closes == 1, f"the scan leaked the descriptor it opened: {closes} closed"


# Child source that makes every ``fstat`` fault and reports what the read answered (the
# three-way value of ``_read_text_lenient``, so a finding and a skip are told apart) and
# how many descriptors the scan closed.
_FSTAT_FAULT_BENDS = (
    "real_fstat, real_close = os.fstat, os.close\n"
    "closed = []\n"
    "def fstat(fd):\n"
    "    raise OSError(9, 'bad descriptor')\n"
    "def close(fd):\n"
    "    closed.append(fd)\n"
    "    return real_close(fd)\n"
    "public_safety.os.fstat = fstat\n"
    "public_safety.os.close = close\n"
    "def payload():\n"
    "    return json.dumps([value, len(closed)])\n"
)
