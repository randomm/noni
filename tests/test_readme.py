"""The README keeps its promises: sections, scripts, gate text and the try-it run.

The README is the one page a team lead reads before attaching noni to a
project, so its claims are product surface. This module reads it the way
``tests/test_gate_wiring.py`` reads the CI workflow and ``pyproject.toml``: as
data, with the assertions standing between the prose and the code.

What is pinned, and why:

- the section order, so the page keeps answering what / why / try it / how in
  the order a first-time reader asks them;
- the size cap, on the same shape as the SKILL.md cap in
  ``tests/test_skill_scrub.py``;
- every path either page names exists in this repository, which is what stops
  the page drifting from the tree;
- the try-it block runs for real, in the topology the page sells: the scripts
  come from a clone of noni (this checkout stands in for it) and ``--repo .``
  names a separate scratch repository, and the block produces the documented
  outcome: one committed record, a census that ends clean on its last line
  with its hygiene scan actually run, and a tree still clean afterwards; a
  second case plants one malformed record and asserts the documented failing
  verdict instead;
- the README links CONTRIBUTING.md, and CONTRIBUTING.md still carries the gate
  commands the CI workflow runs, so the move of that block cannot be a loss.

The hygiene and public-safety classes themselves are tested elsewhere; here the
README only has to stay clean enough for them.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import pytest
from _harness import REPO, _git, subprocess_env
from conftest import NONI_ENV_VARS

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


class StateClaim(NamedTuple):
    """An attached-state exemption: which pattern matched, and the file that
    claims the path. A named pair, so the two halves cannot be swapped."""

    pattern: str
    doc: Path

    @property
    def is_venv(self) -> bool:
        """True when this exemption is the venv-tool kind, not a noni path."""
        return self.pattern in _VENV_PATTERNS


# The pattern key whose proof lives in the gate config rather than a skill.
_VENV_PATTERNS: frozenset[str] = frozenset({r"\.venv/bin/[\w.-]+"})


def _state_token_claim(token: str) -> StateClaim | None:
    """The claiming record when ``token`` names attached state, else None.

    The claiming file is the one the table names, and it must carry the token's
    own basename, so a token cannot be excused by a table nobody maintains.
    """
    for pattern, doc in _STATE_DOCS.items():
        if re.fullmatch(pattern, token):
            return StateClaim(pattern, doc)
    return None


def _readme_text() -> str:
    assert README.is_file(), "README.md is missing"
    return README.read_text(encoding="utf-8")


def _fenced_blocks(text: str) -> list[tuple[str, list[str]]]:
    """The (info string, lines) pairs of every fenced code block in ``text``.

    Parsed by hand rather than with a Markdown library: the README is small,
    the fence style is fixed, and a test must not gain a dependency to read
    the page it is checking.
    """
    blocks: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    for line in text.splitlines():
        fence = re.fullmatch(r"(`{3,}|~{3,})\s*(\S*)\s*", line)
        if fence and current is None:
            current = (fence.group(2), [])
            continue
        if fence and current is not None and line.startswith(fence.group(1)[0]):
            blocks.append(current)
            current = None
            continue
        if current is not None:
            current[1].append(line)
    assert current is None, "README.md has an unterminated code fence"
    return blocks


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

    Split with ``posix=True``, so quotes are removed the way a reader's shell
    removes them: the argv this returns is what gets exec'd, and a value that
    reached the script carrying literal quote characters would be a different
    command from the one on the page.
    """
    commands: list[list[str]] = []
    pending: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        continued = stripped.endswith("\\")
        pending.append(stripped[:-1].rstrip() if continued else stripped)
        if not continued:
            commands.append(shlex.split(" ".join(pending), posix=True))
            pending = []
    assert not pending, "try-it block ends in a line continuation"
    return commands


