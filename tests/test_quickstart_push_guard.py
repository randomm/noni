"""The push guard's own claims, checked against a standing topology.

:mod:`tests.test_quickstart_hygiene` pins the launcher's argv- and env-level rules on
one argv each; the guard over the state clone's push cannot be pinned that way, because
what it must refuse is a *clone whose remote has moved* -- a fact about a tree, read from
git, not about a token. So this module builds the world the page describes, runs Route B
to stand the state clone up, and then rewrites the clone's remote by the two routes git
offers (``set-url`` and ``set-url --push``) to see whether the guard notices.

The distinction the tests below keep insisting on is between three outcomes of one
probe -- a value, an unset key, and a read that failed -- because a guard that reads the
third as the second is a guard that lets the private clone be pushed anywhere.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from quickstart_runner import (
    World,
    build_world,
    config_value,
    git,
    run_route_b,
)
from test_quickstart import _checked


@pytest.fixture()
def world(tmp_path: Path) -> World:
    """The page's topology, standing and installed (see ``build_world``)."""
    return build_world(tmp_path)



def _run_route_b(world: World) -> list[list[str]]:
    """The page's Route B block, run in order, with the project identity it prints.

    The shared command walk is :func:`quickstart_runner.run_route_b` -- one owner,
    so the exit-code test, the origin-contents test and this module all drive the
    same sequence. What this adds is the project's own git identity, which the page
    sets in the Route A section that this module's assertions do not run: Route B's
    ignore-rule line writes into the project, and ``git status`` in the exit-code
    test fails on an untracked ``.gitignore`` unless something has configured the
    tree first. Fixture calls, not page commands -- the page's identity lines are
    checked where they run.
    """
    _checked(git(world.project, "config", "user.name", "Casey", env=world.env),
             "set project identity")
    _checked(git(world.project, "config", "user.email", "casey@example.com", env=world.env),
             "set project email")
    return run_route_b(world)


def _bare_origin(world: World) -> Path:
    """A second bare repository under the scratch root, as a remote to plant.

    Made by ``git init --bare`` in a directory the caller does not have to create:
    ``git -C`` refuses a missing directory, and the topology helper that makes the
    fixture's own origin owns that one tree, not a second one.
    """
    elsewhere = world.origin.parent / "elsewhere"
    elsewhere.mkdir()
    _checked(git(elsewhere, "init", "-q", "--bare", "-b", "main", env=world.env),
             "a second bare origin")
    return elsewhere


def _guard(world: World, argv: list[str], *, state: bool = True) -> None:
    """The push guard, on one argv, with the caller's Route label as a knob."""
    from quickstart_gates import guard_route_b_push

    guard_route_b_push(world.state, ("git", "push"), argv, state, world.origin,
                       world.env, _checked)


def test_the_launcher_refuses_a_push_that_names_another_remote(world: World) -> None:
    """A push of the state clone may only name this fixture's origin and its main.

    The state clone is the private tree in the page's story, so the one command that
    can write outside the scratch trees is guarded at every end that git consults:
    the argv's remote and branch, the clone's ``remote.origin.url``, and its
    ``remote.origin.pushurl`` -- which git prefers over the url for a push, so a
    guard that read only the url would pass a clone whose push end had been moved by
    ``remote set-url --push``. A page (or a rewrite of one) that addressed some other
    remote is refused rather than run.
    """
    _run_route_b(world)  # stand the state clone up, as the page's own commands do
    push = ["git", "-C", str(world.state), "push", "-u", "origin", "main"]
    _guard(world, push)  # the page's line passes
    with pytest.raises(AssertionError, match="origin main"):
        _guard(world, ["git", "-C", str(world.state), "push", "evil", "main"])
    # An origin the fixture did not create is the other half of the same gate.
    elsewhere = _bare_origin(world)
    _checked(git(world.state, "remote", "set-url", "origin", str(elsewhere),
                 env=world.env), "plant a second origin")
    with pytest.raises(AssertionError, match="fixture origin"):
        _guard(world, push)


