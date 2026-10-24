"""Suite-wide test infrastructure for noni's steering-ledger tests.

WHY THIS FILE EXISTS.

A prior driver conftest (tests/conftest.py in the reference driver) clears
every driver-controlled environment variable and redirects HOME so that a test
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
import sys
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

# Make the unified census module importable from test files (no __init__.py;
# sys.path insertion is the established pattern for repo-local modules).
_CENSUS_SCRIPTS = REPO / "skills" / "census" / "scripts"
if str(_CENSUS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CENSUS_SCRIPTS))

# Clear at import time (conftest is imported before any test module is
# collected), so a variable exported by the developer's shell cannot reach a
# test that does not call a helper. Per-test clearing happens in the autouse
# fixture below.
for _var in NONI_ENV_VARS:
    os.environ.pop(_var, None)


def _git(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run git in a repo with a deterministic identity and no GPG signing.

    Mirrors the reference driver's _git helper (test_file_size_ratchet.py): passes
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

    Mirrors the reference driver's _repo helper: the repo is init'd, and a helper is
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


@pytest.fixture
def run_census():
    """Run census.sh against a ledger dir, returning (exit_code, stdout, stderr).

    Shared by every test module so the subprocess invocation logic lives in one
    place. Pass a custom env dict to override PATH or other variables.
    """
    def _run(ledger_dir: Path, *, env: dict | None = None) -> tuple[int, str, str]:
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        proc = subprocess.run(
            ["bash", str(REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"), str(ledger_dir)],
            capture_output=True,
            text=True,
            env=full_env,
            timeout=60,
        )
        return proc.returncode, proc.stdout, proc.stderr
    return _run


# --- E2 session/claim helpers -------------------------------------------------

SESSIONS_SKILL = REPO / "skills" / "sessions-claims" / "scripts"
CENSUS_SESSIONS = SESSIONS_SKILL / "census-sessions.sh"
REGISTER = SESSIONS_SKILL / "register.py"
CLAIM = SESSIONS_SKILL / "claim.py"


def _git_e2(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run git in a repo with a deterministic identity and no GPG signing."""
    cmd = [
        "git", "-C", str(repo),
        "-c", "user.name=Replay",
        "-c", "user.email=replay@fixture.invalid",
        "-c", "commit.gpgsign=false",
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def _git_ok(repo: Path, *args: str) -> subprocess.CompletedProcess:
    proc = _git_e2(repo, *args)
    if proc.returncode != 0:
        raise RuntimeError(f"git {args} failed: {proc.stderr.strip()}")
    return proc


def _git_env_with_identity() -> dict:
    """An env that pins a deterministic git identity for subprocesses.

    claim.py commits under the caller's configured identity (it no longer
    hardcodes one), so the test harness pins one here: GIT_CONFIG_GLOBAL
    points at /dev/null so the host's ~/.gitconfig cannot leak in, and the
    GIT_AUTHOR_*/GIT_COMMITTER_* env vars supply the identity (signing is
    handled by the scripts' own commit.gpgsign=false)."""
    return {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_AUTHOR_NAME": "Replay",
        "GIT_AUTHOR_EMAIL": "replay@fixture.invalid",
        "GIT_COMMITTER_NAME": "Replay",
        "GIT_COMMITTER_EMAIL": "replay@fixture.invalid",
    }


def build_bare_origin(origin: Path, worktrees: list[Path]) -> None:
    """Build a bare origin plus one or more clones all on branch 'main'.

    Every worktree is cloned from the bare origin (so the origin is actually
    shared — not one clone of another) and starts with one committed file so
    it has a commit to push. The caller then drives register.py / claim.py /
    push-retry against the clones.
    """
    origin.mkdir(parents=True, exist_ok=True)
    _git_ok(origin, "init", "-q", "--bare")
    first = worktrees[0]
    first.mkdir(parents=True, exist_ok=True)
    _git_ok(first, "init", "-q")
    _git_ok(first, "checkout", "-q", "-b", "main")
    (first / "README.md").write_text("test repo\n")
    _git_ok(first, "add", "README.md")
    _git_ok(first, "commit", "-q", "-m", "initial commit")
    _git_ok(first, "remote", "add", "origin", str(origin))
    _git_ok(first, "push", "-q", "-u", "origin", "main")
    for wt in worktrees[1:]:
        wt.mkdir(parents=True, exist_ok=True)
        _git_ok(wt.parent, "clone", "-q", str(origin), str(wt))
        _git_ok(wt, "checkout", "-q", "-b", "main")


def _push_with_retry(repo: Path, branch: str, attempts: int = 3) -> None:
    """fetch-rebase-push with at most `attempts` attempts.

    The losing pusher ends rebased-and-pushed (both claims land); the census
    then flags the double-claim. This is the push protocol documented in the
    skill (fetch-rebase-push, at most 3 attempts)."""
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            _git_ok(repo, "fetch", "origin")
            _git_ok(repo, "rebase", f"origin/{branch}")
        proc = _git_e2(repo, "push", "origin", branch)
        if proc.returncode == 0:
            return
        if attempt == attempts:
            raise RuntimeError(f"push failed after {attempts} attempts: {proc.stderr.strip()}")


def run_register(repo: Path, identity: str, **kwargs) -> subprocess.CompletedProcess:
    """Run register.py with --repo repo --identity identity and extra kwargs."""
    extra = []
    for key, value in kwargs.items():
        extra.extend([f"--{key}", str(value)])
    return subprocess.run(
        ["python3", str(REGISTER), "--repo", str(repo), "--identity", identity, *extra],
        capture_output=True,
        text=True,
    )


def run_claim(
    repo: Path, session_id: str, task: str, push: bool = False, **kwargs
) -> subprocess.CompletedProcess:
    """Run claim.py with the standard arguments and optional --push.

    Runs with the deterministic identity env (claim.py commits under the
    caller's configured identity; the harness pins one here)."""
    extra = []
    for key, value in kwargs.items():
        extra.extend([f"--{key}", str(value)])
    cmd = [
        "python3", str(CLAIM),
        "--repo", str(repo),
        "--session-id", session_id,
        "--task", task,
        *extra,
    ]
    if push:
        cmd.append("--push")
    full_env = dict(os.environ)
    full_env.update(_git_env_with_identity())
    return subprocess.run(cmd, capture_output=True, text=True, env=full_env, timeout=120)


@pytest.fixture
def run_sessions_census():
    """Run the sessions census against a sessions dir.

    Returns (exit_code, stdout, stderr). Pass a custom env dict to override
    PATH or other variables.
    """
    def _run(sessions_dir: Path, *, env: dict | None = None) -> tuple[int, str, str]:
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        proc = subprocess.run(
            ["bash", str(CENSUS_SESSIONS), str(sessions_dir)],
            capture_output=True,
            text=True,
            env=full_env,
            timeout=60,
        )
        return proc.returncode, proc.stdout, proc.stderr
    return _run


