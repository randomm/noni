"""The trees the quickstart's page describes, built once per session.

The page names four things a reader creates: a clone of this repository, their own
repository, a private state repository with an origin, and a venv holding the
installed package. This module builds them, and owns the preconditions the launches
depend on -- the env nothing ambient reaches, the seed commit that stands in for the
forge, and the install step whose product every page command runs through.

**The install is session-scoped and the scratch is per-test.** The venv install is
the expensive step (a ``python -m venv`` plus a ``pip install`` of the clone), every
page command needs the same installed console script, and the quickstart's test
modules all need a console script of the *same* tree, so the ``installed`` and
``world`` fixtures in ``tests/conftest.py`` build the install once for the session
and hand it to every module under one name -- the pair of module-scoped copies they
used to each declare could drift to two different clones of the same checkout. A test
that *mutates* the trees -- running the page's writers, or a hostile ``PYTHONPATH``
decoy -- takes its own scratch from :func:`fresh_scratch`, which reuses the installed
venv and the materialised clone and builds a new project, origin and seed in a fresh
directory. A shared world handed to two route runs would let the second see the first
one's ledger.

:func:`run_env` is the module's one claim about the launched commands themselves:
the page sells the install as what makes ``noni`` runnable and states its guarantee
as the commands working with ``PYTHONPATH`` unset, so a launch that inherited the
harness's own ``src/`` pin would pass on an environment the reader does not have.
The two additions :func:`install_venv` needs for pip's own sake are applied there,
not here, so nothing the page launches can inherit them.
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

# The branch the fixture's trees start on, when a test does not name one. Named
# here rather than left to git: the suite's sandboxed HOME carries no gitconfig, so
# an unadorned ``init`` falls back to git's own default and a writer's commit lands
# on a branch the origin never had. One owner for the default, because the Route B
# tests read this branch back (``origin/main`` as the upstream, ``main`` on the
# origin) and a test that wants a different one passes ``branch=`` to
# :func:`fresh_scratch` instead of editing this.
DEFAULT_BRANCH = "main"

_GIT_IDENTITY = ("-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
                 "-c", "commit.gpgsign=false")


class World:
    """One scratch set of the trees the page describes, over a shared install.

    Built by :func:`fresh_scratch`: the venv and the clone come from the module's
    :func:`InstalledWorld` and are shared read-only, and everything the page's
    commands write -- the project, the state clone inside it, and the bare origin
    that stands in for the forge -- is created afresh in ``scratch``.
    """

    def __init__(self, scratch: Path, venv: Path, clone: Path) -> None:
        self.env = run_env()
        self.scratch = scratch
        self.clone = clone
        self.venv = venv
        self.noni = venv / "bin" / "noni"
        self.project = scratch / READER_DIR
        self.origin = scratch / "origin"
        self.state = self.project / STATE_DIR
        # Placeholder values a running tree produces (see
        # ``quickstart_runner.substitute``): the id decide printed, read back off
        # the file it wrote, so the page's direction lines name the record that run
        # actually committed.
        self.placeholders: dict[str, str] = {}
        # The same snapshot for the ledger, taken before the page's decide line.
        self._decisions_before: list[str] | None = None
        # The date the page's decide line records under, or None for today. A
        # launch appends it as --date (see ``quickstart_runner.date_arg``); a test
        # that wants a date other than the host's sets it here. It hangs off the
        # world rather than a fixture because the writers run as subprocesses.
        self.decide_date: str | None = None
        # The branch the project, the origin and (by clone) the state tree are on.
        # Read from, never decided here: :func:`fresh_scratch` sets it, and the
        # Route B assertions read it where they used to spell ``main``.
        self.branch: str = DEFAULT_BRANCH

    def mark_decisions(self) -> None:
        """Record the ledger files on disk, just before the decide line runs."""
        directory = self.state / "noni" / "decisions"
        self._decisions_before = sorted(p.name for p in directory.glob("*.json"))

    def collect_record_id(self) -> None:
        """Take the page's ``<record-id>`` from the record the decide line wrote.

        Read from the state
        clone's own ledger, not from stdout and not from a literal: the record the
        ordering line cites is a file whose name carries the date the writer ran,
        so a value the harness invented would name a record no run could have made
        (that is the bug this collector replaces). With a :meth:`mark_decisions`
        snapshot behind it the read is "this run added exactly one", not "a file is
        there", and the stem goes to the placeholder verbatim -- the ordering
        writer accepts only the name the record's own file carries.
        """
        files = sorted((self.state / "noni" / "decisions").glob("*.json"))
        if self._decisions_before is not None:
            assert len(files) == len(self._decisions_before) + 1, (
                "the page's decide line did not add exactly one record file: "
                f"{self._decisions_before} before, {[f.name for f in files]} after")
        assert files, (
            "the page's decide line wrote no record file under the state clone, "
            "so the ordering line that follows cannot name a real record id")
        self.placeholders["<record-id>"] = files[-1].stem


class InstalledWorld:
    """The module's shared install: the venv holding the clone's package."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.clone = root / CLONE_DIR
        self.venv = root / "venv"
        self.noni = self.venv / "bin" / "noni"


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


