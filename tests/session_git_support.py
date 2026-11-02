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

from _harness import _git_ok, build_bare_origin, build_gone_upstream

from noni import _session_git


def _tracked_session(repo: Path) -> Path:
    """One committed session file under ``repo``, at a fixed path.

    Committed through the primitive itself, which is the point: the cause tests
    ask what the primitive says about the state this helper built, so a baseline
    that did not land must fail here and not silently become a 'nothing to
    commit' the tree never had.
    """
    target = repo / "noni" / "sessions" / "2026-10-01-dddddd.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("- status: active\n", encoding="utf-8")
    ok, why = _session_git.stage_and_commit(repo, target, "register: d")
    if not ok:
        raise AssertionError(f"the fixture could not commit its baseline: {why}")
    shown = _git_ok(repo, "rev-list", "--count", "HEAD").stdout.strip()
    if shown == "0":
        raise AssertionError("the fixture's baseline commit is not on HEAD")
    return target


def _repo(tmp_path: Path, *, isolated: bool = True) -> Path:
    """A git repo with one commit, on main, under tmp_path.

    ``isolated`` decides whether the tree also carries its own committer
    identity in its ``.git/config``. It defaults to True because the suite's
    autouse fixture clears ``GIT_AUTHOR_*`` / ``GIT_COMMITTER_*`` and pins
    ``HOME`` to an empty directory, so a tree that did not name a committer is a
    tree whose commits git refuses ('Author identity unknown') -- and a test
    that wants a refusal of its own would then be observing that one instead of
    the state it set up. A caller that means to drive a git-level refusal builds
    the tree with ``isolated=False`` and supplies the identity itself.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_ok(repo, "init", "-q", "-b", "main")
    if isolated:
        _git_ok(repo, "config", "user.name", "Replay")
        _git_ok(repo, "config", "user.email", "replay@fixture.invalid")
    (repo / "README.md").write_text("test repo\n", encoding="utf-8")
    _git_ok(repo, "add", "README.md")
    _git_ok(repo, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "initial commit")
    return repo


def _commit_files(repo: Path, rev: str = "HEAD") -> list[str]:
    return _git_ok(repo, "show", "--name-only", "--format=", rev).stdout.split()


def _pushable_clone(tmp_path, name="clone"):
    """A clone of a bare origin with one commit pushed, ready to diverge.

    ``name`` lets one test build several clones under one ``tmp_path`` without
    the second iteration writing into the first one's tree.
    """
    origin = tmp_path / f"{name}.origin.git"
    clone = tmp_path / name
    build_bare_origin(origin, [clone])
    return origin, clone


def _gone_upstream_clone(tmp_path, name="gone-clone"):
    """A clone whose upstream branch origin deleted (see build_gone_upstream).

    The half-applied writer path is unreachable any other way: every other
    builder here pushes ``main`` and leaves it in place. The helper asserts its
    own precondition, so a fixture that built the wrong state fails here rather
    than driving a commit that succeeds.
    """
    origin = tmp_path / f"{name}.origin.git"
    clone = tmp_path / name
    build_gone_upstream(origin, [clone])
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
