"""Exit codes of the sessions census against one committed golden fixture per
code.

Each golden fixture under tests/fixtures/sessions-exit-<code>.json describes
the sessions tree the test must set up. The test reads the fixture, builds the
tree in tmp_path, runs the census, and asserts the exit code. A fixture that
is wrong for its code makes the corresponding test fail, so the fixtures and
the script cannot disagree.

The exit codes are:
    0   clean — every session file valid, no double-claims
    3   python3 not found on the reading machine
    30  double-claim: two active claims on the same task from different identities
    31  a claim row was committed without a register file (report-only)
    32  a session file is malformed (missing required field, or a claim row
        with no task reference)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from _harness import run_from, subprocess_env

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"


def _run_sessions_census_bin(path: Path, sessions_dir: Path, env: dict | None = None) -> tuple[int, str, str]:
    """Run a sessions census entry point as a subprocess."""
    full_env = subprocess_env()
    if env:
        full_env.update(env)
    proc = subprocess.run(
        [sys.executable, str(path), str(sessions_dir)],
        capture_output=True,
        text=True,
        env=full_env,
        timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _write_sessions_dir(sessions_dir: Path, files: dict) -> None:
    """Write session files from the fixture's files dict.

    Each value is either:
      - a dict with a 'raw' key → written verbatim (for malformed fixtures), or
      - a dict of fields (identity, host/worktree, started, status, claims[])
        → rendered as the standard register format. Fields not present in the
        dict are omitted (so a file with no identity is a claim-without-).
    """
    sessions_dir.mkdir(parents=True, exist_ok=True)
    for name, spec in files.items():
        path = sessions_dir / name
        if "raw" in spec:
            path.write_text(spec["raw"], encoding="utf-8")
            continue
        lines = []
        for field in ("identity", "host/worktree", "started", "status"):
            if field in spec:
                lines.append(f"- {field}: {spec[field]}")
        lines.append("- claims:")
        for claim in spec.get("claims", []):
            lines.append(f"  - claim: {claim}")
        body = "\n".join(lines) + "\n"
        path.write_text(body, encoding="utf-8")


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


# --- State root: the sessions directory is named by the caller, not by cwd ----
#
# The sessions census takes its state root as one argument (the sessions
# directory of the state root) rather than as a --repo flag, so the contract
# here is the same one the writers are held to with a different shape: the
# directory the run reads is the directory it was given, and the cwd decides
# nothing. Three trees: the state root's register, a decoy register beside the
# cwd carrying a double-claim of its own, and an empty cwd a stray write would
# show up in.

CENSUS_STATE_DIR = "sessions-census-state-root"
CENSUS_CWD_DIR = "sessions-census-cwd"
CENSUS_DECOY_DIR = "sessions-census-decoy"


def _sessions_census_case(tmp_path: Path) -> tuple[Path, Path, Path]:
    """The three trees of one sessions-census run: (state root, decoy, cwd).

    The state root's register is clean and the decoy's is the double-claim, so
    exit 0 is the answer that can only come from reading the right directory: a
    run driven by the cwd would have reported the decoy's two active claims on
    one task. The fixture shape is the one the golden fixtures use.
    """
    root = tmp_path / CENSUS_STATE_DIR / "noni" / "sessions"
    _write_sessions_dir(root, {
        "2026-10-01-aaaaaa.md": {
            "identity": "developer", "host/worktree": "ws-1",
            "started": "2026-10-01T10:00:00Z", "status": "active",
            "claims": ["#1"],
        },
        "2026-10-01-bbbbbb.md": {
            "identity": "reviewer", "host/worktree": "ws-2",
            "started": "2026-10-01T11:00:00Z", "status": "active",
            "claims": ["#2"],
        },
    })
    decoy = tmp_path / CENSUS_DECOY_DIR / "noni" / "sessions"
    _write_sessions_dir(decoy, {
        "2026-10-01-cccccc.md": {
            "identity": "one", "host/worktree": "ws-3",
            "started": "2026-10-01T10:00:00Z", "status": "active",
            "claims": ["#999"],
        },
        "2026-10-01-dddddd.md": {
            "identity": "two", "host/worktree": "ws-4",
            "started": "2026-10-01T10:00:00Z", "status": "active",
            "claims": ["#999"],
        },
    })
    cwd = tmp_path / CENSUS_CWD_DIR
    cwd.mkdir(parents=True, exist_ok=True)
    return root, decoy, cwd


def test_the_state_root_named_by_the_caller_is_the_only_one_read(tmp_path):
    """A clean state root censuses clean while a decoy register beside the cwd
    holds a double-claim the run must never see.

    The entry point is the wrapper the skill documents, launched from the cwd
    with the state root's sessions directory passed as its argument."""
    entry = REPO / "skills" / "sessions-claims" / "scripts" / "census-sessions.py"
    root, _decoy, cwd = _sessions_census_case(tmp_path)

    proc = run_from(cwd, entry, str(root), identity=False)
    assert proc.returncode == 0, (
        f"the state root is clean, so the decoy must not have been read: "
        f"{proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    )
    assert proc.stdout.strip() == "", f"a clean run reports nothing: {proc.stdout}"
    assert "#999" not in proc.stdout, "the decoy's double-claim reached the output"
    assert not (cwd / "noni").exists(), "the census is read-only: it wrote under the cwd"


def test_the_state_roots_own_double_claim_fires_from_a_foreign_cwd(tmp_path):
    """The other half of the pair: a double-claim in the state root is reported
    even though the cwd holds a clean decoy register.

    Without this the test above could be satisfied by a census that read no
    directory at all: both would exit 0."""
    entry = REPO / "skills" / "sessions-claims" / "scripts" / "census-sessions.py"
    _root, decoy, cwd = _sessions_census_case(tmp_path)
    # Swap the two registers: the state root is now the double-claim, the decoy
    # beside the cwd is the clean one.
    root = tmp_path / CENSUS_STATE_DIR / "noni" / "sessions"
    for name in list(root.glob("*.md")):
        name.unlink()
    _write_sessions_dir(root, {
        "2026-10-01-eeeeee.md": {
            "identity": "one", "host/worktree": "ws-1",
            "started": "2026-10-01T10:00:00Z", "status": "active",
            "claims": ["#77"],
        },
        "2026-10-01-ffffff.md": {
            "identity": "two", "host/worktree": "ws-2",
            "started": "2026-10-01T10:00:00Z", "status": "active",
            "claims": ["#77"],
        },
    })

    proc = run_from(cwd, entry, str(root), identity=False)
    assert proc.returncode == 30, (
        f"the state root's own double-claim must fire: {proc.returncode}\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert any(r.get("type") == "double-claim" and r["task"] == "#77" for r in rows), rows
    assert "#999" not in proc.stdout
    assert decoy.is_dir(), "the decoy register must still be there to have been ignored"


# --- Every entry point names the state root; none resolves it from the cwd -----
#
# The module, the .sh wrapper and the steering-ledger --sessions dispatch are
# three routes to one arbiter. A cwd-relative default on any of them would
# census (and report clean for) a register the caller never pointed at, so the
# rule is pinned per route: the run reads the directory it was given, and with
# no directory it fails closed with exit 2 rather than inventing one.

# The three routes the product documents. The package module itself is not one
# of them: it imports ``from . import labels``, so running it by path fails on
# the import rather than censusing anything, and the in-place entry point the
# skills sell is the thin wrapper beside it.
CENSUS_SH = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"
SHIM = REPO / "skills" / "sessions-claims" / "scripts" / "census-sessions.sh"
WRAPPER = REPO / "skills" / "sessions-claims" / "scripts" / "census-sessions.py"


def _run_argv(cwd: Path, argv: list[str]) -> subprocess.CompletedProcess[str]:
    """One sessions-census route launched from ``cwd`` with argv given verbatim.

    The list form is deliberate: the three routes differ only in the command
    prefix (``python``, ``bash``, ``bash census.sh --sessions``), so one runner
    keeps the cwd, the environment and the timeout identical across them and a
    pass on one route means the same thing as a pass on another.
    """
    return subprocess.run(argv, capture_output=True, text=True,
                          env=subprocess_env(), cwd=str(cwd), timeout=60)


def _routes(cwd: Path, target: Path | None) -> list[list[str]]:
    """Every entry point for one sessions census of ``target`` (None = no argument).

    ``target`` is passed as one argv entry (or omitted entirely) so the routes
    differ only in how they reach the same core.
    """
    arg = [str(target)] if target is not None else []
    return [
        [sys.executable, str(WRAPPER), *arg],
        ["bash", str(SHIM), *arg],
        ["bash", str(CENSUS_SH), "--sessions", *arg],
    ]


def test_no_shipped_entry_point_carries_a_cwd_relative_state_default():
    """The census's cwd-relative defaults are gone from every entry point, and
    a new one cannot quietly reintroduce one.

    Three sites used to resolve state from wherever the run sat: the package
    module defaulted to ``Path("noni/sessions")``, the sessions shim to the
    same relative path, and the steering-ledger shim to ``"."``. A default of
    that shape is not a convenience here -- it is a verdict on a tree the
    caller never named, reported in the same bytes as a verdict on the state
    root. This pins the absence of the shape itself, on top of the behavioural
    tests above that pin the refusal.
    """
    sites = {
        "src/noni/census_sessions.py": ['Path("noni/sessions")',
                                        "Path('noni/sessions')"],
        "skills/sessions-claims/scripts/census-sessions.sh":
            ['SESSIONS_DIR="noni/sessions"', 'SESSIONS_DIR="."',
             'SESSIONS_DIR="$PWD'],
        "skills/steering-ledger/scripts/census.sh": ['LEDGER_DIR="."',
                                                     'LEDGER_DIR="./"',
                                                     'LEDGER_DIR="$PWD"'],
    }
    for rel, banned in sites.items():
        source = (REPO / rel).read_text(encoding="utf-8")
        for needle in banned:
            assert needle not in source, f"{rel} still defaults state to {needle!r}"


def test_no_route_writes_anything_under_the_cwd(tmp_path):
    """All three routes, pointed at the state root from a foreign cwd, leave it
    empty: the census is read-only, and a cwd it cannot read from is the one
    place it must not end up having touched.

    The one file a launched interpreter is allowed to leave behind is its own
    coverage data file (the gate measures subprocesses, and the launched
    interpreter writes its data where it starts). Those are named, not swept:
    the assertion is about ``noni/``, and it still fails on anything else.
    """
    root, _decoy, cwd = _sessions_census_case(tmp_path)
    for argv in _routes(cwd, root):
        proc = _run_argv(cwd, argv)
        assert proc.returncode == 0, f"{argv[:3]}: {proc.returncode}\n{proc.stderr}"
        strays = [p.name for p in cwd.iterdir() if not p.name.startswith(".coverage")]
        assert strays == [], f"{argv[:3]} wrote under the cwd: {strays}"
        assert not (cwd / "noni").exists(), f"{argv[:3]} created noni/ under the cwd"


def test_no_route_reads_a_decoy_beside_the_cwd(tmp_path):
    """All three routes read the state root and not the decoy beside the cwd.

    The decoy carries a double-claim, so exit 0 is the only answer that can
    come from the right directory: a route still driven by the cwd would have
    reported 30 for the register sitting next to it.
    """
    root, _decoy, cwd = _sessions_census_case(tmp_path)
    for argv in _routes(cwd, root):
        proc = _run_argv(cwd, argv)
        assert proc.returncode == 0, f"{argv[:3]}: {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
        assert "#999" not in proc.stdout, f"{argv[:3]} read the decoy register"


def test_every_route_refuses_a_missing_sessions_dir(tmp_path):
    """The state root's sessions directory removed: every route fails closed.

    A census that cannot find its register has no findings to report, and a
    run that printed nothing and exited 0 would be read as a clean census by
    whoever scripted it. The refusal names the path it was given and exits 2.
    """
    root, _decoy, cwd = _sessions_census_case(tmp_path)
    for name in root.iterdir():
        name.unlink()
    root.rmdir()
    for argv in _routes(cwd, root):
        proc = _run_argv(cwd, argv)
        assert proc.returncode == 2, f"{argv[:3]}: {proc.returncode}\n{proc.stderr}"
        assert "noni" in proc.stderr, f"{argv[:3]} must name the path: {proc.stderr}"
        assert str(root) in proc.stderr, f"{argv[:3]} must name the path it failed on: {proc.stderr}"
        assert proc.stdout.strip() == "", f"{argv[:3]} printed rows for a tree it could not read"


def test_every_route_refuses_a_sessions_dir_that_is_not_a_directory(tmp_path):
    """The same refusal for a sessions path that exists but is not a directory.

    The two states are the pair the contract pins: a missing path and a path
    that answers to something else (here a plain file) are both usage errors,
    not a census over an empty register.
    """
    root, _decoy, cwd = _sessions_census_case(tmp_path)
    for name in root.iterdir():
        name.unlink()
    root.rmdir()
    root.write_text("i am a file, not a sessions directory\n", encoding="utf-8")
    for argv in _routes(cwd, root):
        proc = _run_argv(cwd, argv)
        assert proc.returncode == 2, f"{argv[:3]}: {proc.returncode}\n{proc.stderr}"
        assert str(root) in proc.stderr, f"{argv[:3]} must name the path: {proc.stderr}"
        assert proc.stdout.strip() == "", f"{argv[:3]} printed rows for a non-directory"


def test_no_route_invents_a_state_root_when_given_no_argument(tmp_path):
    """No argument, from a cwd holding a complete decoy register: exit 2 on every
    route, and no NDJSON row.

    This is the regression the cwd-relative defaults used to allow. With a
    default of ``noni/sessions`` the run would have found the decoy and
    reported 30 for a register nobody pointed it at; with a default of ``.``
    (the steering-ledger shim's old one) it would have audited the cwd as a
    ledger. Either way the exit code would have described a tree other than
    the caller's.
    """
    _root, decoy, cwd = _sessions_census_case(tmp_path)
    assert decoy.is_dir(), "the decoy is the whole point: it must be there to be refused"
    for argv in _routes(cwd, None):
        proc = _run_argv(cwd, argv)
        assert proc.returncode == 2, f"{argv[:3]}: {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
        assert proc.stdout.strip() == "", f"{argv[:3]} censused the decoy: {proc.stdout}"
