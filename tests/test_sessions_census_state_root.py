"""The sessions census reads the state root its caller named, and no other.

A decoy register beside the cwd is never read, and the state root's own double claim
still fires when the command runs from a foreign directory.

Split out of ``tests/test_sessions_census.py``; the builders are in
``tests/sessions_census_fixtures.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from _harness import run_from
from sessions_census_fixtures import _write_sessions_dir

REPO = Path(__file__).resolve().parent.parent

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
