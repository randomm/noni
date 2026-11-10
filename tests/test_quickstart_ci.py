"""The quickstart's CI section, launched on the scratch topology.

The page tells a team to run one census line in a build and to gate the build on
two sets of exit codes. This module settles that half by running it: each route is
driven twice on the same tree -- once as the page's own steps leave it, where the
documented verdict is exit 0, and once with a violation planted under the ``noni/``
tree that route's ``--repo`` names, where the verdict is the ``ledger-record``
code. The planted shape is the malformed record the exit-code contract test commits
-- a ledger file missing its ``question`` field -- so the exit code here is earned
by the same shape that test pins.

The commands are the page's own: they come from
:func:`quickstart_runner.route_commands`, which compares the page's fences against
:mod:`quickstart_golden` before returning them, and they reach
:func:`quickstart_runner.launch`, which refuses an argv no golden list prints.
Nothing here types a census command of its own.

The page parsers this module used to hold -- :func:`quickstart_ci_page.ci_commands`,
:func:`quickstart_ci_page.documented_fail_codes`,
:func:`quickstart_ci_page.documented_warn_codes`,
:func:`quickstart_ci_page.ci_section` -- live in ``tests/quickstart_ci_page.py``,
the non-test helper the check-contract module imports too, so the launches here and
the table agreement there read the same page through one reader.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import census
import quickstart_ci_page
from _harness import _commit_file
from docs_commands import read
from docs_promises import QUICKSTART, STATE_DIR
from quickstart_ci_page import (
    FAIL_SET_PATTERN,
    WARN_SET_PATTERN,
    ci_commands,
    ci_section,
    documented_fail_codes,
    documented_warn_codes,
)
from quickstart_runner import (
    World,
    checked,
    git,
    launch,
    route_commands,
    run_route_b,
)

# The planted violation: a ledger record missing the field the schema requires.
# It is the shape
# ``tests/test_census_exit_codes_contract.py::test_exit_10_malformed_record``
# commits, so the fixture here is the same violation the exit-code contract
# already pins, not a shape this module invented.
_MALFORMED_RECORD_ID = "2026-10-01-alpha"


def _import_helper_clean(launch_modules: tuple[str, ...]) -> list[str]:
    """The launch-layer modules the page reader pulls in on import, read from its AST.

    The static reading is the honest one: this module is already loaded alongside the
    launch layer by the tests around it, so a ``sys.modules`` probe in-process would
    report the suite's imports and not the helper's own, and a helper that drifted
    into launching would still look clean.
    """
    source = Path(quickstart_ci_page.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return [name for name in imported
            if any(name == module or name.startswith(module + ".")
                   for module in launch_modules)]


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


def _committed_malformed_record(tree: Path, env: dict[str, str]) -> None:
    """Plant the malformed record under ``tree`` and commit it, as a CI checkout has it.

    The file is committed because the census reports the ledger as git sees
    it; an uncommitted file would be a tree no build checks out. The writer is the
    harness's own ``_commit_file`` (one commit, one identity, no GPG), which is what
    ``tests/test_census_exit_codes_contract.py::test_exit_10_malformed_record``
    plants, so the census here reads the same shape that test's exit code is earned
    by.
    """
    record = {"id": _MALFORMED_RECORD_ID, "status": "decided",
              "context": "planted for the CI step", "decision": "planted",
              "rejected": [], "source": "free chat", "confirmed_by": "operator",
              "confirmed_at": "2026-10-01T09:00:00Z", "tags": []}
    _commit_file(tree, f"noni/decisions/{_MALFORMED_RECORD_ID}.json",
                 json.dumps(record, indent=2) + "\n")
    # A leftover worktree entry would be an uncommitted file, and the census reads
    # the ledger as git sees it: the verdict below would then be earned by a tree
    # no CI checkout has. The page's own Route A steps leave the project clean, so
    # this holds whatever the planted record adds.
    dirty = git(tree, "status", "--porcelain", env=env).stdout.splitlines()
    assert not [line for line in dirty if line.strip()], (
        f"planting the malformed record left {tree} dirty: {dirty}")


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


def _verdict_line(lines: list[str], expected_tail: str) -> str:
    """The census's summary line, which the page's whole section is about.

    Absent it the run reported no verdict at all, so both halves of the clean and
    failing pair demand it: a run that counted nothing ends
    ``summary: clean; 0 finding(s); verdict ok`` and a failing one names its
    code and the classes that fired.

    The tail is a parameter rather than an ``endswith`` at each call site, and it
    is checked here, because the human half of the line moved for a warn-bearing
    run (issue #117). A reader that only asserted ``startswith("summary: ")``
    would not notice a rewording that ate into ``verdict ok`` -- the exact word
    the CI step this page documents reads to decide the build.
    """
    assert lines and lines[-1].startswith("summary: "), (
        f"the census printed no summary line: {lines[-1:]!r}")
    assert lines[-1].endswith(expected_tail), (
        f"the census's summary line no longer ends with its machine word "
        f"{expected_tail!r}: {lines[-1]!r}")
    return lines[-1]


# --- the page's step, run ---------------------------------------------------

def test_the_ci_step_exits_zero_on_a_clean_route_a_tree(world: World) -> None:
    """The page's Route A census line, run as printed, ends verdict ok.

    The tree is what the page's own Route A steps leave behind, so the clean half
    is asserted on the tree the reader has, not on an empty directory that would
    pass for the wrong reason. That tree is not a run with nothing to report:
    without a deny-list its census counts warn rows, so the step is pinned to end
    ``verdict ok`` on a warn-bearing run too, which is what the page's "a first
    CI run exits 0" promise is actually made of (issue #117).
    """
    for argv in route_commands(("Route A",)):
        checked(launch(world, argv, world.project), f"Route A command {argv}")
    code, stdout = _run_route_a(world, _ci_census_command(state=False))
    lines = _assert_verdict(code, stdout, 0, "the CI census step on a clean tree")
    line = _verdict_line(lines, "verdict ok")
    assert "warning(s)" in line, (
        f"the page's tree carries warn rows, so the step's summary line should "
        f"name them rather than read all-clear: {line!r}")
    assert not git(world.project, "status", "--porcelain",
                   env=world.env).stdout.splitlines(), (
        "the documented CI step left the tree dirty")


def test_the_ci_step_fails_a_route_a_build_on_a_planted_malformed_record(
    world: World,
) -> None:
    """The same step, same tree, one planted violation: the documented fail code.

    The pair with the test above is the whole of the page's promise: nothing but
    the planted ``noni/decisions`` record differs between the two runs, so the exit
    code that changed is the census reading the ledger it was sent to read.
    """
    for argv in route_commands(("Route A",)):
        checked(launch(world, argv, world.project), f"Route A command {argv}")
    _committed_malformed_record(world.project, world.env)
    code, stdout = _run_route_a(world, _ci_census_command(state=False))
    lines = _assert_verdict(code, stdout, census.CLASS_CODE["ledger-record"],
                            "the CI census step on a planted malformed record")
    assert "ledger-record" in _verdict_line(lines, "; verdict fail"), lines[-1]


def test_the_ci_step_exits_zero_on_a_clean_route_b_tree(world: World) -> None:
    """Route B's line, with the state clone as ``--repo``, ends verdict ok."""
    code, stdout = _run_route_b(world, _ci_census_command(state=True))
    lines = _assert_verdict(code, stdout, 0, "the CI step on a clean state clone")
    assert _verdict_line(lines, "verdict ok"), lines[-1]


def test_the_ci_step_fails_a_route_b_build_on_a_planted_malformed_record(
    world: World,
) -> None:
    """The planted record goes under the tree Route B's ``--repo`` names.

    The placement is the point: the census reads only the tree ``--repo`` names,
    so a fixture written beside the project instead of inside the clone would exit
    0 here and the test would pass without the census having read anything. The
    decoy half of that record is the same planted file left out of the state clone's
    own history by the project's ignore rule.
    """
    _run_route_b(world, _ci_census_command(state=True))
    _committed_malformed_record(world.state, world.env)
    argv = _ci_census_command(state=True)
    proc = launch(world, argv, world.project)
    lines = _assert_verdict(proc.returncode, proc.stdout,
                            census.CLASS_CODE["ledger-record"],
                            "the CI step on a state clone holding a planted "
                            "malformed record")
    assert "ledger-record" in _verdict_line(lines, "; verdict fail"), lines[-1]
    # The project's own tree never carried the record, which is what the route's
    # ignore rule buys and what the census must not be blamed for missing.
    assert not list((world.project / "noni" / "decisions").glob("*.json")), (
        "the planted record was written into the code repository, so the route's "
        "--repo no longer decides which tree was read")


def test_the_documented_ci_set_bullets_are_the_ci_section_s_only_two() -> None:
    """The two set bullets the reader gates a build on live in the CI section.

    The launches above earn the exit codes; this settles where the page is allowed
    to state them. The reader of the helper parses the CI section alone and insists
    on exactly one bullet per set, so a third bullet -- with invented codes, beside
    any heading -- is a failure rather than a second copy nobody compares. The
    second half is the cheap one and the reason it is asserted here rather than
    trusted: without it, narrowing the helper's parse to one section could have
    quietly dropped both bullets and left the agreement tests comparing an empty
    set, which is the same shape as a page that never documented a set at all.
    """
    body = ci_section()
    bullets = [line.strip() for line in body.splitlines()
               if line.strip().startswith("- **")]
    assert len(bullets) == 2, (
        f"the CI section must gate a build on exactly two documented sets, found "
        f"{len(bullets)}: {bullets}")
    assert documented_fail_codes(), "the CI section documents no fail set"
    assert documented_warn_codes(), "the CI section documents no warn set"
    # The scoping half, stated over the whole page. Narrowing the reader to the CI
    # section is what stops a stray bullet elsewhere being read as this section's
    # set; it is also why a second set written outside the section would otherwise
    # go unnoticed -- the fence census and the golden comparison cover the page's
    # commands, not its bullets. A reader who found a second pair in another section
    # would have nothing to tell them which governs, so the page gets exactly two.
    page_lines = read(QUICKSTART).splitlines()
    strays = [line.strip() for line in page_lines
              if FAIL_SET_PATTERN.search(line) or WARN_SET_PATTERN.search(line)]
    assert len(strays) == 2, (
        f"the page must state its two gate sets in the CI section and nowhere "
        f"else; found {len(strays)} set bullets: {strays}")
    assert all(line in bullets for line in strays), (
        f"a set bullet sits outside the CI section: {set(strays) - set(bullets)}")


def test_the_page_reader_pulls_no_launch_layer_in() -> None:
    """Importing the page reader is an import of the page readers, nothing more.

    The reason the four parsers left this module is that
    ``tests/test_census_check_contract.py`` -- a contract test that runs no command
    -- had to reach them, and reaching them through this module dragged the launch
    layer and the session-scoped fixtures of ``conftest`` into it. The split only
    buys what it claims if the helper stays launch-free, which is a property of the
    helper's imports and so belongs to the suite rather than to a docstring: a later
    edit that reaches for :func:`quickstart_runner.launch` here would quietly undo
    the split, and every test in the contract module would still be green.
    """
    launched = ("quickstart_topology", "quickstart_page_steps", "_harness")
    observed = _import_helper_clean(launched)
    assert not observed, (
        f"tests/quickstart_ci_page.py pulls the launch layer in on import: "
        f"{observed}; the contract module that reads the documented sets would then "
        "need the fixtures no contract test uses")



