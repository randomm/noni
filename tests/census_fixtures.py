"""Shared builders for the unified census's test suite.

Held in a non-test module so every census test file builds its fixture repo the
same way and pytest never collects the builders as tests of their own. The runners
that call the census live in ``census_run.py``, not here: these only put state on
disk. Copied verbatim from ``tests/test_census_unified.py``, which held the whole
unified suite before the issue #52 split: its ledger-empty, sessions-register,
sessions-listing, sessions-probe, hygiene and ledger-state-vocabulary tests now
live in ``tests/test_census_ledger_empty.py``,
``tests/test_census_sessions_register.py``,
``tests/test_census_sessions_listing_once.py``,
``tests/test_census_sessions_listing_fault.py``,
``tests/test_census_sessions_probe_contract.py``, ``tests/test_census_hygiene.py``
and ``tests/test_census_ledger_state_vocabulary.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from _harness import _commit_file, _git, _init_repo


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

def _session_body(identity: str, status: str = "active", claims: list[str] | None = None,
                  host: str = "ws-1", started: str = "2026-10-01T10:00:00Z") -> str:
    lines = [
        f"- identity: {identity}",
        f"- host/worktree: {host}",
        f"- started: {started}",
        f"- status: {status}",
        "- claims:",
    ]
    for c in claims or []:
        lines.append(f"  - claim: {c}")
    return "\n".join(lines) + "\n"

def _sessions_fixture(tmp_path) -> Path:
    """A repo with two committed register files, so a fault alone decides.

    The ledger is committed too: an isolated fixture repo always emits the
    ``ledger-empty`` warn, and a test that counted every finding row of the run
    would be counting another group's row rather than the fault's. Used by the
    deleted-file class and the listing-fault class, whose rows both have to be
    the fault's and not another group's.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("developer"))
    _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md", _session_body("reviewer"))
    return repo

def _sessions_fault_row(sessions_arg: str, fault: str) -> dict:
    """The one fault row the shared builder composes for a register path.

    Drives ``_append_sessions_listing_fault`` directly with the census's own
    injected helpers, so a claim about which scrubber a field passes through is a
    claim about the row and not about how a test wires the same functions
    together.
    """
    census = census_module()
    found: list[dict] = []
    census._append_sessions_listing_fault(
        Path(sessions_arg), Path("/srv/repos/proj"), False, found, fault)
    assert len(found) == 1, found
    return found[0]

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
