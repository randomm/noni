"""The trees the quickstart's page describes, built once per test.

The page names four things a reader creates: a clone of this repository, their own
repository, a private state repository with an origin, and a venv holding the
installed package. This module builds them, and owns the preconditions the
launcher's measurements depend on -- the env nothing ambient reaches, the seed
commit that stands in for the forge, and the install step whose product every page
command runs through.

:func:`run_env` is the module's one claim about the launched commands themselves:
the page sells the install as what makes ``noni`` runnable and states its guarantee
as the commands working with ``PYTHONPATH`` unset, so a launch that inherited the
harness's own ``src/`` pin would pass on an environment the reader does not have.
The two additions :func:`make_venv` needs for pip's own sake are applied there, not
here, so nothing the page launches can inherit them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from _harness import REPO, subprocess_env
from conftest import NONI_ENV_VARS
from docs_promises import STATE_DIR
from harness_paths import COVERAGE_PROCESS_START, SRC

# What a page launch may not inherit: the harness's ``PYTHONPATH`` pin and
# coverage's subprocess hook. One explicit set, used by the one helper that builds
# a page env, so the strip has an owner and a reader, and cannot be undone by a
# filter that forgot a name. The coverage variables go because a measured child
# writes a data file (see [tool.coverage.run] in pyproject.toml), and a stray file
# in the reader's tree is one more thing a page that promises not to write left
# behind.
AMBIENT_LAUNCH_VARS: frozenset[str] = frozenset(
    {"PYTHONPATH", "COVERAGE_PROCESS_START", "COVERAGE_FILE"})

# The clone directory the page's install commands name, and the placeholder it
# clones from. The clone is materialised rather than fetched (the same choice
# ``readme_support._materialise_clone`` makes), so the URL can stay a placeholder
# and the run stays offline.
CLONE_DIR = "noni"
CLONE_URL = "github.com/OWNER/noni"

# The reader's own repository, as the page names it. Like the README harness's
# placeholder for the reader's tree, the harness supplies the real directory.
READER_DIR = "your-project"

_GIT_IDENTITY = ("-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
                 "-c", "commit.gpgsign=false")


class World:
    """The trees the page describes: the clone, the project, and the origin."""

    def __init__(self, tmp_path: Path) -> None:
        self.env = run_env()
        self.clone = tmp_path / CLONE_DIR
        self.project = tmp_path / READER_DIR
        self.origin = tmp_path / "origin"
        self.state = self.project / STATE_DIR
        self.venv = tmp_path / "venv"
        self.noni = self.venv / "bin" / "noni"
        # Placeholder values a running tree produces (see
        # ``quickstart_runner.substitute``): the id register printed, read back off
        # the file it wrote, so the page's claim line names the session the register
        # line actually allocated.
        self.placeholders: dict[str, str] = {}
        # The session files on disk before the page's register line ran, so the
        # collector can require that line to have added exactly one.
        self._sessions_before: list[str] | None = None

    def mark_sessions(self) -> None:
        """Record the session files on disk, just before the register line runs."""
        directory = self.state / "noni" / "sessions"
        self._sessions_before = sorted(p.name for p in directory.glob("*.md"))

    def collect_session_id(self) -> None:
        """Take the page's ``<session-id>`` from the register file on disk.

        Read from the state clone's own sessions directory, not from stdout: the
        value the next page command must carry is the file the writer committed, and
        reading it back proves that file exists where ``--repo`` points. With a
        :meth:`mark_sessions` snapshot behind it the read is stronger than "a file
        is there": the register line must have added exactly one, so the id the claim
        line carries is the one that run allocated.
        """
        files = sorted((self.state / "noni" / "sessions").glob("*.md"))
        if self._sessions_before is not None:
            assert len(files) == len(self._sessions_before) + 1, (
                "the page's register line did not add exactly one session file: "
                f"{self._sessions_before} before, {[f.name for f in files]} after")
        assert files, (
            "the page's register line wrote no session file under the state clone, "
            "so the claim line that follows cannot name a real session id")
        self.placeholders["<session-id>"] = files[-1].stem


def run_env() -> dict[str, str]:
    """An env with nothing ambient: no inherited git location, identity, path or deny-list.

    Built from a filtered mapping rather than ``os.environ`` for the same reason
    ``readme_support._reader_env`` builds it that way: the page's commands commit, so
    anything git inherits decides which tree they act on and who authors it. The two
    host config files are pinned to the null device, and bytecode caching is off
    because the census loads its siblings in-process -- without it the page's
    read-only promise would be false in the reader's tree.

    What is dropped is the shared ambient list plus :data:`AMBIENT_LAUNCH_VARS`: one
    filter over one explicit set, no pin-then-pop, so nothing the launcher wanted
    clean can come back through a later line.
    """
    drop = frozenset(NONI_ENV_VARS) | AMBIENT_LAUNCH_VARS
    env = {k: v for k, v in subprocess_env().items() if k not in drop}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def checked(proc: subprocess.CompletedProcess[str], what: str) -> None:
    """One harness step that must succeed, with both streams in the failure text."""
    assert proc.returncode == 0, (
        f"{what} failed ({proc.returncode})\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )


def git(repo: Path, *args: str, env: dict[str, str],
        identity: bool = False) -> subprocess.CompletedProcess[str]:
    """One git command, with its output kept for the assertion messages.

    ``identity`` adds the harness's ``-c`` identity, for the trees the page does not
    ask the reader to configure (the seed commit that stands in for the forge). The
    page's own commands run without it: they set their identity with the config lines
    the page prints, and a harness identity would hide a page that forgot to set one.
    """
    args = (*_GIT_IDENTITY, *args) if identity else args
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, env=env, timeout=120)


def init_repo(path: Path, env: dict[str, str], *, branch: str = "main") -> None:
    """``git init -b <branch>`` in a tree that does not exist yet.

    ``git -C`` refuses to enter a missing directory, so the tree is made first. The
    branch is named on the command line, not left to ``init.defaultbranch``: the
    suite's sandboxed HOME carries no gitconfig, so an unadorned ``init`` falls back
    to git's own default and a writer's commit lands on a branch origin never had
    (the reason ``tests/harness_git.build_bare_origin`` names ``-b main`` too).
    """
    path.mkdir(parents=True, exist_ok=True)
    checked(git(path, "init", "-q", "-b", branch, env=env), f"git init {path.name}")


def init_bare(path: Path, env: dict[str, str], branch: str) -> None:
    """A bare repository whose ``HEAD`` names ``branch``.

    The branch is named on ``init`` so the repository's own ``HEAD`` points at it: a
    clone takes its branch from the origin's ``HEAD``, and a bare repository whose
    ``HEAD`` names nothing comes back with no branch at all. No commit is ever made
    in this tree, so nothing pushes to its current branch.
    """
    path.mkdir(parents=True, exist_ok=True)
    checked(git(path, "init", "-q", "--bare", "-b", branch, env=env),
            f"git init --bare {path.name}")


def seed_origin(origin: Path, env: dict[str, str], branch: str = "main") -> None:
    """A bare origin holding one empty commit on ``branch``, as the forge would.

    This is the harness standing in for the forge: the page tells the reader to
    create the repository there, and a clone of a truly empty repository has no
    branch at all, so the writers would commit onto a HEAD of the clone's own making
    and the page's first push would have nothing to name. The branch is created by
    the seed's own push with ``-u`` rather than by ``init`` of the bare repository: a
    bare ``init -b`` checks that branch out, and git then refuses a push to the
    branch its own ``HEAD`` names. ``tests/harness_git.py``'s ``build_bare_origin``
    makes the same choice for the same reason.
    """
    init_bare(origin, env, branch)
    seed = origin.parent / "seed"
    init_repo(seed, env, branch=branch)
    checked(git(seed, "commit", "-q", "--allow-empty", "-m", "first", env=env,
                identity=True), "seed commit")
    checked(git(seed, "remote", "add", "origin", str(origin), env=env), "seed remote")
    checked(git(seed, "push", "-q", "-u", "origin", branch, env=env), "seed push")


def materialise_clone(dest: Path) -> None:
    """The noni clone the page's ``git clone`` produces: this tree's content."""
    shutil.copytree(REPO, dest, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv",
                                                  "*.pyc", ".pytest_cache",
                                                  ".coverage", ".coverage.*",
                                                  "noni.egg-info", ".worktrees"))


def make_venv(world: World) -> None:
    """The page's install step, run once: a venv holding the clone's package.

    The venv and pip themselves are the two steps the suite launches that are not a
    command on the page (the page's reader gets a working pip from their own
    machine), so their env carries the two additions the install needs and no launch
    does: this tree's ``src/`` on ``PYTHONPATH`` (so the build backend imports from
    the tree being measured) and coverage's hook (so the suite's subprocess coverage
    still fires). :func:`run_env` keeps both out of every launch, which is where the
    page's guarantee lives; nothing added here reaches a page command, and the
    ``noni --help`` that ``build_world`` runs under the clean env is what proves it.
    """
    env = dict(world.env)
    env["PYTHONPATH"] = str(SRC)
    env["COVERAGE_PROCESS_START"] = COVERAGE_PROCESS_START
    checked(subprocess.run([sys.executable, "-m", "venv", str(world.venv)],
                           capture_output=True, text=True, env=env, timeout=300),
            "python -m venv")
    checked(subprocess.run([str(world.venv / "bin" / "pip"), "install", "--quiet",
                            "--disable-pip-version-check", str(world.clone)],
                           capture_output=True, text=True, env=env, timeout=600),
            "pip install of the clone")


def build_world(tmp_path: Path) -> World:
    """The page's topology, standing and installed: clone, project, state origin.

    The install step runs here rather than in one test because every command the page
    prints needs the same installed console script, and a per-test install would
    measure pip rather than the page several times over.
    """
    world = World(tmp_path)
    materialise_clone(world.clone)
    init_repo(world.project, world.env)
    seed_origin(world.origin, world.env)
    make_venv(world)
    # The proof that the install was the real thing: the console script the install
    # step produced runs under the *launch* env, which carries no PYTHONPATH at all.
    # A venv whose package came from an inherited path rather than from the install
    # would fail here, naming the install rather than a page command.
    checked(subprocess.run([str(world.noni), "--help"], capture_output=True, text=True,
                           env=world.env, timeout=120, cwd=world.project),
            "noni --help")
    return world
