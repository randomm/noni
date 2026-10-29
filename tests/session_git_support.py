"""Shared fixture builders for the ``_session_git`` suites.

The module under test is the git mechanic the four session writers share, so
every suite here needs the same two things: a repo with one commit on ``main``,
and a clone of a bare origin that can be driven ahead of its clone (to diverge,
to be refused, or to run out of push attempts). Both builders pin their own git
identity because the suite's autouse conftest clears the author/committer
variables — a commit made without them is a commit git refuses.

Keeping the builders here (a non-test module) leaves the assertions with the
test files that state them.
"""

from __future__ import annotations

from pathlib import Path

from _harness import _git_ok, build_bare_origin


def _repo(tmp_path: Path) -> Path:
    """A git repo with one commit, on main, under tmp_path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_ok(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("test repo\n", encoding="utf-8")
    _git_ok(repo, "add", "README.md")
    _git_ok(repo, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "initial commit")
    return repo


def _commit_files(repo: Path, rev: str = "HEAD") -> list[str]:
    return _git_ok(repo, "show", "--name-only", "--format=", rev).stdout.split()


def _pushable_clone(tmp_path):
    """A clone of a bare origin with one commit pushed, ready to diverge."""
    origin = tmp_path / "origin.git"
    clone = tmp_path / "clone"
    build_bare_origin(origin, [clone])
    return origin, clone


def _seed_ahead(origin: Path, tmp_path: Path, name: str,
                files: dict[str, str]) -> Path:
    """Clone ``origin``, commit ``files`` on main, push; return the working tree.

    The clone names ``main`` on the command line: the suite's sandboxed HOME
    carries no ``init.defaultbranch``, so a plain clone takes git's own default
    (master) and the push of ``main`` then has nothing to push.
    """
    seed = tmp_path / name
    seed.mkdir(parents=True)
    work = seed / "w"
    _git_ok(seed, "clone", "-q", "-b", "main", str(origin), str(work))
    for rel, content in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(content, encoding="utf-8")
        _git_ok(work, "add", rel)
    _git_ok(work, "-c", "user.name=Seeder", "-c", "user.email=seeder@fixture.invalid",
            "commit", "-q", "-m", f"seed: {name}")
    _git_ok(work, "push", "-q", "origin", "main")
    return work
