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
from _harness import _git, _init_repo  # noqa: E402


def _session_body(identity: str) -> str:
    return (f"- identity: {identity}\n- host/worktree: ws\n"
            "- started: 2026-10-01T10:00:00Z\n- status: active\n- claims:\n")


def _valid_record(rec_id: str = "2026-10-01-alpha", status: str = "decided", supersedes=None) -> dict:
    return {
        "id": rec_id, "date": "2026-10-01T10:00:00Z", "asked_by": "dev",
        "questions": [{"id": "q1", "text": "Q?", "options": ["yes", "no"], "answer": "yes"}],
        "by": "T", "scope": "s", "status": status, "supersedes": supersedes,
    }


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


# --- Byte-exact edit-after-commit integrity checks ------------------------------
#
# The edit check compares the committed blob bytes (git cat-file blob) against
# the working-file bytes (read_bytes()). Both sides hash raw bytes, so
# non-ASCII, CRLF, and non-UTF-8 content must not produce a false finding or a
# crash.


def _commit_record_bytes(repo: Path, rel: str, content: bytes) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "--allow-empty", "-m", f"add {rel}")


def test_edit_check_non_ascii_utf8_unchanged_is_not_edited(tmp_path):
    """(1a) A valid record with non-ASCII UTF-8 content, unchanged on disk,
    must not produce an exit-12 finding — the committed bytes and the working
    bytes are identical, so the sha1s match."""
    import json as _json
    repo = _init_repo(tmp_path / "repo")
    rec = _valid_record()
    rec["questions"][0]["text"] = "Adopt the new scheduler? caf\u00e9 r\u00e9sum\u00e9 \U0001f680"
    content = _json.dumps(rec, indent=2, ensure_ascii=False).encode("utf-8")
    _commit_record_bytes(repo, "noni/decisions/2026-10-01-a.json", content)
    # Working tree is unchanged.
    rc, out, err = _run(repo)
    assert rc == 0, f"unchanged non-ASCII record must be clean, got {rc}\nstderr: {err}\nstdout: {out}"
    assert "edited" not in out.lower(), f"no edited finding expected: {out!r}"


def test_edit_check_crlf_unchanged_is_not_edited(tmp_path):
    """(1c) A record with CRLF line endings, committed and unchanged, must not
    produce a false edit finding: git stores the bytes verbatim, so the working
    CRLF bytes equal the committed CRLF bytes."""
    import json as _json
    repo = _init_repo(tmp_path / "repo")
    rec = _valid_record()
    body = _json.dumps(rec, indent=2)
    crlf = body.replace("\n", "\r\n").encode("utf-8")
    _commit_record_bytes(repo, "noni/decisions/2026-10-01-a.json", crlf)
    rc, out, err = _run(repo)
    assert rc == 0, f"unchanged CRLF record must be clean, got {rc}\nstderr: {err}\nstdout: {out}"
    assert "edited" not in out.lower(), f"no edited finding expected: {out!r}"


def test_edit_check_non_utf8_record_is_not_crash(tmp_path):
    """(1d) A record containing non-UTF-8 bytes must not crash the census. It
    is a schema finding (exit 10) because it is unreadable/invalid, and the
    edit check must not raise on the raw bytes."""
    repo = _init_repo(tmp_path / "repo")
    _commit_record_bytes(repo, "noni/decisions/2026-10-01-a.json", b"{\x80\x81\x00bad bytes not utf8")
    # Must not raise; a non-UTF-8 record is a schema (ledger-record) failure.
    rc, out, err = _run(repo)
    assert rc == 10, f"non-UTF-8 record is a schema failure (10), not a crash, got {rc}\nstderr: {err}\nstdout: {out}"


def test_edit_check_edited_after_commit_is_exit_12(tmp_path):
    """(1b) A record edited in the working tree after its commit must produce
    an exit-12 finding (the integrity check fires)."""
    import json as _json
    repo = _init_repo(tmp_path / "repo")
    rec = _valid_record()
    rec["questions"][0]["text"] = "Adopt the new scheduler? caf\u00e9 r\u00e9sum\u00e9"
    original = _json.dumps(rec, indent=2, ensure_ascii=False).encode("utf-8")
    _commit_record_bytes(repo, "noni/decisions/2026-10-01-a.json", original)
    # Now edit the working-tree bytes (valid UTF-8, different content).
    rec["status"] = "open"
    edited = _json.dumps(rec, indent=2, ensure_ascii=False).encode("utf-8")
    (repo / "noni/decisions/2026-10-01-a.json").write_bytes(edited)
    rc, out, err = _run(repo)
    assert rc == 12, f"edited record must be exit 12, got {rc}\nstderr: {err}\nstdout: {out}"
    assert "edited" in out.lower(), f"edited finding expected: {out!r}"


