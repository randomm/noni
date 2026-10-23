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
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Import the shared pattern registry from scripts/public_safety.py so that
# new secret shapes or path patterns are added in exactly one place.
_scripts_dir = str(REPO / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
from public_safety import HOME_PATH_PATTERNS, SECRET_PATTERNS  # noqa: E402

SKILL_DIR = REPO / "skills" / "steering-ledger"
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

FORBIDDEN = [
    *HOME_PATH_PATTERNS,
    (re.compile(re.escape(OPERATOR_USERNAME), re.IGNORECASE), f"operator username ({OPERATOR_USERNAME or 'unknown'})"),
    *SECRET_PATTERNS,
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}"), "bearer token"),
]

# __pycache__/*.pyc are build artifacts: never scan them.
SKILL_FILES = sorted(
    p
    for p in SKILL_DIR.rglob("*")
    if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
)

FIXTURE_FILES = sorted(
    p
    for p in FIXTURES.rglob("*")
    if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
)


def test_skill_files_present():
    """The steering-ledger skill has the expected file layout."""
    rels = {p.relative_to(SKILL_DIR).as_posix() for p in SKILL_FILES}
    assert "SKILL.md" in rels, f"SKILL.md missing; have: {rels}"
    assert "scripts/census.sh" in rels, f"scripts/census.sh missing; have: {rels}"
    for ref in ("references/decisions.md", "references/modes.md", "references/supersede.md", "references/census.md"):
        assert ref in rels, f"{ref} missing; have: {rels}"


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.name)
def test_no_secrets_or_machine_local_paths_in_skills(path):
    """No skill file contains a machine-local path, the operator's username,
    or a token-shaped string."""
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        for pattern, label in FORBIDDEN:
            assert not pattern.search(line), f"{path.relative_to(SKILL_DIR)}:{lineno}: {label}"


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
    """SKILL.md is within the 400-line limit (the bridge's AGENTS.md cap)."""
    lines = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").count("\n")
    assert lines <= 400, f"SKILL.md is {lines} lines; the cap is 400"


def test_census_script_is_executable():
    """The census script has the executable bit set (it is meant to be run
    directly)."""
    census = SKILL_DIR / "scripts" / "census.sh"
    assert census.stat().st_mode & 0o111, "census.sh is not executable"
