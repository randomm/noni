"""E5 scenario eval: a deterministic end-to-end harness test.

Tests the scenario builder and census against a throwaway repo with multiple
issues and two concurrent agent clones, plants faults, and proves the census
catches every one and that steered ordering replays from a fresh clone.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from scenario_eval import (
    NOW,
    STALE_AFTER,
    _plant_fault_12,
    build_scenario,
    fresh_clone,
    main,
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
    """Healthy baseline: bare origin plus two clones, each pushing its own file;
    a healthy decision chain sets the
    ordering and the real writers file the item store. Census on a fresh clone
    reports zero fail findings and exit 0."""
    base = _clean_base(tmp_path, "healthy")
    scenario = build_scenario(base, faulted=False)
    clone = fresh_clone(scenario)
    code, rows = run_census_json(clone, NOW, STALE_AFTER)
    findings = normalize_findings(rows)
    assert code == 0, f"expected exit 0, got {code}: {findings}"
    assert len(findings) == 0, f"expected no findings, got: {findings}"


def test_faulted_variant_findings(tmp_path: Path) -> None:
    """Faulted variant: baseline plus planted faults (54, 12, 20).
    Census on a fresh clone reports the normalized finding multiset exactly
    matching the planted set."""
    base = _clean_base(tmp_path, "faulted")
    scenario = build_scenario(base, faulted=True)
    clone = fresh_clone(scenario)
    _plant_fault_12(clone)
    code, rows = run_census_json(clone, NOW, STALE_AFTER)
    findings = normalize_findings(rows)

    # The planted set: {54 on the order the removal left behind, 12, 20}. The
    # ordering-malformed row is the migration refusal: the committed artifact still
    # states the retired schema version and carries an entry with the retired key, so
    # no reader accepts it and no verb rewrites it.
    expected = {
        ("ordering-malformed", 15, "fail", "noni/direction/order.json"),
        ("ledger-edited", 12, "fail", "2026-10-01-d1"),
        ("ledger-chain", 20, "fail", "2026-10-03-d3"),
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
    _, rows1 = run_census_json(clone1, NOW, STALE_AFTER)
    findings1 = normalize_findings(rows1)

    base2 = _clean_base(tmp_path, "det2")
    scenario2 = build_scenario(base2, faulted=True)
    clone2 = fresh_clone(scenario2)
    _plant_fault_12(clone2)
    _, rows2 = run_census_json(clone2, NOW, STALE_AFTER)
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


# --- destructive-delete guards --------------------------------------------


def test_main_explicit_path_non_empty_dir_refused(tmp_path: Path) -> None:
    """An explicit path to a non-empty directory is refused (exit 2, nothing
    deleted): a sentinel file survives the refused run, and no scenario
    artifacts are created there."""
    base = tmp_path / "occupied"
    base.mkdir()
    sentinel = base / "sentinel.txt"
    sentinel.write_text("do not touch\n", encoding="utf-8")

    code = main([str(base)])

    assert code == 2
    assert sentinel.is_file(), "refused run must not delete a foreign file"
    assert sentinel.read_text(encoding="utf-8") == "do not touch\n"
    for name in ("origin.git", "clone-a", "clone-b", "fresh"):
        assert not (base / name).exists(), f"refused run created {name}"


def test_main_no_arg_uses_and_removes_own_temp_dir() -> None:
    """A no-arg standalone run creates its own temp dir, builds, and removes
    exactly that dir (exit 0; no foreign path is ever touched)."""
    code = main([])
    assert code == 0


def test_main_explicit_path_empty_dir_used(tmp_path: Path) -> None:
    """An explicit path that exists as an empty directory is used as-is and
    populated (the run leaves it behind for the operator)."""
    base = tmp_path / "empty-base"
    base.mkdir()

    code = main([str(base)])

    assert code == 0
    assert (base / "origin.git").is_dir()
    assert (base / "clone-a").is_dir()
    assert (base / "clone-b").is_dir()


def test_builder_refuses_non_empty_base_without_deleting(tmp_path: Path) -> None:
    """build_scenario refuses a pre-existing non-empty base (never deletes it)
    but accepts a pre-existing empty base."""
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    sentinel = occupied / "keep-me"
    sentinel.write_text("x\n", encoding="utf-8")

    try:
        build_scenario(occupied)
    except RuntimeError as exc:
        assert "not empty" in str(exc)
    else:
        raise AssertionError("build_scenario must refuse a non-empty base")
    assert sentinel.is_file()
    assert (occupied / "origin.git").exists() is False

    empty = tmp_path / "empty"
    empty.mkdir()
    scenario = build_scenario(empty)
    assert (empty / "origin.git").is_dir()
    assert scenario.base == empty


def test_standalone_subprocess_no_traceback() -> None:
    """``python3 tests/scenario_eval.py`` (no pytest, no argument) runs clean:
    exit 0 per the documented contract and no traceback on stderr. The no-arg
    run also proves the standalone path's imports work without conftest."""
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "scenario_eval.py")],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, f"exit {proc.returncode}\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    assert "Traceback" not in proc.stderr
    # The census runs on the faulted variant, so the documented exit-code
    # contract (lowest finding code wins) surfaces in the printed census exit.
    assert "faulted variant built at" in proc.stdout
    assert "census exit" in proc.stdout
