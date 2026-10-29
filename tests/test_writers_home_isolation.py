"""Every tool reads only under --repo, never from HOME (issue #23, writers).

The state-root contract says the state root is the path --repo names (or the
cwd, for that flag's one documented default) and nothing else. HOME is the
other directory a tool could reach without being told: git reads it for
config, and a path spelled with a leading ~ resolves through it. A hostile
HOME carrying a complete decoy state root is therefore the sharpest test of
the rule -- it is a real tree a tool could have found, in a place the caller
never named. The decoy pattern is the one the census tests use (see
tests/test_env_isolation.py), extended to the writers, because they write and
the census only reads.

Three tests, one pair and one control: every writer runs with HOME redirected
and the decoy's bytes must not move; each writer's own verb must have written
in --repo (a launcher that refused every run would leave the decoy just as
untouched); and the decoy itself must be a state root a tool could have used.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from _harness import REPO, _git_env_with_identity, subprocess_env
from env_isolation_support import (
    BASELINE_DECISION_ID,
    DECOY_SID,
    DECOY_TASK,
    _home_snapshot,
    _home_state_repo,
    _hostile_home,
)

WRITER_LAUNCHERS = {
    # tool -> (script, argv after --repo). The argv is the smallest one each
    # writer accepts: an argument the writer requires must be present or the
    # run fails on usage and measures nothing.
    "register": ("skills/sessions-claims/scripts/register.py",
                 ["--identity", "developer"]),
    "claim": ("skills/sessions-claims/scripts/claim.py",
              ["--session-id", DECOY_SID, "--task", DECOY_TASK]),
    "close": ("skills/sessions-claims/scripts/close.py",
              ["--session-id", DECOY_SID]),
    "release": ("skills/sessions-claims/scripts/release.py",
                ["--session-id", DECOY_SID, "--task", "#7"]),
    "decide": ("skills/steering-ledger/scripts/decide.py",
               ["--slug", "scheduler", "--date", "2026-10-26",
                "--scope", "release ordering", "--asked-by", "developer",
                "--question", "q1=Ship it?", "--option", "q1=yes",
                "--option", "q1=no", "--answer", "q1=yes"]),
    "order": ("skills/direction/scripts/order.py",
              ["add", "7", "--decision", BASELINE_DECISION_ID,
               "--now", "2026-10-02T00:00:00Z"]),
}


def _writers_under_a_hostile_home(tmp_path: Path, monkeypatch):
    """Run every writer with HOME pointing at a decoy state root.

    Returns (home, bytes-before, [(tool, process)], cwd). The caller asserts
    both halves: the home's bytes are unchanged, and each run succeeded. A
    refusal would leave the decoy untouched too, so the verdict alone proves
    nothing -- and neither does a pass, which is why the control test below
    checks the decoy is a tree a writer could actually have used.
    """
    home = _hostile_home(tmp_path)
    root = _home_state_repo(tmp_path)
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    before = _home_snapshot(home)
    results = []
    for tool, (rel_script, argv) in WRITER_LAUNCHERS.items():
        env = subprocess_env()
        env.update(_git_env_with_identity())
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        proc = subprocess.run(
            [sys.executable, str(REPO / rel_script), "--repo", str(root), *argv],
            capture_output=True, text=True, env=env, cwd=str(cwd), timeout=120,
        )
        results.append((tool, proc))
    return home, before, results, cwd


def test_no_writer_reads_or_writes_under_home(tmp_path, monkeypatch):
    """Each writer runs against --repo while HOME holds a complete decoy state
    root: the decoy's bytes are unchanged and no noni/ appears under the cwd.

    This is the HOME half of the isolation pair. The cwd half lives in each
    tool's own state-root test (tests/test_claim_validation.py and the modules
    named there); this one covers the directory a caller never names, which is
    the one a tool reaches by accident rather than by argument.
    """
    home, before, results, cwd = _writers_under_a_hostile_home(tmp_path, monkeypatch)
    failures = {tool: (proc.returncode, proc.stderr[-300:])
                for tool, proc in results if proc.returncode != 0}
    assert not failures, (
        "every writer was given a valid state root, so all must succeed: "
        f"{failures}"
    )
    after = _home_snapshot(home)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert changed == [], (
        "a writer read or wrote under HOME, so a noni/ path resolved from HOME "
        f"rather than --repo; changed: {changed}"
    )
    assert not (cwd / "noni").exists(), "a writer created noni/ under the cwd"


def test_each_writer_actually_wrote_in_the_state_root(tmp_path, monkeypatch):
    """The other half of the pair above: the run must have done its work in --repo.

    A launcher that refused every run would leave the decoy under HOME exactly
    as untouched as a correct one does. What separates the two is that the
    state root's own bytes moved, in the way each verb promises, so each writer
    is checked at its own write here and the isolation claim stops being
    self-certifying.
    """
    _home, _before, _results, _cwd = _writers_under_a_hostile_home(tmp_path, monkeypatch)
    root = tmp_path / "state-root"
    sessions = root / "noni" / "sessions"

    register_files = sorted(p.name for p in sessions.glob("*.md"))
    assert len(register_files) == 2, (
        f"register.py allocates one new session beside the one that was there: "
        f"{register_files}"
    )
    claim_body = (sessions / f"{DECOY_SID}.md").read_text(encoding="utf-8")
    assert f"- claim: {DECOY_TASK}" in claim_body, (
        f"claim.py did not append its row to the state root's register:\n"
        f"{claim_body}"
    )
    assert "- status: closed" in claim_body, (
        "close.py did not move the state root's own session to closed"
    )
    assert "- claim: #7" not in claim_body, (
        "release.py did not remove the row it was given from the state root"
    )
    assert (root / "noni" / "direction" / "order.json").is_file(), (
        "order.py wrote its artifact somewhere other than the state root"
    )
    decisions = sorted(p.name for p in (root / "noni" / "decisions").glob("*.json"))
    assert "2026-10-26-scheduler.json" in decisions, decisions


def test_the_hostile_home_decoy_is_readable(tmp_path):
    """The negative control: the decoy under HOME is a state root a tool could
    have used, not a tree that would have failed on its own terms.

    Without it, the test above could pass because the decoy was unusable rather
    than because the tool ignored it -- the same self-certifying-isolation trap
    the census tests above close for the deny-list.
    """
    home = _hostile_home(tmp_path)
    assert (home / "noni" / "decisions" / "2026-10-01-home-decoy.json").is_file()
    body = (home / "noni" / "sessions" / f"{DECOY_SID}.md").read_text(
        encoding="utf-8")
    assert f"- claim: {DECOY_TASK}" in body, (
        "the decoy register must carry the row a run makes")
    order = json.loads((home / "noni" / "direction" / "order.json").read_text(
        encoding="utf-8"))
    assert order[0]["issue"] == 999
    for rel in ("noni/decisions", "noni/sessions", "noni/direction"):
        assert (home / rel).is_dir(), rel