def init_repo(path: Path, env: dict[str, str], *,
              branch: str = DEFAULT_BRANCH) -> None:
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


def seed_origin(origin: Path, env: dict[str, str],
                branch: str = DEFAULT_BRANCH) -> None:
    """A bare origin holding one empty commit on ``branch``, as the forge would.

    This is the harness standing in for the forge: the page tells the reader to
    create the repository there, and a clone of a truly empty repository has no
    branch at all, so the writers would commit onto a HEAD of the clone's own making
    and the page's first push would have nothing to name. The branch is created by
    the seed's own push with ``-u`` rather than by ``init`` of the bare repository: a
    bare ``init -b`` checks that branch out, and git then refuses a push to the
    branch its own ``HEAD`` names. ``tests/harness_git.py``'s ``build_bare_origin``
    makes the same choice for the same reason. The seed tree is a sibling the caller
    can delete; nothing the page reads lives in it.
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
                                                  "noni.egg-info", "noni_noni.egg-info", ".worktrees"))


def install_venv(installed: InstalledWorld) -> None:
    """The page's install step, run once per module: a venv holding the clone's package.

    The venv and pip themselves are the two steps the suite launches that the page
    only shows as asserted (the page prints `uv tool install` as its primary form and
    this venv pair as its fallback; the launcher compares those fences and never runs
    them -- see :func:`quickstart_runner.install_commands`), so their env carries the
    two additions the install needs and no launch does: this tree's ``src/`` on
    ``PYTHONPATH`` (so the build backend imports from the tree being measured) and
    coverage's hook (so the suite's subprocess coverage
    still fires). :func:`run_env` keeps both out of every launch, which is where the
    page's guarantee lives; nothing added here reaches a page command, and the
    ``noni --help`` that :func:`build_installed_world` runs under the clean env is
    what proves it.
    """
    env = run_env()
    env["PYTHONPATH"] = str(SRC)
    env["COVERAGE_PROCESS_START"] = COVERAGE_PROCESS_START
    checked(subprocess.run([sys.executable, "-m", "venv", str(installed.venv)],
                           capture_output=True, text=True, env=env, timeout=300),
            "python -m venv")
    checked(subprocess.run([str(installed.venv / "bin" / "pip"), "install", "--quiet",
                            "--disable-pip-version-check", str(installed.clone)],
                           capture_output=True, text=True, env=env, timeout=600),
            "pip install of the clone")


def build_installed_world(root: Path) -> InstalledWorld:
    """The module's shared install: the clone materialised, the venv holding it.

    The console script is then run under the *launch* env, which carries no
    ``PYTHONPATH`` at all: a venv whose package came from an inherited path rather
    than from the install would fail here, naming the install rather than a page
    command.
    """
    root.mkdir(parents=True, exist_ok=True)
    installed = InstalledWorld(root)
    materialise_clone(installed.clone)
    install_venv(installed)
    probe = World(root / "probe", installed.venv, installed.clone)
    init_repo(probe.project, probe.env)
    checked(subprocess.run([str(installed.noni), "--help"], capture_output=True,
                           text=True, env=probe.env, timeout=120, cwd=probe.project),
            "noni --help")
    return installed


def fresh_scratch(installed: InstalledWorld, scratch: Path,
                  *, branch: str = DEFAULT_BRANCH) -> World:
    """A per-test set of the mutable trees, over the module's install.

    The project, its state clone and the forge's bare origin are built here, in a
    directory the caller owns and removes: two route runs against one project would
    otherwise see each other's ledger, and the page's own writers are what put it
    there. The venv and the clone are the shared, read-only half.

    ``branch`` is the branch both the project and the forge's repository start on,
    and it is named on every ``init`` rather than left to ``init.defaultbranch``.
    A test that wants the page's first push exercised on a branch other than
    ``main`` -- which is what the page's ``HEAD`` is for -- passes one; the default
    keeps every other walk on the tree the page's prose reads as unremarkable.
    """
    scratch.mkdir(parents=True, exist_ok=True)
    world = World(scratch, installed.venv, installed.clone)
    world.branch = branch
    init_repo(world.project, world.env, branch=branch)
    seed_origin(world.origin, world.env, branch=branch)
    return world
