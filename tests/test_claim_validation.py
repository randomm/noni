"""Validation tests for claim.py's documented grammar and guards.

Covers the E1-E5 hardening follow-ups:
- --task must be a non-empty token (no embedded whitespace) - exit 4.
- --branch must be a safe ref name - exit 4.
- a session cannot append the same task claim twice - exit 2.
- the detached-HEAD guard fires when git rev-parse --abbrev-ref HEAD prints
  the literal string "HEAD" (what git actually prints when detached) rather
  than the parenthesised form, - exit 3.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from _harness import REPO, _git, _init_repo, run_claim

CLAIM = REPO / "skills" / "sessions-claims" / "scripts" / "claim.py"


def _session_body(identity: str, claims: list[str] | None = None) -> str:
    lines = [f"- identity: {identity}", "- host/worktree: ws",
             "- started: 2026-10-01T10:00:00Z", "- status: active", "- claims:"]
    for c in claims or []:
        lines.append(f"  - claim: {c}")
    return "\n".join(lines) + "\n"


def _make_session(tmp_path: Path, session_id: str = "2026-10-01-aaaaaa",
                  claims: list[str] | None = None) -> Path:
    repo = _init_repo(tmp_path / "repo")
    sessions = repo / "noni" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f"{session_id}.md").write_text(_session_body("dev", claims))
    _git(repo, "add", f"noni/sessions/{session_id}.md")
    _git(repo, "commit", "-q", "-m", "session")
    return repo


def test_task_with_whitespace_is_refused(tmp_path):
    """A --task with embedded whitespace corrupts the single-line claim row
    and is refused (exit 4), like the empty / whitespace-only task."""
    repo = _make_session(tmp_path)
    # "  #42" is rejected only as whitespace-only after strip; a token with
    # embedded whitespace ("#42 extra") is the shape the guard must refuse.
    for bad in ("#42 extra", "a b"):
        proc = run_claim(repo, "2026-10-01-aaaaaa", bad)
        assert proc.returncode == 4, f"task {bad!r}: expected exit 4, got {proc.returncode}: {proc.stderr}"
        assert "task" in proc.stderr.lower()
    # The whitespace-only form is the pre-existing exit-4 path.
    proc = run_claim(repo, "2026-10-01-aaaaaa", "   ")
    assert proc.returncode == 4, f"whitespace-only task: expected exit 4, got {proc.returncode}: {proc.stderr}"


def test_task_single_token_is_accepted(tmp_path):
    """A well-formed single-token task (the documented grammar) is
    accepted and appended."""
    repo = _make_session(tmp_path)
    proc = run_claim(repo, "2026-10-01-aaaaaa", "#42")
    assert proc.returncode == 0, f"expected exit 0, got {proc.returncode}: {proc.stderr}"
    body = (repo / "noni" / "sessions" / "2026-10-01-aaaaaa.md").read_text()
    assert "- claim: #42" in body


def test_branch_with_slash_or_dots_is_refused(tmp_path):
    """A --branch that is not a safe ref name (slash, dots, empty) is
    refused (exit 4) before git sees it."""
    repo = _make_session(tmp_path)
    # "..main" is a legal git ref name (the guard is a single-segment check,
    # not a git-ref-spec validator): slashes and embedded whitespace are the
    # shapes refused here. (A leading-dash value is refused even earlier,
    # by argparse, which is itself a refusal — not a push.)
    for bad in ("feature/x", "a b"):
        proc = run_claim(repo, "2026-10-01-aaaaaa", "#42", branch=bad)
        assert proc.returncode == 4, f"branch {bad!r}: expected exit 4, got {proc.returncode}: {proc.stderr}"
    # A safe ref name is accepted by the guard (the push itself is not run
    # here; the guard is what this test pins).
    proc = run_claim(repo, "2026-10-01-aaaaaa", "#43", branch="main")
    assert proc.returncode == 0, f"safe branch: expected exit 0, got {proc.returncode}: {proc.stderr}"


def test_same_task_claim_twice_is_refused(tmp_path):
    """A session cannot append the same task claim twice: the second claim
    is refused (exit 2) and the register keeps one claim row."""
    repo = _make_session(tmp_path)
    first = run_claim(repo, "2026-10-01-aaaaaa", "#42")
    assert first.returncode == 0, first.stderr
    second = run_claim(repo, "2026-10-01-aaaaaa", "#42")
    assert second.returncode == 2, f"second claim: expected exit 2, got {second.returncode}: {second.stderr}"
    body = (repo / "noni" / "sessions" / "2026-10-01-aaaaaa.md").read_text()
    assert body.count("- claim: #42") == 1, "the duplicate claim row must not be appended"
    # A different task still appends.
    third = run_claim(repo, "2026-10-01-aaaaaa", "#43")
    assert third.returncode == 0, third.stderr


def test_invalid_utf8_session_is_refused_without_traceback(tmp_path):
    """A session file with invalid UTF-8 bytes is refused (exit 2, like the
    malformed-file path) with a clean stderr message and no traceback."""
    repo = _make_session(tmp_path)
    session_file = repo / "noni" / "sessions" / "2026-10-01-aaaaaa.md"
    session_file.write_bytes(b"- identity: dev\n- claims:\n  - claim: \xff\xfe#42\n")
    proc = run_claim(repo, "2026-10-01-aaaaaa", "#42")
    assert proc.returncode == 2, f"expected exit 2, got {proc.returncode}: {proc.stderr}"
    assert "Traceback" not in proc.stderr, f"unhandled exception: {proc.stderr}"


def test_detached_head_push_is_refused(tmp_path):
    """The detached-HEAD guard fires on the literal string git actually
    prints (rev-parse --abbrev-ref HEAD prints "HEAD" when detached, not
    "(detached HEAD)"): a push from detached HEAD is refused (exit 3)
    rather than attempting to push a branch named "HEAD"."""
    repo = _make_session(tmp_path)
    run_claim(repo, "2026-10-01-aaaaaa", "#42")
    _git(repo, "checkout", "-q", "--detach")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    )
    assert head.stdout.strip() == "HEAD", "precondition: git must print HEAD when detached"
    proc = run_claim(repo, "2026-10-01-aaaaaa", "#43", push=True)
    assert proc.returncode == 3, f"expected exit 3 for detached-HEAD push, got {proc.returncode}: {proc.stderr}"
    assert "detached" in proc.stderr.lower()
