"""Tests for the exit-code table of the unified census.

Each test plants exactly one violation class in an otherwise clean fixture
repo and asserts the exact exit code. The exit-code contract is:
  0   clean (warnings allowed)
  2   usage error
  10  ledger-record
  12  ledger-edited
  20  ledger-chain
  30  session-double
  31  session-claim
  32  session-malformed
  40  session-stalled (only under --strict)
  41  probe failure (only under --strict)
"""

from __future__ import annotations

import json
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


def _valid_record(rec_id="2026-10-01-alpha", status="decided", supersedes=None) -> dict:
    return {
        "id": rec_id, "date": "2026-10-01T10:00:00Z", "asked_by": "dev",
        "questions": [{"id": "q1", "text": "Q?", "options": ["yes", "no"], "answer": "yes"}],
        "by": "T", "scope": "s", "status": status, "supersedes": supersedes,
    }


def _session_body(identity: str, claims: list[str] | None = None) -> str:
    lines = [f"- identity: {identity}", "- host/worktree: ws",
             "- started: 2026-10-01T10:00:00Z", "- status: active", "- claims:"]
    for c in claims or []:
        lines.append(f"  - claim: {c}")
    return "\n".join(lines) + "\n"


def _run(repo: Path, *args: str) -> int:
    import io
    from contextlib import redirect_stderr, redirect_stdout
    out, err = io.StringIO(), io.StringIO()
    argv = ["--repo", str(repo), "--now", "2026-10-02T00:00:00Z", *args]
    with redirect_stdout(out), redirect_stderr(err):
        return census.main(argv)


def test_exit_0_clean(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json", json.dumps(_valid_record(), indent=2))
    assert _run(repo) == 0


def test_exit_2_bad_now():
    import io
    from contextlib import redirect_stderr
    err = io.StringIO()
    with redirect_stderr(err):
        rc = census.main(["--now", "invalid"])
    assert rc == 2


def test_exit_2_unknown_check():
    import io
    from contextlib import redirect_stderr
    err = io.StringIO()
    with redirect_stderr(err):
        rc = census.main(["--only", "bogus"])
    assert rc == 2


def test_exit_10_schema_violation(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    bad = _valid_record()
    del bad["status"]
    _commit_file(repo, "noni/decisions/2026-10-01-bad.json", json.dumps(bad, indent=2))
    assert _run(repo) == 10


def test_exit_10_empty_ledger(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/.gitkeep", "")
    assert _run(repo) == 10


def test_exit_10_not_valid_json(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-bad.json", "{bad")
    assert _run(repo) == 10


def test_exit_12_edited_after_commit(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json", json.dumps(_valid_record(), indent=2))
    (repo / "noni/decisions/2026-10-01-a.json").write_text(
        json.dumps(_valid_record(status="open"), indent=2)
    )
    assert _run(repo) == 12


def test_exit_20_dangling_supersedes(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-root.json", json.dumps(_valid_record("2026-10-01-root"), indent=2))
    dangling = _valid_record("2026-10-22-d", "decided", "2026-10-99-missing")
    _commit_file(repo, "noni/decisions/2026-10-22-d.json", json.dumps(dangling, indent=2))
    assert _run(repo) == 20


def test_exit_20_cycle(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    a = _valid_record("2026-10-01-a", "decided", "2026-10-02-b")
    b = _valid_record("2026-10-02-b", "decided", "2026-10-01-a")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json", json.dumps(a, indent=2))
    _commit_file(repo, "noni/decisions/2026-10-02-b.json", json.dumps(b, indent=2))
    assert _run(repo) == 20


def test_exit_30_double_claim(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("dev", ["#42"]))
    _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md", _session_body("rev", ["#42"]))
    assert _run(repo) == 30


def test_exit_31_claim_without_register(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    body = ("- host/worktree: ws\n- started: 2026-10-01T10:00:00Z\n"
            "- status: active\n- claims:\n  - claim: #42\n")
    _commit_file(repo, "noni/sessions/2026-10-01-cccccc.md", body)
    assert _run(repo) == 31


def test_exit_32_malformed_claim_row(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    body = ("- identity: dev\n- host/worktree: ws\n- started: 2026-10-01T10:00:00Z\n"
            "- status: active\n- claims:\n\n  - claim:\n")
    _commit_file(repo, "noni/sessions/2026-10-01-dddddd.md", body)
    assert _run(repo) == 32


def test_exit_40_stalled_only_under_strict(tmp_path):
    """A stalled session is a warn (exit 0) without --strict, and a fail
    (exit 40) with --strict. The session must have no commit for >7 days."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("dev"))
    import io
    from contextlib import redirect_stderr, redirect_stdout
    # Without --strict: warn (exit 0)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = census.main(["--repo", str(repo), "--now", "2027-01-01T00:00:00Z", "--stale-after", "1"])
    assert rc == 0, f"expected 0 (warn without --strict), got {rc}: {err.getvalue()}"
    # With --strict: fail (exit 40)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = census.main(["--repo", str(repo), "--now", "2027-01-01T00:00:00Z", "--stale-after", "1", "--strict"])
    assert rc == 40, f"expected 40 (fail with --strict), got {rc}: {err.getvalue()}"


def test_lowest_code_wins(tmp_path):
    """When exit 10 (schema) and 30 (double-claim) both fire, 10 wins."""
    repo = _init_repo(tmp_path / "repo")
    bad = _valid_record()
    del bad["id"]
    _commit_file(repo, "noni/decisions/2026-10-01-bad.json", json.dumps(bad, indent=2))
    _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("dev", ["#1"]))
    _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md", _session_body("rev", ["#1"]))
    assert _run(repo) == 10
