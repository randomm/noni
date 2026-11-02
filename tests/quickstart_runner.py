"""Launching the quickstart's golden commands in the topology its page describes.

Three layers, each readable on its own: ``docs_commands`` / ``docs_promises`` parse
the page, :mod:`quickstart_golden` states what the page must print, and
:mod:`quickstart_topology` builds the trees. This module is the dispatch between a
golden command and an ``exec``: it checks the page against the golden list, then
applies the two moves the harness must make because it cannot be the reader's
machine, and nothing else.

The two moves, and why each is a plain mapping rather than a rule with a defence
beside it:

- **Placeholder substitution.** ``<record-id>`` is the id the reader reads off the
  ``decide`` line's own output, and ``<session-id>`` is the id ``register`` printed,
  so the harness reads the second off the file that line committed. Applied token
  by token, never by rejoining the line: one argv entry holds spaces the reader
  quoted (``q1=Wait a week``), and a join-and-resplit would hand the program those
  words separately -- a different command from the one on the page.
- **Re-rooting.** The page names the state clone by its path *inside* the project
  (``.noni-state``) and the scratch project lives at a generated path, so the value
  of ``-C`` / ``--repo`` becomes the clone's real path. Only that value moves;
  every other token stays as printed, so a wrong verb or flag still fails the way a
  reader would see it.

Both moves are applied **after** the golden comparison, and only to commands the
comparison accepted. That ordering is the whole simplification: a move cannot be
tricked into addressing the wrong tree, because the argv it may touch is one of the
literal lists in :mod:`quickstart_golden`.

Two page steps are not commands a reader's shell ran, so the launcher asserts them
instead of exec'ing them: the ``cd`` into a directory the page cannot name (every
launched command already carries the cwd the harness chose), and the ``echo ... >>
.gitignore`` line, whose payload is written to the scratch project's ignore file --
this repository's own ``.gitignore`` is a gate file no test may modify. The install
section's ``git clone`` and ``pip install`` are the fixture's materialised clone and
its venv install (see :mod:`quickstart_topology`); the ``gh`` recipe is run through
``jq`` by the issue-state test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from docs_promises import STATE_DIR
from quickstart_golden import GOLDEN
from quickstart_topology import (
    CLONE_URL,
    READER_DIR,
    World,
    build_installed_world,
    checked,
    fresh_scratch,
    git,
    run_env,
)

__all__ = [
    "ORDERING_NOW",
    "PLACEHOLDER_VALUES",
    "World",
    "build_installed_world",
    "checked",
    "fresh_scratch",
    "git",
    "golden",
    "launch",
    "recipe_gh_argv",
    "reroot",
    "route_commands",
    "run_env",
    "run_route_b",
    "state_dir_commands",
    "substitute",
]

# A fixed clock for the ordering runs the quickstart's tests make: the ordering
# group's stale class is time-based, and a run without --now would let the host
# clock decide whether a fixture's confirmed stamps read as stale. One owner for
# both quickstart test modules, so the pair cannot drift to different instants.
ORDERING_NOW = "2026-10-27T12:00:00Z"

# The placeholders the page asks the reader to fill from their own run, mapped to
# the value the harness plants. ``<session-id>`` is not here: its value comes from
# the running tree (see ``World.collect_session_id``), and a fixed value would name
# a file the register line cannot have made.
PLACEHOLDER_VALUES = {
    "<record-id>": "2026-11-02-release-scope",
}

# Every command of the golden list, flattened: the literal set :func:`launch`
# compares its argv against before the two moves below touch it, so a command no
# section prints never reaches an exec.
_ALL_GOLDEN: list[list[str]] = [argv for label in GOLDEN for argv in GOLDEN[label]]


def golden(label: tuple[str, ...]) -> list[list[str]]:
    """The literal commands the golden list pins for one page section."""
    commands = GOLDEN[label]
    assert commands, f"the golden list pins no commands for the '{label[0]}' section"
    return commands


def route_commands(label: tuple[str, ...]) -> list[list[str]]:
    """The page's commands for one section, checked against the golden list.

    Parsed from the page's own fences and compared to the literal list before
    anything is returned, so every caller of this helper runs the page it reviewed:
    a command added, dropped, reordered or reworded fails here, naming the section,
    rather than launching something nobody read.
    """
    from docs_commands import block_commands
    from docs_promises import QUICKSTART, bash_blocks_text, section_body

    body = section_body(QUICKSTART.read_text(encoding="utf-8"), label[0])
    commands = [argv for block in bash_blocks_text(body)
                for argv in block_commands(block)]
    expected = golden(label)
    assert commands == expected, (
        f"docs/QUICKSTART.md no longer prints the '{label[0]}' commands the harness "
        f"pins, in this order:\n  page: {commands}\n  golden: {expected}\n"
        "A page change is reviewed by updating tests/quickstart_golden.py.")
    return commands


def substitute(argv: list[str], extra: dict[str, str] | None = None) -> list[str]:
    """Fill the page's placeholders with the values the reader would supply."""
    values = {**PLACEHOLDER_VALUES, **(extra or {})}
    return [values.get(token, token) for token in argv]


