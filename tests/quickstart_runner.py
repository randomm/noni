"""Building the quickstart's topology, and launching its commands.

The reading layer (``docs_commands``, ``docs_promises``) turns the page into
argv. This module turns the page's *trees* into something launchable: the
materialised noni clone, the reader's scratch repository, the private state
repository with its origin, the venv the page's install step produces, and the
dispatch that runs one parsed command in the right tree.

Split from ``tests/test_quickstart.py`` on the same seam the README harness uses
(``readme_support`` holds the machinery, the test module holds the promises):
what lives here is plumbing and its own preconditions, and the assertions about
what the page claims stay with the tests.

Two rules the launcher keeps, because a doc runner that breaks them stops
measuring the page:

- **Nothing ambient reaches a launch.** The page's commands commit, so an
  inherited ``GIT_DIR`` or host identity decides which tree they act on and who
  authors it. The env is built from a filtered mapping, with the two host config
  files pinned to the null device.
- **A command outside the allow-list is refused, not run.** The allow-list is
  the page's own command vocabulary; a rewritten block that gained a command the
  page does not mean fails here rather than being exec'd against the scratch
  trees.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _harness import REPO, subprocess_env
from conftest import NONI_ENV_VARS
from docs_commands import block_commands
from docs_promises import QUICKSTART, STATE_DIR, bash_blocks_text, section_body
from readme_support import _command_words

# The clone directory the page's install commands name, and the placeholder it
# clones from. The clone is materialised rather than fetched (the same choice
# ``readme_support._materialise_clone`` makes), so the URL can stay a
# placeholder and the run stays offline.
CLONE_DIR = "noni"
CLONE_URL = "github.com/OWNER/noni"

# The reader's own repository, as the page names it. Like the README harness's
# placeholder for the reader's tree, the harness supplies the real directory.
READER_DIR = "your-project"

# The command vocabulary the page is allowed to print, as program-and-subcommand
# words. Every command the page prints is one of these; anything else is
# refused rather than exec'd, which is what keeps a rewritten block from running
# something the page never intended (a ``git push`` on the project, say, or a
# ``rm``). Adding a form here is a decision about what the page may tell a
# reader to run, and has to be made on purpose.
LAUNCHABLE: frozenset[tuple[str, ...]] = frozenset({
    ("cd",),
    ("git", "commit"), ("git", "config"), ("git", "clone"), ("git", "push"),
    ("noni", "decide"), ("noni", "register"), ("noni", "claim"),
    ("noni", "order"), ("noni", "census"),
    ("python3", "-m"), ("echo",),
})

# The placeholders the page asks the reader to fill from their own run, mapped to
# the value the harness plants. A page that adds a third placeholder runs the
# literal, which the census refuses -- so the page cannot gain a placeholder
# without the test that supplies it being updated too.
PLACEHOLDER_VALUES = {
    "<record-id>": "2026-11-02-release-scope",
}

_GIT_IDENTITY = ("-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
                 "-c", "commit.gpgsign=false")


class World:
    """The trees the page describes: the clone, the project, and the origin."""

    def __init__(self, tmp_path: Path) -> None:
        self.env = run_env()
        self.clone = tmp_path / CLONE_DIR
        self.project = tmp_path / READER_DIR
        self.origin = tmp_path / "origin"
        self.state = self.project / STATE_DIR
        self.venv = tmp_path / "venv"
        self.noni = self.venv / "bin" / "noni"
        # Placeholder values a running tree produces (see ``substitute``): the id
        # register printed, read back off the file it wrote, so the page's claim
        # line names the session the register line actually allocated.
        self.placeholders: dict[str, str] = {}

    def collect_session_id(self) -> None:
        """Take the page's ``<session-id>`` from the register file on disk.

        Read from the state clone's own sessions directory, not from stdout: the
        value the next page command must carry is the file the writer committed,
        and reading it back proves that file exists where ``--repo`` points.
        """
        files = sorted((self.state / "noni" / "sessions").glob("*.md"))
        assert files, (
            "the page's register line wrote no session file under the state clone, "
            "so the claim line that follows cannot name a real session id")
        self.placeholders["<session-id>"] = files[-1].stem


def run_env() -> dict[str, str]:
    """An env with nothing ambient: no inherited git location, identity or deny-list.

    Built from a filtered mapping rather than ``os.environ`` for the same reason
    ``readme_support._reader_env`` builds it that way: the page's commands commit,
    so anything git inherits decides which tree they act on and who authors it.
    The two host config files are pinned to the null device, and bytecode caching
    is off because the census loads its siblings in-process -- without it the
    page's read-only promise would be false in the reader's tree.
    """
    env = {k: v for k, v in subprocess_env().items() if k not in set(NONI_ENV_VARS)}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def checked(proc: subprocess.CompletedProcess[str], what: str) -> None:
    """One harness step that must succeed, with both streams in the failure text."""
    assert proc.returncode == 0, (
        f"{what} failed ({proc.returncode})\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )


def git(repo: Path, *args: str, env: dict[str, str], identity: bool = False) -> subprocess.CompletedProcess[str]:
    """One git command, with its output kept for the assertion messages.

    ``identity`` adds the harness's ``-c`` identity, for the trees the page does
    not ask the reader to configure (the seed commit that stands in for the
    forge). The page's own commands run without it: they set their identity with
    the ``git config`` lines the page prints, and a harness identity would hide
    a page that forgot to set one.
    """
    args = (*_GIT_IDENTITY, *args) if identity else args
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, env=env, timeout=120)


def init_repo(path: Path, env: dict[str, str], *, branch: str = "main") -> None:
    """``git init -b <branch>`` in a tree that does not exist yet.

    ``git -C`` refuses to enter a missing directory, so the tree is made first.
    The branch is named on the command line, not left to ``init.defaultbranch``:
    the suite's sandboxed HOME carries no gitconfig, so an unadorned ``init``
    falls back to git's own default and a writer's commit lands on a branch
    origin never had (the reason ``tests/harness_git.build_bare_origin`` names
    ``-b main`` too).
    """
    path.mkdir(parents=True, exist_ok=True)
    checked(git(path, "init", "-q", "-b", branch, env=env), f"git init {path.name}")


def init_bare(path: Path, env: dict[str, str], branch: str) -> None:
    """A bare repository whose ``HEAD`` names ``branch``.

    The branch is named on ``init`` so the repository's own ``HEAD`` points at
    it: a clone takes its branch from the origin's ``HEAD``, and a bare
    repository whose ``HEAD`` names nothing comes back with no branch at all.
    No commit is ever made in this tree, so nothing pushes to its current branch.
    """
    path.mkdir(parents=True, exist_ok=True)
    checked(git(path, "init", "-q", "--bare", "-b", branch, env=env),
            f"git init --bare {path.name}")


def seed_origin(origin: Path, env: dict[str, str], branch: str = "main") -> None:
    """A bare origin holding one empty commit on ``branch``, as the forge would.

    This is the harness standing in for the forge: the page tells the reader to
    create the repository there, and a clone of a truly empty repository has no
    branch at all, so the writers would commit onto a HEAD of the clone's own
    making and the page's ``push -u`` would have nothing to name. The branch is
    created by the seed's own ``push -u`` rather than by ``init`` of the bare
    repository: a bare ``init -b`` checks that branch out, and git then refuses a
    push to the branch its own ``HEAD`` names. ``tests/harness_git.py``'s
    ``build_bare_origin`` makes the same choice for the same reason.
    """
    init_bare(origin, env, branch)
    seed = origin.parent / "seed"
    init_repo(seed, env, branch=branch)
    checked(git(seed, "commit", "-q", "--allow-empty", "-m", "first", env=env,
                identity=True), "seed commit")
    checked(git(seed, "remote", "add", "origin", str(origin), env=env), "seed remote")
    checked(git(seed, "push", "-q", "-u", "origin", branch, env=env), "seed push")


def materialise_clone(dest: Path) -> None:
    """The noni clone the page's ``git clone`` produces: this tree's content."""
    shutil.copytree(REPO, dest, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv",
                                                  "*.pyc", ".pytest_cache",
                                                  ".coverage", ".coverage.*",
                                                  "noni.egg-info", ".worktrees"))


def make_venv(world: World) -> None:
    """The page's install step, run once: a venv holding the clone's package."""
    checked(subprocess.run([sys.executable, "-m", "venv", str(world.venv)],
                           capture_output=True, text=True, env=world.env, timeout=300),
            "python -m venv")
    checked(subprocess.run([str(world.venv / "bin" / "pip"), "install", "--quiet",
                            "--disable-pip-version-check", str(world.clone)],
                           capture_output=True, text=True, env=world.env, timeout=600),
            "pip install of the clone")


def build_world(tmp_path: Path) -> World:
    """The page's topology, standing and installed: clone, project, state origin.

    The install step runs here rather than in one test because every command the
    page prints needs the same installed console script, and a per-test install
    would measure pip rather than the page several times over.
    """
    world = World(tmp_path)
    materialise_clone(world.clone)
    init_repo(world.project, world.env)
    seed_origin(world.origin, world.env)
    make_venv(world)
    checked(subprocess.run([str(world.noni), "--help"], capture_output=True, text=True,
                           env=world.env, timeout=120, cwd=world.project),
            "noni --help")
    return world


def words(argv: list[str]) -> tuple[str, ...]:
    """The program and subcommand words of one page line.

    ``readme_support._command_words`` is the shared walk; this names the two rules
    this page's commands need and the README's do not carry:

    - **An option consumes its value**, so ``git -C .noni-state config user.name
      Casey`` is ``('git', 'config')`` and ``python3 -m pip install`` is
      ``('python3', '-m')``. Without it the token after a flag could be read as
      the subcommand the allow-list decides on.
    - **A token may end the walk on ``@``, ``:`` or ``>``** as well as the shared
      pair, because this page prints an scp-style remote, a URL and a redirect.

    The dispatch selects on the program and subcommand without being fooled by an
    argument.
    """
    return _command_words(argv, option_takes_value=True,
                          end_words_on=(".", "/", "@", ":", ">"))


def substitute(argv: list[str], extra: dict[str, str] | None = None) -> list[str]:
    """Fill the page's placeholders with the values the reader would supply.

    Token by token, never by rejoining the line: one argv entry may hold spaces
    the reader quoted (``q1=Wait a week``), and a join-and-resplit would hand the
    program those words as separate arguments -- a different command from the one
    on the page.

    ``extra`` carries the values a running tree produces rather than a reader
    typing (the session id ``register`` printed, which its own ``claim`` line
    then names): a fixed placeholder there would name a file the register step
    cannot have made, and the launch would fail on the fixture, not on the page.
    """
    values = {**PLACEHOLDER_VALUES, **(extra or {})}
    return [values.get(token, token) for token in argv]


def route_commands(label: str) -> list[list[str]]:
    """The commands of the quickstart section whose heading starts with ``label``.

    Selected by heading rather than by fence position, so a block added at the
    bottom of the page cannot be mistaken for either route's.
    """
    body = section_body(QUICKSTART.read_text(encoding="utf-8"), label)
    return [argv for block in bash_blocks_text(body) for argv in block_commands(block)]


def launch(world: World, argv: list[str], cwd: Path, *,
           state: bool = False) -> subprocess.CompletedProcess[str]:
    """One page command, in the topology the page describes.

    ``noni`` is the console script the page's install step produced; ``git``
    addressed to the state clone is re-rooted at the real directory; ``cd`` names
    a directory the page cannot know and so is asserted rather than run, because
    every launched command already carries the cwd the harness chose; the
    ignore-rule line appends to the scratch project's ``.gitignore``. A
    placeholder is substituted with the value the reader would fill in. A word
    outside :data:`LAUNCHABLE` is refused, so a block that gained a command the
    page does not mean fails instead of running it.
    """
    argv = substitute(argv, getattr(world, "placeholders", None))
    key = words(argv)
    assert key in LAUNCHABLE, f"the page prints a command this harness will not run: {argv}"
    if key == ("cd",):
        # The one step into a directory the page cannot name: the harness runs
        # every command with the cwd the page's cd would have landed in, so the
        # line is asserted rather than attempted.
        assert argv[1:] == [READER_DIR], (
            f"the page's cd must name the placeholder for the reader's own "
            f"repository ({READER_DIR}): {argv}")
        return subprocess.CompletedProcess(argv, 0, "", "")
    if key == ("echo",):
        return append_ignore_rule(world, argv)
    if key == ("git", "clone"):
        return state_clone(world, argv, state)
    if argv[0] == "git":
        # Re-root a clone-addressed git line at the real state directory: the
        # page names it by its path inside the project, and the harness knows
        # where the project sits. The subcommand the page chose is kept as
        # printed, so a wrong one still fails the way a reader would see it.
        argv = reroot_state_git(argv, world.state)
    elif argv[0] == "noni":
        argv = reroot_state_repo(argv, world.state)
    program = argv[0]
    if program == "noni":
        program = str(world.noni)
    try:
        return subprocess.run([program, *argv[1:]], cwd=cwd, capture_output=True,
                              text=True, env=world.env, timeout=180)
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - a hung command
        pytest.fail(f"page command hung: {argv}\n{exc}")


def append_ignore_rule(world: World, argv: list[str]) -> subprocess.CompletedProcess[str]:
    """The page's ``echo ... >> .gitignore`` line, applied to the scratch tree.

    Parsed for the path it redirects to rather than replayed by a shell: the only
    page this test can run is the one in this repository, and this repository's
    ``.gitignore`` is a gate file the test must not modify. The payload is taken
    as printed, quotes or no quotes -- the point of the line is the entry it
    appends, and the entry has to name the state directory.
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

    The page writes ``git -C .noni-state <verb> ...``; under the harness the
    project lives at a generated path, so the *token after* ``-C`` has to become
    the clone's absolute path. ``-C`` itself stays: dropping it (or dropping it
    together with its value) would leave ``git <verb> ...`` to run in the
    launcher's cwd, which is the reader's *project* tree, and a ``push -u origin
    main`` would then be made against the code repository instead of the state
    clone. The verb and its arguments are untouched, so a page that named the
    wrong verb still fails the way a reader would see it.
    """
    for index, token in enumerate(argv):
        if token == STATE_DIR and index >= 2:
            return [*argv[:index], str(state), *argv[index + 1:]]
    return argv


def reroot_state_repo(argv: list[str], state: Path) -> list[str]:
    """Point one page ``noni`` line's ``--repo`` at the real state clone.

    The page writes ``noni register --repo .noni-state ...`` from the project's
    root, which is exactly what a reader types. The writer resolves its own
    commits with ``git -C <repo>``, and the project's ``.gitignore`` (which the
    page's own line just wrote) hides the clone from the project's git, so the
    launch has to name the clone's real path or the session verbs would commit
    against the project tree the ignore rule covers. Only the value of
    ``--repo`` moves; every other token is untouched, so a page that named the
    wrong flag or a missing value still fails the way a reader would see it.

    The relative path is refused rather than re-rooted: ``--repo .`` names the
    project, and silently retargeting it would make a Route A launch measure the
    state clone.
    """
    try:
        index = argv.index("--repo")
    except ValueError:
        return argv
    assert index + 1 < len(argv), f"the page prints --repo with no value: {argv}"
    if argv[index + 1] == STATE_DIR:
        return [*argv[:index + 1], str(state), *argv[index + 2:]]
    return argv


def state_clone(world: World, argv: list[str], state: bool) -> subprocess.CompletedProcess[str]:
    """The page's clone step, run for real against a tree the harness created.

    Two clone lines exist on the page and they stand for different things: the
    install section clones noni itself, which the harness materialises from this
    checkout so the URL can stay a placeholder; the state section clones the
    private state repository, which is launched against the origin the fixture
    made. ``state`` says which block the line came from, so the dispatch cannot
    guess from the URL the page prints.
    """
    if not state:
        assert any(CLONE_URL in token for token in argv), (
            f"the install clone must name the page's placeholder URL: {argv}")
        return subprocess.CompletedProcess(argv, 0, "", "")
    assert len(argv) == 4 and argv[3] == STATE_DIR, (
        f"the page's state clone must name the {STATE_DIR} target: {argv}")
    return git(world.project, "clone", "-q", str(world.origin), STATE_DIR,
               env=world.env)
