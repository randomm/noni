"""The launcher's env, pinned where the whole-route runs cannot see it.

``tests/test_quickstart.py`` runs the page; this module checks the one claim the
launcher makes about the environment it hands those commands: **nothing ambient
reaches them**. The page's guarantee is that the commands work because the install
step put the package where the interpreter finds it, and it names the alternative
(``PYTHONPATH=<clone>/src``) as a *separate* state a reader may be in. A launch that
inherited the harness's own ``src/`` pin -- which is what makes the suite's child
processes measure this tree -- would pass on an environment the reader does not
have, and coverage's hook would have a measured child writing a data file into a
tree the page promises the census leaves clean.

Two tests, one assertion seen from both sides: what the launcher hands a command
carries neither variable, and the value it does not carry is one that would have
killed the launch. A strip that removed nothing looks identical to a strip that
removed something unless the inherited value is hostile, so the second test plants a
``PYTHONPATH`` naming a ``noni`` package that raises on import, and pairs the clean
run with the inherited one that must die.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from _harness import REPO
from docs_commands import placeholder_words, read
from docs_promises import PUBLISHING, STATE_DIR
from quickstart_golden import GOLDEN
from quickstart_runner import (
    World,
    build_installed_world,
    fresh_scratch,
    launch,
    reroot,
    route_commands,
    state_dir_commands,
    substitute,
)
from quickstart_topology import AMBIENT_LAUNCH_VARS, InstalledWorld, run_env

# The words the decoy package prints. One owner: the assertion on the inherited
# run and the file that raises share them, so the pairing cannot drift apart and
# leave the clean run's success explaining nothing.
_DECOY_RAISES = 'raise RuntimeError("noni imported from an ambient PYTHONPATH")'

# The modules the console script's import chain reaches. A decoy that shadowed only
# part of the package would let an inherited path import the real siblings and look
# harmless, so the shadow is a whole package.
_DECOY_MODULES = ("__init__.py", "cli.py", "census.py", "census_cli.py",
                  "census_report.py", "census_run.py", "public_safety.py")


@pytest.fixture(scope="module")
def installed(tmp_path_factory: pytest.TempPathFactory) -> Iterator[InstalledWorld]:
    """The module's one venv install of the clone (see ``tests/test_quickstart.py``)."""
    root = tmp_path_factory.mktemp("quickstart-hygiene")
    try:
        yield build_installed_world(root)
    finally:
        import shutil

        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def world(installed: InstalledWorld, tmp_path: Path) -> World:
    """One scratch set of the page's trees, over the module's install."""
    return fresh_scratch(installed, tmp_path / "scratch")


def _census_line() -> list[str]:
    """The Route A census command, as the golden list prints it."""
    return next(argv for argv in route_commands(("Route A",))
                if argv[:2] == ["noni", "census"])