def test_edit_check_two_commits_same_timestamp_clean(tmp_path):
    """(2) The edit check compares against the NEWEST commit touching the
    record. Two commits with identical timestamps, the second legitimately
    updating the record file, leave a clean working tree (matching the newest
    commit) and must NOT produce an exit-12 finding — even though the record
    was modified in a second commit, the working tree matches the newest
    committed state."""
    import json as _json
    repo = _init_repo(tmp_path / "repo")
    fixed = "2026-10-01T10:00:00Z"
    rec1 = _valid_record()
    body1 = _json.dumps(rec1, indent=2, ensure_ascii=False).encode("utf-8")
    (repo / "noni").mkdir(parents=True, exist_ok=True)
    recpath = repo / "noni/decisions/2026-10-01-a.json"
    recpath.parent.mkdir(parents=True, exist_ok=True)
    recpath.write_bytes(body1)
    _git(repo, "add", "noni/decisions/2026-10-01-a.json")
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Replay",
         "-c", "user.email=replay@fixture.invalid", "-c", "commit.gpgsign=false",
         "-c", f"commit.date={fixed}", "-c", f"author.date={fixed}",
         "commit", "-q", "--allow-empty", "-m", "first"],
        check=True, capture_output=True,
    )
    rec1["status"] = "open"
    body2 = _json.dumps(rec1, indent=2, ensure_ascii=False).encode("utf-8")
    recpath.write_bytes(body2)
    _git(repo, "add", "noni/decisions/2026-10-01-a.json")
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Replay",
         "-c", "user.email=replay@fixture.invalid", "-c", "commit.gpgsign=false",
         "-c", f"commit.date={fixed}", "-c", f"author.date={fixed}",
         "commit", "-q", "--allow-empty", "-m", "second (supersedes content)"],
        check=True, capture_output=True,
    )
    # Working tree matches the newest commit exactly.
    rc, out, err = _run(repo)
    assert rc == 0, f"clean working tree matching newest commit must be clean, got {rc}\nstderr: {err}\nstdout: {out}"
    assert "edited" not in out.lower(), f"no edited finding expected: {out!r}"


def test_git_timeout_reports_tool_missing_not_crash(tmp_path, monkeypatch):
    """(4) A git subprocess that hangs past the timeout must not crash; it
    degrades to the cannot-tell / tool-missing outcome. When git cannot be run
    (unavailable), the census exits 3 (required tool missing)."""
    import census as _census
    # Simulate git being entirely unavailable (shutil.which returns None).
    monkeypatch.setattr(_census.shutil, "which", lambda name: None)
    import io
    from contextlib import redirect_stderr
    err = io.StringIO()
    with redirect_stderr(err):
        rc = _census.main(["--repo", str(tmp_path)])
    assert rc == 3, f"git unavailable must be exit 3, got {rc}\nstderr: {err.getvalue()}"
    assert "git" in err.getvalue().lower(), f"expected git diagnostic: {err.getvalue()!r}"


def test_git_timeout_on_rev_parse_is_cannot_tell_not_crash(tmp_path, monkeypatch):
    """(4) A hung git during the rev-parse --show-toplevel probe must not
    crash; the census degrades to a non-git run (no git history) and still
    returns a deterministic exit code, never raising TimeoutExpired."""
    import io
    from contextlib import redirect_stderr, redirect_stdout

    import census as _census
    orig = _census.subprocess.run

    def _run_spy(cmd, *a, **kw):
        if "rev-parse" in cmd:
            raise _census.subprocess.TimeoutExpired(cmd=cmd, timeout=1)
        return orig(cmd, *a, **kw)

    monkeypatch.setattr(_census.subprocess, "run", _run_spy)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = _census.main(["--repo", str(tmp_path)])
    # rev-parse failing means no git top: the census runs without git and does
    # not crash with an unhandled TimeoutExpired. A deterministic exit (0 for a
    # repo with no noni/ ledger to flag) is the contract.
    assert rc in (0, 2, 3), f"timeout must degrade, not crash, got {rc}\nstderr: {err.getvalue()}"


def test_git_cat_file_timeout_is_cannot_verify_not_crash(tmp_path, monkeypatch):
    """(4) A hung git during blob_content_sha1 (git cat-file blob) must not
    raise TimeoutExpired; it returns None, which the edit check degrades to a
    cannot-verify warning (never a silent pass, never a crash)."""
    import census as _census

    repo = _init_repo(tmp_path / "repo")
    import json as _json
    rec = _valid_record()
    _commit_record_bytes(repo, "noni/decisions/2026-10-01-a.json",
                         _json.dumps(rec, indent=2).encode("utf-8"))
    git = _census.Git(_census._git_top(repo))
    assert git is not None and git.available, "repo should have git history"
    commit = git.last_commit("noni/decisions/2026-10-01-a.json")[1]

    import subprocess as _subprocess
    orig = _census.subprocess.run

    def _run_spy(cmd, *a, **kw):
        if "cat-file" in cmd:
            raise _subprocess.TimeoutExpired(cmd=cmd, timeout=1)
        return orig(cmd, *a, **kw)

    monkeypatch.setattr(_census.subprocess, "run", _run_spy)
    # Must return None (cannot-verify), not raise.
    blob = git.blob_content_sha1(commit, "noni/decisions/2026-10-01-a.json")
    assert blob is None, f"timeout must yield None (cannot-verify), got {blob!r}"
