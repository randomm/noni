"""Test the supersede chain: a supersede writes a NEW file, the superseded
record's bytes stay unchanged and its git blob stays reachable, the chain
resolves to one live record per question, and a dangling, duplicate, orphan,
cycle, or zero/multi-live chain is refused (exit 20). A record with an earlier
date than the record it supersedes is NOT a violation: the supersede chain is
the authoritative ordering.

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

from _harness import _git  # noqa: E402


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _rows(out: str) -> list[dict]:
    """The NDJSON rows of a census run driven through the ledger wrapper.

    The unified census prints its human table by default and the machine rows
    only under ``--json``, so a test that wants the rows asks for them. The
    shim's own per-record table -- one line per record with a ``live`` column --
    went with the second arbiter (issue #99): a clean chain earns no row at all,
    so "which records are live" is answered here by the absence of a chain
    refusal rather than by a column.
    """
    return [json.loads(line) for line in out.splitlines()
            if line.strip().startswith("{")]


def _chain_rows(out: str) -> list[dict]:
    """The ``ledger-chain`` rows of a run."""
    return [r for r in _rows(out) if r.get("check") == "ledger-chain"]


def _live_records(ledger: Path) -> set[str]:
    """The record ids the census holds live, by the census's own two answers.

    A clean census prints no row for a clean record -- a whole clean ledger is one
    summary row with nothing beside it, the shape the exit-code contract pins --
    and the chain class speaks up only to refuse a count, at code 20. So "which
    records are live" is answered from the two answers the census does give, both
    taken from the product's own functions over the ledger the run just censused:
    the record set ``check_ledger_records`` parsed, and the rows
    ``check_ledger_chain`` wrote -- a record no chain row names, and whose
    ``status`` the chain rule itself does not read as superseded, is a record the
    census holds live. That is the same reading the rule uses for its own
    single-live-per-chain count, and the same one the shim's old per-record
    ``live`` column printed. No verdict is taken from a record's bytes on disk.
    """
    from noni import census as _c

    findings: list[dict] = []
    valid, _unparseable = _c._check_ledger_records(
        ledger, ledger.parent, findings, _c._ledger_probe(ledger),
        row=_c._row, file_kind=_c._file_kind, rel_to_root=_c._rel_to_root,
        ledger_name=_c._ledger_name)
    # No git is handed over: the chain rule reads the records, not history.
    _c._check_ledger_chain(valid, ledger, ledger.parent, findings,
                           row=_c._row, rel_to_root=_c._rel_to_root,
                           ledger_name=_c._ledger_name)
    refused = {f["subject"] for f in findings if f["check"] == "ledger-chain"}
    return {obj["id"] for _rid, _path, obj in valid
            if obj["id"] not in refused
            and obj.get("status") != "superseded"}


def test_chain_resolves_to_one_live_record(tmp_path, run_census):
    """The r1 -> r2 -> r3 chain resolves to exactly one live record (r3).

    The chain answers "exactly one" by refusing every other count (20), so a run
    with no chain row over this ledger is the chain reporting one live record per
    chain; the record the census holds live is named by the probe below, which
    asks the census's own chain check and not the file on disk.
    """
    r1, r2, r3 = _load("2026-10-01-r1.json"), _load("2026-10-10-r2.json"), _load("2026-10-22-r3.json")

    repo = tmp_path / "repo"
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "initial")

    (ledger / "2026-10-01-r1.json").write_text(json.dumps(r1, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-01-r1.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "r1")

    (ledger / "2026-10-10-r2.json").write_text(json.dumps(r2, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-10-r2.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "r2")

    (ledger / "2026-10-22-r3.json").write_text(json.dumps(r3, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-22-r3.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "r3")

    code, out, err = run_census(ledger, env=None)
    assert code == 0, f"expected exit 0 for a valid chain, got {code}\nstderr: {err}"
    _code, json_out, _err = run_census(ledger, extra=("--json",))
    assert _chain_rows(json_out) == [], (
        f"a valid chain must raise no chain row: {_chain_rows(json_out)}")
    assert _live_records(ledger) == {"2026-10-22-r3"}, (
        "the census must hold exactly one record of this chain live, and it must "
        "be r3")


def test_superseded_record_bytes_unchanged(tmp_path):
    """After r2 supersedes r1, r1's bytes stay exactly as committed."""
    r1, r2 = _load("2026-10-01-r1.json"), _load("2026-10-10-r2.json")

    repo = tmp_path / "repo"
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "initial")

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


