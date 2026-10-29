"""Planting and clearing the deny-list the hygiene class reads.

``_with_denylist`` writes an env-named deny-list holding the entries a test wants
active; ``_clear_denylist`` undoes it. Out of the hygiene test files themselves
because both the class file and the row-contract file plant it. Copied verbatim from
``tests/test_census_unified.py``, whose hygiene class now lives in
``tests/test_census_hygiene.py`` and ``tests/test_census_hygiene_row_contract.py``.
"""

from __future__ import annotations

from pathlib import Path

DENYLIST_ENV_VAR = "NONI_SCRUB_DENYLIST"

def _with_denylist(tmp_path: Path, *entries: str):
    """Activate the deny-list class for a hygiene test.

    The hygiene class always reports: with an absent deny-list its only row is
    the "class inactive" notice. Tests that want the violation rows write an
    env-named deny-list with at least one entry (the seam
    tests/test_public_safety.py uses), so the deny-list row does not drown the
    violation under test. conftest's isolated env has already cleared
    NONI_SCRUB_DENYLIST, so this only ever sees the fixture file.
    """
    import os

    path = tmp_path / "census-hygiene-denylist.txt"
    path.write_text("\n".join(entries) + "\n", encoding="utf-8")
    os.environ[DENYLIST_ENV_VAR] = str(path)

def _clear_denylist() -> None:
    """Undo _with_denylist (conftest's autouse fixture re-clears it per test)."""
    import os

    os.environ.pop(DENYLIST_ENV_VAR, None)
