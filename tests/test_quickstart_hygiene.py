"""The launcher's own hygiene, pinned at the argv and env level.

``tests/test_quickstart.py`` runs the page; this module checks the machinery that
runs it. Both matter to the reader, because a doc runner is only a measurement while
its own decisions hold: a re-rooting that passed an unanchored line through would
address the project tree and still report the page's exit 0, an allow-list walk with
a knob in it could be talked into exec'ing anything, a launch that inherited the
harness's ``PYTHONPATH`` would pass on an environment the reader does not have, and a
push guard that trusted the clone it was handed could send the private state
repository somewhere else.

Each claim is checked where it is decided -- on one argv, or on the env dict --
because the whole-route runs in the other module cannot see any of them: those
launch the commands the page prints, and a page cannot print a line it does not contain.
"""

from __future__ import annotations

import inspect
import os
import subprocess
from pathlib import Path

import pytest
from _harness import REPO
from docs_commands import block_commands, read
from docs_promises import PUBLISHING, QUICKSTART, STATE_DIR
from quickstart_runner import (
    World,
    build_world,
    git,
    launch,
    reroot_state_git,
    reroot_state_repo,
    route_commands,
    words,
)
from readme_support import _quickstart_words
from test_quickstart import _checked


@pytest.fixture()
def world(tmp_path: Path) -> World:
    """The page's topology, standing and installed (see ``build_world``)."""
    return build_world(tmp_path)


def test_reroot_state_git_keeps_the_c_option_and_moves_only_its_value():
    """The re-rooting replaces the value after ``-C``, never ``-C`` itself.

    Dropping the option together with its target leaves ``git push -u origin
    main`` to run in the launcher's cwd, which is the reader's *project* tree: the
    harness would push the code repository and still report the page's exit 0.
    Checked at argv level, because a whole-route run cannot tell the two trees
    apart when both hold a branch called ``main``.
    """
    state = Path("/scratch/project/.noni-state")
    argv = ["git", "-C", STATE_DIR, "push", "-u", "origin", "main"]
    rerooted = reroot_state_git(argv, state)
    assert rerooted == ["git", "-C", str(state), "push", "-u", "origin", "main"], rerooted
    assert rerooted[:2] == ["git", "-C"], (
        f"the re-rooted line lost its -C, so it would run against the project: "
        f"{rerooted}")
    # The verb and its arguments are untouched, so a page that named the wrong
    # verb still fails the way a reader would see it.
    assert rerooted[3:] == argv[3:]
    # A line that names no state directory is returned unchanged: the launcher
    # must not invent a -C for a command the page wrote without one.
    plain = ["git", "config", "user.name", "Casey"]
    assert reroot_state_git(plain, state) == plain


def test_reroot_state_git_refuses_an_unanchored_state_reference():
    """A page git line that names the state directory with no ``-C`` fails closed.

    Passing such an argv through unchanged is the failure mode a whole-route run
    cannot see: ``git push -u origin main`` typed from the project root, with the
    state directory only in the prose, would run against the *project* and still
    report the page's exit 0 -- the push would address the code repository. The
    helper has to refuse it, so the run fails where the mistake is.
    """
    state = Path("/scratch/project/.noni-state")
    unanchored = ["git", "push", "-u", "origin", "main", STATE_DIR]
    with pytest.raises(AssertionError, match="-C"):
        reroot_state_git(unanchored, state)


