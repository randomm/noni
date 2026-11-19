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

    A hygiene test that plants a violation needs an active class: with no list
    configured the class says so in a note and emits no row at all (issue #194),
    and a list that exists and cannot be read answers with its own inactive row.
    Writing an env-named file with at least one entry (the seam
    tests/test_public_safety.py uses) leaves the deny-list row out of the way of
    the violation under test. conftest's isolated env has already cleared
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


def _with_no_denylist(monkeypatch, tmp_path: Path):
    """Close both deny-list routes, so the class is in the ``absent`` state.

    The state the census now answers with a note rather than a warn row: no
    ``NONI_SCRUB_DENYLIST`` and no default file the checker could find. The env
    route is already cleared by conftest's autouse fixture, so the seam that
    decides the state is ``_default_denylist_file``, pointed at a path that does
    not exist (the shape ``tests/test_env_isolation.py`` uses). Returns the target
    module so a caller can hold on to the object the census will actually run.
    """
    from census_hygiene_target import _hygiene_target

    monkeypatch.delenv(DENYLIST_ENV_VAR, raising=False)
    target = _hygiene_target()
    monkeypatch.setattr(target, "_default_denylist_file",
                        lambda repo: tmp_path / "no-such-denylist.txt")
    return target