def _block_words(argv: list[str]) -> tuple[str, ...]:
    """The command words of one line: the program, plus its subcommand.

    ``git config user.name Casey`` reduces to ``('git', 'config')`` and
    ``python3 ../noni/skills/.../decide.py ...`` to ``('python3',)``, which is
    what the allow-list above matches against: the question is which programs a
    page may tell a reader to run, not which flags or targets it passes. The one
    exception is ``git clone <url> <dir>``, a fetch from outside the reader's
    repository, which keeps its two words; ``cd`` is exempt as the one built-in
    the page uses to enter a directory. Ordered, so a permitted ``git config`` is
    not also a permit for any other git subcommand. A token carrying a dot or a
    slash (a path, a URL, a config key, a directory name) ends the words.
    """
    if not argv:
        return ()
    if argv[0] == "cd":
        return ("cd",)
    if argv[0] == "git" and len(argv) > 1 and argv[1] == "clone":
        return ("git", "clone")
    words = [argv[0]]
    for token in argv[1:]:
        if token.startswith("-"):
            continue
        if any(part in token for part in (".", "/")):
            break
        words.append(token)
        break
    return tuple(words)


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


def test_readme_follows_the_documented_section_order() -> None:
    """The page answers what noni is, why, how to try it, and where it stands,
    in that order, so a first-time reader is not handed a design note."""
    text = _readme_text()
    positions: list[int] = []
    for section in EXPECTED_SECTIONS:
        heading = f"## {section}"
        assert heading in text, f"README.md is missing the section {heading!r}"
        positions.append(text.index(heading))
    assert positions == sorted(positions), (
        f"README sections are out of order: {list(EXPECTED_SECTIONS)} expected"
    )
    assert text.index("# noni") < positions[0], "README does not open with the product"


def test_readme_stays_within_the_line_limit() -> None:
    """The page stays short enough to read in one minute (the ticket's cap)."""
    lines = _readme_text().count("\n")
    assert lines <= README_LINE_LIMIT, f"README.md is {lines} lines; the cap is {README_LINE_LIMIT}"


def test_readme_states_the_purity_rule_near_the_end() -> None:
    """The purity sentence moved to the tail of the page but stayed on it: it
    belongs after the reader knows what noni is, not before.

    The rule is pinned to one section by heading, so a purity sentence planted
    above Status cannot satisfy it from the section further down."""
    text = _readme_text()
    section = _section(text, "Purity")
    lowered = section.lower()
    # The rule itself, not the word: the heading carries the word "purity", so
    # checking for it in the body would pass on an empty section.
    assert "no tickets" in lowered and "no backlog" in lowered, (
        "the Purity section does not state the purity rule"
    )
    assert "project-specific" in lowered, "the Purity section does not state the rule"
    earlier = text[: text.index("## Purity")].lower()
    assert "purity" not in earlier, (
        "the purity rule moved back above the end of the page, where a first-time "
        "reader meets design doctrine before the product"
    )


def test_readme_names_what_the_committed_check_does_not_cover() -> None:
    """The public-repo rule has a half the committed patterns cannot enforce:
    operator names, external project or tool names and hostnames live only in
    the untracked deny-list. The page that is a reader's only route to the rule
    has to say so, or a green committed run reads as a scrub-clean guarantee
    when docs/PUBLISHING.md says it is not one."""
    section = _section(_readme_text(), "Contributing")
    lowered = section.lower()
    assert "deny-list" in lowered, (
        "the Contributing section routes the reader to the scrub checklist "
        "without saying the committed check does not cover names or hostnames"
    )
    assert "hostname" in lowered, "the deny-list-only half of the rule is not named"
    assert "docs/PUBLISHING.md" in section, "the checklist itself is not linked"


def test_readme_links_the_contributing_page() -> None:
    """The dev commands moved to CONTRIBUTING.md and the link stayed behind:
    no test of the old page would notice a silent drop of either."""
    assert CONTRIBUTING.is_file(), "CONTRIBUTING.md is missing"
    assert "CONTRIBUTING.md" in _readme_text(), "README.md does not link CONTRIBUTING.md"