def test_reroot_state_repo_has_the_same_anchor_test_as_its_c_twin():
    """The ``--repo`` re-rooting fails closed the way the ``-C`` one does.

    The two helpers move one value (a ``-C`` target, a ``--repo`` value) and both
    must refuse a line that names the state directory anywhere else: a
    ``noni census .noni-state`` would run against the launcher's cwd, which is
    the project, and a whole-route run cannot tell the trees apart. Asserted
    side by side, because the pair is only one rule if both halves hold.
    """
    state = Path("/scratch/project/.noni-state")
    argv = ["noni", "register", "--repo", STATE_DIR, "--identity", "developer"]
    rerooted = reroot_state_repo(argv, state)
    assert rerooted == ["noni", "register", "--repo", str(state), "--identity",
                        "developer"], rerooted
    # A line whose --repo names something else is left alone (``--repo .`` is the
    # project, and retargeting it silently would measure the wrong tree)...
    project_form = ["noni", "census", "--repo", "."]
    assert reroot_state_repo(project_form, state) == project_form
    # ...but a line that names the state directory with no --repo in front of it
    # is refused, exactly as its -C twin refuses an unanchored git line.
    with pytest.raises(AssertionError, match="--repo"):
        reroot_state_repo(["noni", "census", STATE_DIR], state)


def test_the_words_readers_of_the_two_pages_agree_on_every_quickstart_command():
    """The two closed word-readers, checked against each other on the real page.

    ``readme_support`` carries two functions now, each with its rules fixed in its
    body (no knobs a caller could use to re-word a line into something an
    allow-list permits): ``_block_words`` reads the README's block, and
    ``_quickstart_words`` reads this page's. The second is the launcher's reader,
    so the risk the split introduces is drift between the pair. This closes it on
    the only input that matters: every command the page actually prints has to
    reduce the same way under both readers, and the README's rules have to keep
    reducing its own ``git config`` line to the two-word form its allow-list
    matches.
    """
    commands = [argv for label in ("Install", "Route A", "Route B")
                for argv in route_commands(label)]
    assert commands, "the page yields no commands to compare the readers on"
    for argv in commands:
        assert _quickstart_words(argv) == words(argv), argv
    # The README reader keeps its own shape: options do not consume values there.
    assert _quickstart_words(["git", "-C", ".noni-state", "config"]) == ("git", "config")


def test_the_words_walk_stops_at_an_argument_rather_than_reading_it_as_a_subcommand():
    """The third word of a page line never becomes the key the allow-list decides on.

    The vocabulary is program-and-subcommand, so a walk that ran past the first
    non-option word would key a ``git push origin main`` on ``('git', 'push',
    'origin')``: outside the allow-list, and the launch refused on a line the page
    prints. The stop rule is what keeps a permitted command permitted whatever its
    arguments, so it is pinned on the shapes that make it bite -- trailing
    positionals, an option that consumed its value, and the quoted value the page
    carries for a multi-word field.
    """
    assert words(["git", "push", "origin", "main"]) == ("git", "push")
    assert words(["git", "commit", "-m", "first", "--allow-empty"]) == ("git", "commit")
    assert words(["git", "commit", "--allow-empty", "-m", "first"]) == ("git", "commit")
    assert words(["noni", "claim", "--identity", "developer", "q1=Wait a week"]) == (
        "noni", "claim")
    # A bare program with no subcommand word keys on the program alone, which is
    # outside the two-word vocabulary: nothing runs on a name alone.
    assert words(["noni", "--version"]) == ("noni",)


def test_the_publishing_gate_command_is_runnable_from_the_cwd_the_page_states() -> None:
    """The gate the deny-list section names is a fenced command, valid where it sits.

    ``python scripts/public_safety.py`` is the check ``docs/PUBLISHING.md`` step 1
    runs, and the quickstart now prints it inside a bash fence so the suite that
    runs this page's fences sees it at all. Three things make it a promise rather
    than prose: it sits in a ```bash``` fence (a fence with no info string is the
    deny-list file's shape, not a command the reader types), its path resolves
    from the directory the page tells the reader to stand in (the clone's root,
    where the install section's commands leave them), and the launcher's
    vocabulary accepts the line as a command it will run.
    """
    from docs_commands import fenced_pairs

    commands = [argv
             for info, lines in fenced_pairs(read(QUICKSTART)) if info == "bash"
             for argv in block_commands(lines)
             if argv[:2] == ["python", "scripts/public_safety.py"]]
    assert commands, (
        "the quickstart no longer prints the publishing gate command inside a "
        "bash fence, so no test launches it and no path check resolves it")
    assert len(commands) == 1, f"the gate command appears more than once: {commands}"
    argv, = commands
    assert words(argv) == ("python",), f"the gate line is outside the launcher's shape: {argv}"
    target = REPO / argv[1]
    assert target.is_file(), f"{argv[1]} does not exist from the clone root: {target}"
    assert "scripts/public_safety.py" in read(PUBLISHING), (
        "PUBLISHING no longer runs the gate the quickstart points at it for")