def test_the_guard_reads_the_pushurl_git_actually_pushes_to(world: World) -> None:
    """A moved ``pushurl`` reddens the guard even though the url still reads correctly.

    This is the hole the url check alone left: ``git remote set-url --push origin
    <elsewhere>`` leaves ``remote.origin.url`` pointing at the fixture and puts the
    push end somewhere else, and git prefers it, so a green Route B run could have
    pushed the private state clone to a repository this run never made. The unset
    case has to stay green too -- ``git config --get`` exits 1 with no output when a
    key is unset, and that is the state of the clone the fixture builds.
    """
    _run_route_b(world)
    push = ["git", "-C", str(world.state), "push", "-u", "origin", "main"]
    _checked(git(world.state, "config", "--get", "remote.origin.url", env=world.env),
             "the clone's url before the pushurl is planted")
    # The precondition, read from git rather than assumed: this clone has no
    # pushurl, and the guard still lets the page's line through.
    unset = config_value(world.state, "remote.origin.pushurl", env=world.env)
    assert unset.returncode == 1 and not unset.stdout.strip(), (
        f"the fixture's clone already carries a pushurl, so the unset case below "
        f"is not being tested: rc={unset.returncode} "
        f"stdout={unset.stdout!r} stderr={unset.stderr!r}")
    _guard(world, push)
    elsewhere = _bare_origin(world)
    _checked(git(world.state, "remote", "set-url", "--push", "origin", str(elsewhere),
                 env=world.env), "move only the clone's push end")
    # The url still names the fixture: an assertion that passed here was the bug.
    _checked(git(world.state, "config", "--get", "remote.origin.url", env=world.env),
             "the clone's url after the pushurl was planted")
    with pytest.raises(AssertionError, match="pushurl"):
        _guard(world, push)


def test_the_guard_is_keyed_on_the_argv_not_the_callers_route_label(world: World) -> None:
    """A push into the state clone is guarded whatever route the caller claims.

    The label is an argument the caller chooses, so a guard keyed on it can be
    skipped by launching the same line as Route A: the write is identical, and the
    page cannot print such a line, which is exactly why only an argv-level test sees
    it. The negative halves keep the guard from over-reaching in the other direction
    -- a push of the *project* is not the private state clone, and a launched verb
    that is not ``push`` is not the command being guarded.
    """
    from quickstart_gates import guard_route_b_push

    _run_route_b(world)
    push = ["git", "-C", str(world.state), "push", "-u", "origin", "main"]
    # The Route A claim does not skip it: state=False is what a Route A caller passes.
    _guard(world, push, state=False)
    with pytest.raises(AssertionError, match="origin main"):
        _guard(world, ["git", "-C", str(world.state), "push", "evil", "main"],
               state=False)
    # Same argv, wrong verb in the key: not the guarded command, so not guarded.
    guard_route_b_push(world.state, ("git", "commit"), push, False, world.origin,
                       world.env, _checked)
    # A push of the project tree is not the state clone, so the guard stays out of
    # the way of the writers' own ``--push`` on the code repository.
    guard_route_b_push(world.state, ("git", "push"),
                       ["git", "-C", str(world.project), "push", "-u", "origin", "main"],
                       False, world.origin, world.env, _checked)


def test_a_probe_that_cannot_run_fails_loudly_not_as_an_empty_value(
        world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard does not compare a dead probe's empty stdout against the origin.

    ``git config --get`` has three outcomes and the guard tells them apart: 0 is a
    value, 1 means unset (allowed for ``pushurl``, which the fixture leaves unset),
    and anything else means the read itself failed. A probe that returned 128 with
    nothing on stdout -- no tree, an unreadable config, a git too old for the flag --
    looked like "no value" to a comparison on stdout alone, and for a clone whose
    expected url was the empty string it would have compared equal. Both streams have
    to appear in the message as well, so the reader sees what git said.
    """
    import quickstart_gates

    _run_route_b(world)
    push = ["git", "-C", str(world.state), "push", "-u", "origin", "main"]
    sentinel = "probe could not run: no such tree"

    def dead_probe(repo, key, *, env):
        return subprocess.CompletedProcess(["git", "config", "--get", key], 128, "",
                                           sentinel)

    monkeypatch.setattr(quickstart_gates, "config_value", dead_probe)
    with pytest.raises(AssertionError) as caught:
        _guard(world, push)
    text = str(caught.value)
    assert sentinel in text, (
        f"a failed probe's stderr did not reach the failure message: {text!r}")
    assert "128" in text, f"the probe's exit code did not reach the message: {text!r}"
    # And the guard's own assertion message names the probe that disagreed.
    monkeypatch.undo()
    from quickstart_gates import guard_route_b_push
    with pytest.raises(AssertionError) as caught:
        guard_route_b_push(world.project, ("git", "push"),
                           ["git", "-C", str(world.project), "push", "-u", "origin",
                            "main"], True, world.origin, world.env, _checked)
    assert "probe" in str(caught.value)
