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

A ledger directory that exists but cannot be listed is a probe fault, not a
state of the tree: it is reported as a ``ledger-edited`` cannot-tell row, so it
leaves the run at 0 and lifts it to 12 under --strict (the row's class code),
never at 42 -- which belongs to the ledger-empty warn the fault must not be
mistaken for. See test_unreadable_ledger_dir_is_cannot_tell_not_empty.

The four warn classes 42/43/44/50 are reported without --strict but exit 0;
--strict promotes each to its own code.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
import census  # noqa: E402
from _harness import (  # noqa: E402
    _commit_file,
    _fault_the_ledger_listing,
    _home_path_violation,
    _init_repo,
    _secret_violation,
)

# Synthetic violation shapes, built by tests/_harness.py from public_safety's
# own pattern tables (see there for why they are not literals and why the
# construction is not copy-pasted into this file).
_HOME_PATH = _home_path_violation()
_SECRET = _secret_violation()


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


def _rows(repo: Path, *args: str) -> list[dict]:
    """The finding rows of a --json run (the exit code is asserted separately)."""
    import io
    from contextlib import redirect_stderr, redirect_stdout
    out, err = io.StringIO(), io.StringIO()
    argv = ["--repo", str(repo), "--now", "2026-10-02T00:00:00Z", "--json", *args]
    with redirect_stdout(out), redirect_stderr(err):
        census.main(argv)
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


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


def test_recordless_ledger_dir_is_ledger_empty_warn(tmp_path):
    """An existing decisions/ directory with no *.json record is the
    ledger-empty warn (operator decision on issue #33, which reverses the
    exit-10 ruling of issue #23): a freshly attached project with no decisions
    yet must census clean, so this run exits 0 and 42 under --strict."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/.gitkeep", "")
    assert _run(repo, "--skip", "hygiene") == 0
    assert _run(repo, "--skip", "hygiene", "--strict") == 42
    assert _run(repo, "--only", "ledger-empty", "--strict") == 42


def test_unreadable_ledger_dir_is_cannot_tell_not_empty(tmp_path, monkeypatch):
    """A decisions/ directory that exists and cannot be listed is not the
    recordless tree: it is a probe fault, reported as a ledger-edited
    cannot-tell row -- a warn that leaves the run at 0 and --strict lifts to
    the class's 12, the same pair every other cannot-tell row keeps.

    The pair sits beside test_recordless_ledger_dir_is_ledger_empty_warn on
    purpose: the two trees differ only in whether the census could read them,
    and their codes differ (0/12 against 0/42) so an operator can tell a
    project that has never steered anything apart from a ledger that went
    unreadable."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json",
                 json.dumps(_valid_record(), indent=2))
    _fault_the_ledger_listing(monkeypatch, repo / "noni" / "decisions")

    assert _run(repo, "--skip", "hygiene") == 0
    assert _run(repo, "--skip", "hygiene", "--strict") == 12
    assert _run(repo, "--only", "ledger-edited", "--strict") == 12
    rows = [r for r in _rows(repo, "--skip", "hygiene") if r.get("kind") == "finding"]
    assert [r["check"] for r in rows] == ["ledger-edited"], (
        f"an unreadable ledger answers no state word, so ledger-empty adds "
        f"nothing of its own: {rows}"
    )
    assert rows[0]["severity"] == "warn" and rows[0]["code"] == 12, rows[0]
    assert "readdir" in rows[0]["message"] and "denied" in rows[0]["message"], (
        f"the OSError text must reach the operator: {rows[0]['message']}"
    )
    assert not rows[0]["subject"].startswith("/"), (
        f"no machine-local path in the row: {rows[0]}"
    )


def test_the_unreadable_ledger_row_survives_a_filter_that_named_no_ledger_class(
    tmp_path, monkeypatch
):
    """The filter must not be able to buy back the clean verdict.

    ``--only`` drops rows of classes it does not name, and the fault row is a
    ``ledger-edited`` row like any other. What it is also is a whole-artifact
    row: the group's own filter keeps it, and the group runs even when the
    filter named none of its classes -- a run that could not read the ledger
    and said nothing would report the same clean as a run that read it and
    found nothing."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json",
                 json.dumps(_valid_record(), indent=2))
    _fault_the_ledger_listing(monkeypatch, repo / "noni" / "decisions")

    for extra in (("--only", "session-double"), ("--skip", "ledger-edited"),
                  ("--only", "session-stalled", "--strict")):
        # hygiene is skipped explicitly rather than left in: its always-on
        # "deny-list inactive" row would sit beside the fault row without
        # changing this assertion's meaning.
        rows = _rows(repo, "--skip", "hygiene", *extra)
        found = [r for r in rows if r.get("kind") == "finding"]
        assert [r["check"] for r in found] == ["ledger-edited"], (
            f"{extra}: the unreadable ledger must still be reported: {found}"
        )
        assert "readdir" in found[0]["message"], found[0]
        # warn by default, 12 under --strict, whichever filter was used.
        expected = 12 if "--strict" in extra else 0
        assert _run(repo, "--skip", "hygiene", *extra) == expected, f"{extra}: expected {expected}"


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


def test_recordless_ledger_dir_reports_the_empty_state(tmp_path):
    """The recordless decisions/ directory reports the same state word as a
    missing decisions/: the warn row names 'empty' either way, and the run is
    clean without --strict."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/.gitkeep", "")
    assert _run(repo, "--skip", "hygiene") == 0
    rows = [r for r in _rows(repo, "--skip", "hygiene") if r.get("check") == "ledger-empty"]
    assert len(rows) == 1, f"expected one ledger-empty row: {rows}"
    assert "(empty)" in rows[0]["message"], f"state word missing: {rows[0]['message']}"


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