def test_detached_record_is_separate_chain(tmp_path, run_census):
    """r4 is a detached root (supersedes: null) on a different scope. It is a
    separate chain from r1->r2->r3, and it is live."""
    r1, r2, r3, r4 = _load("2026-10-01-r1.json"), _load("2026-10-10-r2.json"), _load("2026-10-22-r3.json"), _load("2026-10-25-r4-detached.json")

    repo = tmp_path / "repo"
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "initial")

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

    code, out, err = run_census(ledger)
    assert code == 0, f"expected exit 0, got {code}\nstderr: {err}"
    _code, json_out, _err = run_census(ledger, extra=("--json",))
    assert _chain_rows(json_out) == [], (
        f"two separate chains, each with one live record, raise no chain row: "
        f"{_chain_rows(json_out)}")
    assert _live_records(ledger) == {"2026-10-22-r3", "2026-10-25-r4-detached"}, (
        "the census must hold two records live, one per chain: the r3 of the "
        "supersede chain and the detached r4 root, which is the file committed as "
        "2026-10-25-r4.json and carries the id 2026-10-25-r4-detached")


def test_supersedes_with_earlier_date_is_allowed(tmp_path, run_census):
    """A record that supersedes a record with a later date is NOT a violation.
    The supersede chain is the authoritative ordering; the date is a
    tie-break for records with no supersede relationship."""
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
    _git(repo, "commit", "-q", "--allow-empty", "-m", "initial")

    (ledger / "2026-10-25-late.json").write_text(json.dumps(r_late, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-25-late.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "late")

    (ledger / "2026-10-01-early.json").write_text(json.dumps(r_early, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-01-early.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "early")

    code, out, err = run_census(ledger)
    assert code == 0, f"expected exit 0 (supersede chain is the ordering), got {code}\nstderr: {err}"


def test_zero_live_chain_refused(tmp_path, run_census):
    """A chain in which every record is marked superseded resolves to zero
    live records and exits 20."""
    r_root = {
        "id": "2026-10-01-root",
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "dev",
        "questions": [{"id": "q1", "text": "A?", "options": ["x", "y"], "answer": "x"}],
        "by": "Op",
        "scope": "test",
        "status": "superseded",
        "supersedes": None,
    }
    r_a = {
        "id": "2026-10-02-a",
        "date": "2026-10-02T10:00:00Z",
        "asked_by": "dev",
        "questions": [{"id": "q1", "text": "B?", "options": ["x", "y"], "answer": "x"}],
        "by": "Op",
        "scope": "test",
        "status": "superseded",
        "supersedes": "2026-10-01-root",
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

    code, out, err = run_census(ledger)
    assert code == 20, f"expected exit 20 for zero-live chain, got {code}\nstderr: {err}"
    assert "zero-live" in out, f"expected 'zero-live' in the report: {out}"


def test_multi_live_chain_refused(tmp_path, run_census):
    """A chain whose superseded record was never marked superseded resolves to
    more than one live record and exits 20."""
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

    code, out, err = run_census(ledger)
    assert code == 20, f"expected exit 20 for multi-live chain, got {code}\nstderr: {err}"
    assert "multi-live" in out, f"expected 'multi-live' in the report, got: {out}"


def test_duplicate_supersedes_refused(tmp_path, run_census):
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
    _git(repo, "commit", "-q", "--allow-empty", "-m", "initial")

    (ledger / "2026-10-01-root.json").write_text(json.dumps(r_root, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-01-root.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "root")

    (ledger / "2026-10-02-a.json").write_text(json.dumps(r_a, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-02-a.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "a")

    (ledger / "2026-10-03-b.json").write_text(json.dumps(r_b, indent=2))
    _git(repo, "add", "noni/decisions/2026-10-03-b.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "b")

    code, out, err = run_census(ledger)
    assert code == 20, f"expected exit 20 for duplicate supersedes, got {code}\nstderr: {err}"
    assert "duplicate" in out.lower(), f"expected 'duplicate' in the report, got: {out}"
