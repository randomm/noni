"""The quickstart's promises, run for real.

``docs/QUICKSTART.md`` is the page a new team follows when the README's five
minutes are not enough: it carries the install forms (there is no package index
to install from), both state-root routes, the ignore rule, the one-time first
push, the deny-list file and the ``--issue-state`` recipe. The enforcement rule
of ``docs/PRODUCT.md`` §6 says prose is convention, not enforcement, so this
module reads the page as data and runs it: every fenced command in every route is
launched against a tree the page describes, and each has to exit 0.

The three layers are separate, each on the seam that makes the other two
readable: ``docs_commands`` and ``docs_promises`` turn the page into argv over a
declared set of files, ``quickstart_runner`` builds the trees and launches one
argv, and this module holds only what the page claims. What each test pins, and
why only this test can:

- the commands are the page's own, parsed out of its fences, so a rewrite that
  quietly drops the ``git push -u`` step or the ignore rule fails here rather
  than leaving a reader to discover it;
- the placeholders the page asks the reader to fill are substituted with real
  values, not deleted: a command that only works because a flag went missing is
  not the command on the page;
- the ``--issue-state`` recipe is run through ``jq`` and handed to the census's
  own reader, so the two shapes it refuses -- a padded or numeric key, a state
  word it may not name -- cannot come back into the recipe unnoticed;
- the deny-list section names the file, its location, and the fact that a file
  holding only blanks and comments is still inactive: the state a reader who
  "just created the file" lands in and cannot explain from the census row.

The launches run in throwaway trees under ``tmp_path`` with no ambient git state,
exactly like the README try-it harness, and never touch this repository.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from _harness import REPO
from docs_commands import comment_lines, fenced_blocks, placeholder_words, read
from docs_promises import (
    DENYLIST_STATES,
    ISSUE_STATE_RECIPE,
    QUICKSTART,
    STATE_DIR,
)
from quickstart_runner import (
    World,
    build_world,
    git,
    launch,
    route_commands,
    run_env,
    words,
)
from quickstart_runner import (
    checked as _checked,
)


@pytest.fixture
def world(tmp_path: Path) -> World:
    """The page's topology, standing and installed: clone, project, state origin."""
    return build_world(tmp_path)


def _page() -> str:
    return read(QUICKSTART)


# --- The page's shape -------------------------------------------------------

def test_the_quickstart_page_is_linked_and_within_its_size():
    """The page exists, the README names it by exact path, and it stays short.

    The README's own gate caps that page at 150 lines, so the quickstart earns
    its keep only by being short enough to read after the README: 400 is the
    cap ``tests/test_skill_scrub.py`` sets on a SKILL.md, and this is a page a
    reader is meant to finish.
    """
    assert QUICKSTART.is_file(), "docs/QUICKSTART.md is missing"
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "docs/QUICKSTART.md" in readme, "README does not link the quickstart"
    lines = _page().count("\n")
    assert lines <= 400, f"docs/QUICKSTART.md is {lines} lines; the cap is 400"


def test_the_page_covers_both_routes_the_issue_named():
    """Both state routes are named with their commands, not just described.

    The default route is in-project state; the second is a private state
    repository cloned inside the project as ``.noni-state`` with an ignore rule
    and a one-time first push. A page that dropped the ignore rule or the push
    would still read well and still leave a reader with a writer that fails.
    """
    text = _page()
    lowered = text.lower()
    for phrase in ("noni/", STATE_DIR):
        assert phrase in text, f"the quickstart does not name {phrase!r}"
    assert "gitignore" in lowered, "the ignore rule is not on the page"
    assert "push -u origin" in text, "the one-time first push is not on the page"
    assert "--repo " + STATE_DIR in text, "the state-repo route has no --repo form"


def test_no_comment_line_is_a_command_the_page_means_to_run():
    """The comment exemption cannot hide a real command.

    The runner skips lines beginning ``#`` because a shell never runs those. If
    a placeholder of the page's own ever landed inside such a line, the
    substitution in the launcher would silently stop covering it, so the shape of
    the block is checked rather than trusted.
    """
    for block in fenced_blocks(_page(), info="bash"):
        for line in comment_lines(block):
            assert not placeholder_words(line), (
                f"a placeholder sits in a comment line, which the runner skips: {line!r}"
            )


