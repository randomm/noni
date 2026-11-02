"""Launching the quickstart's commands, in the topology its page describes.

The reading layer (``docs_commands``, ``docs_promises``) turns the page into argv;
``quickstart_topology`` builds the trees; ``quickstart_gates`` decides what may be
exec'd. This module is the dispatch between them: it takes one parsed command,
re-roots the page's relative paths at the harness's real directories, and runs it.

Split from ``tests/test_quickstart.py`` on the same seam the README harness uses
(``readme_support`` holds the machinery, the test module holds the promises): what
lives here is plumbing and its own preconditions, and the assertions about what the
page claims stay with the tests.

Two rules the dispatcher keeps, because a doc runner that breaks them stops
measuring the page:

- **A command outside the allow-list is refused, not run** -- and the decision is
  taken on the *re-rooted* argv, immediately before the exec, so it is a decision
  about the argv that actually runs.
- **A page line that names the state directory must name it through the one anchor
  the re-rooting understands** (``git -C`` / ``--repo``), or it is refused rather
  than passed through unchanged.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from docs_commands import block_commands
from docs_promises import QUICKSTART, STATE_DIR, bash_blocks_text, section_body
from quickstart_gates import LAUNCHABLE, gate_page_command, guard_route_b_push
from quickstart_topology import (
    CLONE_URL,
    READER_DIR,
    World,
    build_world,
    checked,
    git,
    run_env,
)

__all__ = [
    "ORDERING_NOW",
    "PLACEHOLDER_VALUES",
    "World",
    "build_world",
    "checked",
    "git",
    "launch",
    "reroot_state_git",
    "reroot_state_repo",
    "route_commands",
    "run_env",
    "state_clone",
    "substitute",
    "words",
]

# A fixed clock for the ordering runs the quickstart's tests make: the ordering
# group's stale class is time-based, and a run without --now would let the host
# clock decide whether a fixture's confirmed stamps read as stale. One owner for
# both quickstart test modules, so the pair cannot drift to different instants.
ORDERING_NOW = "2026-10-27T12:00:00Z"

# The placeholders the page asks the reader to fill from their own run, mapped to
# the value the harness plants. A page that adds a third placeholder runs the
# literal, which the census refuses -- so the page cannot gain a placeholder
# without the test that supplies it being updated too.
PLACEHOLDER_VALUES = {
    "<record-id>": "2026-11-02-release-scope",
}

# Characters that mark a token as something other than a command word on this
# page: the README reader's pair, plus the ones this page's remote, URL and
# redirect carry.
_WORD_ENDS: tuple[str, ...] = (".", "/", "@", ":", ">")


def words(argv: list[str]) -> tuple[str, ...]:
    """The program and subcommand words of one quickstart line, by fixed rules.

    The rules are constants of this function's body, not parameters: the allow-list
    is the page's command vocabulary, so a knob that could re-word a line into
    something the vocabulary permits would let the launcher exec what the page never
    printed. The two rules this page needs, and which the README reader
    (``readme_support._block_words``) deliberately does not carry:

    - **An option consumes its value**, so ``git -C .noni-state config user.name
      Casey`` is ``('git', 'config')`` and ``python3 -m pip install`` is
      ``('python3', '-m')``. Without it the token after a flag could be read as the
      subcommand the allow-list decides on.
    - **A token ends the walk** when it carries any of :data:`_WORD_ENDS`, because
      this page prints an scp-style remote, a URL and a redirect.

    The dispatch selects on the program and subcommand without being fooled by an
    argument.
    """
    if not argv:
        return ()
    if argv[0] == "cd":
        return ("cd",)
    if argv[0] == "git" and len(argv) > 1 and argv[1] == "clone":
        return ("git", "clone")
    found: list[str] = [argv[0]]
    index = 1
    while index < len(argv):
        token = argv[index]
        if token.startswith("-"):
            # An option consumes the token after it, unless it carries its own value
            # with ``=``. The message option keeps its word: the gate for the
            # branch-creating line reads it as part of that line's shape.
            index += 1 if (token.startswith("--") and "=" in token) else 2
            if token == "-m":
                found.append(token)
            continue
        if any(part in token for part in _WORD_ENDS):
            break
        found.append(token)
        break
    return tuple(found)


def substitute(argv: list[str], extra: dict[str, str] | None = None) -> list[str]:
    """Fill the page's placeholders with the values the reader would supply.

    Token by token, never by rejoining the line: one argv entry may hold spaces the
    reader quoted (``q1=Wait a week``), and a join-and-resplit would hand the program
    those words as separate arguments -- a different command from the one on the page.

    ``extra`` carries the values a running tree produces rather than a reader typing
    (the session id ``register`` printed, which its own ``claim`` line then names): a
    fixed placeholder there would name a file the register step cannot have made, and
    the launch would fail on the fixture, not on the page.
    """
    values = {**PLACEHOLDER_VALUES, **(extra or {})}
    return [values.get(token, token) for token in argv]


def route_commands(label: str) -> list[list[str]]:
    """The commands of the quickstart section whose heading starts with ``label``.

    Selected by heading rather than by fence position, so a block added at the bottom
    of the page cannot be mistaken for either route's.
    """
    body = section_body(QUICKSTART.read_text(encoding="utf-8"), label)
    return [argv for block in bash_blocks_text(body) for argv in block_commands(block)]


def launch(world: World, argv: list[str], cwd: Path, *,
           state: bool = False) -> subprocess.CompletedProcess[str]:
    """One page command, in the topology the page describes.

    ``noni`` is the console script the page's install step produced; ``git``
    addressed to the state clone is re-rooted at the real directory; ``cd`` names a
    directory the page cannot know and so is asserted rather than run, because every
    launched command already carries the cwd the harness chose; the ignore-rule line
    appends to the scratch project's ``.gitignore``. A placeholder is substituted with
    the value the reader would fill in. A word outside the allow-list is refused, so a
    block that gained a command the page does not mean fails instead of running it.
    """
    argv = substitute(argv, getattr(world, "placeholders", None))
    key = words(argv)
    assert key in LAUNCHABLE, (
        f"the page prints a command this harness will not run: {argv}")
    if key == ("cd",):
        # The one step into a directory the page cannot name: the harness runs every
        # command with the cwd the page's cd would have landed in, so the line is
        # asserted rather than attempted.
        assert argv[1:] == [READER_DIR], (
            f"the page's cd must name the placeholder for the reader's own "
            f"repository ({READER_DIR}): {argv}")
        return subprocess.CompletedProcess(argv, 0, "", "")
    if key == ("echo",):
        return append_ignore_rule(world, argv)
    if key == ("git", "clone"):
        return state_clone(world, argv, state)
    if argv[0] == "git":
        # Re-root a clone-addressed git line at the real state directory: the page
        # names it by its path inside the project, and the harness knows where the
        # project sits. The subcommand the page chose is kept as printed, so a wrong
        # one still fails the way a reader would see it.
        argv = reroot_state_git(argv, world.state)
    elif argv[0] == "noni":
        argv = reroot_state_repo(argv, world.state)
    # The allow-list and the guards are decided on the *re-rooted* argv, immediately
    # before the exec, and derived there rather than carried from the top of the
    # function: re-rooting is what turns the page's clone-addressed push into a
    # command addressed at a real path, and a decision taken before that move is a
    # decision about a different argv than the one about to run.
    key = words(argv)
    assert key in LAUNCHABLE, (
        f"the page prints a command this harness will not run: {argv}")
    gate_page_command(key, argv)
    guard_route_b_push(world.state, key, argv, state, world.origin, world.env, checked)
    program = argv[0]
    if program == "noni":
        program = str(world.noni)
    try:
        return subprocess.run([program, *argv[1:]], cwd=cwd, capture_output=True,
                              text=True, env=world.env, timeout=180)
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - a hung command
        pytest.fail(f"page command hung: {argv}\n{exc}")


def append_ignore_rule(world: World,
                       argv: list[str]) -> subprocess.CompletedProcess[str]:
    """The page's ``echo ... >> .gitignore`` line, applied to the scratch tree.

    Parsed for the path it redirects to rather than replayed by a shell: the only page
    this test can run is the one in this repository, and this repository's
    ``.gitignore`` is a gate file the test must not modify. The payload is taken as
    printed, quotes or no quotes -- the point of the line is the entry it appends, and
    the entry has to name the state directory.
    """
    joined = " ".join(argv)
    match = re.search(r">>\s*(\S+)$", joined)
    assert match, f"the ignore-rule line is not an append to a file: {joined!r}"
    assert match.group(1).endswith(".gitignore"), (
        f"the ignore-rule line writes somewhere other than .gitignore: {joined!r}")
    payload = re.match(r"echo\s+(.+?)\s+>>", joined)
    assert payload, f"the ignore-rule line echoes nothing: {joined!r}"
    entry = payload.group(1).strip().strip("'\"")
    assert STATE_DIR in entry, f"the ignore rule does not name the state directory: {joined!r}"
    (world.project / ".gitignore").write_text(entry + "\n", encoding="utf-8")
    return subprocess.CompletedProcess(argv, 0, "", "")


def reroot_state_git(argv: list[str], state: Path) -> list[str]:
    """Point one page ``git`` line at the real state clone.

    The page writes ``git -C .noni-state <verb> ...``; under the harness the project
    lives at a generated path, so the *token after* ``-C`` has to become the clone's
    absolute path. ``-C`` itself stays: dropping it (or dropping it together with its
    value) would leave the verb to run in the launcher's cwd, which is the reader's
    *project* tree, and the first push would then be made against the code repository
    instead of the state clone. The verb and its arguments are untouched, so a page
    that named the wrong verb still fails the way a reader would see it.

    A line that names the state directory with no ``-C`` in front of it fails closed
    here rather than passing through: an unanchored reference runs against the
    launcher's cwd (the project), which is the confusion this helper exists to prevent,
    and a whole-route run cannot tell the two trees apart when both hold a branch
    called ``main``.
    """
    if STATE_DIR not in argv:
        return argv
    anchors = [index for index, token in enumerate(argv)
               if token == "-C" and index + 1 < len(argv) and argv[index + 1] == STATE_DIR]
    assert anchors, (
        f"a page git line references the state directory {STATE_DIR!r} with no "
        f"'-C {STATE_DIR}' anchor, so the harness cannot point it at the real "
        f"clone: {argv}")
    index = anchors[0]
    return [*argv[:index + 1], str(state), *argv[index + 2:]]


def reroot_state_repo(argv: list[str], state: Path) -> list[str]:
    """Point one page ``noni`` line's ``--repo`` at the real state clone.

    The page writes ``noni register --repo .noni-state ...`` from the project's root,
    which is exactly what a reader types. The writer resolves its own commits with
    ``git -C <repo>``, and the project's ``.gitignore`` (which the page's own line just
    wrote) hides the clone from the project's git, so the launch has to name the
    clone's real path or the session verbs would commit against the project tree the
    ignore rule covers. Only the value of ``--repo`` moves; every other token is
    untouched, so a page that named the wrong flag or a missing value still fails the
    way a reader would see it.

    A relative value is refused rather than re-rooted: ``--repo .`` names the project,
    and silently retargeting it would make a Route A launch measure the state clone.

    Like its ``-C`` twin, a line that names the state directory anywhere other than as
    the value of ``--repo`` fails closed: such a line has no anchor to move, and
    passing it through would run it against the project while the run still reported
    the page's exit 0.
    """
    anchored = False
    try:
        index = argv.index("--repo")
    except ValueError:
        index = -1
    if index >= 0:
        assert index + 1 < len(argv), f"the page prints --repo with no value: {argv}"
        if argv[index + 1] == STATE_DIR:
            anchored = True
            if argv.count(STATE_DIR) == 1:
                return [*argv[:index + 1], str(state), *argv[index + 2:]]
    assert anchored or STATE_DIR not in argv, (
        f"a page noni line references the state directory {STATE_DIR!r} outside "
        f"the value of --repo, so the harness cannot point it at the real clone: "
        f"{argv}")
    return argv


def state_clone(world: World, argv: list[str],
                state: bool) -> subprocess.CompletedProcess[str]:
    """The page's clone step, run for real against a tree the harness created.

    Two clone lines exist on the page and they stand for different things: the install
    section clones noni itself, which the harness materialises from this checkout so
    the URL can stay a placeholder; the state section clones the private state
    repository, which is launched against the origin the fixture made. ``state`` says
    which block the line came from, so the dispatch cannot guess from the URL the page
    prints.
    """
    if not state:
        assert words(argv) == ("git", "clone"), f"not a clone line: {argv}"
        assert any(CLONE_URL in token for token in argv), (
            f"the install clone must name the page's placeholder URL: {argv}")
        return subprocess.CompletedProcess(argv, 0, "", "")
    assert len(argv) == 4 and argv[3] == STATE_DIR, (
        f"the page's state clone must name the {STATE_DIR} target: {argv}")
    return git(world.project, "clone", "-q", str(world.origin), STATE_DIR,
               env=world.env)
