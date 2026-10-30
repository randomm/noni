"""register.py writes its state under --repo and nowhere else.

register.py is the writer that creates ``noni/sessions/`` in the first place, so
a run that resolved that directory from its cwd would seed a project nobody
pointed it at. Three trees per run: the state repository (a git repo holding no
``noni/`` yet), a decoy register beside the cwd, and an empty cwd a stray write
would show up in. Each assertion below names which of the three it measures.

Split out of ``test_register_defaults.py``, which keeps the writer's own
defaults, refusals and idempotency paths.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from _harness import REGISTER, _git_ok, run_from
from register_refusal_fixtures import _fields, _git_repo, _sid_of

REGISTER_STATE_DIR = "register-state-root"
REGISTER_CWD_DIR = "register-cwd"
REGISTER_DECOY_DIR = "register-decoy"
REGISTER_DECOY_SID = "2026-10-01-dddddd"


def _register_case(tmp_path: Path) -> tuple[Path, Path, Path]:
    """The three trees of one register state-root run: (root, decoy, cwd)."""
    root = _git_repo(tmp_path)
    root = root.rename(tmp_path / REGISTER_STATE_DIR)
    decoy = tmp_path / REGISTER_DECOY_DIR
    sessions = decoy / "noni" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / f"{REGISTER_DECOY_SID}.md").write_text(
        "# session decoy\n\n- identity: decoy\n- host/worktree: decoy (decoy)\n"
        "- started: 2026-10-01T10:00:00Z\n- status: active\n- claims:\n"
        "  - claim: #999\n",
        encoding="utf-8",
    )
    cwd = tmp_path / REGISTER_CWD_DIR
    cwd.mkdir(parents=True, exist_ok=True)
    return root, decoy, cwd


def _register_from(cwd: Path, repo: Path, identity: str = "developer"
                   ) -> subprocess.CompletedProcess[str]:
    """register.py launched from ``cwd``, with ``--repo`` naming the state root."""
    return run_from(cwd, REGISTER, "--repo", str(repo), "--identity", identity)


def test_register_creates_the_register_only_under_the_state_root(tmp_path):
    """A first registration creates ``noni/sessions/`` in the state repository
    and leaves the decoy and the cwd exactly as they were."""
    root, decoy, cwd = _register_case(tmp_path)
    decoy_bytes = (decoy / "noni" / "sessions" / f"{REGISTER_DECOY_SID}.md").read_bytes()
    assert not (root / "noni").exists(), "the state root must start with no noni/"

    proc = _register_from(cwd, root)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    files = list((root / "noni" / "sessions").glob("*.md"))
    assert len(files) == 1, f"one register file is one registration: {files}"
    body = files[0].read_text(encoding="utf-8")
    assert _fields(body)["identity"] == "developer"
    # The commit landed in the state repository, not wherever the run happened
    # to be launched from: HEAD's only path is the new register file.
    subject = _git_ok(root, "log", "-1", "--format=%s").stdout.strip()
    assert subject.startswith("register:"), subject
    assert (decoy / "noni" / "sessions" / f"{REGISTER_DECOY_SID}.md").read_bytes() \
        == decoy_bytes, (
        "the run touched the decoy register beside its cwd, so the sessions "
        "directory resolved from somewhere other than --repo"
    )
    assert not (cwd / "noni").exists(), "the run created noni/ under the cwd"


def test_register_reuses_the_state_roots_marker_not_the_cwds(tmp_path):
    """The working-copy marker is read from ``--repo`` too: a second run in the
    same state root continues the session instead of minting a new one, even
    though both runs launch from an unrelated directory."""
    root, _decoy, cwd = _register_case(tmp_path)
    first = _register_from(cwd, root)
    assert first.returncode == 0, first.stderr
    sid = _sid_of(first.stdout)

    second = _register_from(cwd, root)
    assert second.returncode == 0, second.stderr
    assert f"{sid}.md already registered" in second.stdout, second.stdout
    assert len(list((root / "noni" / "sessions").glob("*.md"))) == 1, (
        "a second run allocated a second session, so the marker was not the "
        "state root's"
    )


def test_register_refuses_a_repo_that_is_not_a_directory(tmp_path):
    """A --repo naming no directory is a usage error (exit 2) naming the
    argument, and it creates nothing beside the cwd."""
    _root, decoy, cwd = _register_case(tmp_path)
    decoy_bytes = (decoy / "noni" / "sessions" / f"{REGISTER_DECOY_SID}.md").read_bytes()

    proc = _register_from(cwd, tmp_path / "no-such-state-root")
    assert proc.returncode == 2, f"expected exit 2, got {proc.returncode}: {proc.stderr}"
    assert "--repo" in proc.stderr.lower(), proc.stderr
    assert "directory" in proc.stderr.lower(), proc.stderr
    assert (decoy / "noni" / "sessions" / f"{REGISTER_DECOY_SID}.md").read_bytes() \
        == decoy_bytes
    assert not (cwd / "noni").exists()
