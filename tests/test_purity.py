"""Purity tests: the noni purity rule (README "no project-specific content")
must itself be a test.

The purity rule has two tiers:
1. Core skills carry neither project content nor driver-tool vocabulary.
2. The fixture set carries no machine-local path and no operator-specific
   content.

These tests enforce the two-tier purity:
- The core skill files (SKILL.md, references/*.md) contain no references to
  specific attached projects, no vocabulary from any specific driver, tracker
  or project, and no project-specific content.
- The fixture set (tests/fixtures/) contains no machine-local paths
  (/home/<user>, /Users/<user>) and no operator-specific content.

The banned vocabulary for tier 1 is the untracked local deny-list loaded via
``public_safety.load_denylist`` — the same source the scrub uses — so no real
external tool/project name ever has to be committed to this file. When the
deney-list is absent the vocabulary check is skipped via pytest.skip with a
visible reason (same contract as the scrub); the structural purity checks
(no committed .git dirs, product docs exist) still run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# The shared pattern registry and the deny-list loader, from the package's own
# checker, so that new secret shapes or path patterns are added in exactly one
# place and the banned vocabulary is the same deny-list the scrub uses (never a
# committed list of real names).
from public_safety import (  # noqa: E402
    FIXTURE_HOME_PATH_PATTERNS,
    HOME_PATH_PATTERNS,
    load_denylist,
)

SKILL_DIRS = [REPO / "skills" / "steering-ledger", REPO / "skills" / "sessions-claims",
              REPO / "skills" / "census", REPO / "skills" / "direction"]
FIXTURES = REPO / "tests" / "fixtures"
README = REPO / "README.md"
PRODUCT = REPO / "docs" / "PRODUCT.md"

# Banned vocabulary for the core skill files: the untracked local deny-list
# (two-tier purity: the core must be viable with no adapter installed). Real
# external tool/project names live only in that deny-list and in adapters;
# nothing real is committed here. Loaded once at module import; when the
# deny-list is absent or inactive, the vocabulary check is skipped via
# pytest.skip with a visible reason (same contract as the scrub's deny-list
# class) while the structural checks below still run.
_DENYLIST = load_denylist()
FORBIDDEN_VOCAB = [
    (re.compile(re.escape(entry), re.IGNORECASE), "external tool/project vocabulary")
    for entry in _DENYLIST.entries
]

# Machine-local path patterns. The known-identity patterns come from the
# shared registry; the fixture-only catch-alls retain any-username coverage
# (the shared registry is deliberately limited to well-known identities for
# the scrub, where any-user names are the deny-list class's job).
FORBIDDEN_PATHS: tuple[tuple[re.Pattern, str], ...] = tuple(HOME_PATH_PATTERNS) + tuple(FIXTURE_HOME_PATH_PATTERNS)

SKILL_CORE_FILES = sorted(
    p
    for d in SKILL_DIRS
    for p in d.rglob("*.md")
    if p.is_file() and "__pycache__" not in p.parts
)

FIXTURE_FILES = sorted(
    p
    for p in FIXTURES.rglob("*")
    if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
)


@pytest.mark.parametrize("path", SKILL_CORE_FILES, ids=lambda p: p.name)
def test_core_skill_has_no_driver_tool_vocabulary(path):
    """The core skill files contain no vocabulary from any specific driver,
    tracker or project. The two-tier purity rule: the core must be viable with
    no adapter installed, and the adapters are the only place those names
    appear.
    """
    if _DENYLIST.status != "ok" or not _DENYLIST.entries:
        # Same contract as the scrub: without an active deny-list the
        # vocabulary class is skipped visibly (pytest.skip, not a silent
        # no-op pass).
        pytest.skip(
            f"deny-list inactive: {_DENYLIST.status}; core skill files "
            "unchecked for external tool/project vocabulary. This is NOT "
            "a purity guarantee. See docs/PUBLISHING.md step 1."
        )
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        for pattern, label in FORBIDDEN_VOCAB:
            rel = path.relative_to(SKILL_DIRS[0].parent.parent) if path.is_relative_to(REPO) else path.name
            assert not pattern.search(line), f"{rel}:{lineno}: {label}"


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_fixtures_have_no_machine_local_paths(path):
    """The fixture set contains no machine-local paths (/home/<user>,
    /Users/<user>). The noni purity rule: no project-specific content, and the
    fixture set itself must be cloneable without a host dependency."""
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        for pattern, label in FORBIDDEN_PATHS:
            assert not pattern.search(line), f"{path.relative_to(FIXTURES)}:{lineno}: {label}"


def test_readme_states_the_purity_rule():
    """The README explicitly states the purity rule: no project-specific
    content. This pins the rule so it cannot be silently removed."""
    assert README.is_file(), "README.md is missing"
    text = README.read_text(encoding="utf-8")
    assert "purity" in text.lower(), "README does not mention the purity rule"
    assert "no project-specific" in text.lower() or "project-specific" in text.lower(), (
        "README does not state the 'no project-specific content' rule"
    )


def test_product_md_exists():
    """The product document exists (it is the binding reference for the
    steering ledger's record shape and the census's exit codes)."""
    assert PRODUCT.is_file(), "docs/PRODUCT.md is missing"


def test_no_committed_git_dir_in_fixtures():
    """The fixtures directory contains no committed .git directory. The
    replay-repo fixture is generated by generate.sh (not committed), so no
    .git dir should be in the fixtures tree."""
    git_dirs = list(FIXTURES.rglob(".git"))
    assert not git_dirs, f"found committed .git dirs in fixtures: {[str(p) for p in git_dirs]}"