def reroot(argv: list[str], state: Path) -> list[str]:
    """Point one golden command's state path at the real clone.

    The page writes ``git -C .noni-state <verb> ...`` and ``noni ... --repo
    .noni-state ...`` from the project's root, which is what a reader types; the
    harness knows where the project sits and the page cannot. Only the value of the
    anchor moves.

    The preconditions the mapping is defined over are asserted here rather than
    assumed from the list it happens to run on: a command that names the state
    directory as a whole token must name it exactly once, and exactly as the value of
    the one ``-C`` / ``--repo`` anchor being moved. A golden line that broke either
    shape would leave the mapping guessing which of two tokens to move, so it raises
    instead. The page's ``git clone`` of the state repository is the one golden
    command exempted: it names the directory as its target and the launcher handles
    it before this mapping, in :func:`state_clone`.
    """
    anchors = [position for position, token in enumerate(argv)
               if token in ("-C", "--repo") and position + 1 < len(argv)
               and argv[position + 1] == STATE_DIR]
    if STATE_DIR in argv and argv[1:2] != ["clone"]:
        # The page's state ``git clone`` is the one golden command that names the
        # directory as its own target rather than as an anchor value; the launcher
        # dispatches it before it ever reaches this mapping (see ``state_clone``).
        assert argv.count(STATE_DIR) == 1, (
            f"a command names the state directory more than once, so the re-rooting "
            f"has no single value to move: {argv}")
        assert len(anchors) == 1, (
            f"the command names the state directory outside a -C/--repo value, so "
            f"there is no anchor to move: {argv}")
    elif any(token in ("-C", "--repo") for token in argv):
        assert not anchors, f"an anchor names the state directory: {argv}"
    if not anchors:
        return list(argv)
    position = anchors[0]
    return [*argv[:position + 1], str(state), *argv[position + 2:]]


def state_dir_commands() -> list[list[str]]:
    """Every golden command that names the state clone as the tree itself.

    A whole-token mention, so the page's two other references to the directory (the
    ignore-rule payload ``/.noni-state/`` and nothing else) are not confused with a
    path the writer opens. These are the commands the re-rooting is defined over,
    and the ones the test over the golden list checks: each names the clone exactly
    once, and the ones the launcher moves name it exactly as the value of one of the
    two anchors it understands (``git -C <clone>``, ``noni ... --repo <clone>``).
    The clone line carries the directory as its target and is asserted where it is
    dispatched, in :func:`state_clone`.
    """
    return [argv for label in GOLDEN for argv in GOLDEN[label]
            if STATE_DIR in argv]


def recipe_gh_argv() -> list[str]:
    """The page's ``gh issue list`` recipe line, as the golden list prints it."""
    from quickstart_golden import ISSUE_STATE

    argv = [command for command in golden(ISSUE_STATE) if command[0] == "gh"]
    assert len(argv) == 1, f"the page must print exactly one gh recipe: {argv}"
    return argv[0]


def run_route_b(world: World) -> list[list[str]]:
    """Every Route B command the page prints, launched in order and checked.

    The one walk every Route B test drives: the project's git identity comes from the
    page's own Route A config lines (Route B's ignore-rule line writes into the
    project, and ``git status`` there reports an untracked ``.gitignore`` unless the
    tree has an identity), the register line's session id has to be read off disk
    *after* that line and *before* the claim line that names it, and the snapshot
    that makes that read mean "this run added one" has to be taken before register
    ran. Two copies of that sequence drift -- one drops the snapshot, the other gains
    a config call the page never printed -- and then the two modules stop running the
    same route.
    """
    _checked_identity(world)
    commands = route_commands(("Route B",))
    for argv in commands:
        if argv[:2] == ["noni", "register"]:
            world.mark_sessions()
        proc = launch(world, argv, world.project)
        checked(proc, f"Route B command {argv}")
        if argv[:2] == ["noni", "register"]:
            world.collect_session_id()
    return commands


