"""The shared reading layer for the README's promises: parsing, extraction, paths.

``tests/test_readme.py`` asserts against the page; this module is how it reads
it. The two are separated because the CI wheel job runs the test module by name
(gate-file territory) while the reading layer is ordinary module code, and a
1000-line test file is one file too many under the source-size cap.

What lives here is the machinery, not the promises: fenced-block and section
parsing, the try-it block's command extraction and its allow-list, the clone
topology (the materialised clone, the reader's scratch repository, the launch
environment), and the path/hygiene helpers the page checks depend on. The
assertions stay with the tests.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _harness import REPO, _git, subprocess_env
from conftest import NONI_ENV_VARS
from docs_commands import block_commands, fenced_pairs

README = REPO / "README.md"
CONTRIBUTING = REPO / "CONTRIBUTING.md"

# The ordered ``##`` sections the page must carry (the H1 that opens it is
# asserted separately, by test_readme_follows_the_documented_section_order).
EXPECTED_SECTIONS: tuple[str, ...] = (
    "The problem",
    "What you get",
    "Try it in five minutes",
    "How it works",
    "Status",
    "Purity",
    "Contributing",
)

# The line cap the ticket sets for the page (the SKILL.md cap in
# tests/test_skill_scrub.py is the precedent for a doc size assertion).
README_LINE_LIMIT = 150

# The gate commands the README used to carry and CONTRIBUTING.md now carries.
# The same three coverage steps tests/test_gate_wiring.py requires of CI, plus
# the venv setup that makes them runnable.
CONTRIBUTING_GATE_COMMANDS: tuple[str, ...] = (
    "python -m venv .venv",
    '.venv/bin/pip install -e ".[dev]"',
    ".venv/bin/ruff check .",
    ".venv/bin/coverage run -m pytest",
    ".venv/bin/coverage combine",
    ".venv/bin/coverage report",
)

# A repo-relative script or file path: at least one directory segment, so bare
# words in prose ("the what", "a name") are not mistaken for paths.
_PATH_TOKEN = re.compile(r"(?<![\w./-])((?:[\w.-]+/)+[\w.-]+)")

# The clone directory the page's paths run from, the placeholder the page's
# clone line stands in for, and the checker the census's hygiene class must find
# beside the scripts it runs.
NONI_DIR = "noni"
_CLONE_URL_PLACEHOLDER = "github.com/OWNER/noni"
# The directory the page's ``cd`` step stands in for (the reader's own
# repository, whose name the page cannot know). It is excused from the
# path-exists check like the ``<skill>`` placeholder; the try-it test supplies
# the real tree and runs there.
_READER_DIR_PLACEHOLDER = "your-project"

# The row the census prints when its hygiene checker is absent or broken: the
# subject and the wording that name a scan that never ran. The clean try-it run
# must NOT carry it, which is what makes the reader's tree prove the checker
# was present (lens HIGH).
_HYGIENE_NOT_RUN_MARKER = "hygiene scan did not run"

# A path the page's clone line stands in for: the repository URL is a
# placeholder, so the clone directory named inside it is excused from the
# path-exists check the same way the ``<skill>`` placeholder is.
_CLONE_PATH = f"{NONI_DIR}/skills"

# The programs a try-it block may name besides a noni script, as the ordered
# program and subcommand words (a tuple, not a set, so ``git config`` and a bare
# ``git`` or a future ``git push`` stay distinguishable and a new permitted form
# has to be added here on purpose): ``cd`` (the one step into the reader's own
# repository), ``git clone`` (the page's first step, run outside the reader's
# repository) and ``git config`` for the identity lines decide.py's refusal and
# commit require. The clone is the one documented command the test does not
# launch: it is materialised instead (see ``_materialise_clone``), so its URL can
# stay the placeholder the page prints. ``decide.py`` refuses with exit 3 and the
# hint ``git -C <repo> config user.name <name>`` when the tree has no identity,
# so the page that tells a reader to set one is quoting the product's own fix.
_ALLOWED_SHELL: frozenset[tuple[str, ...]] = frozenset(
    {("cd",), ("git", "clone"), ("git", "config")})

# The commands a documented path must actually run: one writer and the arbiter.
# Dropping either leaves the page promising a five-minute tour that no longer
# reaches a census verdict, which a block that merely runs would not notice.
REQUIRED_TRY_IT_SCRIPTS: frozenset[str] = frozenset({"decide.py", "census.py"})

# The only keys a ``git config`` line may set. An arbitrary key would let the
# page plant config the reader does not want (or that redirects the writer),
# and the two names below are the only ones the documented run needs.
_ALLOWED_GIT_CONFIG_KEYS: frozenset[str] = frozenset({"user.name", "user.email"})

# The shapes of the paths noni creates inside the project it attaches to, and
# the venv the dev commands install into, each mapped to the claiming file that
# must document it. One mapping, so a pattern can never exist in one container
# and not the other. ``_claim_is_documented`` proves the claiming file says so.
_STATE_DOCS: dict[str, Path] = {
    r"noni/decisions/?": Path("skills/steering-ledger/SKILL.md"),
    r"noni/sessions/?": Path("skills/sessions-claims/SKILL.md"),
    r"noni/direction/?": Path("skills/direction/SKILL.md"),
    r"noni/direction/order\.json": Path("skills/direction/SKILL.md"),
    r"\.venv/bin/[\w.-]+": Path("pyproject.toml"),
}

# The pattern key whose proof lives in the gate config rather than a skill.
_VENV_PATTERNS: frozenset[str] = frozenset({r"\.venv/bin/[\w.-]+"})

# Spelled-out counts the page may use for the subcommand sentence, so a reader
# gets prose and the pin still has a number to compare against.
_NUMBER_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10,
}

_SUMMARY_SEGMENT = re.compile(
    r"^(summary: clean; )(\d+) finding\(s\); (verdict (?:ok|fail))$"
)

# The warn rows a reader's first census run carries, and the reason each is
# counted without changing the verdict. The hygiene row is the one the page's
# wording depends on: with the checker present (the clone topology) it names the
# ``deny-list`` half that did not run, operator config a first run does not have,
# and never ``hygiene scan`` reporting that its checker sat outside the tree (see
# ``_HYGIENE_NOT_RUN_MARKER``, which the run below asserts absent). The
# second row appears until the first record exists (the ledger has nothing to
# arbitrate), which is why the count is compared as a floor rather than pinned:
# the run the page describes is the one after ``decide.py`` has written, and the
# census is read in the same sitting. Keeping the rows as data here, and
# requiring the count the page shows to be the number of rows the run reports,
# is what stops the page's line and the census's line drifting apart quietly.
_CLEAN_RUN_WARN_ROWS: tuple[str, ...] = ("deny-list", "ledger-empty")

# coverage's subprocess data file name, as [tool.coverage.run] produces it with
# parallel = true: ``.coverage.<host>.pid<pid>.<seq>``. Pinned here against the
# harness's own COVERAGE_PROCESS_START being set, not against a product path.
_COVERAGE_DATA_FILE = re.compile(r"^\.coverage\.[^.]+\.pid\d+\.[\w-]+\.[\w-]+$")

# The variables that must not reach a documented launch. Sourced from the same
# list conftest clears, so there is one owner of the set.
_AMBIENT_GIT_VARS: frozenset[str] = frozenset(NONI_ENV_VARS)


def _readme_text() -> str:
    assert README.is_file(), "README.md is missing"
    return README.read_text(encoding="utf-8")


def _fenced_blocks(text: str) -> list[tuple[str, list[str]]]:
    """The (info string, lines) pairs of every fenced code block in ``text``.

    The shared fence reader is ``docs_commands.fenced_pairs`` (README, quickstart
    and the promises modules all read fences the same way); this wraps it with the
    README's own failure text. An unterminated fence is a malformed page, not a
    partial read.
    """
    try:
        return fenced_pairs(text)
    except AssertionError as exc:
        pytest.fail(f"README.md: {exc}")


def _try_it_block() -> list[str]:
    """The lines of the try-it block, by section heading, not by fence position.

    Scoped to ``## Try it in five minutes`` and required to be the section's one
    and only ```bash fence: taking the last fence on the page would let a second
    bash block added anywhere below silently re-target every assertion in this
    module to a block the five-minute promise does not live in.
    """
    bash_blocks = [lines for info, lines in _fenced_blocks(_try_it_section())
                   if info == "bash"]
    assert len(bash_blocks) == 1, (
        f"the try-it section must document exactly one bash block to try, "
        f"found {len(bash_blocks)}"
    )
    return bash_blocks[0]


def _try_it_section() -> str:
    """The body of the section the five-minute promise lives in."""
    return _section(_readme_text(), "Try it in five minutes")


def _safe_relative(token: str) -> bool:
    """True when ``token`` stays inside the tree it is joined to.

    A documented path is copied by a reader verbatim, so a traversal token is
    admissible only in the one form the page uses: the clone-rooted script path
    ``../noni/skills/...``, which resolves against the clone the page clones.
    Any other ``..`` (or an absolute path) is a broken promise, and the
    normalised form has to equal the raw token.
    """
    if not token or token.startswith("-") or os.path.isabs(token):
        return False
    if ".." in Path(token).parts or token.startswith("../"):
        return token.startswith(f"../{NONI_DIR}/skills/")
    return os.path.normpath(token) == token.rstrip("/")


def _clone_script(argv: list[str]) -> str:
    """The clone-relative script path of one documented command.

    ``../noni/`` is where the page says the clone sits (beside the reader's
    repository); inside the test the clone is materialised under the scratch
    root, so the bare remainder resolves against this repository, which carries
    the same tracked content a clone of a release checks out.
    """
    clone_root = f"../{NONI_DIR}/"
    assert argv[1].startswith(clone_root), (
        f"try-it script must run from the clone the page names: {argv[1]} "
        f"(expected to start with {clone_root!r})"
    )
    script = argv[1][len(clone_root):]
    assert _safe_relative(script), f"script path escapes the clone: {argv[1]}"
    return script


def _argv_for_run(argv: list[str], clone: Path, repo: Path) -> list[str]:
    """The argv for one documented command, in the clone topology.

    ``python3`` becomes the running interpreter (so the block measures the same
    Python the suite runs under) and the script path is re-rooted at ``clone``,
    the materialised noni clone. The argv is otherwise verbatim, so ``--repo .``
    still names the reader's repository, which is ``repo``, the command's cwd.
    The clone's ``git`` identity lines are executed against ``repo`` as written.
    """
    if argv[0] == "python3":
        assert len(argv) > 1, f"try-it command names no script: {argv}"
        script = _clone_script(argv)
        resolved = (REPO / script).resolve()
        assert resolved.is_file(), f"try-it block names no such script: {argv[1]}"
        assert str(resolved).startswith(str(REPO.resolve()) + os.sep), (
            f"{argv[1]} resolves outside this repository: {resolved}"
        )
        assert (clone / script).is_file(), (
            f"the materialised clone is missing {script}: the run would not be "
            "against the tree the page sells"
        )
        return [sys.executable, str(clone / script), *argv[2:]]
    if _block_words(argv) == ("git", "config"):
        return ["git", "-C", str(repo), *argv[1:]]
    return list(argv)


def _block_commands(lines: list[str]) -> list[list[str]]:
    """The commands of one block as argv lists, continuations joined.

    The single implementation is ``docs_commands.block_commands``, shared with the
    quickstart's runner: it drops the page's own ``#`` prose lines, joins
    backslash continuations and splits with ``posix=True``, so quotes are removed
    the way a reader's shell removes them. The argv it returns is what gets
    exec'd, and a value that reached the script carrying literal quote characters
    would be a different command from the one on the page.
    """
    return block_commands(lines)


def _block_words(argv: list[str]) -> tuple[str, ...]:
    """The command words of one README line: the program, plus its subcommand.

    The rules are fixed in this body, not passed in: the allow-list above is the
    page's command vocabulary, so a caller that could re-parameterise the walk
    could re-word a line into something the vocabulary permits. The README's
    rules:

    - ``git config user.name Casey`` reduces to ``('git', 'config')`` and
      ``python3 ../noni/skills/.../decide.py ...`` to ``('python3',)``, which is
      what the allow-list matches against: the question is which programs a page
      may tell a reader to run, not which flags or targets it passes.
    - ``git clone <url> <dir>`` is the one two-word form that survives intact, as
      the fetch from outside the reader's repository; ``cd`` is the one built-in
      and keeps its single word.
    - A token carrying a dot or a slash (a path, a URL, a config key, a directory
      name) ends the words, so a permitted ``git config`` is not also a permit for
      any other git subcommand.
    - An option does *not* consume its value here: the README's block carries no
      ``-C``, so the first word after any flags is the subcommand.

    The quickstart's rules are the sibling :func:`_quickstart_words`, which differ
    in exactly two ways and name the page they read.
    """
    if not argv:
        return ()
    if argv[0] == "cd":
        return ("cd",)
    if argv[0] == "git" and len(argv) > 1 and argv[1] == "clone":
        return ("git", "clone")
    words: list[str] = [argv[0]]
    for token in argv[1:]:
        if token.startswith("-"):
            continue
        if "." in token or "/" in token:
            break
        words.append(token)
        break
    return tuple(words)


def _quickstart_words(argv: list[str]) -> tuple[str, ...]:
    """The command words of one quickstart line, by that page's own fixed rules.

    Kept beside :func:`_block_words` rather than merged with it: the two pages'
    commands differ in exactly two ways, each rule has to be readable against the
    page it serves, and neither function takes a knob -- a shared walker with
    parameters lets a caller re-word a line into something the other page's
    allow-list permits.

    - **An option consumes its value**: this page prints
      ``git -C .noni-state config user.name Casey``, where the verb -- not the
      directory -- is the subcommand, and ``python3 -m pip install``, where the
      ``-m`` belongs to the command.
    - **A token ends the walk** when it carries ``@``, ``:``, ``>``, a dot or a
      slash: this page prints an scp-style remote, a URL and a redirect.

    ``quickstart_runner.words`` is the launcher's copy of these rules (the import
    below is what keeps the two in step), and ``tests/test_quickstart.py`` asserts
    the pair agree on every line the page prints.
    """
    from quickstart_runner import words

    return words(argv)


def _script_name(argv: list[str]) -> str:
    """The basename of the script one documented command runs, by name not substring.

    ``"census.py" in argv[1]`` would also accept a path naming, say,
    ``census_ordering.py`` and let the assertion below run against the wrong
    process's output. ``argv[1]`` is only consulted for a python3 launch that
    has a script position.
    """
    if argv[0] != "python3" or len(argv) < 2 or argv[1].startswith("-"):
        return ""
    return Path(argv[1]).name


def _section_of(doc: Path, heading: str) -> str:
    """The body of one ``## heading`` section of any page, by heading."""
    return _section(doc.read_text(encoding="utf-8"), heading)


def _section(text: str, heading: str) -> str:
    """The body of one ``## heading`` section, up to the next heading."""
    start = text.find(f"## {heading}")
    assert start >= 0, f"README.md has no '## {heading}' section"
    rest = text[start + len(f"## {heading}"):]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def _paths_in(text: str) -> list[str]:
    return [token for token in _PATH_TOKEN.findall(text) if not token.startswith("http")]


def _materialise_clone(clone: Path) -> None:
    """The noni clone the page's ``git clone`` produces, under the scratch root.

    A copy of this working tree with the untracked build droppings removed, so
    the clone holds the release content a reader gets in the layout a clone
    checks out: ``skills/`` and ``scripts/`` as siblings under one root, which is
    what lets the census find its hygiene checker beside the scripts it runs.
    """
    shutil.copytree(REPO, clone, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv",
                                                  "*.pyc", ".pytest_cache",
                                                  ".coverage", ".coverage.*",
                                                  "noni.egg-info", ".worktrees"))


def _reader_repository(tmp_path: Path) -> Path:
    """The scratch tree the reader runs the block from: an init'd repo, no noni
    state and no identity.

    Nothing noni is pre-installed: the page promises the reader's project stays
    theirs, and the census must find no ``noni/`` state to begin with. No identity
    is planted either: the try-it block sets both keys itself, and a harness
    identity would hide a page that forgot to set one. The tree has no commits and
    holds nothing noni, which is the first-run case the page sells (the census's
    own ``rev-parse --show-toplevel`` probe makes it a git repository whatever its
    commit state).
    """
    repo = tmp_path / "reader"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    return repo


def _reader_env() -> dict[str, str]:
    """The env for the documented launches: nothing ambient, and no writes.

    Built from an empty mapping rather than ``os.environ`` because the block runs
    ``decide.py --repo .`` and ``census.py --repo .``, so anything git inherits
    changes which repository the page's commands act on or what they read from
    it. Two families matter:

    - ``GIT_DIR`` / ``GIT_WORK_TREE`` / ``GIT_INDEX_FILE`` and the rest of
      :data:`conftest.NONI_ENV_VARS`, which a developer's shell can leave
      exported from a worktree. tests/conftest.py clears them from
      ``os.environ`` per test; the same list is dropped here so a variable the
      suite means to keep out cannot re-enter through the child env.
    - the git config files, both pinned to the null device. The sibling writers'
      tests reach this through :func:`_git_env_with_identity`, which merges the
      same pins plus an author identity; this launcher cannot take that merge,
      because decide.py takes ``by`` from ``git config user.name`` and the commit
      author from ``user.email`` of the *tree*, and the page's own block is what
      sets them (see ``_try_it_commands``). Injecting the harness identity would
      test a tree the page does not describe.

    Bytecode caching is switched off because the census loads its siblings
    in-process: without this the read-only promise on the page is false in the
    reader's own committed tree, where a ``__pycache__/`` directory would appear.
    """
    env = {k: v for k, v in subprocess_env().items() if k not in _AMBIENT_GIT_VARS}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run_documented(cmd: list[str], repo: Path,
                     env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """One documented command, with a hang reported as the command that hung.

    ``subprocess.run`` raises ``TimeoutExpired`` out of the call, so without this
    wrapper a wedged documented command surfaces as a harness traceback naming no
    argv, no stdout and no stderr.
    """
    try:
        return subprocess.run(cmd, cwd=repo, capture_output=True, text=True,
                              env=env, timeout=120)
    except subprocess.TimeoutExpired as exc:
        partial = _partial_text(exc.stdout)
        stderr = _partial_text(exc.stderr)
        pytest.fail(
            f"documented command hung for 120s: {cmd}\nstdout: {partial}\nstderr: {stderr}"
        )


def _partial_text(stream: str | bytes | None) -> str:
    """The text of a captured stream from a TimeoutExpired, decoded leniently."""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", "replace")
    return stream or ""
