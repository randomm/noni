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
- every path a fenced block names exists in this repository, which is what
  stops the copy drifting from the tree;
- the try-it block runs for real against a throwaway repository and produces
  the documented outcome: one committed record and a census that ends clean;
- the README links CONTRIBUTING.md, and CONTRIBUTING.md still carries the gate
  commands the CI workflow runs, so the move of that block cannot be a loss.

The hygiene and public-safety classes themselves are tested elsewhere; here the
README only has to stay clean enough for them.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from _harness import REPO, _git, subprocess_env

README = REPO / "README.md"
CONTRIBUTING = REPO / "CONTRIBUTING.md"

# The sections a first-time reader needs, in the order the page answers them.
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

# The programs a try-it block may name besides a noni script. ``decide.py``
# refuses with exit 3 and the hint ``git -C <repo> config user.name <name>``
# when the tree has no identity, so the page that tells a reader to set one is
# quoting the product's own fix rather than inventing a shell step.
_ALLOWED_SHELL: frozenset[frozenset[str]] = frozenset(
    {frozenset({"git"}), frozenset({"git", "config"})}
)

# The shapes of the paths noni creates inside the project it attaches to, and
# the venv the dev commands install into. Neither exists in this repository;
# each is claimed by the tool that makes it, and the check below proves the
# claiming file says so.
_ATTACHED_STATE_PATTERNS: tuple[str, ...] = (
    r"noni/decisions/?",
    r"noni/sessions/?",
    r"noni/direction/?",
    r"noni/direction/order\.json",
    r"\.venv/bin/[\w.-]+",
)

# The commands a documented path must actually run: one writer and the arbiter.
# Dropping either leaves the page promising a five-minute tour that no longer
# reaches a census verdict, which a block that merely runs would not notice.
REQUIRED_TRY_IT_SCRIPTS: frozenset[str] = frozenset({"decide.py", "census.py"})

# Where an attached-state or venv claim is documented, keyed by pattern.
_STATE_DOCS: dict[str, str] = {
    r"noni/decisions/?": "skills/steering-ledger/SKILL.md",
    r"noni/sessions/?": "skills/sessions-claims/SKILL.md",
    r"noni/direction/?": "skills/direction/SKILL.md",
    r"noni/direction/order\.json": "skills/direction/SKILL.md",
    r"\.venv/bin/[\w.-]+": "pyproject.toml",
}


def _state_token_claim(token: str) -> tuple[str, str] | None:
    """The (pattern, claiming file) when ``token`` names attached state.

    None for a token that is not an attached-state shape. The claiming file is
    the one the table names, and it must carry the token's own basename, so a
    token cannot be excused by a table nobody maintains.
    """
    for pattern in _ATTACHED_STATE_PATTERNS:
        if re.fullmatch(pattern, token):
            doc = _STATE_DOCS[pattern]
            return (pattern, doc)
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
    """The lines of the try-it block: the last ```bash fence on the page."""
    bash_blocks = [lines for info, lines in _fenced_blocks(_readme_text()) if info == "bash"]
    assert bash_blocks, "README.md documents no bash block to try"
    return bash_blocks[-1]


def _argv_for_run(argv: list[str]) -> list[str]:
    """The argv for one documented command, resolved against this checkout.

    ``python3`` becomes the running interpreter, so the block measures the same
    Python the suite runs under. A script path is resolved against the
    repository rather than the attached project: the page tells a reader to put
    ``skills/`` in their own tree, and this test uses the one copy that exists.
    """
    if argv[0] == "python3":
        assert len(argv) > 1, f"try-it command names no script: {argv}"
        return [sys.executable, str(REPO / argv[1]), *argv[2:]]
    return list(argv)


def _block_commands(lines: list[str]) -> list[list[str]]:
    """The commands of one block as argv lists, continuations joined, quotes kept."""
    commands: list[list[str]] = []
    pending: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        continued = stripped.endswith("\\")
        pending.append(stripped[:-1].rstrip() if continued else stripped)
        if not continued:
            commands.append(shlex.split(" ".join(pending), posix=False))
            pending = []
    assert not pending, "try-it block ends in a line continuation"
    return commands


def _block_words(argv: list[str]) -> frozenset[str]:
    """The command words of one line: the program, plus its subcommand.

    ``git config user.name Casey`` reduces to ``{git, config}`` and
    ``python3 skills/.../decide.py ...`` to ``{python3}``, which is what the
    allow-list above matches against: the question is which programs a page may
    tell a reader to run, not which flags it passes.
    """
    if not argv:
        return frozenset()
    words = {argv[0]}
    for token in argv[1:]:
        if token.startswith("-"):
            continue
        if any(part in token for part in (".", "/")):
            break
        words.add(token)
        break
    return frozenset(words)


