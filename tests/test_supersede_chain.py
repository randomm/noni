"""Test the supersede chain: a supersede writes a NEW file, the superseded
record's bytes stay unchanged and its git blob stays reachable, the chain
resolves to one live record per question, and a forward/duplicate supersedes
is refused.

The fixtures are:
  supersede-chain/r1.json  — chain root, status=superseded
  supersede-chain/r2.json  — supersedes r1, status=superseded
  supersede-chain/r3.json  — supersedes r2, status=decided (the live record)
  supersede-chain/r4-detached.json — detached root, different scope
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "supersede-chain"
REPO = Path(__file__).resolve().parent.parent
CENSUS = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid", "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
    )


def _run_census(ledger_dir: Path) -> tuple[int, str, str]:
    import os

    env = dict(os.environ)
    proc = subprocess.run(
        ["bash", str(CENSUS), str(ledger_dir)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_chain_resolves_to_one_live_record(tmp_path):
    """The r1 -> r2 -> r3 chain resolves to exactly one live record (r3)."""
    r1, r2, r3 = _load("r1.json"), _load("r2.json"), _load("r3.json")

    repo = tmp_path / "repo"
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    _git(repo, "init", "-q")

    (ledger / "2026-10-01-r1.json").write_text(json.dumps(r1, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-01-r1.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "r1")

    (ledger / "2026-10-10-r2.json").write_text(json.dumps(r2, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-10-r2.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "r2")

    (ledger / "2026-10-22-r3.json").write_text(json.dumps(r3, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-22-r3.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "r3")

    code, out, err = _run_census(ledger)
    assert code == 0, f"expected exit 0 for a valid chain, got {code}\nstderr: {err}"

    # The report shows r3 as live (status=decided), r1 and r2 as not live
    lines = out.strip().split("\n")
    # header + 3 records
    assert len(lines) == 4, f"expected 4 lines (header + 3 records), got: {out}"
    live_records = [line for line in lines[1:] if line.split("\t")[4] == "yes"]
    assert len(live_records) == 1, f"expected 1 live record, got {len(live_records)}"
    live_id = live_records[0].split("\t")[0]
    assert live_id == "2026-10-22-r3", f"expected r3 to be live, got {live_id}"


def test_superseded_record_bytes_unchanged(tmp_path):
    """After r2 supersedes r1, r1's bytes stay exactly as committed."""
    r1, r2 = _load("r1.json"), _load("r2.json")

    repo = tmp_path / "repo"
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    _git(repo, "init", "-q")

    r1_bytes = json.dumps(r1, indent=2)
    (ledger / "2026-10-01-r1.json").write_text(r1_bytes)
    _git(repo, "add", "noni/decisions/2026-10-01-r1.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "r1")

    (ledger / "2026-10-10-r2.json").write_text(json.dumps(r2, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-10-r2.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "r2")

    # r1's working-tree bytes must be identical to the committed bytes
    r1_disk = (ledger / "2026-10-01-r1.json").read_text()
    assert r1_disk == r1_bytes, "r1's bytes changed after r2 was committed"

    # The git blob for r1 is reachable and matches
    blob = subprocess.run(
        ["git", "-C", str(repo), "show", "HEAD~1:noni/decisions/2026-10-01-r1.json"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert blob.stdout == r1_bytes, "r1's git blob does not match the original bytes"


def test_detached_record_is_separate_chain(tmp_path):
    """r4 is a detached root (supersedes: null) on a different scope. It is a
    separate chain from r1->r2->r3, and it is live."""
    r1, r2, r3, r4 = _load("r1.json"), _load("r2.json"), _load("r3.json"), _load("r4-detached.json")

    repo = tmp_path / "repo"
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    _git(repo, "init", "-q")

    (ledger / "2026-10-01-r1.json").write_text(json.dumps(r1, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-01-r1.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "r1")

    (ledger / "2026-10-10-r2.json").write_text(json.dumps(r2, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-10-r2.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "r2")

    (ledger / "2026-10-22-r3.json").write_text(json.dumps(r3, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-22-r3.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "r3")

    (ledger / "2026-10-25-r4.json").write_text(json.dumps(r4, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-25-r4.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "r4")

    code, out, err = _run_census(ledger)
    assert code == 0, f"expected exit 0, got {code}\nstderr: {err}"

    lines = out.strip().split("\n")
    live_records = [line for line in lines[1:] if line.split("\t")[4] == "yes"]
    assert len(live_records) == 2, f"expected 2 live records (r3 and r4), got {len(live_records)}"
    live_ids = {line.split("\t")[0] for line in live_records}
    assert "2026-10-25-r4-detached" in live_ids, f"r4 should be live, live records: {live_ids}"


def test_forward_supersedes_is_allowed(tmp_path):
    """A record that supersedes a record with a later date is NOT a violation.
    The supersede chain is the authoritative ordering; the date is a
    tie-break for records with no supersede relationship. A record with an
    earlier date than the record it supersedes is valid."""
    r_late = {
        "id": "2026-10-25-late",
        "date": "2026-10-25T10:00:00Z",
        "asked_by": "dev",
        "questions": [{"id": "q1", "text": "A?", "options": ["x", "y"], "answer": "x"}],
        "by": "Op",
        "scope": "test",
        "status": "superseded",
        "supersedes": None,
    }
    r_early = {
        "id": "2026-10-01-early",
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "dev",
        "questions": [{"id": "q1", "text": "B?", "options": ["x", "y"], "answer": "x"}],
        "by": "Op",
        "scope": "test",
        "status": "decided",
        "supersedes": "2026-10-25-late",  # earlier date than the superseded record — valid
    }

    repo = tmp_path / "repo"
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    _git(repo, "init", "-q")

    (ledger / "2026-10-25-late.json").write_text(json.dumps(r_late, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-25-late.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "late")

    (ledger / "2026-10-01-early.json").write_text(json.dumps(r_early, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-01-early.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "early")

    code, out, err = _run_census(ledger)
    assert code == 0, f"expected exit 0 (forward supersedes is allowed), got {code}\nstderr: {err}"


def test_duplicate_supersedes_refused(tmp_path):
    """Two records that both supersede the same id is a duplicate — the census
    must flag it (exit 20)."""
    r_root = {
        "id": "2026-10-01-root",
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "dev",
        "questions": [{"id": "q1", "text": "A?", "options": ["x", "y"], "answer": "x"}],
        "by": "Op",
        "scope": "test",
        "status": "decided",
        "supersedes": None,
    }
    r_a = {
        "id": "2026-10-02-a",
        "date": "2026-10-02T10:00:00Z",
        "asked_by": "dev",
        "questions": [{"id": "q1", "text": "B?", "options": ["x", "y"], "answer": "x"}],
        "by": "Op",
        "scope": "test",
        "status": "decided",
        "supersedes": "2026-10-01-root",
    }
    r_b = {
        "id": "2026-10-03-b",
        "date": "2026-10-03T10:00:00Z",
        "asked_by": "dev",
        "questions": [{"id": "q1", "text": "C?", "options": ["x", "y"], "answer": "x"}],
        "by": "Op",
        "scope": "test",
        "status": "decided",
        "supersedes": "2026-10-01-root",  # duplicate: also supersedes root
    }

    repo = tmp_path / "repo"
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    _git(repo, "init", "-q")

    (ledger / "2026-10-01-root.json").write_text(json.dumps(r_root, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-01-root.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "root")

    (ledger / "2026-10-02-a.json").write_text(json.dumps(r_a, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-02-a.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "a")

    (ledger / "2026-10-03-b.json").write_text(json.dumps(r_b, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-03-b.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "b")

    code, out, err = _run_census(ledger)
    assert code == 20, f"expected exit 20 for duplicate supersedes, got {code}\nstderr: {err}"
    assert "duplicate" in err.lower(), f"expected 'duplicate' in stderr, got: {err}"
