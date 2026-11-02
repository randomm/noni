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

import os
from pathlib import Path

from _harness import _git_ok, build_bare_origin, build_gone_upstream

from noni import _session_git

# The identity-free environment a refused commit needs: no global config for git
# to read a committer out of, and the PATH the harness pins. One copy here, so
# the writer suites and the classifier suite refuse a commit the same way.
_PATH = os.environ.get("PATH", "/usr/bin:/bin")


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


# --- the private-state route: a project cwd and a relative --repo -----------
#
# The quickstart's alternative state root (docs/PRODUCT.md 7) is a repository
# nested inside the project and git-ignored by it, which a reader names on the
# command line as a relative --repo. Every launcher the suite had built its
# --repo off an absolute tmp_path, so no test ever sent the relative form and
# the route broke unnoticed: the writers handed git a pathspec with the --repo
# component still in it, a path that does not exist inside the state clone.

# Where the nested clone sits, and the name the project ignores for it.
STATE_DIR = "st"
STATE_BODY = ("# session {sid}\n\n- identity: dev\n- host/worktree: host (repo)\n"
              "- started: 2026-10-01T10:00:00Z\n- status: {status}\n- claims:\n"
              "  - claim: #1\n  - claim: #2\n")


def _nested_state(tmp_path: Path, sid: str, *, status: str = "active",
                  name: str = "project", decoy: bool = True,
                  upstream: bool = True) -> tuple[Path, Path, Path]:
    """The private-state route as a reader sets it up: (project, state root, session file).

    The project is a git repository; the state root is a *separate* git
    repository nested inside it and named in the project's ``.gitignore``, which
    is the layout docs/PRODUCT.md 7 sells. It carries one committed session at
    ``status``, holding the two claim rows release.py chooses between.

    ``decoy`` commits a file at the doubled path (``st/noni/sessions/<sid>.md``),
    the path a pathspec that still carries the --repo component names. It is
    committed rather than left untracked so a fix that hands git the doubled
    string cannot pass on a clean tree: such a run either refuses the real path
    or commits the decoy, and the caller's name-set assertion sees which.

    ``upstream`` gives the clone an origin and pushes ``main``, so a refused
    commit is classified by what actually went wrong rather than by the absence
    of an upstream.
    """
    project = tmp_path / name
    project.mkdir(parents=True)
    _git_ok(project, "init", "-q", "-b", "main")
    (project / "README.md").write_text("project\n", encoding="utf-8")
    _git_ok(project, "add", "README.md")
    _git_ok(project, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "initial commit")
    (project / ".gitignore").write_text(f"{STATE_DIR}/\n", encoding="utf-8")
    _git_ok(project, "add", ".gitignore")
    _git_ok(project, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "ignore the state clone")

    state = project / STATE_DIR
    state.mkdir()
    _git_ok(state, "init", "-q", "-b", "main")
    _git_ok(state, "config", "user.name", "Replay")
    _git_ok(state, "config", "user.email", "replay@fixture.invalid")
    session = state / "noni" / "sessions" / f"{sid}.md"
    session.parent.mkdir(parents=True)
    session.write_text(STATE_BODY.format(sid=sid, status=status), encoding="utf-8")
    _git_ok(state, "add", f"noni/sessions/{sid}.md")
    _git_ok(state, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", f"register: {sid}")
    if decoy:
        twin = state / STATE_DIR / "noni" / "sessions" / f"{sid}.md"
        twin.parent.mkdir(parents=True)
        twin.write_text("decoy at the doubled path\n", encoding="utf-8")
        _git_ok(state, "add", f"{STATE_DIR}/noni/sessions/{sid}.md")
        _git_ok(state, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
                "commit", "-q", "-m", f"decoy: {sid}")
    if upstream:
        origin = tmp_path / f"{name}.origin.git"
        origin.mkdir()
        _git_ok(tmp_path, "init", "-q", "--bare", str(origin))
        _git_ok(state, "remote", "add", "origin", str(origin))
        _git_ok(state, "push", "-q", "-u", "origin", "main")
    return project, state, session


def _committed_names(state: Path, rev: str = "HEAD~1..HEAD") -> list[str]:
    """The exact paths one commit moved, read from git rather than from a writer.

    ``diff --name-only`` of the commit range, not ``show``: the assertion this
    serves is the *name set*, and a writer that committed its file and the
    decoy alongside it has to fail it.
    """
    return _git_ok(state, "diff", "--name-only", rev).stdout.split()


# --- the writer-honesty contract on the nested state clone --------------------
#
# AC4 of the relative-repo issue: a writer that does not finish leaves the state
# clone's tracked files byte-identical and its index clean. Measuring that on
# this fixture rather than on a plain repo is the point: on a nested clone a
# pathspec that still carries the --repo component is a *different* tracked path
# (the decoy), so a writer that admitted it would report success and move a path
# nobody named. The snapshot is of the tracked paths only -- an untracked file
# the fixture planted beside them is not the writer's dirt to lose.


def _tracked_bytes(state: Path) -> dict[str, bytes]:
    """Every committed file in ``state`` as ``path -> bytes``, read from git.

    ``ls-tree -r HEAD`` supplies both the membership and the blob ids, so the
    snapshot is the committed content rather than whatever the work tree holds --
    and so a path this run wrote and nobody ever committed is simply not in it.
    The blob id is the whole claim: git will not hand back an id for a path whose
    committed bytes differ, so a run that changed one is reported even when its
    file is gone from the tree again by the time this is read.
    """
    listing = _git_ok(state, "ls-tree", "-r", "--format=%(path) %(objectname)",
                      "HEAD").stdout
    return dict(line.split(" ", 1) for line in listing.splitlines() if line)


def _assert_writer_left_nothing_behind(state: Path, before: dict[str, bytes],
                                      staged: list[str]) -> None:
    """AC4: the committed bytes are unmoved, and the staged set is just ``staged``.

    A refused commit leaves its own path staged by contract (the writer's add
    step ran and its commit did not, and ``stage_and_commit`` never unstages
    somebody else's entry), so "the index is clean" is the wrong promise here.
    What the honesty contract requires is that the staged set is *exactly* the
    one path this run owns: a doubled pathspec stages the decoy too, and a
    writer that admitted it fails here whatever it printed.

    ``staged`` is never empty, and that is a precondition rather than a style
    point: a caller that passed ``[]`` would make the comparison below a test
    that any refusal of a path git never staged passes for free. The committed
    bytes are compared separately because a staged entry and a commit are
    different faults -- the caller pins HEAD too.
    """
    assert staged, "the caller must name the paths this run owns, or measure nothing"
    assert _tracked_bytes(state) == before, (
        "a writer that did not finish changed the state clone's committed bytes"
    )
    actual = _git_ok(state, "diff", "--cached", "--name-only").stdout.split()
    assert actual == staged, (
        f"the run staged {actual}, expected exactly {staged}"
    )


def _strip_identity(state: Path) -> None:
    """Take the clone's own committer identity away, so the commit is refused.

    The refusal the writer suites already use (see ``test_session_close``): it is
    the honest state -- a private state repository prepared on a machine that
    never configured a committer -- and it leaves the run's own path handling as
    the only variable being measured.
    """
    _git_ok(state, "config", "--unset", "user.name")
    _git_ok(state, "config", "--unset", "user.email")
