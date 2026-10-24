"""Shared git / script helpers for the steering-ledger test harness.

Held in its own module (not ``conftest.py``) so that ``scenario_eval.py`` —
which is both a test module and a standalone build tool
(``python tests/scenario_eval.py <path>``) — can import these helpers
without pulling in ``conftest.py`` and its module-level ``import pytest``.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


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


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run git with the deterministic harness identity (Replay), checking.

    The shared form the test modules' private ``_git`` helpers used:
    ``-c user.name/user.email/commit.gpgsign=false`` and ``check=True``.
    Returns the CompletedProcess so callers can read stdout (e.g. a
    ``git status --porcelain`` round-trip). ``_git_e2`` (no identity pin, no
    check) stays for the push-retry path, which drives its own git config."""
    cmd = [
        "git", "-C", str(repo),
        "-c", "user.name=Replay",
        "-c", "user.email=replay@fixture.invalid",
        "-c", "commit.gpgsign=false",
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def _init_repo(path: Path) -> Path:
    """Create and initialise a throwaway git repo at ``path``."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "commit", "-q", "--allow-empty", "-m", "initial")
    return path


def _commit_file(repo: Path, rel: str, content: str) -> None:
    """Write ``content`` to ``repo/rel`` and commit it under the harness
    identity (creating parent dirs as needed)."""
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "--allow-empty", "-m", f"add {rel}")


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


def git_pin_date(repo: Path, iso_utc: str, *args: str) -> subprocess.CompletedProcess:
    """Run a git command with identity and commit dates pinned.

    ``iso_utc`` is the fixed timestamp; GIT_CONFIG_GLOBAL/SYSTEM point at
    /dev/null to block host gitconfig."""
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    env = dict(os.environ)
    env.update(_git_env_with_identity())
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    env["GIT_AUTHOR_DATE"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    env["GIT_COMMITTER_DATE"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    proc = subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git (pinned {iso_utc}) {args} failed: {proc.stderr.strip()}"
        )
    return proc


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


def push_with_retry(repo: Path, branch: str, attempts: int = 3) -> None:
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


SESSIONS_SKILL = REPO / "skills" / "sessions-claims" / "scripts"
CENSUS_SESSIONS = SESSIONS_SKILL / "census-sessions.sh"
REGISTER = SESSIONS_SKILL / "register.py"
CLAIM = SESSIONS_SKILL / "claim.py"


def run_register(repo: Path, identity: str, **kwargs) -> subprocess.CompletedProcess:
    """Run register.py with --repo repo --identity identity and extra kwargs."""
    extra = []
    for key, value in kwargs.items():
        extra.extend([f"--{key}", str(value)])
    return subprocess.run(
        ["python3", str(REGISTER), "--repo", str(repo), "--identity", identity, *extra],
        capture_output=True,
        text=True,
        timeout=120,
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