# The word a venv tool's claim is checked for in the file that owns the gate.
_VENV_CLAIM = "pip"


def _section(text: str, heading: str) -> str:
    """The body of one ``## heading`` section, up to the next heading."""
    start = text.find(f"## {heading}")
    assert start >= 0, f"README.md has no '## {heading}' section"
    rest = text[start + len(f"## {heading}"):]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def _paths_in(text: str) -> list[str]:
    return [token for token in _PATH_TOKEN.findall(text) if not token.startswith("http")]


def test_readme_follows_the_documented_section_order():
    """The page answers what noni is, why, how to try it, and where it stands,
    in that order, so a first-time reader is not handed a design note."""
    text = _readme_text()
    positions = []
    for section in EXPECTED_SECTIONS:
        heading = f"## {section}"
        assert heading in text, f"README.md is missing the section {heading!r}"
        positions.append(text.index(heading))
    assert positions == sorted(positions), (
        f"README sections are out of order: {list(EXPECTED_SECTIONS)} expected"
    )
    assert text.index("# noni") < positions[0], "README does not open with the product"


def test_readme_stays_within_the_line_limit():
    """The page stays short enough to read in one minute (the ticket's cap)."""
    lines = _readme_text().count("\n")
    assert lines <= README_LINE_LIMIT, f"README.md is {lines} lines; the cap is {README_LINE_LIMIT}"


def test_readme_states_the_purity_rule_near_the_end():
    """The purity sentence moved to the tail of the page but stayed on it: it
    belongs after the reader knows what noni is, not before.

    The rule is pinned to one section by heading, so a purity sentence planted
    above Status cannot satisfy it from the section further down."""
    text = _readme_text()
    section = _section(text, "Purity")
    lowered = section.lower()
    assert "purity" in lowered, "the Purity section does not name the purity rule"
    assert "project-specific" in lowered, "the Purity section does not state the rule"
    earlier = text[: text.index("## Purity")].lower()
    assert "purity" not in earlier, (
        "the purity rule moved back above the end of the page, where a first-time "
        "reader meets design doctrine before the product"
    )


def test_readme_links_the_contributing_page():
    """The dev commands moved to CONTRIBUTING.md and the link stayed behind:
    no test of the old page would notice a silent drop of either."""
    assert CONTRIBUTING.is_file(), "CONTRIBUTING.md is missing"
    assert "CONTRIBUTING.md" in _readme_text(), "README.md does not link CONTRIBUTING.md"


def test_contributing_carries_the_gate_commands():
    """The moved block is the gate CI runs, not a summary of it.

    The commands are read from the CI workflow rather than copied as literals,
    so a gate step that changes there fails here instead of leaving the page
    documenting a gate nobody runs.
    """
    body = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    contributing = CONTRIBUTING.read_text(encoding="utf-8")
    for command in CONTRIBUTING_GATE_COMMANDS:
        assert command in contributing, f"CONTRIBUTING.md does not document {command!r}"
        if command.startswith("python -m venv"):
            continue  # CI sets the venv up in its own step
        step = command.split(" ", 2)[1] if command.startswith(".venv/bin") else command
        assert step in body, f"CI does not run {command!r}, which CONTRIBUTING.md documents"


def test_every_path_the_readme_names_exists():
    """No command or sentence on either page names a script or file this
    repository does not have, so the copy cannot drift from the tree.

    Two kinds of token cannot resolve here and are checked instead against the
    file that makes the claim: a placeholder path (``<skill>``) is resolved by
    substituting each skill that exists, and attached state (``noni/...``,
    ``.venv/bin/...``) has to appear in the skill or config that creates it."""
    skills = sorted(p.name for p in (REPO / "skills").iterdir() if p.is_dir())
    missing = []
    for doc in (README, CONTRIBUTING):
        for token in _paths_in(doc.read_text(encoding="utf-8")):
            if "<" in token:
                if any((REPO / token.replace("<skill>", name)).exists() for name in skills):
                    continue
                missing.append(f"{doc.name}: {token} (no skill matches the placeholder)")
                continue
            if (REPO / token).exists():
                continue
            claim = _state_token_claim(token)
            if claim is not None and _claim_is_documented(token, claim[1]):
                continue
            missing.append(f"{doc.name}: {token}")
    assert not missing, f"docs name paths that do not exist: {sorted(missing)}"


