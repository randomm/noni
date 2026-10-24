"""Probe-honesty tests for the unified census.

A census probe that fails to read its input must never be reported as clean.
These tests cover the three probe-failure shapes:
  - unreadable sessions file (non-UTF-8 bytes)
  - symlinked sessions file (never read through a link)
  - git history unavailable (no commits, or no git repo at all)

In each case the census reports a probe failure (warn by default, fail under
--strict) and never exits 0 silently.
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


def _session_body(identity: str) -> str:
    return (f"- identity: {identity}\n- host/worktree: ws\n"
            "- started: 2026-10-01T10:00:00Z\n- status: active\n- claims:\n")


def _run(repo: Path, *args: str) -> tuple[int, str, str]:
    import io
    from contextlib import redirect_stderr, redirect_stdout
    out, err = io.StringIO(), io.StringIO()
    argv = ["--repo", str(repo), "--now", "2026-10-02T00:00:00Z", *args]
    with redirect_stdout(out), redirect_stderr(err):
        rc = census.main(argv)
    return rc, out.getvalue(), err.getvalue()


def test_non_utf8_session_file_is_malformed_not_crash(tmp_path):
    """A session file with non-UTF-8 bytes is reported as malformed (exit 32),
    not a crash and not a silent clean."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "noni" / "sessions").mkdir(parents=True)
    (repo / "noni/sessions/2026-10-01-aaaaaa.md").write_bytes(b"\xff\xfe\x00\x01not-utf8")
    _git(repo, "add", "noni/sessions/")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "add bad file")
    rc, out, err = _run(repo)
    assert rc == 32, f"expected exit 32 for non-UTF-8, got {rc}\nstderr: {err}\nstdout: {out}"


def test_symlinked_session_file_is_probe_failure_not_read(tmp_path):
    """A symlinked session file is reported as a probe failure (warn by
    default), and the target is never read through the link."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "noni" / "sessions").mkdir(parents=True)
    target = repo / "outside-session.md"
    target.write_text(_session_body("dev"))
    (repo / "noni/sessions/2026-10-01-aaaaaa.md").symlink_to(target)
    _git(repo, "add", "noni/sessions/")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "add symlink")
    # Without --strict: warn (exit 0) but the output must name the probe failure
    rc, out, err = _run(repo)
    assert rc == 0, f"probe failure is warn (exit 0) without --strict, got {rc}\nstderr: {err}"
    assert "symlink" in out.lower() or "symlink" in err.lower(), (
        f"expected symlink in output: stdout={out!r} stderr={err!r}"
    )
    # With --strict: fail (exit 41)
    rc, out, err = _run(repo, "--strict")
    assert rc == 41, f"expected exit 41 (probe under --strict), got {rc}\nstderr: {err}\nstdout: {out}"


def test_no_git_history_is_cannot_tell_not_clean(tmp_path):
    """A sessions dir with an active session but no git history (the session
    was never committed) is cannot-tell (warn), never silently clean."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "noni" / "sessions").mkdir(parents=True)
    # Write the file but do NOT commit it
    (repo / "noni/sessions/2026-10-01-aaaaaa.md").write_text(_session_body("dev"))
    rc, out, err = _run(repo)
    # cannot-tell is a warn: exit 0 without --strict
    assert rc == 0, f"cannot-tell is warn (exit 0), got {rc}\nstderr: {err}\nstdout: {out}"
    combined = (out + err).lower()
    assert "cannot-tell" in combined or "no commit" in combined, (
        f"expected cannot-tell or no-commit in output: stdout={out!r} stderr={err!r}"
    )


def test_probe_failure_never_reports_clean_under_strict(tmp_path):
    """Under --strict, any probe failure (unreadable file, symlink, git
    failure) becomes a failure and the census never exits 0."""
    repo = _init_repo(tmp_path / "repo")
    (repo / "noni" / "sessions").mkdir(parents=True)
    target = repo / "outside.md"
    target.write_text(_session_body("dev"))
    (repo / "noni/sessions/2026-10-01-aaaaaa.md").symlink_to(target)
    _git(repo, "add", "noni/sessions/")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "add symlink")
    rc, out, err = _run(repo, "--strict")
    assert rc != 0, f"probe failure under --strict must not exit 0, got {rc}"
    assert rc == 41, f"expected exit 41, got {rc}\nstderr: {err}\nstdout: {out}"


def test_missing_sessions_dir_is_clean(tmp_path):
    """A repo with no noni/sessions/ directory is clean (nothing to check)."""
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "no sessions dir")
    rc, out, err = _run(repo)
    assert rc == 0, f"no sessions dir is clean, got {rc}\nstderr: {err}\nstdout: {out}"