def test_the_page_launches_are_measured_with_no_pythonpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The env the page's commands run in carries nothing ambient, and the host
    has something hostile in it while they run.

    The page's guarantee is that the commands work because the install step put
    the package somewhere the interpreter finds, and it names the alternative
    (``PYTHONPATH=<clone>/src``) as a *separate* state a reader may be in. A
    launch that inherited the harness's own ``src/`` pin -- which is what makes
    the suite's child processes measure this tree -- could pass on an environment
    the reader does not have, and coverage's hook would have a measured child
    writing a data file into a tree the page promises the census leaves clean.

    Three things, because any one of them can be true with the launcher still
    leaking:

    - the host environment carries a ``PYTHONPATH`` and a coverage hook that are
      not the harness's own, set by this test before the topology is built;
    - what the launcher hands a command contains neither;
    - and the planted path is one that would actually kill a launch that read it,
      so the second bullet is not vacuously true of an inherited variable that
      named nothing.
    """
    from quickstart_topology import AMBIENT_LAUNCH_VARS, run_env

    monkeypatch.setenv("PYTHONPATH", "/nonexistent/host-pythonpath")
    monkeypatch.setenv("COVERAGE_PROCESS_START", str(REPO / "pyproject.toml"))
    monkeypatch.setenv("COVERAGE_FILE", str(tmp_path / ".coverage.host"))
    world = build_world(tmp_path)

    for env in (run_env(), world.env):
        for name in AMBIENT_LAUNCH_VARS:
            assert name not in env, f"a page launch inherits {name}={env[name]!r}"
        assert "GIT_DIR" not in env and "GIT_INDEX_FILE" not in env, env
    # The strip is a filter over one set: the names appear in the builder's
    # source as what it hands to the filter, never as something pinned and then
    # popped (a pin-then-pop is a two-step the second half can lose).
    builder = inspect.getsource(run_env)
    assert "AMBIENT_LAUNCH_VARS" in builder, (
        "run_env no longer filters the one explicit set of launch variables")
    assert ".pop(" not in builder and "del env" not in builder, (
        "run_env restores a variable by pin-then-pop instead of one filter")
    # The install is what the runs depend on: the console script the page's
    # install step produced is the program the launcher execs for every noni line,
    # and it runs from the clean env, not from the interpreter's own path.
    assert world.noni.is_file(), "the harness's install produced no console script"
    census_line = next(argv for argv in route_commands("Route A")
                       if words(argv) == ("noni", "census"))
    launched = launch(world, census_line, world.project)
    assert launched.returncode == 0, (
        f"the page's census line does not run in the harness's env: "
        f"{launched.returncode} {launched.stdout!r} {launched.stderr!r}")


def test_a_hostile_pythonpath_kills_a_launch_that_inherits_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The decoy behind the bullet above: an inherited ``PYTHONPATH`` is fatal.

    A strip that removed nothing would look identical to a strip that removed
    something, unless the inherited value is one that breaks the launched
    program. So the world is built with a ``PYTHONPATH`` pointing at a tree
    holding a ``noni`` package that raises on import: the clean launch env must
    not read it, and the same command run under the *inherited* environment must
    die. The pairing is what makes the isolation claim non-self-certifying, the
    same shape ``tests/test_env_isolation.py`` uses for a hostile HOME.
    """
    hostile = tmp_path / "hostile-src"
    package = hostile / "noni"
    package.mkdir(parents=True)
    # A whole shadow package, not one module: the console script imports the
    # package and its run modules, and a decoy that only shadows half of them
    # would let an inherited path import the real siblings and appear harmless.
    for name in ("__init__.py", "cli.py", "census.py", "census_cli.py",
                 "census_report.py", "census_run.py", "public_safety.py"):
        (package / name).write_text(
            'raise RuntimeError("noni imported from an ambient PYTHONPATH")\n',
            encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(hostile))
    monkeypatch.setenv("COVERAGE_PROCESS_START", str(REPO / "pyproject.toml"))
    world = build_world(tmp_path)
    census_line = next(argv for argv in route_commands("Route A")
                       if words(argv) == ("noni", "census"))
    clean = launch(world, census_line, world.project)
    assert clean.returncode == 0, (
        f"the page's census line died under a hostile host PYTHONPATH, so the "
        f"launch env is not clean: {clean.returncode} {clean.stderr!r}")
    # The pairing control: the same console script, launched with the host's own
    # environment (what a launcher that kept PYTHONPATH would hand it), must read
    # the decoy. Without this the clean run above is equally true of a decoy the
    # child never could have seen.
    inherited = subprocess.run([str(world.noni), "--help"], capture_output=True,
                               text=True, env=dict(os.environ), cwd=world.project,
                               timeout=120)
    assert inherited.returncode != 0 and "ambient PYTHONPATH" in inherited.stderr, (
        "the decoy package was not read by a launch that inherits the host "
        "PYTHONPATH, so the clean run above proves nothing: "
        f"{inherited.returncode} {inherited.stderr[:300]!r}")


