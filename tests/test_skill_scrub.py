"""Scrub check for the steering-ledger skill and its fixtures.

Fails on absolute home paths, the operator's username (parameterised, not
hard-coded), and token-shaped strings. Env-var names (e.g. GH_TOKEN) and
documented ~/ forms are allowed.

The operator username is read from the git config of the repo (user.name) or
from the $USER environment variable, not hard-coded. This is the fix for a
prior version of this check which hard-coded a real username — the noni
purity rule says no project-specific content, and the operator's username is
project-specific.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# The shared pattern registry, from the package's own checker, so that new
# secret shapes or path patterns are added in exactly one place.
from public_safety import FIXTURE_HOME_PATH_PATTERNS, HOME_PATH_PATTERNS, SECRET_PATTERNS  # noqa: E402

SKILL_DIRS = [REPO / "skills" / "steering-ledger", REPO / "skills" / "sessions-claims",
              REPO / "skills" / "census", REPO / "skills" / "direction"]
FIXTURES = REPO / "tests" / "fixtures"


def _operator_username() -> str:
    """Resolve the operator's username from the environment or git config.

    Parameterised: reads $USER, then git config user.name, then falls back to
    the OS-level username. This is the fix for a prior version of this check
    which hard-coded a real username.
    """
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    if user:
        return user
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO), "config", "user.name"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        name = result.stdout.strip()
        if name:
            return name
    except (subprocess.SubprocessError, OSError):
        pass
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return ""


OPERATOR_USERNAME = _operator_username()

FORBIDDEN: list[tuple[re.Pattern, str]] = [
    *HOME_PATH_PATTERNS,
    *FIXTURE_HOME_PATH_PATTERNS,
    (re.compile(re.escape(OPERATOR_USERNAME), re.IGNORECASE), f"operator username ({OPERATOR_USERNAME or 'unknown'})"),
    *SECRET_PATTERNS,
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}"), "bearer token"),
]

# __pycache__/*.pyc are build artifacts: never scan them.
SKILL_FILES = sorted(
    p
    for d in SKILL_DIRS
    for p in d.rglob("*")
    if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
)

FIXTURE_FILES = sorted(
    p
    for p in FIXTURES.rglob("*")
    if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
)


def test_skill_files_present():
    """The steering-ledger skill has the expected file layout, including the
    decide.py writer next to the read-only census shim."""
    rels = {p.relative_to(d).as_posix() for d in SKILL_DIRS for p in SKILL_FILES if p.is_relative_to(d)}
    assert "SKILL.md" in rels, f"SKILL.md missing; have: {rels}"
    assert "scripts/census.sh" in rels, f"scripts/census.sh missing; have: {rels}"
    assert "scripts/decide.py" in rels, f"scripts/decide.py missing; have: {rels}"
    # decide.py's git runner and atomic writer no longer live beside it: they are
    # package modules (noni.gitwrite), whose presence in the package is pinned by
    # test_package_files_present. The wrapper this directory must still carry is
    # the entry point the skill documents.
    for ref in ("references/decisions.md", "references/modes.md", "references/supersede.md", "references/census.md"):
        assert ref in rels, f"{ref} missing; have: {rels}"
    # The direction skill's writer is part of the scrubbed layout too: a skill
    # directory whose script quietly left the list would stop being scrubbed.
    direction = REPO / "skills" / "direction"
    direction_rels = {p.relative_to(direction).as_posix()
                      for p in SKILL_FILES if p.is_relative_to(direction)}
    assert "SKILL.md" in direction_rels, f"direction SKILL.md missing; have: {direction_rels}"
    assert "scripts/order.py" in direction_rels, (
        f"scripts/order.py missing; have: {direction_rels}")
    # The writer's helper modules are package modules now, not files of this
    # skill; the wrapper that the skill documents is what must remain here.


def test_package_files_present():
    """Every shipped tool is a package module, and no helper quietly left.

    The skills' directories carry only wrappers now, so the module list that used
    to be pinned by the skill layout has to be pinned here instead: a helper that
    left ``src/noni/`` would stop being scrubbed (the parametrised scan below
    walks the skill directories, not the package). The coverage gate and the
    wheel have their own lists, and tests/test_gate_wiring.py and
    tests/test_wheel_contents.py compare those against the directory itself, so
    all four views of the shipped set are pinned somewhere.
    """
    shipped = {p.name for p in (REPO / "src" / "noni").glob("*.py")}
    for module in (
        "census.py", "census_hygiene.py", "census_json.py", "census_ledger.py",
        "census_ordering.py", "census_ordering_readers.py", "census_sessions.py",
        "census_sessions_probe.py", "census_text.py",
        "claim.py", "cli.py",
        "decide.py", "gitenv.py", "gitwrite.py", "labels.py", "order.py",
        "order_gitwrite.py",
        "orderschema.py", "orderstate.py", "public_safety.py", "register.py",
        "shim_help.py", "targetschema.py",
    ):
        assert module in shipped, f"src/noni/{module} missing; have: {sorted(shipped)}"


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.name)
def test_no_secrets_or_machine_local_paths_in_skills(path):
    """No skill file contains a machine-local path, the operator's username,
    or a token-shaped string."""
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        for pattern, label in FORBIDDEN:
            rel = next((path.relative_to(d).as_posix() for d in SKILL_DIRS if path.is_relative_to(d)), str(path))
            assert not pattern.search(line), f"{rel}:{lineno}: {label}"


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_no_secrets_or_machine_local_paths_in_fixtures(path):
    """No fixture file contains a machine-local path, the operator's username,
    or a token-shaped string. This is the noni purity rule: no project-specific
    content, and the fixture set itself carries no machine-local path."""
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        for pattern, label in FORBIDDEN:
            # Skip the operator-username check for fixtures that are supposed
            # to carry a generic "Operator" name — the fixtures use "Operator"
            # as a generic author name, not the real operator's username.
            if "operator username" in label:
                continue
            assert not pattern.search(line), f"{path.relative_to(FIXTURES)}:{lineno}: {label}"


def test_skill_md_within_agents_size_limit():
    """SKILL.md is within the 400-line limit (the driver's AGENTS.md cap)."""
    for d in SKILL_DIRS:
        skill_md = d / "SKILL.md"
        if skill_md.is_file():
            lines = skill_md.read_text(encoding="utf-8").count("\n")
            assert lines <= 400, f"{d.name}/SKILL.md is {lines} lines; the cap is 400"


def test_census_script_is_executable():
    """Both steering-ledger scripts have the executable bit (they are meant to
    be run directly): the read-only census shim and the decide.py writer."""
    for name in ("census.sh", "decide.py"):
        script = REPO / "skills" / "steering-ledger" / "scripts" / name
        assert script.stat().st_mode & 0o111, f"{name} is not executable"


# The four sessions writers, each documented in SKILL.md as
# ``scripts/<name>.py --repo ...`` -- the form that fails with "Permission
# denied" on a fresh clone when the bit is missing.
SESSIONS_WRAPPERS = ("register.py", "claim.py", "close.py", "release.py")


def test_sessions_writers_are_executable():
    """All four session writers are executable, as the skill invokes them.

    The wrapper form is the one SKILL.md documents, so a writer that landed in
    the tree at 0644 is broken product surface rather than a cosmetic detail:
    the reader's first ``scripts/close.py --repo .`` would not run.
    """
    for name in SESSIONS_WRAPPERS:
        script = REPO / "skills" / "sessions-claims" / "scripts" / name
        assert script.stat().st_mode & 0o111, f"{name} is not executable"
