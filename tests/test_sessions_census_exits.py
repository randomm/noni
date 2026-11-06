"""The sessions census's exit codes, one fixture per code.

0 clean, 3 no interpreter, 30 double claim, 31 claim without register, 32 malformed
claim row, and the lowest code winning when several fire.

Split out of ``tests/test_sessions_census.py``; the builders are in
``tests/sessions_census_fixtures.py``.
"""

from __future__ import annotations

import json
import subprocess

from _harness import REPO, subprocess_env
from sessions_census_fixtures import (
    _fixture,
    _run_sessions_census_bin,
    _write_sessions_dir,
)

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


def _rows_of(out: str) -> list[dict]:
    """The NDJSON rows of a census run.

    The wrapper's report is the unified census's, which prints a human table by
    default and NDJSON only under ``--json``, so a test that reads rows has to ask
    for them. The old sessions parser printed NDJSON always; that difference is the
    one place the wrapper is not byte-identical to what it replaced, and it is the
    census's own format rather than a second one.
    """
    return [json.loads(line) for line in out.strip().splitlines()
            if line.strip().startswith("{")]


def test_exit_30_double_claim(tmp_path, run_sessions_census):
    """Two active claims on the same task from different identities exits 30
    and the NDJSON output names the task."""
    fx = _fixture("sessions-exit-30.json")
    assert fx["exit_code"] == 30
    sessions = tmp_path / "noni" / "sessions"
    _write_sessions_dir(sessions, fx["files"])
    code, out, err = run_sessions_census(sessions, env=None)
    assert code == 30, f"expected exit 30, got {code}\nstderr: {err}\nstdout: {out}"
    code, json_out, err = run_sessions_census(sessions, extra=("--json",))
    rows = _rows_of(json_out)
    double = [r for r in rows if r.get("check") == "session-double"]
    assert double, f"no session-double row in output: {json_out}"
    assert double[0]["subject"] == "#42", (
        f"the row does not name the claimed task: {double[0]}")
    # The row names both identities' sessions.
    message = double[0]["message"]
    for identity in ("developer", "reviewer"):
        assert identity in message, f"{identity} absent from the row: {message}"


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
    _code, json_out, _err = run_sessions_census(sessions, extra=("--json",))
    rows = _rows_of(json_out)
    assert any(r.get("check") == "session-claim" for r in rows), (
        f"no session-claim row: {json_out}")


def test_exit_32_malformed_claim_row(tmp_path, run_sessions_census):
    """A registered session file with a claim row that has no task reference
    exits 32."""
    fx = _fixture("sessions-exit-32.json")
    assert fx["exit_code"] == 32
    sessions = tmp_path / "noni" / "sessions"
    _write_sessions_dir(sessions, fx["files"])
    code, out, err = run_sessions_census(sessions)
    assert code == 32, f"expected exit 32, got {code}\nstderr: {err}\nstdout: {out}"
    _code, json_out, _err = run_sessions_census(sessions, extra=("--json",))
    rows = _rows_of(json_out)
    assert any(r.get("check") == "session-malformed" for r in rows), (
        f"no session-malformed row: {json_out}")


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
    malformed claim row exits 32 — the two must not be conflated.

    Both files carry an allocated name (``<date>-<6 hex>.md``): an unallocated
    name is its own malformed row, and this test is about the claims list.
    """
    sessions = tmp_path / "noni" / "sessions"
    sessions.mkdir(parents=True)
    body = ("- identity: developer\n"
            "- host/worktree: host-a (workstation-a)\n"
            "- started: 2026-10-01T10:00:00Z\n"
            "- status: active\n"
            "- claims:\n")
    (sessions / "2026-10-01-aaaaaa.md").write_text(body, encoding="utf-8")
    code, out, err = run_sessions_census(sessions)
    assert code == 0, f"empty claims must be clean, got {code}: {err}"

    (sessions / "2026-10-01-bbbbbb.md").write_text(
        body + "  - claim:\n", encoding="utf-8")
    code, out, err = run_sessions_census(sessions)
    assert code == 32, f"malformed claim row must exit 32, got {code}: {err}"


def test_an_unallocated_register_name_is_malformed(tmp_path, run_sessions_census):
    """A register file the allocator never named is refused and named.

    The rule the empty-claims test above has to work around: a file whose name is
    not ``<date>-<6 hex>.md`` is not a register this protocol wrote, so the census
    refuses it (32) rather than trusting its contents.
    """
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
    assert code == 32, f"an unallocated register name must be refused: {code} {out}"
    assert "2026-10-01-empty.md" in out, (
        f"the row must name the file it refused: {out}")


def test_same_identity_multiple_sessions_not_double_claim(tmp_path, run_sessions_census):
    """The same identity in two sessions for the same task is reported
    separately as ``session-same-identity``, not as a double-claim (exit 30)."""
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
    _code, json_out, _err = run_sessions_census(sessions, extra=("--json",))
    rows = _rows_of(json_out)
    assert any(r.get("check") == "session-same-identity" for r in rows), (
        f"no session-same-identity row: {json_out}")
    assert not any(r.get("check") == "session-double" for r in rows), (
        f"the same identity across two sessions was called a double-claim: {json_out}")


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
    # The table itself carries the rows (the report names each class and its
    # code), and the exit line on stderr directs the reader to what ran.
    assert "session-double" in out, f"the winning class is not in the report: {out}"
    assert "session-malformed" in out, (
        f"every check ran, so the losing class is reported too: {out}")
    assert "every check ran" in err, (
        f"stderr must say no check was skipped: {err}")


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


def test_the_ledger_wrapper_is_not_a_sessions_route(tmp_path):
    """``census.sh --sessions DIR`` is not a route any more, and says so.

    The ledger shim used to carry a ``--sessions`` dispatch into a second parser
    of its own. The parser and the flag are both gone (issue #99): the census gets
    the option, refuses it, and the caller who types the old form gets the
    census's refusal and its usage code rather than a silent census of the wrong
    group.
    """
    ledger_census = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"
    assert ledger_census.is_file(), "steering-ledger census.sh missing"
    fx = _fixture("sessions-exit-30.json")
    sessions = tmp_path / "noni" / "sessions"
    _write_sessions_dir(sessions, fx["files"])
    proc = subprocess.run(
        ["bash", str(ledger_census), "--sessions", str(sessions)],
        capture_output=True, text=True, env=subprocess_env(), timeout=60,
    )
    assert proc.returncode == 2, (
        f"the retired dispatch must be a refusal, not a census: "
        f"{proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    combined = proc.stdout + proc.stderr
    assert "--sessions" in combined, (
        f"the refusal must name the option it refused: {combined}")
    assert "session-double" not in combined, (
        f"a refused run censused the register anyway: {combined}")


def test_every_fixture_has_its_exit_code():
    """The fixture's exit_code field matches the code in the filename, so a
    rename or a wrong fixture cannot slip through unnoticed."""
    for f in sorted(FIXTURES.glob("sessions-exit-*.json")):
        fx = _fixture(f.name)
        code_in_name = int(f.stem.replace("sessions-exit-", "").split("-", 1)[0])
        assert fx["exit_code"] == code_in_name, (
            f"{f.name}: exit_code in fixture is {fx['exit_code']} but filename says {code_in_name}"
        )