def test_the_page_names_no_other_interpreter_for_a_shell_wrapper():
    """The bash shims are never shown under ``python3`` on this page.

    ``skills/*/scripts/census.sh`` and ``census-sessions.sh`` are bash scripts;
    the interpreter they exec is their own business. A page that showed
    ``python3 <path>.sh`` would hand the reader a traceback, and the README's
    python3 launches are all ``.py`` entry points. The same rule over every page
    in scope is ``tests/test_docs_invocation.py``; this one is the page whose
    commands are launched here.
    """
    offenders = [line for block in fenced_blocks(_page(), info=None) for line in block
                 if re.search(r"python3?\s+\S*\.sh\b", line)]
    assert not offenders, f"the page runs a shell script under python3: {offenders}"


# --- The page's commands, run ------------------------------------------------

def test_route_a_commands_all_exit_zero(world: World) -> None:
    """Every command of the in-project route runs and exits 0, and the outcome
    the page claims for it is there: one committed record, a census that ends
    with its verdict line, and a project tree the census left clean."""
    commands = route_commands("Route A")
    assert commands, "the quickstart no longer has a Route A command block"
    census_lines: list[str] = []
    for argv in commands:
        proc = launch(world, argv, world.project)
        _checked(proc, f"Route A command {argv}")
        if words(argv)[:2] == ("noni", "census"):
            census_lines = proc.stdout.splitlines()
    assert census_lines, "the Route A block never runs the census"
    assert census_lines[-1].startswith("summary: ") and census_lines[-1].endswith(
        "verdict ok"), f"the census did not end with its verdict line: {census_lines[-1:]!r}"
    records = sorted((world.project / "noni" / "decisions").glob("*.json"))
    assert len(records) == 1, f"expected one record, got {[p.name for p in records]}"
    head = git(world.project, "log", "--oneline", env=world.env).stdout
    assert records[0].stem in head, f"the record is not committed: {head!r}"
    dirty = git(world.project, "status", "--porcelain", env=world.env).stdout.splitlines()
    assert dirty == [], f"the documented path left the tree dirty: {dirty}"


def test_route_b_commands_all_exit_zero(world: World) -> None:
    """Every command of the private-state-repo route runs and exits 0.

    This is the route the README cannot carry: a second clone inside the
    project, an ignore rule, a first push, and then the same writers with
    ``--repo .noni-state``. Each of those steps is a place the page can be
    subtly wrong -- a push before the branch exists, an ignore rule that ignores
    the wrong path, a writer pointed at the project instead of the state clone --
    and each is observed here rather than assumed.
    """
    commands = route_commands("Route B")
    assert commands, "the quickstart no longer has a Route B command block"
    for argv in commands:
        proc = launch(world, argv, world.project, state=True)
        _checked(proc, f"Route B command {argv}")

    assert (world.state / "noni" / "decisions").is_dir(), "no ledger under the state clone"
    assert (world.project / ".gitignore").is_file(), "the ignore rule was never written"
    assert STATE_DIR + "/" in (world.project / ".gitignore").read_text(encoding="utf-8"), \
        "the ignore rule does not name the state directory"
    status = git(world.project, "status", "--porcelain", env=world.env)
    _checked(status, "project status")
    assert STATE_DIR not in status.stdout, (
        f"the state clone is visible to the project's git, so the ignore rule "
        f"is not doing its job: {status.stdout!r}"
    )
    _checked(git(world.origin, "rev-parse", "--verify", "main", env=world.env),
             "the state branch on the origin")
    assert [a for a in commands if words(a)[:2] == ("noni", "census")], \
        "the Route B block never runs the census"


