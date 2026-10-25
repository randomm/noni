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
  42  ledger-empty (only under --strict)
  43  session-same-identity (only under --strict)
  44  session-deleted (only under --strict)
  50  hygiene (only under --strict)

The four warn classes 42/43/44/50 are reported without --strict but exit 0;
--strict promotes each to its own code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_CENSUS_DIR = str(REPO / "skills" / "census" / "scripts")
if _CENSUS_DIR not in sys.path:
    sys.path.insert(0, _CENSUS_DIR)

import census  # noqa: E402
from _harness import _commit_file, _home_path_violation, _init_repo, _secret_violation  # noqa: E402

# Synthetic violation shapes, built by tests/_harness.py from public_safety's
# own pattern tables (see there for why they are not literals and why the
# construction is not copy-pasted into this file).
_HOME_PATH = _home_path_violation()
_SECRET = _secret_violation()

_scripts_dir = str(REPO / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)


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


def test_exit_10_empty_ledger_dir_stays_ledger_record(tmp_path):
    """An existing decisions/ directory with no *.json record keeps the
    ledger-record fail class (PM decision on issue #23): the ledger-empty
    class adds rows only where the census used to report nothing, so this run
    exits 10, not 0."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/.gitkeep", "")
    assert _run(repo) == 10
    assert _run(repo, "--only", "ledger-record") == 10


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


def test_exit_42_ledger_empty(tmp_path):
    """noni/ present with no decisions/ directory is the warn ledger-empty
    class: exit 0 without --strict, exit 42 under --strict. The register side
    is clean, so this class alone decides the code."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/README.md", "noni lives here\n")
    assert _run(repo) == 0
    assert _run(repo, "--only", "ledger-empty", "--strict") == 42


def test_exit_42_never_weakens_the_empty_ledger_failure(tmp_path):
    """The decision in one line: the empty decisions/ directory is exit 10 both
    with and without --strict, i.e. ledger-empty did not soften it."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/.gitkeep", "")
    assert _run(repo, "--strict", "--skip", "hygiene") == 10


def test_exit_42_ledger_absent(tmp_path):
    """A repo with no noni/ at all is ledger-empty, not a silent clean: one
    row, exit 0 without --strict, exit 42 under --strict. hygiene is skipped
    so the class under test is the one that decides the code."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "README.md", "# empty\n")
    assert _run(repo) == 0
    assert _run(repo, "--only", "ledger-empty", "--strict") == 42


def _session_body_same_identity_repo(tmp_path, status="active"):
    """A repo with two non-terminal session files sharing one identity."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("dev"))
    _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md", _session_body("dev"))
    return repo


def test_exit_43_session_same_identity(tmp_path):
    """Two active sessions with the same identity are the warn
    session-same-identity class: exit 0 without --strict, 43 under --strict.
    hygiene is skipped so the class under test decides the code."""
    repo = _session_body_same_identity_repo(tmp_path)
    assert _run(repo) == 0
    assert _run(repo, "--only", "session-same-identity", "--strict") == 43


def test_exit_44_session_deleted(tmp_path):
    """A session file added in history and deleted from the working tree is
    the warn session-deleted class: exit 0 without --strict, 44 under
    --strict. hygiene is skipped so the class under test decides the code."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("dev"))
    _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md", _session_body("rev"))
    (repo / "noni/sessions/2026-10-01-bbbbbb.md").unlink()
    assert _run(repo) == 0
    assert _run(repo, "--only", "session-deleted", "--strict") == 44


def test_exit_50_hygiene(tmp_path):
    """A tracked file with a home path / secret shape is the warn hygiene
    class: exit 0 without --strict, 50 under --strict. The deny-list is made
    active so the row fires on the violation and not on the inactive class."""
    import public_safety

    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "note.md", _HOME_PATH + "\n")
    denylist = tmp_path / "denylist.txt"
    denylist.write_text("synthetic-project-name\n", encoding="utf-8")
    import os

    os.environ[public_safety.DENYLIST_ENV_VAR] = str(denylist)
    try:
        assert _run(repo, "--only", "hygiene") == 0
        assert _run(repo, "--only", "hygiene", "--strict") == 50
    finally:
        del os.environ[public_safety.DENYLIST_ENV_VAR]


def test_lowest_code_wins(tmp_path):
    """When exit 10 (schema) and 30 (double-claim) both fire, 10 wins."""
    repo = _init_repo(tmp_path / "repo")
    bad = _valid_record()
    del bad["id"]
    _commit_file(repo, "noni/decisions/2026-10-01-bad.json", json.dumps(bad, indent=2))
    _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("dev", ["#1"]))
    _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md", _session_body("rev", ["#1"]))
    assert _run(repo) == 10
