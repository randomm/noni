"""Shared builders for the sessions census tests.

The runners that launch each shipped entry point, the fixture-dir writer, and the
state-root / decoy / cwd case builder. Held in a non-test module so the three split
test files drive the same entry points the same way and pytest never collects the
builders as tests. Copied verbatim from ``tests/test_sessions_census.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from _harness import subprocess_env

CENSUS_CWD_DIR = "sessions-census-cwd"

CENSUS_DECOY_DIR = "sessions-census-decoy"

REPO = Path(__file__).resolve().parent.parent

CENSUS_SH = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"

CENSUS_STATE_DIR = "sessions-census-state-root"

FIXTURES = REPO / "tests" / "fixtures"

SHIM = REPO / "skills" / "sessions-claims" / "scripts" / "census-sessions.sh"

WRAPPER = REPO / "skills" / "sessions-claims" / "scripts" / "census-sessions.py"

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
