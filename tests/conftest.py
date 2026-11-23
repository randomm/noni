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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Shared git / script helpers live in _harness.py (not here) so that
# scenario_eval.py — both a test module and a standalone build tool — can
# import them without pulling in this file's module-level pytest import.
from _harness import (
    DECIDE,
    REPO,
    _git_ok,
    build_bare_origin,
    git_pin_date,
    push_with_retry,
    run_decide,
    subprocess_env,
)
from harness_git_containment import assert_own_repo_top

__all__ = [
    "DECIDE",
    "REPO",
    "_git_ok",
    "build_bare_origin",
    "checkout_config_unchanged",
    "config_changed",
    "git_pin_date",
    "push_with_retry",
    "run_decide",
    "shared_git_config_bytes",
    "shared_git_config_path",
    "subprocess_env",
]

# Environment variables the census script or the tests read. Cleared for
# every test; a test that wants one sets it explicitly.
#
# GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE: if the developer's shell has any of
# these set (e.g. from a git worktree or a `git` command that left them
# exported), the census's `git rev-parse --show-toplevel` would resolve to
# the host's repo instead of the test's throwaway repo. Clearing them per test
# makes the census's git resolution deterministic.
#
# HOME: redirected to a sandbox so `git config` lookups and any `~/...`
# resolution in the tests or the census resolve into the sandbox rather than
# the real account.
#
# NONI_SCRUB_DENYLIST: the census's hygiene class runs public_safety's
# tracked-file scan in-process, and that scan reads this variable (and the
# install-root default file) for the deny-list of operator/external names.
# Left set by the developer's shell it would make every census hygiene test
# scan against private vocabulary the fixtures were not written against —
# the same host-dependent-passes-in-CI bug as a hostile HOME. Cleared per test
# like the git vars; a test that wants a deny-list sets it explicitly (or
# monkeypatches public_safety._default_denylist_file).
#
# NONI_SCRUB_ALLOWLIST: the same argument one layer up, and a sharper one. The product
# no longer reads this variable -- the committed allowlist is the only route there is --
# but a value inherited from the developer's shell is still cleared so the inertness
# test below is the only thing that sets it, and nothing about a test's verdict can turn
# on a variable the harness put in the environment.
NONI_ENV_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "NONI_SCRUB_DENYLIST",
    "NONI_SCRUB_ALLOWLIST",
)

# Make the package importable from test files whether or not it was installed:
# src/ is on sys.path via _harness, and no skill scripts/ directory ever goes on
# the path (the wrappers there are shims, and a lookalike earlier on sys.path
# must not be trusted as the census's own code).
#
# The same pin has to reach a *child* process, which is what makes this a conftest
# line rather than a _harness one: the shell wrapper (census.sh)
# resolves noni with the plain interpreter their preamble finds, and a wrapper is a
# child that imports pytest never sees. With the package uninstalled -- the state of
# a plain clone, and of CI before the wheel step -- such a child answered "the noni
# package is not importable" and exited 3, so every test that launches a wrapper
# depended on the host's venv happening to carry an editable install. The inherited
# value is kept and src/ put first, which is the same rule harness_runners pins for
# the python launchers, applied once for the whole session.
_INHERITED_PYTHONPATH = os.environ.get("PYTHONPATH")
os.environ["PYTHONPATH"] = (
    str(REPO / "src") + os.pathsep + _INHERITED_PYTHONPATH
    if _INHERITED_PYTHONPATH else str(REPO / "src"))

# The interpreter the census wrapper execs. census.sh reads
# NONI_PYTHON (defaulting to python3); exporting sys.executable here makes the
# wrapper run the same interpreter pytest itself runs under, which is the one
# coverage's subprocess hook can measure. setdefault, not set: a caller that
# exports its own NONI_PYTHON keeps it, and tests/test_decide_census_sh.py builds
# its own PATH-less env to prove exit 3.
os.environ.setdefault("NONI_PYTHON", sys.executable)