def test_contributing_carries_the_gate_commands() -> None:
    """The moved block is the gate CI runs, not a summary of it.

    The commands are read from the CI workflow rather than copied as literals,
    so a gate step that changes there fails here instead of leaving the page
    documenting a gate nobody runs. The comparison is on parsed argv tokens, not
    a substring: ``"." in body`` or ``"-m" in body`` matches anything.
    """
    body = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    contributing = CONTRIBUTING.read_text(encoding="utf-8")
    for command in CONTRIBUTING_GATE_COMMANDS:
        assert command in contributing, f"CONTRIBUTING.md does not document {command!r}"
        argv: tuple[str, ...] = tuple(shlex.split(command, posix=True))
        if not argv[0].startswith(".venv/bin/"):
            continue  # the venv setup step, which CI does in its own step
        tool, rest = Path(argv[0]).name, argv[1:]
        assert tool and rest, (
            f"gate command {command!r} is not a pinned venv tool with a subcommand; "
            "the token comparison below needs both"
        )
        # CI installs a pinned tool set rather than the project's own extras, so
        # the install step is compared on ``pip install`` alone; the lint and
        # coverage steps are compared on tool plus subcommand, which is what a
        # bare substring would otherwise let a short token (``.``, ``-m``) match
        # by accident.
        compared = rest[:1]
        expected_run = f"{tool} {' '.join(compared)}"
        if tool == "coverage":
            # CI runs the three coverage steps as one shell block, so each sits
            # on its own line rather than after ``run:``.
            expected_run = f".venv/bin/{expected_run}"
        assert expected_run in body, (
            f"CI does not run {expected_run}, which CONTRIBUTING.md documents as "
            f"{command!r}"
        )


def test_contributing_points_the_purity_rule_at_its_scrub() -> None:
    """The scrub pointer belongs with the purity rule it qualifies, not under the
    coverage paragraph: the sentence that used to connect them moved once and
    lost its referent. Pinned by heading, the way the README's purity sentence
    is."""
    section = CONTRIBUTING.read_text(encoding="utf-8")
    purity = _section_of(CONTRIBUTING, "Purity")
    assert "docs/PUBLISHING.md" in purity, (
        "the scrub checklist is not linked from the Purity section, so the reader "
        f"meets the rule here without its enforcement: {section[:80]!r}..."
    )


def test_every_path_the_readme_names_exists() -> None:
    """No command or sentence on either page names a script or file this
    repository does not have, so the page cannot drift from the tree.

    The repository URL on the page's clone line is a placeholder, so the clone
    itself is not executable here: the test materialises it (see
    ``_materialise_clone``) and only the commands that operate on the reader's
    repository are run. Two kinds of token cannot resolve here and are checked
    instead against the file that makes the claim: a placeholder path
    (``<skill>``, or the clone directory inside the placeholder URL) is resolved
    by substituting each skill that exists or by the clone layout, and attached
    state (``noni/...``, ``.venv/bin/...``) has to appear in the skill or config
    that creates it. A traversal token is a failure rather than an existence
    hit: ``skills/../x`` resolves inside this checkout and would satisfy
    ``.exists()`` while handing the reader a path that does not exist in their
    tree."""
    skills = sorted(p.name for p in (REPO / "skills").iterdir() if p.is_dir())
    missing: list[str] = []
    for doc in (README, CONTRIBUTING):
        body = doc.read_text(encoding="utf-8")
        for token in _paths_in(body):
            if "<" in token:
                if any((REPO / token.replace("<skill>", name)).exists() for name in skills):
                    continue
                missing.append(f"{doc.name}: {token} (no skill matches the placeholder)")
                continue
            if token == _CLONE_PATH and _CLONE_URL_PLACEHOLDER in body:
                # The clone directory under the placeholder clone URL: the
                # scripts under it are checked by the try-it assertions, which
                # run them from the materialised clone.
                continue
            if token == _READER_DIR_PLACEHOLDER:
                # The reader's own repository, named by the block's cd step: the
                # test supplies that tree and runs there.
                continue
            if not _safe_relative(token):
                missing.append(f"{doc.name}: {token} (not a tree-relative path)")
                continue
            if token.startswith("../"):
                # A clone-rooted path: ``..`` has no meaning from this checkout's
                # root, so it is checked where it resolves, as a file of the clone
                # (which is this repository's tracked content).
                if (REPO / _clone_script(["python3", token])).is_file():
                    continue
                missing.append(f"{doc.name}: {token} (no such script in the clone)")
                continue
            if (REPO / token.rstrip("/")).exists():
                continue
            claim = _state_token_claim(token)
            if claim is not None and _claim_is_documented(token, claim):
                continue
            missing.append(f"{doc.name}: {token}")
    assert not missing, f"docs name paths that do not exist: {sorted(missing)}"