def _run_route_b(world: World) -> list[list[str]]:
    """The page's Route B block, run in order. Shared by its two assertions."""
    _checked(git(world.project, "config", "user.name", "Casey", env=world.env),
             "set project identity")
    _checked(git(world.project, "config", "user.email", "casey@example.com", env=world.env),
             "set project email")
    commands = route_commands("Route B")
    for argv in commands:
        proc = launch(world, argv, world.project, state=True)
        assert proc.returncode == 0, (
            f"Route B command {argv} exited {proc.returncode}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
        # The register line's placeholder is the file that line just wrote; it is
        # read back from disk before the claim line that names it runs.
        if argv[:2] == ["noni", "register"]:
            world.collect_session_id()
    return commands


def test_the_launcher_refuses_a_push_that_names_another_remote(world: World) -> None:
    """A Route B push may only name this fixture's origin and its main.

    The state clone is the private tree in the page's story, so the one command
    that can write outside the scratch trees is guarded at both ends: the argv's
    remote and branch, and the clone's ``remote.origin.url`` as the git config
    reports it. A page (or a rewrite of one) that addressed some other remote is
    refused rather than run, and a run that had quietly rewritten the clone's
    origin -- a ``--pushurl``, a ``set-url`` -- is refused by the same gate.
    """
    from quickstart_gates import guard_route_b_push

    def guard(argv):
        guard_route_b_push(world.state, ("git", "push"), argv, True, world.origin,
                           world.env, _checked)

    _run_route_b(world)  # stand the state clone up, as the page's own commands do
    push = ["git", "-C", str(world.state), "push", "-u", "origin", "main"]
    guard(push)  # the page's line passes
    with pytest.raises(AssertionError, match="origin main"):
        guard(["git", "-C", str(world.state), "push", "evil", "main"])
    # An origin the fixture did not create is the other half of the same gate.
    elsewhere = world.origin.parent / "elsewhere"
    _checked(git(world.state, "remote", "set-url", "origin", str(elsewhere),
                 env=world.env), "plant a second origin")
    with pytest.raises(AssertionError, match="fixture origin"):
        guard(push)
