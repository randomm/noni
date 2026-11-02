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

import re
from pathlib import Path

import pytest
from _harness import REPO
from docs_commands import comment_lines, fenced_blocks, placeholder_words, read
from docs_promises import (
    DENYLIST_STATES,
    QUICKSTART,
    STATE_DIR,
)
from harness_runners import run_noni
from quickstart_runner import (
    World,
    build_world,
    git,
    launch,
    reroot_state_git,
    route_commands,
    words,
)
from quickstart_runner import checked as _checked

# A fixed clock for the ordering run that reads the recipe's map: the ordering
# group's stale class is time-based, and a run without --now would let the host
# clock decide whether the fixture's confirmed stamps read as stale.
ORDERING_NOW = "2026-10-27T12:00:00Z"

# The two runs of item 5 compare one tree's plain and ``--json`` output; the note
# they are compared on is read out of the product by ``_note_from_product``.


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
        if words(argv)[:2] == ("noni", "register"):
            world.collect_session_id()

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
    # The page promises the first push makes every later push and pull work
    # "without naming the remote again", and `-u` is the whole of that promise.
    # An exit-0 push proves nothing about the tracking branch, so the upstream
    # the clone itself reports is read here: a push that lost its -u would leave
    # the writers' later ``--push`` with no branch to name.
    upstream = git(world.state, "rev-parse", "--abbrev-ref", "--symbolic-full-name",
                   "@{u}", env=world.env)
    _checked(upstream, "the state clone's upstream after the page's first push")
    assert upstream.stdout.strip() == "origin/main", (
        f"the page's first push did not set the branch's upstream to origin/main, "
        f"so the later --push runs have no remote-tracking branch: "
        f"{upstream.stdout!r} {upstream.stderr!r}")
    assert [a for a in commands if words(a)[:2] == ("noni", "census")], \
        "the Route B block never runs the census"


def test_the_state_route_leaves_the_origin_holding_the_writers_commits(world: World) -> None:
    """The record the state route writes is reachable on the origin once pushed.

    The page's first-push promise is only worth anything if a later clone of that
    branch sees the ledger; a run that committed locally and never landed anywhere
    would pass the exit-code assertions above.
    """
    for argv in route_commands("Route B"):
        proc = launch(world, argv, world.project, state=True)
        _checked(proc, f"Route B command {argv}")
        if words(argv)[:2] == ("noni", "register"):
            world.collect_session_id()
    pushed = git(world.origin, "ls-tree", "--name-only", "main", env=world.env)
    _checked(pushed, "origin main tree")
    assert "noni" in pushed.stdout.split(), (
        f"the state branch holds no noni/ directory: {pushed.stdout!r}"
    )


def test_the_ordering_note_appears_in_human_mode_and_not_in_json(world: World) -> None:
    """The page's claim about the ``--json`` stream, observed on the Route A tree.

    The page tells the reader the census says out loud that ``ordering-closed``
    was not evaluated, and that ``--json`` mode prints no such line. Both halves
    are about output, so both are read from two runs of the same census over the
    same tree: the note is there without ``--json`` and absent with it, and the
    JSON run still reaches its verdict line in the summary row. A page that
    claimed the opposite (or dropped the human-mode half) fails here.
    """
    for argv in route_commands("Route A"):
        _checked(launch(world, argv, world.project), f"Route A command {argv}")

    plain = run_noni("census", "--repo", str(world.project), "--only", "ordering-closed",
                     cwd=world.project, env=world.env)
    _checked(plain, "the plain census run")
    note = _note_from_product()
    assert note in plain.stdout, (
        f"the census does not print the note the page quotes it as printing: "
        f"{plain.stdout!r}")

    as_json = run_noni("census", "--repo", str(world.project), "--only",
                      "ordering-closed", "--json", cwd=world.project, env=world.env)
    _checked(as_json, "the --json census run")
    assert note not in as_json.stdout, (
        f"--json mode prints the note the page says it never prints: "
        f"{as_json.stdout!r}")
    assert as_json.stdout.strip(), "--json mode printed no stream at all"



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

def _note_from_product() -> str:
    """The ordering-closed note, assembled from the census's own source.

    The sentence is written in the run's body across two string literals, so this
    reads the print call out of ``census_run.py`` and joins them. Quoting the
    literal here instead would let the page and this test agree with each other
    while both drifted away from the tool.
    """
    source = (REPO / "src" / "noni" / "census_run.py").read_text(encoding="utf-8")
    match = re.search(r'print\("(note: ordering-closed was not evaluated[^"]*)"\s*'
                      r'([^)]*)\)', source, re.S)
    assert match, "the census no longer prints the ordering-closed note this test cites"
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(0))
    assert parts and parts[0].startswith("note: ordering-closed was not evaluated"), parts
    return "".join(parts)


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
