"""The working-copy marker on the routes that do not reuse the marked session.

``--no-commit`` writes a session file and runs no git. It is also the route the
docs give to a caller that plants more than one session in one working copy, so
it does not reuse and does not mark: the marked session stays where it was. The
two consequences the marker's text can reach are therefore both in play here
even though the route commits nothing: the file the run reads (the marked
session's, for the reuse verdict) and the name ``--file`` may match.

Both are gated by the one read in ``register._read_marked_name``, so these tests
hold the route to what the docs promise rather than to an implementation:

* marker text that is not a session id is refused at the read and the run says
  so, whether or not a commit follows;
* the written file, its printed path and the pathspec name only this run's
  allocation, never a name built from marker text;
* ``--file`` matches the marked name only on the route that actually reuses the
  marked session (see the ``references/register.md`` one-writer invariant).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _harness import REGISTER, SRC, _git_env_with_identity, subprocess_env
from conftest import run_register
from register_refusal_fixtures import _git_repo, _head

from noni import _marker

MARKED_SID = "2026-10-01-bbbbbb"


def _marked_repo(tmp_path: Path, marked_body: str | None = None) -> tuple[Path, Path]:
    """A committed repo whose working copy is marked for ``MARKED_SID``.

    The marked session's file is committed with the identity the harness pins,
    so HEAD, the marker and the file agree before the run under test starts.
    ``marked_body`` lets a caller plant a file whose status the run must read.

    The marker is written last, after the commits, and re-checked: a marker is
    working-copy state a run leaves behind after it committed, so that is the
    order the fixture builds, and the check is what turns a marker that did not
    survive the commits into a fixture error rather than a test that measures
    the unmarked path while claiming to measure the marked one.
    """
    repo = _git_repo(tmp_path)
    sessions = repo / "noni" / "sessions"
    sessions.mkdir(parents=True)
    body = marked_body or ("- identity: marked-owner\n- host/worktree: ws\n"
                           "- started: 2026-10-01T10:00:00Z\n- status: active\n"
                           "- claims:\n")
    (sessions / f"{MARKED_SID}.md").write_text(body, encoding="utf-8")
    _git_repo_commit(repo)
    marker = repo / ".git" / _marker.MARKER_NAME
    marker.write_text(MARKED_SID + "\n", encoding="utf-8")
    assert marker.is_file() and _marker.read_marker(marker) == MARKED_SID, (
        "precondition: the working copy must start marked for the session the "
        "run under test is told about")
    return repo, marker


def _git_repo_commit(repo: Path) -> None:
    """Commit what the fixture just wrote, under the harness identity."""
    from _harness import _git

    _git(repo, "add", "noni/sessions")
    _git(repo, "commit", "-q", "-m", "marked session")


def _run_no_commit_argv(repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """One ``--no-commit`` run launched with argv spelled out, no launcher sugar.

    Launched through the documented wrapper (the form the skills show) under the
    harness identity env, so the refusal branch is reached exactly as an operator
    would reach it and no git identity is missing for the fixture's own commits.
    """
    env = subprocess_env()
    env.update(_git_env_with_identity())
    return subprocess.run(
        [sys.executable, str(REGISTER),
         "--repo", str(repo), "--identity", "developer", "--no-commit", *extra],
        capture_output=True, text=True, env=env, timeout=120)


def _allocation_line_sid(stdout: str) -> str:
    """The session id from the ``left uncommitted`` line of a --no-commit run."""
    tail = stdout.strip().split(" -> ")[-1].rsplit(" left uncommitted", 1)[0]
    return tail.rsplit("/", 1)[-1].removesuffix(".md")


def test_no_commit_with_a_valid_marker_allocates_and_does_not_mark(tmp_path):
    """Baseline for the route: a valid marker is neither continued nor moved.

    Everything below asserts against this shape, so it is pinned first: the run
    leaves HEAD where it was, writes its own new file, and leaves the marker
    naming the session the earlier run owns.
    """
    repo, marker = _marked_repo(tmp_path)
    head_before = _head(repo)

    proc = _run_no_commit_argv(repo)

    assert proc.returncode == 0, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert "left uncommitted" in proc.stdout, proc.stdout
    sid = _allocation_line_sid(proc.stdout)
    assert sid != MARKED_SID, "an opted-out run reused the marked session"
    assert (repo / "noni" / "sessions" / f"{sid}.md").is_file()
    assert marker.read_text(encoding="utf-8") == MARKED_SID + "\n", (
        "an opted-out run moved the working copy's marker")
    assert _head(repo) == head_before, "--no-commit may not run git"


def test_no_commit_reads_the_marker_through_the_name_guard(tmp_path):
    """Marker text is gated on the read even on the route that writes no commit.

    The marker is uncommitted local state, so its text is an input: hand-edited
    or left by a run on a moved tree, it can read back as a traversal. The gate
    must not be paid for only by the committing path -- an opted-out run still
    reads the marked file to decide the reuse, and still prints a path -- so the
    text is refused at the read, said on stderr, and no path is built from it.
    """
    repo = _git_repo(tmp_path)
    victim = tmp_path / "victim.md"
    victim.write_text("- identity: dev\n- status: active\n- claims:\n",
                      encoding="utf-8")
    marker = repo / ".git" / _marker.MARKER_NAME
    marker.write_text("../../../../victim\n", encoding="utf-8")
    head_before = _head(repo)

    proc = _run_no_commit_argv(repo)

    assert proc.returncode == 0, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert "not a session id" in proc.stderr.lower(), proc.stderr
    assert _marker.MARKER_NAME in proc.stderr, proc.stderr
    sid = _allocation_line_sid(proc.stdout)
    assert (repo / "noni" / "sessions" / f"{sid}.md").is_file()
    # Nothing outside the state root was read from or written to.
    assert victim.read_text(encoding="utf-8") == \
        "- identity: dev\n- status: active\n- claims:\n"
    assert not list(tmp_path.glob("noni")), "register wrote beside the state root"
    assert _head(repo) == head_before, "--no-commit may not run git"


def _allocation_driver(tmp_path: Path) -> Path:
    """A driver that runs ``register.main`` with the allocator pinned.

    The allocation is minted from the clock, so the only way a test can name
    this run's allocation on the command line is to fix what the allocator
    produces. The driver lives under ``tmp_path`` and puts ``src/`` on
    ``sys.path`` itself, so nothing is created inside the shipped skills/ tree.
    """
    driver_dir = tmp_path / "_no_commit_marker_driver"
    driver_dir.mkdir(exist_ok=True)
    driver = driver_dir / "drive_register.py"
    driver.write_text(
        "import os\n"
        "import sys\n"
        f"sys.path.insert(0, {str(SRC)!r})\n"
        "from noni import register\n"
        "register._make_session_id = lambda: os.environ['NONI_TEST_SESSION_ID']\n"
        "raise SystemExit(register.main(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    return driver


def _run_allocated_no_commit(tmp_path: Path, repo: Path, session_id: str,
                             *extra: str) -> subprocess.CompletedProcess[str]:
    """One ``--no-commit`` run whose allocation is ``session_id``, argv spelled out.

    The same launcher shape for every route here, so each test differs only in
    the argv it adds. It also returns the completed run for a caller that needs
    the allocation first and the refusal second in the same tree: the id is
    minted from the clock, so the allocation must be pinned to be nameable.
    """
    env = subprocess_env()
    env["NONI_TEST_SESSION_ID"] = session_id
    env.update(_git_env_with_identity())
    return subprocess.run(
        [sys.executable, str(_allocation_driver(tmp_path)),
         "--repo", str(repo), "--identity", "developer", "--no-commit", *extra],
        capture_output=True, text=True, env=env, timeout=120)


def test_no_commit_does_not_admit_the_marked_name_via_file(tmp_path):
    """``--file`` may name the marked file only on the route that reuses it.

    The one-writer invariant admits two names: this run's allocation and the
    marked session's file. The second belongs to the route that continues the
    marked session; an opted-out run allocates a new one and writes that and
    nothing else, so the marked name is not on its admitted list. Admitting it
    here would let a caller point an allocating run at the marked file and have
    its bytes replaced by an identity that is not the marked one.
    """
    repo, marker = _marked_repo(tmp_path)
    marked_file = repo / "noni" / "sessions" / f"{MARKED_SID}.md"
    marked_bytes = marked_file.read_bytes()
    head_before = _head(repo)
    allocated = "2026-10-02-aaaaaa"

    proc = _run_allocated_no_commit(tmp_path, repo, allocated,
                                    "--file", f"noni/sessions/{MARKED_SID}.md")

    assert proc.returncode == 2, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert "refusing to write" in proc.stderr, proc.stderr
    assert marked_file.read_bytes() == marked_bytes, (
        "an opted-out run wrote into the marked session's file")
    # Only the run's own allocation could have been written, and it was not:
    # the refusal is decided before the write.
    assert [p.name for p in (repo / "noni" / "sessions").glob("*.md")] == [
        f"{MARKED_SID}.md"]
    assert marker.read_text(encoding="utf-8") == MARKED_SID + "\n"
    assert _head(repo) == head_before


def test_no_commit_admits_only_this_runs_allocation(tmp_path):
    """The admitted name on this route is the printed allocation, and it works.

    The counterpart to the refusal above: the guard is not simply closed on the
    ``--no-commit`` route, it admits exactly one name -- the path this run
    allocated, which is the path the run prints.
    """
    repo, _marker_path = _marked_repo(tmp_path)
    allocated = "2026-10-02-bbbbbb"
    stray = repo / "noni" / "sessions" / "stray.md"

    # The run's own allocation, named on the command line the way the reference
    # documents it: the path the run prints is the path the guard admits.
    proc = _run_allocated_no_commit(tmp_path, repo, allocated,
                                    "--file", f"noni/sessions/{allocated}.md")

    assert proc.returncode == 0, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert (repo / "noni" / "sessions" / f"{allocated}.md").is_file()
    assert _allocation_line_sid(proc.stdout) == allocated
    assert not stray.exists(), "a refused name was written"


def test_no_commit_refuses_a_third_name(tmp_path):
    """The admitted set on this route is one name, not three.

    The marked file is excluded by the test above and the allocation is admitted
    by the one before; a name that is neither is refused, so the narrowing did
    not simply open the guard to anything under ``noni/sessions/``.
    """
    repo, _marker_path = _marked_repo(tmp_path)
    allocated = "2026-10-02-cccccc"

    refused = _run_allocated_no_commit(tmp_path, repo, allocated,
                                       "--file", "noni/sessions/stray.md")

    assert refused.returncode == 2, f"{refused.returncode}: {refused.stderr}"
    assert "refusing to write" in refused.stderr, refused.stderr
    assert not (repo / "noni" / "sessions" / "stray.md").exists()


def test_no_commit_with_a_terminal_marked_session_does_not_admit_it(tmp_path):
    """A marked session that has ended is not a target either.

    Same rule as ``--no-commit`` and for the same reason: the route allocates,
    so the marked name is not on its admitted list. The route is reached without
    ``--no-commit`` here, which pins that the narrowing follows the allocation
    and not the flag.
    """
    repo, _marker_path = _marked_repo(
        tmp_path,
        marked_body="- identity: marked-owner\n- status: closed\n- claims:\n")
    marked_file = repo / "noni" / "sessions" / f"{MARKED_SID}.md"
    marked_bytes = marked_file.read_bytes()

    proc = run_register(repo, "developer", file=f"noni/sessions/{MARKED_SID}.md")

    assert proc.returncode == 2, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert "refusing to write" in proc.stderr, proc.stderr
    assert marked_file.read_bytes() == marked_bytes
    assert "allocating a new session" in proc.stdout, proc.stdout


def test_the_reusing_route_still_admits_the_marked_name(tmp_path):
    """The positive half of the narrowing: a reuse still accepts the marked path.

    A caller repeating an earlier run's path explicitly is the documented use of
    ``--file``, and the only route on which the marked session's file is the
    file the run acts on is the one that reuses it. Narrowing the admitted set
    must not have cost that caller its command.
    """
    repo, _marker_path = _marked_repo(tmp_path)

    proc = run_register(repo, "marked-owner", file=f"noni/sessions/{MARKED_SID}.md")

    assert proc.returncode == 0, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert f"{MARKED_SID}.md" in proc.stdout or MARKED_SID in proc.stdout, proc.stdout
    assert "already registered" in proc.stdout, proc.stdout
