"""E5 scenario eval: a deterministic end-to-end harness test.

Tests the scenario builder and census against a throwaway repo with multiple
issues and two concurrent agent sessions, plants faults, and proves the census
catches every one and that steered ordering replays from a fresh clone.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from scenario_eval import (
    _plant_fault_12,
    build_scenario,
    fresh_clone,
    normalize_findings,
    run_census_json,
)


def _clean_base(tmp_path: Path, name: str = "scenario") -> Path:
    """Create a clean base directory for a scenario."""
    base = tmp_path / name
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    return base


def test_healthy_baseline(tmp_path: Path) -> None:
    """Healthy baseline: bare origin plus two clones; session A and B register;
    A claims task #1, B claims task #2; a healthy decision chain sets the
    ordering. Census on a fresh clone reports zero fail findings and exit 0."""
    base = _clean_base(tmp_path, "healthy")
    scenario = build_scenario(base, faulted=False)
    clone = fresh_clone(scenario)
    code, rows = run_census_json(clone, scenario.now, scenario.stale_after)
    findings = normalize_findings(rows)
    assert code == 0, f"expected exit 0, got {code}: {findings}"
    assert len(findings) == 0, f"expected no findings, got: {findings}"


def test_faulted_variant_findings(tmp_path: Path) -> None:
    """Faulted variant: baseline plus planted faults (30, 31, 12, 20, 40).
    Census on a fresh clone reports the normalized finding multiset exactly
    matching the planted set."""
    base = _clean_base(tmp_path, "faulted")
    scenario = build_scenario(base, faulted=True)
    clone = fresh_clone(scenario)
    _plant_fault_12(clone)
    code, rows = run_census_json(clone, scenario.now, scenario.stale_after)
    findings = normalize_findings(rows)

    # The planted set: {30 on #1, 31, 12, 20, 40 for agent-c}
    expected = {
        ("session-double", 30, "fail", "#1"),
        ("session-claim", 31, "fail", "<session>"),
        ("ledger-edited", 12, "fail", "2026-10-01-d1"),
        ("ledger-chain", 20, "fail", "2026-10-03-d3"),
        ("session-stalled", 40, "fail", "<session>"),
    }
    actual = set(findings)
    assert actual == expected, f"findings mismatch:\nexpected: {expected}\nactual: {actual}"
    # Exit code: lowest code wins (12)
    assert code == 12, f"expected exit 12, got {code}"


def test_determinism(tmp_path: Path) -> None:
    """Building and running the faulted variant twice yields an identical
    normalized finding set."""
    base1 = _clean_base(tmp_path, "det1")
    scenario1 = build_scenario(base1, faulted=True)
    clone1 = fresh_clone(scenario1)
    _plant_fault_12(clone1)
    _, rows1 = run_census_json(clone1, scenario1.now, scenario1.stale_after)
    findings1 = normalize_findings(rows1)

    base2 = _clean_base(tmp_path, "det2")
    scenario2 = build_scenario(base2, faulted=True)
    clone2 = fresh_clone(scenario2)
    _plant_fault_12(clone2)
    _, rows2 = run_census_json(clone2, scenario2.now, scenario2.stale_after)
    findings2 = normalize_findings(rows2)

    assert findings1 == findings2, (
        f"determinism violated:\nrun1: {findings1}\nrun2: {findings2}"
    )


def test_fresh_clone_replay(tmp_path: Path) -> None:
    """After deleting all clones, a new clone of the origin yields the healthy
    chain's live record (the steered ordering) from committed files alone.
    The assertion targets only the healthy chain."""
    base = _clean_base(tmp_path, "replay")
    scenario = build_scenario(base, faulted=False)

    # Delete all clones
    for clone_name in ("clone-a", "clone-b"):
        clone_path = base / clone_name
        if clone_path.exists():
            shutil.rmtree(clone_path)

    # Fresh clone
    clone = fresh_clone(scenario)
    ledger = clone / "noni" / "decisions"

    # The healthy chain: d1 (superseded) -> d2 (decided)
    d1_path = ledger / "2026-10-01-d1.json"
    d2_path = ledger / "2026-10-02-d2.json"
    assert d1_path.is_file(), "d1 not found in fresh clone"
    assert d2_path.is_file(), "d2 not found in fresh clone"

    d1 = json.loads(d1_path.read_text())
    d2 = json.loads(d2_path.read_text())

    # The chain resolves to exactly one live (decided) record
    assert d1["status"] == "superseded"
    assert d2["status"] == "decided"
    assert d2["supersedes"] == d1["id"]

    # The steered ordering is readable from the live record
    assert d2["scope"] == "release ordering"
    assert d2["questions"][0]["answer"] == "yes"


def test_clean_variant_zero_findings(tmp_path: Path) -> None:
    """Clean variant = healthy baseline only: census on a fresh clone reports
    zero fail findings and exit 0 (proves 'nothing unplanted')."""
    base = _clean_base(tmp_path, "clean")
    scenario = build_scenario(base, faulted=False)
    clone = fresh_clone(scenario)
    code, rows = run_census_json(clone, scenario.now, scenario.stale_after)
    findings = normalize_findings(rows)
    fail_findings = [f for f in findings if f[2] == "fail"]
    assert code == 0, f"expected exit 0, got {code}: {findings}"
    assert len(fail_findings) == 0, f"expected no fail findings, got: {fail_findings}"
