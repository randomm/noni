"""Planting and clearing the committed allowlist the hygiene scan reads.

``_with_allowlist`` writes an env-named allowlist holding the entries a test wants
honoured; ``_clear_allowlist`` undoes it. Beside ``census_denylist.py`` for the same
reason: both the scrub tests and the census's hygiene tests plant it, and a third copy
in a third file is how the format and the tests drift.

Unlike the deny-list, the allowlist is a *committed* file in product terms -- an
exemption widens what the gate accepts, so it must be reviewable. The env var exists for
a caller that keeps its config outside the tree, and it is the cheap route for a test:
planting a tracked file means a commit per case, which is what the committed-path tests
below ``_with_committed_allowlist`` do when the test's claim is about tracked-ness
itself.
"""

from __future__ import annotations

import os
from pathlib import Path

ALLOWLIST_ENV_VAR = "NONI_SCRUB_ALLOWLIST"


def _allowlist_line(path: str, label: str, reason: str = "test fixture") -> str:
    """One allowlist line in the product's format: ``path | label | reason``."""
    return f"{path} | {label} | {reason}"


def _with_allowlist(tmp_path: Path, *lines: str, name: str = "allowlist.txt") -> Path:
    """Activate the allowlist for one test and return the file it wrote.

    conftest's autouse fixture has already cleared ``NONI_SCRUB_ALLOWLIST``, so this
    only ever sees the fixture file it writes here.
    """
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[ALLOWLIST_ENV_VAR] = str(path)
    return path


def _clear_allowlist() -> None:
    """Undo :func:`_with_allowlist` (conftest's autouse fixture re-clears it per test)."""
    os.environ.pop(ALLOWLIST_ENV_VAR, None)


def _committed_allowlist_path(repo: Path) -> Path:
    """The name a committed allowlist carries: the product's constant, not a literal.

    A fixture that typed the filename would keep committing nothing after a rename,
    which is half of AC1 a test could otherwise hide.
    """
    from noni import public_safety

    return repo / public_safety.ALLOWLIST_FILENAME


def _with_committed_allowlist(repo: Path, *lines: str, commit_only: bool = False) -> Path:
    """Write the tree's own tracked allowlist, and commit it.

    The committed route is the one the ticket asks for, and the one a test about
    tracked-ness, staleness or the file's own exemption needs: the env route would let
    a claim about a committed file pass on a file git has never seen.

    Everything in the working tree is added, not only the file: a test that planted a
    fixture and then called this helper must not lose the fixture from the listing,
    since the scan answers for exactly what ``git ls-files`` holds. ``commit_only``
    skips the blanket add for the one test that needs a working-tree file to stay out
    of the listing.
    """
    from _harness import _git

    path = _committed_allowlist_path(repo)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if commit_only:
        _git(repo, "add", "--", path.name)
    else:
        _git(repo, "add", "--", ".")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "allowlist fixture")
    return path


def _entry_fixture(tmp_path: Path, *lines: str) -> Path:
    """Write an allowlist file without naming it in the environment.

    For the tests that hand the path to the loader's seam (``_default_allowlist_file``)
    rather than to the env var, so the precedence rule keeps its own coverage.
    """
    path = tmp_path / "committed-allowlist.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