def test_the_state_re_rooting_is_applied_to_the_commands_that_name_the_clone() -> None:
    """The two moves the launcher makes are plain mappings over the golden list.

    ``-C``/``--repo`` re-rooting and placeholder substitution are sound because
    their domain is the literal list in :mod:`quickstart_golden`: every golden
    command that names the state clone names it exactly once and exactly as the
    value of one of those two anchors, so the mapping has no ambiguous case to
    guess at, and every placeholder is one of the two tokens the harness fills.
    Checked on the golden list rather than on invented argv -- invented argv is the
    hostile-page case this harness no longer models, and the commands that are run
    are exactly these.
    """
    for argv in state_dir_commands():
        assert argv.count(STATE_DIR) == 1, f"a golden line names the clone twice: {argv}"
    for argv in _rooted_commands():
        anchor = next(i for i, token in enumerate(argv) if token in ("-C", "--repo"))
        assert argv[anchor + 1] == STATE_DIR, (
            f"a golden line whose state path moves has no anchor: {argv}")
        moved = reroot(argv, Path("/scratch/project/.noni-state"))
        assert moved[anchor + 1] == "/scratch/project/.noni-state", moved
        assert moved[:anchor + 1] == argv[:anchor + 1], moved
        assert moved[anchor + 2:] == argv[anchor + 2:], moved
    # The commands that name the clone by another route -- the clone target and the
    # ignore-rule payload -- are the only ones with no anchor, and they are asserted
    # where they are dispatched, so the mapping is not handed a case it never handles.
    unrooted = [argv for argv in state_dir_commands() if argv not in _rooted_commands()]
    assert [argv[:2] for argv in unrooted] == [["git", "clone"]], unrooted
    # The ignore-rule payload names the directory inside a token (``/.noni-state/``),
    # so it is not one of the commands above; it is checked by append_ignore_rule.
    payload = [argv for label in GOLDEN for argv in GOLDEN[label]
               if argv[0] == "echo" and STATE_DIR in " ".join(argv)]
    assert len(payload) == 1, payload
    # Placeholders are the page's literal tokens, filled from one small mapping.
    assert set(_PLACEHOLDERS_ON_PAGE) <= {"<record-id>", "<session-id>"}, _PLACEHOLDERS_ON_PAGE
    filled = substitute(["noni", "order", "--repo", ".noni-state", "add", "12",
                         "--decision", "<record-id>"], {"<session-id>": "s-1"})
    assert filled[7] == "2026-11-02-release-scope", filled
    assert filled[:7] == ["noni", "order", "--repo", ".noni-state", "add", "12",
                          "--decision"], filled


def _all_golden_commands() -> list[list[str]]:
    return [argv for label in GOLDEN for argv in GOLDEN[label]]


def _rooted_commands() -> list[list[str]]:
    """The golden commands whose state path the launcher moves.

    These are the commands the re-rooting is defined over: the state clone appears
    as the value of one of the two anchors the harness reads (``git -C <clone>``,
    ``noni ... --repo <clone>``). The page's other two mentions of the directory --
    the ``git clone`` target and the ignore-rule payload -- are not options and are
    not moved: they are asserted where they are dispatched, in ``state_clone`` and
    ``append_ignore_rule``.
    """
    from quickstart_runner import reroot as _reroot

    scratch = Path("/scratch/project/.noni-state")
    return [argv for argv in state_dir_commands() if _reroot(argv, scratch) != argv]


# The placeholder tokens the golden list carries as literals, read from the page's
# commands, so a page that gained a third one fails here and the harness has to be
# told what fills it.
_PLACEHOLDERS_ON_PAGE: list[str] = sorted({
    token for argv in _all_golden_commands() for token in argv
    if placeholder_words(token)
})


def test_the_publishing_gate_command_is_a_real_command_of_the_page() -> None:
    """The gate the deny-list section names sits in a bash fence and resolves.

    ``python scripts/public_safety.py`` is the check ``docs/PUBLISHING.md`` step 1
    runs, and the quickstart prints it inside a ```bash``` fence so the suite that
    runs this page's fences sees it at all -- a fence with no info string is the
    deny-list file's shape, not a command the reader types. Three things make it a
    promise rather than prose: it is one of the golden commands (so it is the line
    a human reviewed), its path resolves from the directory the page tells the
    reader to stand in (the clone's root, where the install section leaves them),
    and PUBLISHING still owns the gate it points at.
    """
    from quickstart_golden import DENYLIST

    commands = [argv for argv in route_commands(DENYLIST)
                if argv[:2] == ["python", "scripts/public_safety.py"]]
    assert commands, (
        "the quickstart no longer prints the publishing gate command inside a "
        "bash fence, so no test launches it and no path check resolves it")
    assert len(commands) == 1, f"the gate command appears more than once: {commands}"
    argv, = commands
    target = REPO / argv[1]
    assert target.is_file(), f"{argv[1]} does not exist from the clone root: {target}"
    assert "scripts/public_safety.py" in read(PUBLISHING), (
        "PUBLISHING no longer runs the gate the quickstart points at it for")


