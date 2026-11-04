"""The quickstart's CI section, launched on the scratch topology.

The page tells a team to run one census line in a build and to gate the build on
two sets of exit codes. This module settles that half by running it: each route is
driven twice on the same tree -- once as the page's own steps leave it, where the
documented verdict is exit 0, and once with a violation planted under the ``noni/``
tree that route's ``--repo`` names, where the verdict is the ``session-double``
code. The planted shape is the double claim the exit-code contract test commits --
two committed register files, two identities, one task -- so the exit code here is
earned by the same shape that test pins.

The commands are the page's own: they come from
:func:`quickstart_runner.route_commands`, which compares the page's fences against
:mod:`quickstart_golden` before returning them, and they reach
:func:`quickstart_runner.launch`, which refuses an argv no golden list prints.
Nothing here types a census command of its own.

The page parser below (:func:`documented_fail_codes`, :func:`documented_warn_codes`,
:func:`ci_commands`, :func:`ci_section`) is public for
``tests/test_census_check_contract.py``, the module that holds the check contract
and asserts the documented sets and the ``--strict`` prose against the table.
"""

from __future__ import annotations

import re
from pathlib import Path

import census
from _harness import _commit_file
from census_fixtures import _session_body
from docs_promises import QUICKSTART, STATE_DIR
from quickstart_golden import CI
from quickstart_runner import (
    World,
    checked,
    git,
    launch,
    route_commands,
    run_route_b,
)

# The planted violation: the task both identities claim, and the two session ids
# the committed files carry. The names are the shape
# ``tests/test_census_exit_codes_contract.py::test_exit_30_double_claim`` commits,
# so the fixture here is the same double claim the exit-code contract already
# pins, not a shape this module invented.
_CLAIMED_TASK = "#42"
_CLAIMANT_IDS = ("2026-10-01-aaaaaa", "2026-10-01-bbbbbb")


def ci_commands() -> list[list[str]]:
    """The CI section's commands, as the page prints them (golden-checked).

    Public because the agreement module checks the documented step against them:
    the same parsed lines, not a second reading of the fences.
    """
    return route_commands(CI)


def _ci_census_command(*, state: bool) -> list[str]:
    """The route's census line, taken from the page rather than typed here.

    The section must print exactly one census line per route: a second one would
    be a second command no test names, and the launcher would run it under the
    same name as this one.
    """
    want = STATE_DIR if state else "."
    matches = [argv for argv in ci_commands()
               if argv[:2] == ["noni", "census"]
               and argv[2:4] == ["--repo", want]]
    assert len(matches) == 1, (
        f"the CI section must print exactly one census line with --repo {want}: "
        f"{matches}")
    return matches[0]


def _committed_double_claim(tree: Path, env: dict[str, str]) -> None:
    """Plant the double claim under ``tree`` and commit it, as a CI checkout has it.

    Both files are committed because the census reports the register as git sees
    it; an uncommitted pair would be a tree no build checks out. The writer is the
    harness's own ``_commit_file`` (one commit, one identity, no GPG), which is what
    ``tests/test_census_exit_codes_contract.py::test_exit_30_double_claim`` plants,
    so the census here reads the same shape that test's exit code is earned by.
    """
    for session_id in _CLAIMANT_IDS:
        identity = "dev" if session_id.endswith("aaaaaa") else "rev"
        # ``claims`` is the third parameter, not the second: passed positionally it
        # would land in ``status`` and the pair would census as a malformed register
        # rather than as one task claimed twice.
        body = _session_body(identity, claims=[_CLAIMED_TASK])
        _commit_file(tree, f"noni/sessions/{session_id}.md", body)
    # A leftover worktree entry would be an uncommitted file, and the census reads
    # the register as git sees it: the verdict below would then be earned by a tree
    # no CI checkout has. The page's own Route A steps leave the project clean, so
    # this holds whatever the planted pair adds.
    dirty = git(tree, "status", "--porcelain", env=env).stdout.splitlines()
    assert not [line for line in dirty if line.strip()], (
        f"planting the double claim left {tree} dirty: {dirty}")


def _run_route_a(world: World, argv: list[str]) -> tuple[int, str]:
    """The page's Route A line, launched, with its exit code and stdout."""
    proc = launch(world, argv, world.project)
    return proc.returncode, proc.stdout


def _run_route_b(world: World, argv: list[str]) -> tuple[int, str]:
    """The page's Route B line, launched after the route that creates the clone.

    Route B's clone exists only because the page's own steps made it, so the walk
    that prints the record id and pushes the branch runs first; its exit codes are
    the promise ``tests/test_quickstart.py`` makes, and here they are a precondition.
    """
    run_route_b(world)
    proc = launch(world, argv, world.project)
    return proc.returncode, proc.stdout


def _assert_verdict(proc_returncode: int, stdout: str, expected: int,
                    what: str) -> list[str]:
    """One census run's verdict, pinned to one exit code, with its rows returned.

    A single pinned value rather than a range: exit 0 and exit 30 are the pair the
    page promises, and a run that answered nothing (a usage error, a missing tool)
    has to fail here rather than look like the clean half.
    """
    lines = stdout.splitlines()
    assert proc_returncode == expected, (
        f"{what} exited {proc_returncode}, not {expected}\n"
        f"stdout: {stdout}\nrows: {lines}")
    return lines