# Clear at import time (conftest is imported before any test module is
# collected), so a variable exported by the developer's shell cannot reach a
# test that does not call a helper. Per-test clearing happens in the autouse
# fixture below.
for _var in NONI_ENV_VARS:
    os.environ.pop(_var, None)


def _git(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run git in a repo with a deterministic identity and no GPG signing.

    Mirrors the _git helper of the driver-side suite it was taken from: passes
    -c user.name / -c user.email / -c commit.gpgsign=false so a throwaway
    repo never inherits the host's git identity or a GPG requirement.

    The target is first checked by :func:`harness_git_containment.assert_own_repo_top`,
    the one choke point issue #220 put in front of every harness ``git -C`` runner: a
    config write against a directory that is not its own repository lands in whatever
    repository encloses it, which is how a fixture's identity came to sit in this
    checkout's shared config.

    ``init`` is the one verb excepted, exactly as in ``harness_git._git``: an
    uninitialised directory is what an init is for, and the callers that init here
    (this module's ``git_repo`` fixture among them) go on to commit, which the guard
    does gate. Leaving ``init`` gated would refuse every legitimate fixture.
    """
    if not (args and args[0] == "init"):
        assert_own_repo_top(repo, env)
    cmd = ["git", "-C", str(repo), "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid", "-c", "commit.gpgsign=false", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)


# --- the session guard over this checkout's own git config -----------------------
#
# ``git -C <dir> config`` walks up when ``<dir>`` is not a repository, so a fixture
# that ran against a plain directory under the checkout wrote its identity into the
# real repository's shared config and every commit made in the checkout and its
# worktrees afterwards was authored by the fixture (issue #220). The runners refuse
# that now; this fixture is what makes the refusal observable rather than trusted.
# It takes the bytes of the checkout's shared ``.git/config`` at session start and
# fails the session if they are not those bytes at teardown -- so a leak that some
# future helper routes around the runners still reddens the run, on the run that
# caused it.
#
# The file is read through ``git rev-parse --git-common-dir`` rather than by joining
# ``<repo>/.git/config``: under a worktree -- which is where the suite really runs,
# in a driver's tree -- ``.git`` is a pointer file and the shared config is the
# checkout's. That is the file the bug wrote into, so that is the file the guard
# digests.
#
# The guard is session-scoped and autouse, so no module opts out and none can forget
# to ask for it. It writes nothing: it reads this repository and compares.


def shared_git_config_path(root: Path = REPO) -> Path:
    """The shared ``.git/config`` of the repository that contains ``root``.

    Resolved, so the comparison is against one file however the path was spelled.
    A repository whose git directory does not exist yet (a tree with no config at
    all) has no bytes, which :func:`shared_git_config_bytes` reports as ``b''``
    rather than raising: the guard still fires when such a tree gains a config.
    """
    shown = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-common-dir"],
                          capture_output=True, text=True, timeout=60)
    assert shown.returncode == 0, (
        f"git could not name the common git directory of {root}: {shown.stderr.strip()}")
    common = Path(shown.stdout.strip())
    if not common.is_absolute():
        common = root / common
    return common.resolve() / "config"


def shared_git_config_bytes(root: Path = REPO) -> bytes:
    """The bytes of that config, or ``b''`` when there is no such file."""
    config = shared_git_config_path(root)
    return b"" if not config.is_file() else config.read_bytes()


def config_changed(before: bytes, after: bytes, config: Path) -> str | None:
    """The one comparison the session guard makes: ``None`` for unchanged.

    Kept apart from the fixture so the pairing test can hand it bytes of its own: a
    guard whose comparison is only ever seen agreeing would pass while blind, and the
    only way to know it is not is to show it reporting a change.
    """
    if before == after:
        return None
    return (f"the suite changed {config} ({len(before)} bytes at session start, "
            f"{len(after)} at teardown). No test may write this repository's git "
            f"config (AGENTS.md: tests that need git settings use a throwaway repo "
            f"under tmp_path). The bytes that differ: "
            f"{_first_diff_line(before, after)}")


def _first_diff_line(before: bytes, after: bytes) -> str:
    """The first line that differs, decoded loosely so the report cannot raise."""
    lines = before.splitlines()
    added = after.splitlines()
    for index in range(max(len(lines), len(added))):
        left = lines[index].decode("utf-8", "replace") if index < len(lines) else "<absent>"
        right = added[index].decode("utf-8", "replace") if index < len(added) else "<absent>"
        if left != right:
            return f"line {index + 1}: {left!r} -> {right!r}"
    return "<no line differs: only the byte encoding does>"


@pytest.fixture(scope="session", autouse=True)
def checkout_config_unchanged():
    """Fail the session if this run wrote the real checkout's ``.git/config``.

    The digest is taken before any test runs and compared after the last one, so a
    leak is reported by the run that made it rather than by whoever notices the
    author of their commits eight hundred commits later. It reads the checkout and
    writes nothing; the file it names is the operator's to repair, not the suite's.
    """
    config = shared_git_config_path()
    before = shared_git_config_bytes()
    yield
    problem = config_changed(before, shared_git_config_bytes(), config)
    assert problem is None, problem


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


# The allowlist tests are split across four modules (the 500-line cap, with the seam at
# what an entry exempts / what a stale entry earns / what a refused file does / what the
# CLI exits with) and all four run over one throwaway tree. Its builder lives in
# tests/allowlist_tree.py so the fixture has one owner; re-exported here because conftest
# is the only module pytest collects fixtures from outside a test file -- the same shape
# the quickstart topology fixtures below use.
from allowlist_tree import clean_repo  # noqa: E402,F401  (a re-exported fixture)


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
    """Run the ledger wrapper over a ledger dir, returning (exit, stdout, stderr).

    Shared by every test module so the subprocess invocation logic lives in one
    place. The wrapper is a thin route to the unified census, so this is the
    entry point that answers for both: the census's own flags are accepted and
    reach the census unchanged, and the exit code is the census's. Pass a custom
    env dict to override PATH or other variables, and ``extra`` for census flags
    (``--json`` for the machine rows, ``--strict`` to promote the warns).
    """
    def _run(ledger_dir: Path, *, env: dict | None = None,
             extra: tuple[str, ...] = ()) -> tuple[int, str, str]:
        full_env = subprocess_env()
        if env:
            full_env.update(env)
        proc = subprocess.run(
            ["bash", str(REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"),
             str(ledger_dir), *extra],
            capture_output=True,
            text=True,
            env=full_env,
            timeout=60,
        )
        return proc.returncode, proc.stdout, proc.stderr
    return _run


# --- the quickstart harness's shared topology --------------------------------
#
# Both quickstart test modules (tests/test_quickstart.py and
# tests/test_quickstart_hygiene.py) launch the page's commands, and each used to
# declare its own module-scoped copy of these two fixtures: two venv installs of the
# same checkout per run, free to drift apart in their teardown (one removed its
# root, the other forgot to). They live here at session scope, because the install is
# the expensive step and every module needs a console script of the *same* tree; the
# bodies stay in tests/quickstart_topology.py, which owns how the trees are built.
# conftest.py is the only module pytest collects fixtures from outside a test file,
# so this is the one place the pair can have a single owner.


@pytest.fixture(scope="session")
def installed(tmp_path_factory):
    """The session's one venv install of the materialised clone, for every launch.

    The install is the page's own step and every quickstart command needs its console
    script, so it runs once for the session; the trees a test mutates come from
    :func:`world` and are per-test. The directory is removed on teardown -- /tmp is
    tmpfs here, and an installed venv left behind is not scratch, it is a leak.
    """
    from quickstart_topology import build_installed_world

    root = tmp_path_factory.mktemp("quickstart-install")
    try:
        yield build_installed_world(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def world(installed, tmp_path):
    """One scratch set of the page's trees, over the session's install."""
    from quickstart_topology import fresh_scratch

    return fresh_scratch(installed, tmp_path / "scratch")
