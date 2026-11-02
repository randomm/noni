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
    gate_page_command,
    launch,
    reroot_state_git,
    reroot_state_repo,
    route_commands,
    words,
)
from readme_support import _block_words, _quickstart_words


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


def test_an_ambiguous_state_reference_is_refused_not_guessed_at() -> None:
    """A page line that names the state directory twice is an assertion, not a guess.

    The anchor rule is "exactly once, exactly as the ``--repo`` value", and the two
    ways a line broke it before were both silent. A second ``--repo`` left the helper
    to re-root the first one and hand the writer a line with two --repo values (git
    and argparse each take one of them, and not necessarily the moved one), so the
    record was committed into whichever tree the parser preferred while the run still
    reported the page's exit 0. A second ``.noni-state`` in a position the helper does
    not move -- a positional, or a ``--git-dir`` rather than a ``-C`` -- was passed
    through untouched, which is the unanchored case under a different spelling. Both
    are asserted for ``--repo`` and for its ``-C`` twin, and the negative half pins
    that a line which names the state directory nowhere is still returned unchanged.
    """
    state = Path("/scratch/project/.noni-state")
    duplicated_repo = [
        # --repo given twice, the state directory as the second value
        ["noni", "register", "--repo", ".", "--repo", STATE_DIR],
        # --repo given twice, the state directory as the first value
        ["noni", "register", "--repo", STATE_DIR, "--repo", "."],
        # one --repo, and the state directory also sits as a positional
        ["noni", "census", "--repo", ".", STATE_DIR],
        # one --repo, and the state directory also sits as a second --repo value
        ["noni", "census", "--repo", STATE_DIR, STATE_DIR],
    ]
    for argv in duplicated_repo:
        with pytest.raises(AssertionError):
            reroot_state_repo(argv, state)
    # The same line with a second token that merely *contains* the state name is not
    # a second mention of the tree: the count is on whole tokens, and an answer that
    # happens to quote the directory is the page's prose, not a path the writer opens.
    quoted = ["noni", "claim", "--repo", STATE_DIR, "--answer", "q1=" + STATE_DIR]
    assert reroot_state_repo(quoted, state) == [
        "noni", "claim", "--repo", str(state), "--answer", "q1=" + STATE_DIR], quoted
    # A page line that does not name the state directory at all is passed through
    # untouched: the helper adds no anchor the page did not print.
    for argv in (["noni", "census", "--repo", "."],
                 ["noni", "decide", "--slug", "release-scope"]):
        assert reroot_state_repo(argv, state) == argv

    duplicated_c = [
        # -C given twice: git takes the last, so re-rooting the first moves nothing
        ["git", "-C", STATE_DIR, "-C", ".", "push", "-u", "origin", "main"],
        # the state directory as a positional next to a -C that names something else
        ["git", "-C", ".", "push", "-u", "origin", "main", STATE_DIR],
        # the state directory named by --git-dir instead of -C: no anchor to move,
        # so the verb would run against the launcher's cwd and still report exit 0
        ["git", "--git-dir", STATE_DIR, "push", "-u", "origin", "main"],
    ]
    for argv in duplicated_c:
        with pytest.raises(AssertionError):
            reroot_state_git(argv, state)
    assert reroot_state_git(["git", "commit", "--allow-empty", "-m", "x"], state) == [
        "git", "commit", "--allow-empty", "-m", "x"]