def _verdict_line(lines: list[str]) -> str:
    """The census's summary line, which the page's whole section is about.

    Absent it the run reported no verdict at all, so both halves of the clean and
    failing pair demand it: a clean run ends ``summary: ... verdict ok`` and a
    failing one names its code and the classes that fired.
    """
    assert lines and lines[-1].startswith("summary: "), (
        f"the census printed no summary line: {lines[-1:]!r}")
    return lines[-1]


# --- the page's step, run ---------------------------------------------------

def test_the_ci_step_exits_zero_on_a_clean_route_a_tree(world: World) -> None:
    """The page's Route A census line, run as printed, ends verdict ok.

    The tree is what the page's own Route A steps leave behind, so the clean half
    is asserted on the tree the reader has, not on an empty directory that would
    pass for the wrong reason.
    """
    for argv in route_commands(("Route A",)):
        checked(launch(world, argv, world.project), f"Route A command {argv}")
    code, stdout = _run_route_a(world, _ci_census_command(state=False))
    lines = _assert_verdict(code, stdout, 0, "the CI census step on a clean tree")
    assert _verdict_line(lines).endswith("verdict ok"), lines[-1]
    assert not git(world.project, "status", "--porcelain",
                   env=world.env).stdout.splitlines(), (
        "the documented CI step left the tree dirty")


def test_the_ci_step_fails_a_route_a_build_on_a_planted_double_claim(
    world: World,
) -> None:
    """The same step, same tree, one planted violation: the documented fail code.

    The pair with the test above is the whole of the page's promise: nothing but
    the planted ``noni/sessions`` pair differs between the two runs, so the exit
    code that changed is the census reading the claim it was sent to read.
    """
    for argv in route_commands(("Route A",)):
        checked(launch(world, argv, world.project), f"Route A command {argv}")
    _committed_double_claim(world.project, world.env)
    code, stdout = _run_route_a(world, _ci_census_command(state=False))
    lines = _assert_verdict(code, stdout, census.CLASS_CODE["session-double"],
                            "the CI census step on a planted double claim")
    assert "session-double" in _verdict_line(lines), lines[-1]


def test_the_ci_step_exits_zero_on_a_clean_route_b_tree(world: World) -> None:
    """Route B's line, with the state clone as ``--repo``, ends verdict ok."""
    code, stdout = _run_route_b(world, _ci_census_command(state=True))
    lines = _assert_verdict(code, stdout, 0, "the CI step on a clean state clone")
    assert _verdict_line(lines).endswith("verdict ok"), lines[-1]


def test_the_ci_step_fails_a_route_b_build_on_a_planted_double_claim(
    world: World,
) -> None:
    """The planted pair goes under the tree Route B's ``--repo`` names.

    The placement is the point: the census reads only the tree ``--repo`` names,
    so a fixture written beside the project instead of inside the clone would exit
    0 here and the test would pass without the census having read anything. The
    decoy half of that claim is the same planted pair left out of the state clone's
    own history by the project's ignore rule.
    """
    _run_route_b(world, _ci_census_command(state=True))
    _committed_double_claim(world.state, world.env)
    argv = _ci_census_command(state=True)
    proc = launch(world, argv, world.project)
    lines = _assert_verdict(proc.returncode, proc.stdout,
                            census.CLASS_CODE["session-double"],
                            "the CI step on a state clone holding a planted "
                            "double claim")
    assert "session-double" in _verdict_line(lines), lines[-1]
    # The project's own tree never carried the pair, which is what the route's
    # ignore rule buys and what the census must not be blamed for missing.
    assert not list((world.project / "noni" / "sessions").glob("*.md")), (
        "the planted claim was written into the code repository, so the route's "
        "--repo no longer decides which tree was read")


# --- the documented sets against the one declaration ------------------------

_FAIL_SET = re.compile(r"\*\*fail the build\*\* on ([\d, and]+);")
_WARN_SET = re.compile(r"\*\*report without failing\*\* on ([\d, and]+)\.")


def _documented_codes(pattern: re.Pattern) -> set[int]:
    """One set of codes as the CI section prints them, read out of the page.

    Located by the bullet's own wording so a rewrite that drops the set fails here
    rather than leaving the agreement test comparing an empty set against the table.
    """
    text = QUICKSTART.read_text(encoding="utf-8")
    match = pattern.search(text)
    assert match, f"the CI section no longer prints its codes as {pattern.pattern!r}"
    codes = {int(token) for token in re.findall(r"\d+", match.group(1))}
    assert codes, f"the documented set is empty: {match.group(1)!r}"
    return codes


def documented_fail_codes() -> set[int]:
    """The codes the page says fail a build."""
    return _documented_codes(_FAIL_SET)


def documented_warn_codes() -> set[int]:
    """The codes the page says a build reports without failing."""
    return _documented_codes(_WARN_SET)


def ci_section() -> str:
    """The CI section's own text, located by its heading.

    Public for the agreement module, which asserts prose promises about this one
    section rather than re-locating it by heading.
    """
    from docs_promises import section_body

    return section_body(QUICKSTART.read_text(encoding="utf-8"), CI[0])