def _checked_identity(world: World) -> None:
    """The project's git identity, from the page's own Route A config lines.

    Not a fixture identity: the page sets the identity in the section this walk does
    not run, and a harness identity would hide a page that forgot to set one.
    """
    for argv in route_commands(("Route A",)):
        if argv[:2] == ["git", "config"]:
            checked(run_git_config(world, argv, world.project),
                    f"Route A identity line {argv}")


def run_git_config(world: World, argv: list[str],
                   cwd: Path) -> subprocess.CompletedProcess[str]:
    """One ``git config`` line of the page, addressed at ``cwd``.

    The page types these from the project root, where bare ``git config`` reads the
    project's config; the harness's cwd is the scratch project, so the line runs with
    an explicit ``-C`` for that tree and its words otherwise verbatim.
    """
    return git(cwd, *argv[1:], env=world.env)


def launch(world: World, argv: list[str],
           cwd: Path) -> subprocess.CompletedProcess[str]:
    """One golden command, in the topology the page describes.

    Order matters: the argv is a golden one (the caller got it from
    :func:`route_commands`, which compared it), so the moves below are applied to a
    known list, and the program a ``noni`` line names is the console script the
    fixture's install produced.
    """
    assert argv in _ALL_GOLDEN, (
        f"launch() was handed an argv no golden list prints: {argv}")
    if argv[0] == "cd":
        # The one step into a directory the page cannot name: every launched command
        # already runs with the cwd the page's cd would have landed in.
        assert argv == ["cd", READER_DIR], (
            f"the page's cd must name the placeholder for the reader's own "
            f"repository ({READER_DIR}): {argv}")
        return subprocess.CompletedProcess(argv, 0, "", "")
    if argv[0] == "echo":
        return append_ignore_rule(world, argv)
    if argv[0] == "git" and argv[1] == "clone":
        return state_clone(world, argv)
    argv = reroot(substitute(argv, world.placeholders), world.state)
    program = str(world.noni) if argv[0] == "noni" else argv[0]
    return _exec(program, argv, cwd, world.env)


def _exec(program: str, argv: list[str], cwd: Path,
          env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """One page command under the launch env, with a hang named as the command."""
    try:
        return subprocess.run([program, *argv[1:]], cwd=cwd, capture_output=True,
                              text=True, env=env, timeout=180)
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - a hung command
        pytest.fail(f"page command hung: {argv}\n{exc}")


def append_ignore_rule(world: World,
                       argv: list[str]) -> subprocess.CompletedProcess[str]:
    """The page's ``echo ... >> .gitignore`` line, applied to the scratch tree.

    The payload is taken from the golden list and written to the scratch project's
    ignore file: this repository's own ``.gitignore`` is a gate file, so the line
    cannot be replayed by a shell in the tree the tests run from.
    """
    entry = argv[1].strip()
    assert entry.startswith("/") and entry.endswith("/"), (
        f"the ignore rule is not a rule for a directory: {argv}")
    assert STATE_DIR in entry, f"the ignore rule does not name the state directory: {argv}"
    assert argv[2:] == [">>", ".gitignore"], (
        f"the ignore-rule line writes somewhere other than .gitignore: {argv}")
    (world.project / ".gitignore").write_text(entry + "\n", encoding="utf-8")
    return subprocess.CompletedProcess(argv, 0, "", "")


def state_clone(world: World, argv: list[str]) -> subprocess.CompletedProcess[str]:
    """The page's state-repository clone, run for real against the fixture's origin.

    The page prints two clones and they stand for different things. The install
    section's clone of noni is the fixture's materialised copy (its URL is the
    OWNER placeholder, and the run stays offline); the state section's clone of the
    private repository is launched against the bare origin the fixture seeded, so
    the branch, the upstream and the pushed commits the tests read afterwards are
    the product of the line the page prints.
    """
    if CLONE_URL in " ".join(argv):
        assert argv[2] == "https://github.com/OWNER/noni" and argv[3] == "noni", (
            f"the install clone must name the page's placeholder URL: {argv}")
        return subprocess.CompletedProcess(argv, 0, "", "")
    assert argv[2].endswith(".git") and argv[3] == STATE_DIR, (
        f"the page's state clone must name the {STATE_DIR} target: {argv}")
    return git(world.project, "clone", "-q", str(world.origin), STATE_DIR,
               env=world.env)