def test_the_page_launches_are_measured_with_no_pythonpath(world: World) -> None:
    """What the launcher hands a page command carries no ``PYTHONPATH`` and no
    coverage hook, and the console script the install produced is what runs.

    The host carries both while this runs (see the fixture below), so the assertion
    is not vacuously true of variables that were never there; the decoy test pairs it
    with a value that would have broken a launch that read them.
    """
    for env in (run_env(), world.env):
        for name in AMBIENT_LAUNCH_VARS:
            assert name not in env, f"a page launch inherits {name}={env[name]!r}"
        assert "GIT_DIR" not in env and "GIT_INDEX_FILE" not in env, env
    # The strip is a filter over one set: the names appear in the builder's source as
    # what it hands to the filter, never as something pinned and then popped (a
    # pin-then-pop is a two-step whose second half can be lost).
    builder = _source_of(run_env)
    assert "AMBIENT_LAUNCH_VARS" in builder, (
        "run_env no longer filters the one explicit set of launch variables")
    assert ".pop(" not in builder and "del env" not in builder, (
        "run_env restores a variable by pin-then-pop instead of one filter")
    # The install is what the runs depend on: the console script the page's install
    # step produced is the program the launcher execs for every noni line, and it
    # runs from the clean env, not from the interpreter's own path.
    assert world.noni.is_file(), "the harness's install produced no console script"
    launched = launch(world, _census_line(), world.project)
    assert launched.returncode == 0, (
        f"the page's census line does not run in the harness's env: "
        f"{launched.returncode} {launched.stdout!r} {launched.stderr!r}")


def test_a_hostile_pythonpath_kills_a_launch_that_inherits_it(
    tmp_path: Path, installed: InstalledWorld,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The decoy behind the bullet above: an inherited ``PYTHONPATH`` is fatal.

    The world is built with a ``PYTHONPATH`` naming a tree that holds a ``noni``
    package which raises on import: the clean launch env must not read it, and the
    same command run under the *inherited* environment must die. The pairing is what
    makes the isolation claim non-self-certifying, the same shape
    ``tests/test_env_isolation.py`` uses for a hostile HOME.
    """
    hostile = tmp_path / "hostile-src"
    package = hostile / "noni"
    package.mkdir(parents=True)
    for name in _DECOY_MODULES:
        (package / name).write_text(_DECOY_RAISES + "\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(hostile))
    monkeypatch.setenv("COVERAGE_PROCESS_START", str(REPO / "pyproject.toml"))
    world = fresh_scratch(installed, tmp_path / "scratch")
    clean = launch(world, _census_line(), world.project)
    assert clean.returncode == 0, (
        f"the page's census line died under a hostile host PYTHONPATH, so the "
        f"launch env is not clean: {clean.returncode} {clean.stderr!r}")
    # The pairing control: the same console script, launched with the host's own
    # environment (what a launcher that kept PYTHONPATH would hand it), must read the
    # decoy. Without this the clean run above is equally true of a decoy the child
    # never could have seen.
    inherited = subprocess.run([str(world.noni), "census", "--repo", str(world.project)],
                               capture_output=True, text=True, env=dict(os.environ),
                               cwd=world.project, timeout=120)
    assert inherited.returncode != 0 and "ambient PYTHONPATH" in inherited.stderr, (
        "the decoy package was not read by a launch that inherits the host "
        "PYTHONPATH, so the clean run above proves nothing: "
        f"{inherited.returncode} {inherited.stderr[:300]!r}")


@pytest.fixture(autouse=True)
def _host_carries_the_variables(_host_pythonpath: None) -> None:
    """Every test in this module runs with a ``PYTHONPATH`` and a coverage hook set."""


@pytest.fixture
def _host_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    """The host's own hostile variables, planted before the launcher builds an env.

    A path that names nothing real would keep the first test's assertions from
    meaning anything (an inherited variable that pointed nowhere is harmless either
    way), so it names a directory that exists and a config file that does.
    """
    monkeypatch.setenv("PYTHONPATH", str(Path.cwd() / "src"))
    monkeypatch.setenv("COVERAGE_PROCESS_START", str(REPO / "pyproject.toml"))
    monkeypatch.setenv("COVERAGE_FILE", str(Path.cwd() / ".coverage.host-probe"))


def _source_of(function) -> str:
    """The text of one helper's body, so a claim about its shape is checkable."""
    import inspect

    return inspect.getsource(function)