def _claim_is_documented(token: str, doc_rel: str) -> bool:
    """True when ``doc_rel`` makes the same claim about ``token``.

    The claim is checked where it is made: the directory or file noni tells a
    reader it will create has to appear in the skill that creates it, and a venv
    tool has to appear in the gate configuration that installs it (CI's own
    install step runs ``.venv/bin/pip``, which is the other route to it).
    """
    doc = REPO / doc_rel
    if not doc.is_file():
        return False
    body = doc.read_text(encoding="utf-8")
    if doc_rel == "pyproject.toml":
        body += (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        return _VENV_CLAIM in body
    return Path(token).name.rstrip("/") in body


def _try_it_commands() -> list[list[str]]:
    """The try-it block's commands, with the identity line required to be there.

    ``decide.py`` refuses exit 3 without a name in ``git config user.name``, so
    a page that dropped that line documents a five-minute path that stops at the
    first command. The test runs with the tree's identity set the way a reader's
    own repository has it, so it cannot notice that on its own.
    """
    commands = _block_commands(_try_it_block())
    assert commands, "try-it block is empty"
    identity = [argv for argv in commands if _block_words(argv) == frozenset({"git", "config"})]
    assert identity, (
        "the try-it block does not set git config user.name, so the documented "
        "path would stop at decide.py's exit-3 identity refusal"
    )
    return commands


def test_try_it_block_names_scripts_that_run():
    """Every command in the try-it block is a real entry point: git for the
    identity line, an existing executable skill script run under python3
    otherwise. A bare ``decide.py`` would satisfy a name-existence check and
    fail on a real shell, so the interpreter is part of the contract."""
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
        script = REPO / argv[1]
        assert script.is_file(), f"try-it block names no such script: {argv[1]}"
        # The census module has no shebang (it is always launched by path, the
        # way the census skill documents it), so only the writer is required to
        # carry the executable bit that tests/test_skill_scrub.py pins.
        if script.name == "decide.py":
            assert script.stat().st_mode & 0o111, f"{argv[1]} is not executable"
        ran_a_script = True
    assert ran_a_script, "try-it block runs no noni script"
    named = {Path(argv[1]).name for argv in commands if _block_words(argv) != frozenset({"git"})
             and len(argv) > 1}
    assert REQUIRED_TRY_IT_SCRIPTS <= named, (
        f"try-it block must record a decision and read the census; it names {sorted(named)}"
    )


def test_the_documented_try_it_path_works(tmp_path):
    """The README's own commands, run verbatim against a throwaway repository,
    produce the outcome the page promises: a committed record, a census that
    reads clean, and a tree that stays clean afterwards.

    The scripts run from this checkout (the page says copy them into your
    project; the test keeps one copy of them) and the attached repository is
    the ``--repo .`` the page shows, so the cwd is the attached project.
    """
    repo = tmp_path / "attached"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "initial")
    _git(repo, "config", "user.name", "Replay")
    _git(repo, "config", "user.email", "replay@fixture.invalid")

    text = _readme_text()
    assert "summary: clean" in text and "verdict ok" in text, (
        "README no longer documents the census's clean line, so the assertion "
        "below would no longer be the page's own promise"
    )

    env = subprocess_env()
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"

    for argv in _try_it_commands():
        cmd = _argv_for_run(argv)
        proc = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, env=env, timeout=120
        )
        assert proc.returncode == 0, (
            f"documented command failed ({proc.returncode}): {argv}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
        if argv[0] == "python3" and "census.py" in argv[1]:
            assert "summary: clean" in proc.stdout and "verdict ok" in proc.stdout, (
                f"the census did not report the documented clean result: {proc.stdout}"
            )

    records = sorted((repo / "noni" / "decisions").glob("*.json"))
    assert len(records) == 1, f"expected one committed record, got {[p.name for p in records]}"
    assert records[0].read_text(encoding="utf-8").strip(), "the record is empty"
    head = _git(repo, "log", "--oneline", "--format=%s").stdout
    assert records[0].stem in head, (
        f"the record is not committed: HEAD subjects are {head!r}"
    )
    assert _git(repo, "status", "--porcelain", "--", "noni").stdout == "", (
        "the documented path left the attached tree dirty, which contradicts the page "
        "(a whole-tree check would also catch coverage's own subprocess data files, "
        "which this run writes into the scratch tree by design)"
    )


@pytest.mark.parametrize("tool", ("decide.py", "census.py"))
def test_the_try_it_scripts_are_where_the_readme_says(tool):
    """The two scripts the page hands a reader are in the skill directories the
    page implies (skills/<skill>/scripts/), not somewhere the copy would miss."""
    matches = sorted(p.name for p in (REPO / "skills").glob(f"*/scripts/{tool}"))
    assert matches == [tool], f"expected exactly one {tool} under skills/, found {matches}"