def test_the_config_gate_walks_past_options_rather_than_trusting_a_position() -> None:
    """The identity-key gate reads the key git reads, not the word after ``config``.

    ``git`` re-interprets what follows ``config``: an option there changes what the
    next word means, so a gate that checked "the token at index 2" would screen a word
    git does not treat as the key and let the real one through unexamined. Each case
    below carries a key that the harness may set, a transport token that it may not,
    or both, in an option position or in a value an option consumed; the expectation is
    what the gate has to do about it.
    """
    def allows(argv):
        try:
            gate_page_command(("git", "config"), argv)
        except AssertionError:
            return False
        return True

    identity = ["user.name", "Casey"]
    # The page's own lines pass, and a read-only query is not a write: the gate does
    # not refuse the page reading a key it may not set.
    assert allows(["git", "config", *identity])
    assert allows(["git", "-C", ".noni-state", "config", "user.email",
                   "casey@example.invalid"])
    assert allows(["git", "config", "--get", "user.name"])
    assert allows(["git", "config", "--get-all", "user.email"])
    assert allows(["git", "config", "--get", "remote.origin.url"])
    assert allows(["git", "config", "--get", "user.name", "Casey"])
    assert allows(["git", "config", "user.name", "Casey", "--null"])
    # A key outside the identity pair is refused, wherever it sits.
    assert not allows(["git", "config", "core.sshCommand", "ssh -i /tmp/k"])
    assert not allows(["git", "config", "url.https://x/.insteadOf", "git@x:"])
    assert not allows(["git", "config", "URL.X.INSTEADOF", "git@x:"])
    assert not allows(["git", "config", "remote.origin.pushurl", "/tmp/elsewhere"])
    assert not allows(["git", "config", "remote.origin.pushURL", "/tmp/elsewhere"])
    # A value-taking option consumes its value, so the token after it is not the key,
    # and a flag that redirects the write is refused rather than exec'd.
    assert not allows(["git", "config", "-f", "/tmp/other", *identity])
    assert not allows(["git", "config", "user.name", "Casey", "--file", "/tmp/x"])
    assert not allows(["git", "config", "--unknown-flag", "user.name"])
    # The smuggling cases: a transport name, a path, or the state directory in an
    # option position, in a value an option consumed, or past the key -- with a
    # permitted-looking key in the visible slot each time.
    assert not allows(["git", "config", "--get", "remote.origin.pushurl"])
    assert not allows(["git", "config", "--get-urlmatch", "remote.origin.pushurl",
                       "push"])
    assert not allows(["git", "config", "--get", "user.name", "Casey",
                       "--get-urlmatch", "remote.origin.pushurl"])
    assert not allows(["git", "config", "-f", "user.name", "--push", "origin", "x"])
    assert not allows(["git", "config", "--get", "user.name", "url.evil/.insteadOf"])
    assert not allows(["git", "config", "user.name", "Casey", "--get-urlmatch",
                       "remote.origin.pushurl"])
    assert not allows(["git", "config", "--get=remote.origin.pushurl", "user.name"])
    assert not allows(["git", "config", "user.name", "Casey", "/tmp/evil"])
    assert not allows(["git", "config", "user.name", "Casey", STATE_DIR])
    # --push is git's remote-writing form and the page has no use for it: refused in
    # every position, including behind a permitted key.
    assert not allows(["git", "config", "--push", "user.name"])
    assert not allows(["git", "config", "user.name", "Casey", "--push"])
    assert not allows(["git", "config", "user.name", "Casey", "--push", "origin"])
    assert not allows(["git", "config", "--get", "user.name", "Casey", "--push"])
    assert not allows(["git", "config", "--push=user.name"])
    # A line with no key at all is refused rather than treated as a no-op.
    assert not allows(["git", "config"])
    assert not allows(["git", "config", "--get"])


def test_the_words_readers_of_the_two_pages_agree_on_every_quickstart_command():
    """Two independent readers of one grammar, cross-checked on the real page.

    ``readme_support`` carries three closed readers, each with its rules fixed in
    its own body (no knobs a caller could use to re-word a line into something an
    allow-list permits): ``_block_words`` reads the README's block with the README's
    rules, ``_quickstart_words`` reads this page with this page's rules, and
    ``quickstart_runner.words`` is the launcher's copy of the quickstart's rules --
    the one the allow-list is actually decided on.

    The pair that matters is the last two: they read the same grammar for the same
    page, so a comparison between them is a measurement only while neither delegates
    to the other. Both have their walk written out in their own body, which is what
    makes the cross-check below able to fail -- and the cross-check runs on the only
    input that matters, every command the page actually prints, plus the shapes the
    page does not print today and could gain (a token carrying each word-ending
    character, an option that consumes a value, ``-m``, ``--flag=value``).
    """
    commands = [argv for label in ("Install", "Route A", "Route B")
                for argv in route_commands(label)]
    assert commands, "the page yields no commands to compare the readers on"
    for argv in commands:
        assert _quickstart_words(argv) == words(argv), argv
    # The shapes above are what the page prints; these are the shapes it could gain,
    # so a reader that drifted only on an unprinted form is caught too.
    for argv in ("git", "python3", "noni", "echo"):
        for token in ("a.b", "a/b", "a@b", "a:b", "a>b"):
            assert _quickstart_words([argv, "sub", token]) == words([argv, "sub", token])
    for argv in (["git", "-C", ".noni-state", "config", "user.name", "Casey"],
                 ["python3", "-m", "pip", "install", "./noni"],
                 ["git", "commit", "--allow-empty", "-m", "first"],
                 ["git", "push", "--force-with-lease=refs/heads/main", "origin", "main"]):
        assert _quickstart_words(argv) == words(argv), argv
    # Neither reader is the other by reference: a body that re-exported its sibling
    # would satisfy every assertion above and measure nothing.
    for reader in (_quickstart_words, words):
        assert reader.__code__.co_filename != (
            (_quickstart_words if reader is words else words).__code__.co_filename), (
            f"{reader.__name__} is the other reader's body, so the cross-check "
            "above compares a function with itself")
    # The README reader keeps its own shape: an option is skipped, not skipped *over*,
    # so the word after ``-C`` is the one its walk stops on -- the directory, where
    # the quickstart's walk (which lets an option consume its value) reaches the verb.
    # That difference is the two pages' grammar, and it is why the cross-check above is
    # a measurement rather than a tautology: on the quickstart's own line the two
    # readers must agree, and on a shape only the README's rules could print they must
    # not, or one of the two bodies has silently become the other's.
    assert _block_words(["git", "-C", "x", "config"]) == ("git", "x")
    assert _quickstart_words(["git", "-C", "x", "config"]) == ("git", "config")
    assert _block_words(["git", "-C", ".noni-state", "config"]) == ("git",)
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

