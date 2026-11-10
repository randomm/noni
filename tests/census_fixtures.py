"""Shared builders for the unified census's test suite.

Held in a non-test module so every census test file builds its fixture repo the
same way and pytest never collects the builders as tests of their own. The runners
that call the census live in ``census_run.py``, not here: these only put state on
disk. Copied verbatim from ``tests/test_census_unified.py``, which held the whole
unified suite before the issue #52 split: its ledger-empty,
hygiene and ledger-state-vocabulary tests now
live in ``tests/test_census_ledger_empty.py``,
``tests/test_census_hygiene.py``
and ``tests/test_census_ledger_state_vocabulary.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from _harness import _git


def _commit_dir_state(repo: Path, dirname: str) -> None:
    """Commit the current on-disk contents of a directory (adds + removes) so
    that deletions are part of the committed state."""
    target = repo / dirname
    for p in target.iterdir():
        _git(repo, "add", "-f", str(p))
    _git(repo, "add", "-u", dirname)
    _git(repo, "commit", "-q", "--allow-empty", "-m", f"update {dirname}")

def _valid_record(rec_id: str = "2026-10-01-alpha", status: str = "decided", supersedes=None) -> dict:
    return {
        "id": rec_id,
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "developer",
        "questions": [
            {"id": "q1", "text": "Adopt the new scheduler?", "options": ["yes", "no"], "answer": "yes"}
        ],
        "by": "Operator",
        "scope": "release ordering",
        "status": status,
        "supersedes": supersedes,
    }


def _ndjson_rows(stdout: str) -> list[dict]:
    rows = []
    for line in stdout.strip().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows

def census_module():
    """The census module, for tests that pin one of its contract constants."""
    import importlib

    return importlib.import_module("census")
