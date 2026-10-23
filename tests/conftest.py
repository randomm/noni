"""Suite-wide test infrastructure for noni's steering-ledger tests.

WHY THIS FILE EXISTS.

The bridge's conftest.py (tests/conftest.py in pi-tehas-hermes-bridge) clears
every bridge-controlled environment variable and redirects HOME so that a test
that expects "no projects" fails on the developer's machine while passing in
CI, where the variable is simply unset. That is the bug the fixture closes:
the suite must mean the same thing on every host.

The noni equivalent: the census script reads the git history of the ledger
directory to attribute authors and detect post-commit edits. A test that
builds a throwaway git repo in tmp_path must not inherit a hostile HOME that
points at a real ledger, or a hostile GIT_DIR / GIT_WORK_TREE that points at
the host's repo. This conftest clears those variables and redirects HOME to a
sandbox per test.

The assertion that makes this trustworthy is in tests/test_env_isolation.py:
the suite is re-run with HOME pointed at a temp dir containing a *decoy*
ledger, and the test asserts the decoy is not read. Empty-passes-because-
nothing-was-there is exactly the false positive this fixture would otherwise
allow.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

# Environment variables the census script or the tests read. Cleared for
# every test; a test that wants one sets it explicitly.
#
# GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE: if the developer's shell has any of
# these set (e.g. from a git worktree or a `git` command that left them
# exported), the census's `git rev-parse --show-toplevel` would resolve to the
# host's repo instead of the test's throwaway repo. Clearing them per test
# makes the census's git resolution deterministic.
#
# HOME: redirected to a sandbox so `git config` lookups and any `~/...`
# resolution in the tests or the census resolve into the sandbox rather than
# the real account.
NONI_ENV_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
)

REPO = Path(__file__).resolve().parent.parent

# Clear at import time (conftest is imported before any test module is
# collected), so a variable exported by the developer's shell cannot reach a
# test that does not call a helper. Per-test clearing happens in the autouse
# fixture below.
for _var in NONI_ENV_VARS:
    os.environ.pop(_var, None)


def _git(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run git in a repo with a deterministic identity and no GPG signing.

    Mirrors the bridge's _git helper (test_file_size_ratchet.py): passes
    -c user.name / -c user.email / -c commit.gpgsign=false so a throwaway
    repo never inherits the host's git identity or a GPG requirement.
    """
    cmd = ["git", "-C", str(repo), "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid", "-c", "commit.gpgsign=false", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)


@pytest.fixture(autouse=True)
def isolated_noni_env(tmp_path, monkeypatch):
    """Clear every host-controlled input the census reads, for every test.

    autouse so that a test added later cannot opt out by forgetting to call a
    helper — the failure this prevents is silent and host-specific.
    """
    for var in NONI_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    home = tmp_path / "_noni_isolated_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    yield


@pytest.fixture
def git_repo(tmp_path):
    """A throwaway git repo with a deterministic identity, in tmp_path.

    Mirrors the bridge's _repo helper: the repo is init'd, and a helper is
    returned for committing files with the deterministic identity.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")

    def commit(files: dict[str, str], msg: str = "snapshot"):
        for rel, content in files.items():
            target = repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            _git(repo, "add", rel)
        _git(repo, "commit", "-q", "--allow-empty", "-m", msg)

    return repo, commit

