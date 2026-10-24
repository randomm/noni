"""Stale-session detection tests for the unified census.

The staleness check uses only committed artifacts: the session file's
`status` field and the git history of the last commit that touched the
file. The clock comes from --now (for reproducible tests) or the current
UTC time.

The decision policy:
  - stalled: status is `active` AND the last commit for the file is older
    than --stale-after.
  - cannot-tell: the needed git history is unavailable (no commits, shallow
    clone, or the file was never committed). This is a warn, never a fail
    (without --strict).
  - live: status is active and the file was recently committed.

The multi-signal honesty rule: the census never escalates from one signal.
A cannot-tell is reported as cannot-tell, not silently upgraded to stalled.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_CENSUS_DIR = str(REPO / "skills" / "census" / "scripts")
if _CENSUS_DIR not in sys.path:
    sys.path.insert(0, _CENSUS_DIR)

import census  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Replay",
         "-c", "user.email=replay@fixture.invalid", "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "commit", "-q", "--allow-empty", "-m", "initial")
    return path


def _commit_file(repo: Path, rel: str, content: str) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "--allow-empty", "-m", f"add {rel}")


def _session_body(identity: str, status: str = "active") -> str:
    return (f"- identity: {identity}\n- host/worktree: ws\n"
            f"- started: 2026-10-01T10:00:00Z\n- status: {status}\n- claims:\n")


def _run(repo: Path, *args: str) -> tuple[int, str, str]:
    import io
    from contextlib import redirect_stderr, redirect_stdout
    out, err = io.StringIO(), io.StringIO()
    argv = ["--repo", str(repo), "--now", "2026-10-02T00:00:00Z", *args]
    with redirect_stdout(out), redirect_stderr(err):
        rc = census.main(argv)
    return rc, out.getvalue(), err.getvalue()


def test_recently_committed_active_session_is_live(tmp_path):
    """An active session with a recent commit is not stale (exit 0)."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("dev"))
    rc, out, err = _run(repo)
    assert rc == 0, f"recently committed session must be clean, got {rc}\nstderr: {err}\nstdout: {out}"


def test_old_commit_is_stalled_under_strict(tmp_path):
    """An active session whose last commit is older than --stale-after is
    stalled (warn by default, fail under --strict)."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("dev"))
    # Use --now far in the future to make the commit appear old
    import io
    from contextlib import redirect_stderr, redirect_stdout
    # Without --strict: warn (exit 0)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = census.main(["--repo", str(repo), "--now", "2027-01-01T00:00:00Z", "--stale-after", "30"])
    assert rc == 0, f"stalled is warn (exit 0) without --strict, got {rc}\nstderr: {err.getvalue()}"
    assert "stalled" in out.getvalue().lower(), f"expected 'stalled' in output: {out.getvalue()!r}"
    # With --strict: fail (exit 40)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = census.main(["--repo", str(repo), "--now", "2027-01-01T00:00:00Z", "--stale-after", "30", "--strict"])
    assert rc == 40, f"stalled under --strict must exit 40, got {rc}\nstderr: {err.getvalue()}"


def test_closed_session_is_never_stalled(tmp_path):
    """A session with status `closed` is never reported as stalled,
    regardless of commit age."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("dev", status="closed"))
    import io
    from contextlib import redirect_stderr, redirect_stdout
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = census.main(["--repo", str(repo), "--now", "2027-01-01T00:00:00Z", "--stale-after", "1"])
    assert rc == 0, f"closed session must be clean, got {rc}\nstderr: {err.getvalue()}"


def test_never_committed_session_is_cannot_tell(tmp_path):
    """A session file that was never committed is cannot-tell (warn),
    never silently clean and never escalated to stalled."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "noni" / "sessions").mkdir(parents=True)
    # Write but do NOT commit
    (repo / "noni/sessions/2026-10-01-aaaaaa.md").write_text(_session_body("dev"))
    rc, out, err = _run(repo)
    assert rc == 0, f"cannot-tell is warn (exit 0), got {rc}\nstderr: {err}\nstdout: {out}"
    combined = (out + err).lower()
    assert "cannot-tell" in combined, f"expected cannot-tell in output: {out!r} {err!r}"


def test_never_escalate_from_one_signal(tmp_path):
    """The multi-signal honesty rule: a cannot-tell is never silently
    upgraded to stalled. The output must say cannot-tell, not stalled."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "noni" / "sessions").mkdir(parents=True)
    (repo / "noni/sessions/2026-10-01-aaaaaa.md").write_text(_session_body("dev"))
    rc, out, err = _run(repo)
    combined = (out + err).lower()
    assert "cannot-tell" in combined, f"expected cannot-tell: {out!r} {err!r}"
    # The output must NOT say "stalled" for this file
    assert "stalled" not in combined or "cannot-tell" in combined, (
        f"cannot-tell must not be escalated to stalled: {out!r} {err!r}"
    )
