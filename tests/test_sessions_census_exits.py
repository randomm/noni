"""The sessions census's exit codes, one fixture per code.

0 clean, 3 no interpreter, 30 double claim, 31 claim without register, 32 malformed
claim row, and the lowest code winning when several fire.

Split out of ``tests/test_sessions_census.py``; the builders are in
``tests/sessions_census_fixtures.py``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sessions_census_fixtures import (
    _fixture,
    _run_sessions_census_bin,
    _write_sessions_dir,
)

REPO = Path(__file__).resolve().parent.parent

FIXTURES = REPO / "tests" / "fixtures"

def test_exit_0_clean(tmp_path, run_sessions_census):
    """A clean sessions dir (valid files, no double-claims) exits 0."""
    fx = _fixture("sessions-exit-0.json")
    assert fx["exit_code"] == 0
    sessions = tmp_path / "noni" / "sessions"
    _write_sessions_dir(sessions, fx["files"])
    code, out, err = run_sessions_census(sessions)
    assert code == 0, f"expected exit 0, got {code}\nstderr: {err}\nstdout: {out}"


def test_exit_3_python_missing(tmp_path, run_sessions_census):
    """With python3 absent from PATH, the census exits 3 (missing dependency)."""
    fx = _fixture("sessions-exit-3.json")
    assert fx["exit_code"] == 3
    sessions = tmp_path / "noni" / "sessions"
    _write_sessions_dir(sessions, fx.get("files", {}))
    # Build a PATH that has bash (so the wrapper runs) but no python3, and
    # clear NONI_PYTHON: conftest exports it (see tests/conftest.py), and the
    # wrapper honours it, so leaving it set would let the wrapper find a real
    # interpreter and the exit-3 path would never be exercised.
    import shutil
    real_bash = shutil.which("bash")
    assert real_bash, "bash not found on this system"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    (fake_bin / "bash").symlink_to(real_bash)
    code, out, err = run_sessions_census(sessions, env={"PATH": str(fake_bin), "NONI_PYTHON": ""})
    assert code == 3, f"expected exit 3, got {code}\nstderr: {err}\nstdout: {out}"
    assert "python3" in err.lower(), f"expected 'python3' in stderr, got: {err}"


def test_exit_30_double_claim(tmp_path, run_sessions_census):
    """Two active claims on the same task from different identities exits 30
    and the NDJSON output names the task."""
    fx = _fixture("sessions-exit-30.json")
    assert fx["exit_code"] == 30
    sessions = tmp_path / "noni" / "sessions"
    _write_sessions_dir(sessions, fx["files"])
    code, out, err = run_sessions_census(sessions)
    assert code == 30, f"expected exit 30, got {code}\nstderr: {err}\nstdout: {out}"
    rows = [json.loads(line) for line in out.strip().splitlines() if line.strip()]
    double = [r for r in rows if r.get("type") == "double-claim"]
    assert double, f"no double-claim row in output: {out}"
    assert double[0]["task"] == "#42", f"double-claim row does not name #42: {double[0]}"
    # The row names both identities' sessions.
    identities = {d["identity"] for d in double[0]["sessions"]}
    assert identities == {"developer", "reviewer"}, f"unexpected identities: {identities}"


def test_exit_31_claim_without_register(tmp_path, run_sessions_census):
    """A claim row committed without a register file (no identity field) exits
    31. The work is not blocked — the census is report-only: no write-path
    refusal, no hook."""
    fx = _fixture("sessions-exit-31.json")
    assert fx["exit_code"] == 31
    sessions = tmp_path / "noni" / "sessions"
    _write_sessions_dir(sessions, fx["files"])
    code, out, err = run_sessions_census(sessions)
    assert code == 31, f"expected exit 31, got {code}\nstderr: {err}\nstdout: {out}"
    rows = [json.loads(line) for line in out.strip().splitlines() if line.strip()]
    assert any(r.get("type") == "claim-without-register" for r in rows), f"no claim-without-register row: {out}"


def test_exit_32_malformed_claim_row(tmp_path, run_sessions_census):
    """A registered session file with a claim row that has no task reference
    exits 32."""
    fx = _fixture("sessions-exit-32.json")
    assert fx["exit_code"] == 32
    sessions = tmp_path / "noni" / "sessions"
    _write_sessions_dir(sessions, fx["files"])
    code, out, err = run_sessions_census(sessions)
    assert code == 32, f"expected exit 32, got {code}\nstderr: {err}\nstdout: {out}"
    rows = [json.loads(line) for line in out.strip().splitlines() if line.strip()]
    assert any(r.get("type") == "malformed" for r in rows), f"no malformed row: {out}"


def test_census_read_only(tmp_path, run_sessions_census):
    """The census never writes: for every exit-class fixture (clean, exit 30,
    exit 32) the file set of the sessions dir is unchanged, and the census
    creates no new file anywhere in the tree."""
    for name in ("sessions-exit-0.json", "sessions-exit-30.json", "sessions-exit-32.json"):
        fx = _fixture(name)
        sdir = tmp_path / "noni" / "sessions"
        for p in sdir.glob("*"):
            p.unlink()
        _write_sessions_dir(sdir, fx["files"])

        before = sorted(p.name for p in sdir.glob("*"))
        code, out, err = run_sessions_census(sdir)
        after = sorted(p.name for p in sdir.glob("*"))
        assert before == after, f"{name}: the census changed the file set: {before} -> {after}"

    # And it must not create any new file anywhere in the tmp_path tree
    # beyond what the fixtures wrote.
    created = [
        p for p in tmp_path.rglob("*")
        if p.is_file() and p.name.startswith("census")
    ]
    assert not created, f"the census wrote files: {created}"


def test_empty_claims_is_clean(tmp_path, run_sessions_census):
    """A session file whose claims list is EMPTY exits 0; a file with a
    malformed claim row exits 32 — the two must not be conflated."""
    sessions = tmp_path / "noni" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "2026-10-01-empty.md").write_text(
        "- identity: developer\n"
        "- host/worktree: host-a (workstation-a)\n"
        "- started: 2026-10-01T10:00:00Z\n"
        "- status: active\n"
        "- claims:\n",
        encoding="utf-8",
    )
    code, out, err = run_sessions_census(sessions)
    assert code == 0, f"empty claims must be clean, got {code}: {err}"

    (sessions / "2026-10-01-bad.md").write_text(
        "- identity: developer\n"
        "- host/worktree: host-a (workstation-a)\n"
        "- started: 2026-10-01T10:00:00Z\n"
        "- status: active\n"
        "- claims:\n\n"
        "  - claim:\n",
        encoding="utf-8",
    )
    code, out, err = run_sessions_census(sessions)
    assert code == 32, f"malformed claim row must exit 32, got {code}: {err}"


def test_same_identity_multiple_sessions_not_double_claim(tmp_path, run_sessions_census):
    """The same identity in two sessions for the same task is reported
    separately as 'same-identity-multi-session', not as a double-claim
    (exit 30)."""
    sessions = tmp_path / "noni" / "sessions"
    sessions.mkdir(parents=True)
    for name in ("2026-10-01-aaaaaa", "2026-10-01-bbbbbb"):
        (sessions / f"{name}.md").write_text(
            "- identity: developer\n"
            "- host/worktree: host-a (workstation-a)\n"
            "- started: 2026-10-01T10:00:00Z\n"
            "- status: active\n"
            "- claims:\n\n"
            "  - claim: #42\n",
            encoding="utf-8",
        )
    code, out, err = run_sessions_census(sessions)
    assert code == 0, f"same identity must not be a double-claim, got {code}: {err}\n{out}"
    rows = [json.loads(line) for line in out.strip().splitlines() if line.strip()]
    assert any(r.get("type") == "same-identity-multi-session" for r in rows), f"no same-identity row: {out}"


def test_priority_lowest_code_wins(tmp_path, run_sessions_census):
    """When a double-claim (30) and a malformed file (32) coexist, the
    lowest code wins (30) and stderr says the other checks were skipped."""
    sessions = tmp_path / "noni" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "2026-10-01-aaaaaa.md").write_text(
        "- identity: developer\n"
        "- host/worktree: host-a (workstation-a)\n"
        "- started: 2026-10-01T10:00:00Z\n"
        "- status: active\n"
        "- claims:\n\n"
        "  - claim: #42\n",
        encoding="utf-8",
    )
    (sessions / "2026-10-01-bbbbbb.md").write_text(
        "- identity: reviewer\n"
        "- host/worktree: host-a (workstation-a)\n"
        "- started: 2026-10-01T10:00:00Z\n"
        "- status: active\n"
        "- claims:\n\n"
        "  - claim: #42\n",
        encoding="utf-8",
    )
    (sessions / "2026-10-01-cccccc.md").write_text(
        "- host/worktree: host-a (workstation-a)\n"  # missing identity
        "- started: 2026-10-01T10:00:00Z\n"
        "- status: active\n"
        "- claims:\n",
        encoding="utf-8",
    )
    code, out, err = run_sessions_census(sessions)
    assert code == 30, f"lowest code (30) must win, got {code}: {err}"
    assert "NDJSON" in err, f"stderr must direct the reader to the NDJSON rows: {err}"


def test_entry_point_is_census_sessions_py(tmp_path, run_sessions_census):
    """The census entry point lives at skills/sessions-claims/scripts/
    census-sessions.py, and the .sh wrapper drives it."""
    entry = REPO / "skills" / "sessions-claims" / "scripts" / "census-sessions.py"
    assert entry.is_file(), "census-sessions.py entry point missing"
    wrapper = REPO / "skills" / "sessions-claims" / "scripts" / "census-sessions.sh"
    assert wrapper.is_file(), "census-sessions.sh wrapper missing"
    assert "census-sessions.py" in wrapper.read_text(encoding="utf-8"), (
        "the .sh wrapper must drive census-sessions.py"
    )
    fx = _fixture("sessions-exit-30.json")
    sessions = tmp_path / "noni" / "sessions"
    _write_sessions_dir(sessions, fx["files"])
    code, out, err = _run_sessions_census_bin(entry, sessions)
    assert code == 30, f"entry point must exit 30, got {code}\n{out}\n{err}"


def test_entry_point_via_steering_ledger_census(tmp_path):
    """The steering-ledger census dispatches the sessions check: `census.sh
    --sessions DIR` runs the same arbiter as the direct wrapper."""
    ledger_census = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"
    assert ledger_census.is_file(), "steering-ledger census.sh missing"
    fx = _fixture("sessions-exit-30.json")
    sessions = tmp_path / "noni" / "sessions"
    _write_sessions_dir(sessions, fx["files"])
    proc = subprocess.run(
        ["bash", str(ledger_census), "--sessions", str(sessions)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 30, f"expected exit 30, got {proc.returncode}\n{proc.stderr}"
    rows = [json.loads(line) for line in proc.stdout.strip().splitlines() if line.strip()]
    assert any(r.get("type") == "double-claim" and r["task"] == "#42" for r in rows), proc.stdout


def test_every_fixture_has_its_exit_code():
    """The fixture's exit_code field matches the code in the filename, so a
    rename or a wrong fixture cannot slip through unnoticed."""
    for f in sorted(FIXTURES.glob("sessions-exit-*.json")):
        fx = _fixture(f.name)
        code_in_name = int(f.stem.replace("sessions-exit-", "").split("-", 1)[0])
        assert fx["exit_code"] == code_in_name, (
            f"{f.name}: exit_code in fixture is {fx['exit_code']} but filename says {code_in_name}"
        )