def test_the_state_route_leaves_the_origin_holding_the_writers_commits(world: World) -> None:
    """The record the state route writes is reachable on the origin once pushed.

    The page's first-push promise is only worth anything if a later clone of that
    branch sees the ledger; a run that committed locally and never landed anywhere
    would pass the exit-code assertions above.
    """
    for argv in route_commands("Route B"):
        launch(world, argv, world.project, state=True)
    pushed = git(world.origin, "ls-tree", "--name-only", "main", env=world.env)
    _checked(pushed, "origin main tree")
    assert "noni" in pushed.stdout.split(), (
        f"the state branch holds no noni/ directory: {pushed.stdout!r}"
    )


def test_the_issue_state_recipe_produces_a_map_the_census_accepts(tmp_path: Path) -> None:
    """The gh + jq recipe on the page is run, not quoted.

    ``jq`` is invoked with the page's own filter over a payload shaped like the
    tracker's output (issue numbers as numbers, states upper-case), and the result
    is fed through the census's own reader. The two refusals that reader makes -- a
    key that is not the bare decimal spelling, a state word outside the two it
    names -- are the reason the filter carries ``tostring`` and ``ascii_downcase``,
    so both are checked here with the filter removed: a recipe that lost either
    would pass a reading test and fail a reader.
    """
    from noni.census_ordering import ISSUE_STATE_STATES
    from noni.census_ordering_readers import load_issue_state

    filter_text = _issue_state_filter()
    payload = tmp_path / "issues.json"
    payload.write_text(json.dumps([{"number": 7, "state": "CLOSED"},
                                   {"number": 12, "state": "OPEN"}]), encoding="utf-8")
    proc = _jq(filter_text, payload)
    _checked(proc, "the page's jq recipe")
    map_path = tmp_path / "issue-state.json"
    map_path.write_text(proc.stdout, encoding="utf-8")
    result = load_issue_state(map_path, ISSUE_STATE_STATES, _file_kind, _identity,
                              _strict_json)
    assert result.problem is None, f"the census refuses the page's map: {result.problem}"
    assert result.map == {"7": "closed", "12": "open"}, result.map

    # Without tostring the keys arrive as numbers and the reader refuses them;
    # without ascii_downcase the state words do. Both are the recipe's job.
    for name, broken in (("tostring", filter_text.replace(".number | tostring", ".number")),
                         ("ascii_downcase",
                          filter_text.replace(".state | ascii_downcase", ".state"))):
        _assert_broken_filter(tmp_path, name, broken, payload)


def _assert_broken_filter(tmp_path: Path, name: str, broken: str, payload: Path) -> None:
    """One variant of the recipe, with one required conversion removed.

    A filter that breaks ``jq`` outright is the same failure to the reader as one
    that emits a map the census refuses: no usable file. The empty document is
    what jq leaves behind, and the census calls that a map that answers nothing,
    so it counts as a refusal for the same reason -- the recipe did not produce
    the map the page promises.
    """
    from noni.census_ordering import ISSUE_STATE_STATES
    from noni.census_ordering_readers import load_issue_state

    filter_text = _issue_state_filter()
    assert broken != filter_text, f"the page's filter no longer names {name}"
    faulty = _jq(broken, payload)
    assert faulty.returncode != 0 or faulty.stdout.strip() not in ("", "{}", "{\n}"), (
        f"the recipe without {name} produced no usable map either: "
        f"rc={faulty.returncode} stderr={faulty.stderr.strip()!r}"
    )
    bad = tmp_path / f"bad-{name}.json"
    bad.write_text(faulty.stdout, encoding="utf-8")
    verdict = load_issue_state(bad, ISSUE_STATE_STATES, _file_kind, _identity, _strict_json)
    assert verdict.problem is not None or verdict.map != {"7": "closed", "12": "open"}, (
        f"a filter without {name} still produced the map the page promises, so "
        f"the assertion above pins nothing"
    )


