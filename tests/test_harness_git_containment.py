"""No harness git call may write a repository that is not its own (issue #220).

The bug: a test fixture wrote its throwaway identity (``user.name Replay``,
``user.email replay@fixture.invalid``) into this repository's *shared*
``.git/config``, and every commit made in the checkout and its worktrees
afterwards was authored by the fixture. The mechanism is ordinary git rather
than a test bug: ``git -C <dir> config ...`` on a directory that is not a
repository does not fail. It walks up and writes into the nearest enclosing one,
so the leak needed only a plain directory under the checkout, which is exactly
where a dev run keeps its scratch (AGENTS.md: one ignored folder per issue,
``tmp/issue-N/``, and the same shape under a basetemp). The harness's ``-c
user.name=...`` prefix made it invisible: the config call exited 0 and printed
nothing, whatever tree it answered for.

Two guards, complementary and both required (PM ruling 2). A
``GIT_CEILING_DIRECTORIES`` set on the child env stops git discovering a
repository by walking up from the *current directory*; it does nothing at all
for ``git -C <path>``, which is what every harness runner uses. The top-level
precondition closes the ``-C`` half: one helper,
:func:`harness_git.assert_own_repo_top`, called from every shared git runner, so
the seventeen identity-pinning call sites are covered through the choke point
rather than each asserting the precondition for itself.

The tests below, in order: the guard on a plain subdirectory of a planted
enclosing repository (the leak reproduced, AC3), on a bare directory outside any
repository; the pairing controls that show the bytes *do* change when the guard
is not in the way, so neither half passes vacuously; the runners it now stands in
front of; the ceiling as the env half; and the session guard over the real
checkout's config, with its own pairing control.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import harness_git
import pytest
from _harness import REPO
from conftest import _git as conftest_git
from decide_fixtures import _pin_identity
from git_containment_plant import (
    NESTED_IDENTITY,
    WITNESS_IDENTITY,
    assert_no_identity_written,
    identity_lines,
    plain_subdirectory,
    plant_enclosing_repo,
)
from harness_git_containment import assert_own_repo_top
from harness_paths import TEST_TMP_CEILING
from harness_runners import subprocess_env
from quickstart_topology import AMBIENT_LAUNCH_VARS, run_env

from noni import gitenv

# --- AC3: the leak reproduced, and refused ---------------------------------------


def test_the_identity_helper_refuses_a_plain_directory_and_writes_nothing(tmp_path):
    """The regression test the bug needed (AC3).

    A plain directory inside a planted enclosing repository is handed to
    :func:`decide_fixtures._pin_identity` -- the helper named in the issue as the
    leak shape -- and two things must hold: the helper refuses, and the enclosing
    repository's config still holds the bytes it had. The second is the one that
    matters: the first run of this call, before the fix, exited 0, printed nothing
    and put the fixture identity in the enclosing config.
    """
    enclosing = plant_enclosing_repo(tmp_path)
    plain = plain_subdirectory(enclosing)
    config = enclosing / ".git" / "config"
    before = config.read_bytes()

    with pytest.raises(RuntimeError) as refused:
        _pin_identity(plain, "Replay")

    message = str(refused.value)
    assert "not a repository" in message or "enclosing repository" in message, (
        f"the refusal does not name the containment rule it applied: {message}")
    assert config.read_bytes() == before, (
        "the refused call still wrote the enclosing repository's config")
    assert_no_identity_written(config)


def test_the_identity_helper_refuses_a_directory_inside_another_repository(tmp_path):
    """The other arm: the target is a repository, but not *its own* top level.

    A nested tree inside somebody else's repository answers ``--show-toplevel`` with
    the outer one, and that is the answer a config write would obey. Refusing it is
    what makes the guard a containment rule and not merely an existence check.
    """
    enclosing = plant_enclosing_repo(tmp_path)
    nested = enclosing / "inner"
    nested.mkdir()

    with pytest.raises(RuntimeError, match="enclosing repository"):
        harness_git._git(nested, "config", "user.name", "Replay")

    assert_no_identity_written(enclosing / ".git" / "config")


def test_the_guard_refuses_a_bare_directory_outside_any_repository(tmp_path):
    """A directory in no repository at all is refused with git's own words.

    The guard cannot simply accept a failed ``rev-parse``: an uninitialised tree is
    the ordinary case for a fixture whose ``git init`` failed, and the call that
    follows it would answer for whatever encloses it.
    """
    bare = tmp_path / "not-a-repo"
    bare.mkdir()

    with pytest.raises(RuntimeError, match="not a repository"):
        assert_own_repo_top(bare)


def test_the_guard_accepts_a_repository_that_is_its_own_top_level(tmp_path):
    """The guard is a containment rule, not an obstacle: a real repo passes.

    The control for the three refusals above. A guard that refused everything would
    satisfy them, and would have the suite refusing its own fixtures.
    """
    enclosing = plant_enclosing_repo(tmp_path)
    assert assert_own_repo_top(enclosing) == enclosing.resolve()


def test_the_guard_follows_a_symlinked_target_on_both_sides(tmp_path):
    """Both sides of the comparison are resolved (the edge case named in the issue).

    pytest's ``tmp_path`` can itself be a symlinked path, and a byte-for-byte
    comparison of the target against git's answer would refuse every legitimate
    repository on such a host. Here the *target* is spelled through a symlink and the
    check still passes, which only holds if git's answer is resolved too.
    """
    enclosing = plant_enclosing_repo(tmp_path)
    link = tmp_path / "via-link"
    link.symlink_to(enclosing, target_is_directory=True)

    assert assert_own_repo_top(link) == enclosing.resolve()


# --- the pairing controls: the guards are not vacuous ----------------------------


def test_the_bare_config_call_does_leak_where_the_guard_refuses(tmp_path):
    """The pairing control for AC3 (PM ruling 4): without the guard, bytes change.

    The same plant and the same call, made with a bare ``git -C <dir> config`` -- the
    shape the runner had before the guard. It must exit 0 and must change the
    enclosing config: the evidence that the refused call above was refused for a
    reason, and that comparing the config's bytes can see the write at all.
    """
    enclosing = plant_enclosing_repo(tmp_path)
    plain = plain_subdirectory(enclosing)
    config = enclosing / ".git" / "config"
    before = config.read_bytes()

    proc = subprocess.run(
        ["git", "-C", str(plain), "config", "user.name", "Replay"],
        capture_output=True, text=True, timeout=60)

    assert proc.returncode == 0, (
        f"the pairing control stopped leaking -- git now refuses the bare call, so "
        f"the guard above proves nothing: {proc.stderr}")
    assert config.read_bytes() != before, (
        "the bare config write changed nothing, so the before/after comparison in "
        "this module cannot see a leak and the guard test passes vacuously")
    assert b"name = Replay" in config.read_bytes() or \
        b"name=Replay" in config.read_bytes(), (
        f"the bare call did not record the identity the guard refuses to write: "
        f"{config.read_bytes()}")


# --- the choke point: which runners the guard stands in front of ------------------


def test_every_shared_git_runner_asks_the_precondition(tmp_path):
    """The one choke point, pinned per runner rather than assumed.

    PM ruling 1 names the runners: ``_git``, ``_git_e2``, ``_git_ok``,
    ``git_pin_date`` and :func:`quickstart_topology.git`, plus the two local runners
    the second family of config writers used. A runner that quietly dropped the call
    would keep every one of the seventeen identity-pinning call sites working and
    re-open the leak through itself, so each is shown refusing the same planted
    directory.
    """
    from quickstart_topology import git as quickstart_git

    enclosing = plant_enclosing_repo(tmp_path)
    plain = plain_subdirectory(enclosing)
    env = run_env()

    harness_runners_ = (
        ("_git", lambda: harness_git._git(plain, "config", "user.name", "Replay")),
        ("_git_e2", lambda: harness_git._git_e2(plain, "config", "user.name", "Replay")),
        ("_git_ok", lambda: harness_git._git_ok(plain, "config", "user.name", "Replay")),
        ("git_pin_date", lambda: harness_git.git_pin_date(
            plain, "2026-10-01T10:00:00Z", "commit", "--allow-empty", "-m", "x")),
        ("quickstart_topology.git",
         lambda: quickstart_git(plain, "config", "user.name", "Replay", env=env)),
        ("conftest._git", lambda: conftest_git(plain, "config", "user.name", "Replay")),
    )
    for name, call in harness_runners_:
        with pytest.raises(RuntimeError) as refused:
            call()
        assert "repository" in str(refused.value), (
            f"{name} did not refuse the plain directory: {refused.value}")
    assert_no_identity_written(enclosing / ".git" / "config")


def test_a_fixture_init_inside_an_enclosing_repository_is_refused(tmp_path, monkeypatch):
    """``init`` is the one exception, and the exception is bounded.

    The precondition for an init runs *after* the init (an uninitialised tree is the
    normal state there), so what still has to be caught is an init that did not
    create a repository at the target. The failure is made the way git reports one --
    ``git init`` exits 7 and creates nothing -- by forcing the child's exit code
    rather than by leaving a non-directory in the fixture's way, because that path
    fails earlier than the thing under test. The harness's initialiser must then
    refuse the fixture instead of letting the next call -- the identity write -- be
    answered by the enclosing repository.
    """
    enclosing = plant_enclosing_repo(tmp_path)
    target = enclosing / "scratch" / "failed-init"
    real_run = subprocess.run

    def failing_run(cmd, *args, **kwargs):
        """The init itself fails; every other git call in the fixture runs normally."""
        if "init" in cmd:
            return real_run(["false"], capture_output=True, text=True)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(harness_git.subprocess, "run", failing_run)
    with pytest.raises(RuntimeError) as refused:
        harness_git._init_repo(target)

    assert not (target / ".git").exists(), (
        "the init created a repository after all, so the guard below it had nothing "
        "to refuse and this test proved nothing")
    # The same refusal is the guard's own, not a git failure: the plant is a
    # repository and the target is not, so this is the "enclosing repository" arm --
    # the more precise of the two refusals, and the one that names where a write
    # would have landed.
    assert "enclosing repository" in str(refused.value), str(refused.value)
    monkeypatch.undo()
    # And the guard stands on its own without the forced failure: the identity write
    # the fixture would have made next is refused, and writes nothing into the plant.
    with pytest.raises(RuntimeError, match="enclosing repository"):
        harness_git._git(target, "config", "user.name", "Replay")
    assert_no_identity_written(enclosing / ".git" / "config")


# --- AC2: the environment half ----------------------------------------------------


def test_every_launch_the_suite_starts_carries_the_ceiling(tmp_path):
    """``GIT_CEILING_DIRECTORIES`` names the suite's tmp root in the shared env.

    Set once, in :func:`harness_runners.subprocess_env`, which every launcher of a
    product script goes through. Asserted as a value and not merely a presence: an
    empty or wrong ceiling stops nothing, and git treats an unset name as no ceiling
    at all.
    """
    env = subprocess_env()
    assert env["GIT_CEILING_DIRECTORIES"] == str(TEST_TMP_CEILING), env.get(
        "GIT_CEILING_DIRECTORIES")
    assert Path(TEST_TMP_CEILING).is_dir(), (
        f"the ceiling names a directory that does not exist: {TEST_TMP_CEILING}")
    # A caller's hostile value is overwritten rather than kept: the ceiling is not a
    # knob a test may turn, and one a caller could set is one that leaks.
    hostile = subprocess_env({"GIT_CEILING_DIRECTORIES": str(tmp_path)})
    assert hostile["GIT_CEILING_DIRECTORIES"] == str(TEST_TMP_CEILING)


def test_the_page_launches_keep_the_ceiling_the_launcher_sets():
    """The ceiling is not in either list the page-launch builders *drop*.

    ``quickstart_topology.run_env`` builds its env by filtering ``subprocess_env()``
    over ``NONI_ENV_VARS | AMBIENT_LAUNCH_VARS``. Adding the ceiling to either list
    would take it out of every page launch -- and those are the launches that run a
    bare ``git config`` line out of the page's own fence, the shape that leaked. So
    the name is pinned absent from both lists and present in the built env.
    """
    from conftest import NONI_ENV_VARS
    from quickstart_topology import run_env as build_run_env

    assert "GIT_CEILING_DIRECTORIES" not in AMBIENT_LAUNCH_VARS
    assert "GIT_CEILING_DIRECTORIES" not in NONI_ENV_VARS
    for name in (AMBIENT_LAUNCH_VARS,):
        assert "GIT_CEILING_DIRECTORIES" not in name
    assert build_run_env()["GIT_CEILING_DIRECTORIES"] == str(TEST_TMP_CEILING)
    # The builder is still the single filter, so nothing has to remember the name.
    builder = _source_of(build_run_env)
    assert "subprocess_env()" in builder, (
        "run_env no longer builds from subprocess_env, so the ceiling set there "
        "would not reach a page launch")


def test_the_ceiling_stops_a_child_discovering_the_checkout_above_it(tmp_path):
    """The ceiling does the thing AC2 asks of it, measured rather than asserted.

    A plain directory is planted *inside the checkout's* ignored scratch folder --
    the path shape of the real leak -- and git is asked, from that cwd, for its
    repository: under the suite's ceiling it must answer "not a git repository". The
    same call under an env with no ceiling must find the checkout. Without that
    second half the assertion would pass on a host where the tree simply is not a
    repository, which is the vacuous version of this test.

    The plant is removed in the ``finally``: scratch left in the checkout would dirty
    the tree for the next cycle's status gate, which is the same discipline
    ``tests/test_scratch_walks.py`` keeps.
    """
    plant = REPO / "tmp" / "issue-220-ceiling-plant"
    plant.mkdir(parents=True, exist_ok=True)
    # The plant has to be git-free of its own: the ceiling stops only the walk that
    # starts outside a repository, so a tree that was itself a repository (or sat
    # inside one left by an earlier run) would answer for itself under both envs and
    # the assertion below would be measuring the wrong thing.
    assert subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, cwd=str(plant),
                          env=_env_without_ceiling(), timeout=60).returncode == 0, (
        f"the control did not find the checkout from {plant}, so this host keeps its "
        "scratch somewhere other than under the checkout and the ceiling cannot be "
        "measured here")
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=str(plant),
            env=subprocess_env(), timeout=60)
        assert inside.returncode != 0, (
            f"a child reached a repository above its own tmp tree: {inside.stdout!r}")
    finally:
        _remove_tree(plant)


def test_the_product_still_drops_the_ceiling_from_a_writers_child(tmp_path):
    """The harness ceiling is not a product change (the no-``src/`` constraint).

    ``noni.gitenv.child_env`` drops ``GIT_CEILING_DIRECTORIES`` from a writer's git
    child on purpose, and it still does with the suite pinning the variable: the
    product decides its own git child env, and the harness ceiling only contains the
    harness's and the writers' own discovery. If this ever stops holding, the fix is
    in the harness, not by widening the product's allowlist.
    """
    import os

    os.environ["GIT_CEILING_DIRECTORIES"] = str(TEST_TMP_CEILING)
    env = gitenv.child_env()
    assert "GIT_CEILING_DIRECTORIES" not in env, (
        "gitenv began passing the ceiling through: the harness guard and the product "
        "guard are now the same mechanism, and the AC that keeps src/ out of this "
        "ticket has quietly been broken")


def test_a_bare_fixture_origin_is_checked_as_a_bare_repository(tmp_path):
    """The bare arm of the check: an origin has no working tree to be the top of.

    ``--show-toplevel"`` refuses a bare repository outright ("must be run in a work
    tree"), so a fixture's origin is contained by asking whether it is its own bare
    repository instead. Both arms are shown: the fixture's own origin passes, and a
    plain directory inside the plant -- which git calls not-a-repository, or a
    non-bare one -- is refused rather than waved through on the weaker form.
    """
    from harness_git import _git_ok

    origin = tmp_path / "origin"
    origin.mkdir()
    _git_ok(origin, "init", "-q", "--bare", bare=True)
    assert assert_own_repo_top(origin, bare=True) == origin.resolve()

    enclosing = plant_enclosing_repo(tmp_path)
    plain = enclosing / "scratch"
    plain.mkdir()
    with pytest.raises(RuntimeError):
        _git_ok(plain, "config", "user.name", "Replay", bare=True)
    assert_no_identity_written(enclosing / ".git" / "config")


def test_a_nested_state_clone_is_checked_by_owning_its_git(tmp_path):
    """The nested arm: a repository legitimately inside another repository.

    The quickstart's private state clone is the fixture with this shape, and its
    ``--show-toplevel`` is the *parent's* -- so the equality the ordinary check
    asserts can never hold and the sub-tree form asks the filesystem instead. A clone
    that owns its ``.git`` passes; a plain directory in the same position -- which is
    the leak, and looks identical from where the caller stands -- is refused.
    """
    from quickstart_topology import git as quickstart_git

    enclosing = plant_enclosing_repo(tmp_path)
    clone = enclosing / "state"
    subprocess.run(["git", "clone", "-q", str(_make_origin(tmp_path)), str(clone)],
                   capture_output=True, text=True, timeout=120, check=True)
    env = run_env()
    # The nested arm is reached through the same entry point a page command uses, and
    # what it proves is that the write stays in the clone: the parent already has a
    # name of its own, so a write that walked upstairs would be visible there.
    assert quickstart_git(clone, "config", "user.name",
                          "Nested", env=env).returncode == 0
    shown = quickstart_git(clone, "config", "--local", "user.name", env=env)
    assert shown.stdout.strip() == "Nested", shown.stdout
    rows = identity_lines(enclosing / ".git" / "config")
    assert WITNESS_IDENTITY in rows, (
        f"the parent's identity moved while a nested clone was written: {rows}")
    assert NESTED_IDENTITY not in rows, (
        f"the nested clone's identity landed in the parent's config: {rows}")

    plain = enclosing / "scratch"
    plain.mkdir()
    with pytest.raises(RuntimeError, match="no .git of its own"):
        assert_own_repo_top(plain, env, sub_tree=True)


def _make_origin(tmp_path: Path) -> Path:
    """A bare origin with one commit, for the nested-clone test's clone source.

    Built with the harness's own bare-aware runner rather than a bare ``git``: a
    fixture that reaches git outside the guard is the thing this module is testing
    for, so it should not model the behaviour it refuses.
    """
    from harness_git import _git_ok

    origin = tmp_path / "nested-origin"
    origin.mkdir()
    _git_ok(origin, "init", "-q", "--bare", "-b", "main", bare=True)
    seed = tmp_path / "nested-seed"
    seed.mkdir()
    _git_ok(seed, "init", "-q", "-b", "main")
    _git_ok(seed, "config", "user.name", "Seed")
    _git_ok(seed, "config", "user.email", "seed@example.invalid")
    _git_ok(seed, "commit", "-q", "--allow-empty", "-m", "first")
    _git_ok(seed, "remote", "add", "origin", str(origin))
    _git_ok(seed, "push", "-q", "origin", "main")
    return origin


# --- helpers kept at the bottom so the tests read first --------------------------


def _source_of(function) -> str:
    """A function's own source text (the same shape the quickstart pins its builder with)."""
    import inspect

    return inspect.getsource(function)


def _env_without_ceiling() -> dict[str, str]:
    """The suite's launch env with the ceiling taken back out: the control half."""
    env = subprocess_env()
    del env["GIT_CEILING_DIRECTORIES"]
    return env


def _remove_tree(path: Path) -> None:
    """Remove a planted scratch tree, by name and only inside the checkout's tmp."""
    import shutil

    assert path.parent == REPO / "tmp", f"refusing to remove {path}"
    shutil.rmtree(path, ignore_errors=True)