def _claim_is_documented(token: str, claim: StateClaim) -> bool:
    """True when the claiming file makes the same claim about ``token``.

    Both branches prove the same kind of thing: that the token's own basename
    appears in the file that owns it. The claim is checked where it is made: the
    directory or file noni tells a reader it will create has to appear in the
    skill that creates it, and a venv tool has to appear in the gate
    configuration that installs it (CI's own install step runs ``.venv/bin/pip``,
    which is the other route to it). Checking the basename on the venv branch
    too is what stops a fabricated ``.venv/bin/whatever`` passing on a word that
    has nothing to do with it.
    """
    doc = REPO / claim.doc
    if not doc.is_file():
        return False
    body = doc.read_text(encoding="utf-8")
    if claim.is_venv:
        body += (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    return Path(token).name.rstrip("/") in body


def _try_it_commands() -> list[list[str]]:
    """The commands of the try-it block that operate on the reader's repository.

    The page's two outside steps are asserted here and then dropped: the
    ``git clone`` of the placeholder URL and the ``cd`` into the reader's own
    directory. The first is replaced by the materialised clone
    (``_materialise_clone``) and the second by the scratch tree the commands run
    in (``_reader_repository``), so nothing in the run reaches the network or a
    directory the page cannot name.

    ``decide.py`` refuses exit 3 without a name in ``git config user.name``, and
    the commit it then makes also needs ``user.email``, so a page that dropped
    either line documents a five-minute path that stops partway. The identity the
    run has is the one the block itself sets, which is why the launcher env
    carries none of its own (see :func:`_reader_env`).
    """
    commands = _block_commands(_try_it_block())
    assert commands, "try-it block is empty"
    for argv in commands:
        words = _block_words(argv)
        if words == ("python3",):
            # A noni script: its clone-rooted path is validated where it is
            # launched (see ``_argv_for_run`` and
            # ``test_try_it_block_names_scripts_that_run``).
            continue
        assert words in _ALLOWED_SHELL, (
            f"try-it block runs a command the page may not name: {argv}"
        )
        if words == ("cd",):
            # The one step into the reader's own repository: the page cannot name
            # that directory, so it is a placeholder the test supplies.
            assert len(argv) == 2 and argv[1] == _READER_DIR_PLACEHOLDER, (
                f"the try-it block's cd must name the placeholder for the reader's "
                f"own repository ({_READER_DIR_PLACEHOLDER}): {argv}"
            )
        elif words == ("git", "clone"):
            # The page's first step, run outside the reader's repository: the test
            # materialises the clone, so the URL stays the placeholder and only the
            # target directory is compared.
            assert len(argv) == 4 and argv[3] == NONI_DIR, (
                f"git clone must name the placeholder URL and the {NONI_DIR} target "
                f"the paths run from: {argv}"
            )
            assert _CLONE_URL_PLACEHOLDER in argv[2], (
                f"git clone must use the page's placeholder URL: {argv}"
            )
        if words == ("git", "config"):
            # Exactly ``git config <key> <value>``, and only the identity keys.
            # argv[2] is the key position, so a value that happens to contain a
            # permitted key cannot satisfy this, and an arbitrary key fails.
            assert len(argv) == 4, (
                f"git config line must be the two-word form git config KEY VALUE: {argv}"
            )
            assert argv[2] in _ALLOWED_GIT_CONFIG_KEYS, (
                f"the try-it block sets git config {argv[2]!r}, which the page "
                "does not need and the test does not allow"
            )
    identity = [argv for argv in commands if _block_words(argv) == ("git", "config")]
    # The config key is argv[2] of ``git config <key> <value>``: checked at the
    # position rather than as a substring of every argument, so a value that
    # happens to contain the word cannot satisfy it.
    keys = {argv[2] for argv in identity if len(argv) > 2}
    for key in ("user.name", "user.email"):
        assert key in keys, (
            f"the try-it block does not set git config {key}, so the documented "
            "path would stop at decide.py's identity refusal or its commit"
        )
    return [argv for argv in commands if _block_words(argv) not in
            (("cd",), ("git", "clone"))]


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


# The variables that must not reach a documented launch. Sourced from the same
# list conftest clears, so there is one owner of the set.
_AMBIENT_GIT_VARS: frozenset[str] = frozenset(NONI_ENV_VARS)


def test_try_it_block_names_scripts_that_run() -> None:
    """Every command in the try-it block is a real entry point: a permitted
    git form (the clone, the two identity lines), or an existing noni script run
    under python3 from the clone path the page prints. A bare ``decide.py``
    would satisfy a name-existence check and fail on a real shell, so the
    interpreter and the clone-rooted script path are both part of the
    contract."""
    commands = _try_it_commands()
    ran_a_script = False
    for argv in commands:
        if _block_words(argv) in _ALLOWED_SHELL:
            continue
        assert argv[0] == "python3", (
            f"try-it block runs a program the page may not name: {argv}; "
            "a noni script goes under python3"
        )
        assert len(argv) > 1, f"try-it command names no script: {argv}"
        script = _clone_script(argv)
        target = REPO / script
        assert target.is_file(), f"try-it block names no such script: {argv[1]}"
        # Both scripts the page hands a reader are launched as ``python3
        # <path>``, so neither needs a shebang or the executable bit: census.py
        # carries neither by design (it is launched by path, and loads its own
        # siblings the same way). The launch form, not the file mode, is what the
        # page commits a reader to.
        if Path(script).name == "decide.py":
            assert target.suffix == ".py", f"{argv[1]} is not a Python script"
        ran_a_script = True
    assert ran_a_script, "try-it block runs no noni script"
    named = {_script_name(argv) for argv in commands}
    assert REQUIRED_TRY_IT_SCRIPTS <= named, (
        f"try-it block must record a decision and read the census; it names {sorted(named)}"
    )


def _assert_documented_summary(line: str, expected: str) -> int:
    """Check the census's last line against the page's, and return the count it reports.

    Whole-segment equality is the assertion: a page that moved ``verdict ok``
    into an earlier message, or a census that dropped ``summary: clean`` from the
    final line, would keep two independent substring tests green while the line
    the reader compares against had changed. The count between ``clean;`` and
    ``verdict ok`` is the one part the page leaves open (see
    ``_CLEAN_RUN_WARN_ROWS``), so it is parsed rather than compared and handed
    back for the caller to tie to the rows above.
    """
    reported = _summary_parts(line)
    documented = _summary_parts(expected)
    assert reported[0] == documented[0] and reported[2] == documented[2], (
        f"the census's summary line is not the page's: {line!r} != {expected!r}"
    )
    count = reported[1]
    assert count is not None, f"the summary line carries no finding count: {line!r}"
    return count


_SUMMARY_SEGMENT = re.compile(
    r"^(summary: clean; )(\d+) finding\(s\); (verdict (?:ok|fail))$"
)


def _summary_parts(line: str) -> tuple[str, int | None, str]:
    """The ``(head, count, tail)`` of a census summary line, count None if absent.

    Parsed as one whole shape rather than split on a substring, so a line that
    merely contains the two phrases in some other arrangement does not parse."""
    match = _SUMMARY_SEGMENT.match(line)
    if match is None:
        return (line, None, "")
    return (match.group(1), int(match.group(2)), match.group(3))


def _documented_summary_line() -> str:
    """The census's clean summary line, lifted from the fenced block in the try-it section.

    The page prints ``summary: clean; N finding(s); verdict ok``: the count sits
    between the two phrases every clean run emits. Reading the shape off the page
    keeps the assertion the page's own promise rather than a copy of it, and the
    ``N`` is filled with the count a clean run reports (see
    ``_CLEAN_RUN_WARN_ROWS``), which the page tells the reader to expect.
    """
    shown = [line.strip() for line in _try_it_section().splitlines() if line.strip()]
    candidates = [line for line in shown
                  if line.startswith("summary:") and line.endswith("verdict ok")]
    assert candidates, (
        "the try-it section no longer shows the census's summary line, so the "
        "assertion in the try-it test would not be the page's own promise"
    )
    line = candidates[0]
    head, _, tail = line.partition("clean;")
    count, _, _ = tail.rpartition("verdict ok")
    assert head == "summary: " and count.strip() == "N finding(s);", (
        f"the documented summary line does not have the shape the census always "
        f"prints, count included: {line!r}"
    )
    # A concrete count so the caller can compare a real line to it; the caller
    # checks only the count itself, which is the part the page leaves open.
    return f"summary: clean; {len(_CLEAN_RUN_WARN_ROWS)} finding(s); verdict ok"


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


def _assert_hygiene_ran(lines: list[str]) -> None:
    """The census ran its hygiene checker: no row of this run says it did not.

    ``hygiene scan`` is the subject the census gives the row it emits when
    ``scripts/public_safety.py`` is missing, unloadable, or the tree is not a
    git repository. Asserting its absence is what makes the run proof that the
    checker was present: a planted or missing checker, or a --repo the census
    cannot resolve, fails here rather than reading as a clean summary.
    """
    not_run = [line for line in lines if _HYGIENE_NOT_RUN_MARKER in line]
    assert not not_run, (
        "the documented run reports its hygiene scan as not run, so the tree is "
        f"not the topology the page sells: {not_run}"
    )


def test_the_documented_try_it_path_works(tmp_path: Path) -> None:
    """The README's own commands, run verbatim against a materialised noni clone
    and a separate scratch repository, produce what the page promises: one
    committed record, a census whose last line is the documented clean summary
    with its hygiene scan actually run, and a tree that stays clean afterwards.

    The topology is the documented one: the scripts come from the clone the page
    clones, ``--repo .`` names the reader's own repository (the commands' cwd),
    and nothing is installed in that repository beforehand. That is the only
    shape in which the promise can break, and the only one whose census output a
    reader can compare to the page.
    """
    clone = tmp_path / NONI_DIR
    _materialise_clone(clone)
    repo = _reader_repository(tmp_path)
    summary_line = _documented_summary_line()
    env = _reader_env()

    for argv in _try_it_commands():
        cmd = _argv_for_run(argv, clone, repo)
        proc = _run_documented(cmd, repo, env)
        assert proc.returncode == 0, (
            f"documented command failed ({proc.returncode}): {argv}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
        if _script_name(argv) == "census.py":
            lines = proc.stdout.splitlines()
            assert lines, f"the census printed nothing: {argv}"
            _assert_hygiene_ran(lines)
            reported = _assert_documented_summary(lines[-1], summary_line)
            # Every row the summary counted must appear above it, by class word:
            # a count that did not come from the rows would be a number the page
            # invented.
            for row_class in _CLEAN_RUN_WARN_ROWS[:reported]:
                assert any(row_class in line for line in lines[:-1]), (
                    f"the summary counted {reported} finding(s) but no row names "
                    f"{row_class!r}:\n{proc.stdout}"
                )

    records = sorted((repo / "noni" / "decisions").glob("*.json"))
    assert len(records) == 1, f"expected one committed record, got {[p.name for p in records]}"
    assert records[0].read_text(encoding="utf-8").strip(), "the record is empty"
    head = _git(repo, "log", "--oneline", "--format=%s").stdout
    assert records[0].stem in head, (
        f"the record is not committed: HEAD subjects are {head!r}"
    )
    # The whole tree, because that is the page's promise: a ``-- noni`` scope
    # would permit untracked state anywhere else in the reader's tree, which is
    # precisely what "it never writes" rules out. One class of file is excluded,
    # and the exclusion is named rather than scoped around: when the suite runs
    # under the documented gate, each launched interpreter writes coverage's own
    # ``.coverage.<host>.pid<pid>.*`` data file into the tree it ran in. Those
    # are the harness measuring the product, not the product writing, and they
    # are matched by a pattern anchored at the file's own start so no product
    # output can hide behind them.
    dirty = [line for line in _git(repo, "status", "--porcelain").stdout.splitlines()
             if not _coverage_data_line(line)]
    assert dirty == [], (
        "the documented path left the reader's tree dirty, which contradicts the "
        f"page: {dirty}"
    )


# coverage's subprocess data file name, as [tool.coverage.run] produces it with
# parallel = true: ``.coverage.<host>.pid<pid>.<seq>``. Pinned here against the
# harness's own COVERAGE_PROCESS_START being set, not against a product path.
_COVERAGE_DATA_FILE = re.compile(r"^\.coverage\.[^.]+\.pid\d+\.[\w-]+\.[\w-]+$")


def _coverage_data_line(porcelain_line: str) -> bool:
    """True when one porcelain row names a coverage data file, not a product file.

    Only an untracked (``??``) row at the tree's top level counts: a modified or
    staged entry, or anything inside ``noni/`` or ``skills/``, is never coverage's
    and so is never excused here.
    """
    if not porcelain_line.startswith("?? "):
        return False
    path = porcelain_line[3:].strip().rstrip("/")
    return "/" not in path and bool(_COVERAGE_DATA_FILE.match(path))


def test_the_try_it_census_reports_a_failure_it_found(tmp_path: Path) -> None:
    """The documented census command also has to fail honestly.

    The page sells the census's "honest exit codes", and the clean-run test above
    pins only the exit-0 half, so a regression that turned a finding into a clean
    verdict would pass it. One malformed register file is planted in the same
    scratch tree and the same census command from the block is run against it, so
    the failing rendering (non-zero exit, a fail verdict line, the class word and
    the row's own subject) is observed rather than assumed.
    """
    clone = tmp_path / NONI_DIR
    _materialise_clone(clone)
    repo = _reader_repository(tmp_path)
    sessions = repo / "noni" / "sessions"
    sessions.mkdir(parents=True)
    # An allocated register name is <YYYY-MM-DD>-<6 hex>.md; this one is not.
    (sessions / "2026-10-01-not-hex.md").write_text("- identity: x\n", encoding="utf-8")

    census = [argv for argv in _try_it_commands() if _script_name(argv) == "census.py"]
    assert census, "the try-it block does not run the census"
    proc = _run_documented(_argv_for_run(census[0], clone, repo), repo, _reader_env())
    assert proc.returncode != 0, (
        f"a malformed register file did not fail the census: rc={proc.returncode}, "
        f"stdout: {proc.stdout}"
    )
    lines = proc.stdout.splitlines()
    assert lines and lines[-1].startswith("summary: ") and lines[-1].endswith("; verdict fail"), (
        f"the failing run did not end with a fail verdict line: {lines[-1:]!r}"
    )
    assert any("session-malformed" in line and "2026-10-01-not-hex.md" in line
               for line in lines), (
        f"the malformed register file was not reported by name: {proc.stdout}"
    )


@pytest.mark.parametrize("tool", ("decide.py", "census.py"))
def test_the_try_it_scripts_are_where_the_readme_says(tool: str) -> None:
    """The two scripts the page hands a reader are in the skill directories the
    page implies (skills/<skill>/scripts/), where a clone checks them out."""
    matches = sorted(p.name for p in (REPO / "skills").glob(f"*/scripts/{tool}"))
    assert matches == [tool], f"expected exactly one {tool} under skills/, found {matches}"