def test_the_page_says_what_is_skipped_without_the_state_file() -> None:
    """The page states the census's own note text, and that it is human-readable
    output only.

    The census prints the note on stdout in human mode and nothing in ``--json``
    mode; a reader told only that "the check does not run" will go looking for it
    in a ``--json`` stream and conclude the census is silent. The literal is the
    product's own, so a rename of the note fails here rather than leaving the page
    quoting a line nobody prints.
    """
    source = (REPO / "src" / "noni" / "census_run.py").read_text(encoding="utf-8")
    assert "ordering-closed was not evaluated" in source, "the note left the product"
    text = _page()
    assert "ordering-closed was not evaluated" in text, "the page does not name the note"
    assert "never contacts a tracker" in text, "the page does not say why"
    assert "json" in text.lower(), "the page does not say the note is human-mode only"


def test_the_page_names_the_deny_list_a_strict_run_needs() -> None:
    """Where the page meets --strict and the hygiene class, it names the file.

    The name, the location and the purpose, plus the state a reader who "just
    created the file" lands in: a file of blanks and comments only is still
    inactive. The name is read from the product's own constant, so a rename fails
    the page rather than letting it document a file that no longer exists.
    """
    from noni import public_safety

    text = _page()
    assert public_safety.DENYLIST_FILENAME in text, (
        f"the page does not name {public_safety.DENYLIST_FILENAME!r}")
    assert public_safety.DENYLIST_ENV_VAR in text, (
        f"the page does not name the {public_safety.DENYLIST_ENV_VAR} route")
    assert public_safety.default_denylist_file(REPO).name in text
    lowered = text.lower()
    for phrase in (*DENYLIST_STATES, "#"):
        assert phrase in text or phrase in lowered, (
            f"the deny-list section does not mention {phrase!r}")


def test_the_page_says_no_package_index_carries_noni() -> None:
    """The install prose retracts the package-index claim instead of repeating it.

    ``pip install noni`` does not fail: it installs a different project's wheel
    and leaves the reader with a ``noni`` that has no census in it. The page has to
    say so, and give the two forms that do work.
    """
    lowered = _page().lower()
    assert "not published" in lowered, "the page does not say noni is absent from the index"
    assert "pip install ./noni" in _page(), "the page gives no install form naming the clone"
    assert "PYTHONPATH" in _page(), "the page does not name the PYTHONPATH route"


def test_the_page_names_the_three_prerequisites() -> None:
    """jq, an identity in the state tree, and a Python 3 the wrapper can exec.

    Each one decides whether a first run works, and none of them is something noni
    can check for the reader before they type the command.
    """
    text = _page()
    assert "jq" in text, "the page does not name jq"
    assert "user.name" in text and "user.email" in text, "the page omits the git identity"
    assert "NONI_PYTHON" in text, "the page does not name the wrapper's interpreter variable"


# --- helpers used only by this module ---------------------------------------

def _jq(filter_text: str, payload: Path):
    import subprocess

    return subprocess.run(["jq", filter_text, str(payload)], capture_output=True,
                          text=True, env=run_env(), timeout=60)


def _file_kind(path: Path) -> tuple[str, str | None]:
    if path.is_symlink():
        return "symlink", "a symlink, which the census will not follow"
    if path.is_dir():
        return "directory", "a directory"
    if not path.exists():
        return "absent", "no such file"
    return "regular", None


def _identity(text: str) -> str:
    return text


def _strict_json(raw: bytes) -> object:
    from noni.census_json import load_json_strict

    return load_json_strict(raw)


def _issue_state_filter() -> str:
    """The jq filter the page's recipe carries, read out of the page.

    Located by its two obligations: a key built with ``tostring`` and a value
    built with ``ascii_downcase``. A page that reworded the recipe into prose fails
    here rather than letting the recipe test read a filter out of thin air.
    """
    joined = ISSUE_STATE_RECIPE.search(_page())
    assert joined is not None, (
        "the page no longer carries a jq recipe that builds a map with tostring "
        "and ascii_downcase")
    match = re.search(r"'([^']*from_entries[^']*)'", joined.group(0))
    assert match, (
        f"the recipe's filter is not quoted where the page prints it: {joined.group(0)!r}")
    return match.group(1)
