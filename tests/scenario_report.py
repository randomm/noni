"""Running the census over a built scenario and normalizing its findings.

Moved out of ``scenario_eval.py`` for the file-size ratchet (issue #52).
A helper module: never named ``test_*``. It sits at the top of the one-way
scenario layering (``scenario_core`` <- ``scenario_faults`` <-
``scenario_build`` <- this file) and also carries the standalone entry point
``main`` that ``scenario_eval`` re-exports and its ``__main__`` guard calls.

"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from scenario_build import build_scenario, fresh_clone
from scenario_core import _CENSUS, ISSUE_STATE_REL, SESSION_ID_RE
from scenario_faults import _plant_fault_12


def run_census_json(clone: Path, now: str, stale_after: str) -> tuple[int, list[dict]]:
    """Run the unified census --json --strict on clone; return (exit, rows).

    The hygiene class (50) is skipped for this fixture. The scenario is
    self-contained on purpose — it asserts on the planted protocol faults, not
    on public-repo hygiene — and a throwaway clone of a bare origin has no
    deny-list, so hygiene would report its inactive class on every build and
    --strict would turn that always-report into an exit 50 that masks the
    planted codes. The hygiene class has its own tests in
    tests/test_census_hygiene.py; this fixture measures the
    ledger/session/ordering arbiter. ``--ordering`` and ``--issue-state`` are
    passed explicitly rather than left to the defaults: the closed check is not
    evaluated at all without a state file, so an implicit run would silently
    leave one of the three ordering classes unasked.
    """
    from _harness import subprocess_env as _harness_subprocess_env

    proc = subprocess.run(
        [sys.executable, str(_CENSUS), "--repo", str(clone), "--json", "--strict",
         "--skip", "hygiene", "--now", now, "--stale-after", stale_after,
         "--ordering", str(clone / "noni" / "direction" / "order.json"),
         "--issue-state", str(clone / ISSUE_STATE_REL)],
        capture_output=True, text=True, timeout=120,
        env=_harness_subprocess_env(),
    )
    rows = [json.loads(line) for line in proc.stdout.strip().splitlines() if line.strip()]
    return proc.returncode, rows


def _mask(value: str) -> str:
    """Mask the random session-id suffix so two builds normalize identically."""
    return SESSION_ID_RE.sub("<session>", value)


def normalize_findings(rows: list[dict]) -> list[tuple[str, int, str, str]]:
    """The normalized finding multiset: (check, code, severity, subject).

    The subject is the census row's subject with the random 6-hex session-id
    suffix masked; a session finding is identified by its build-time-known
    identity (the register file's identity field names it), never by the
    random id.
    """
    return [
        (row["check"], row["code"], row["severity"], _mask(row["subject"]))
        for row in rows
        if row.get("kind") == "finding"
    ]


def main(argv: list[str]) -> int:
    """Standalone entry point.

    No argument: build the faulted variant in a fresh
    ``tempfile.mkdtemp(prefix="noni-scenario-")`` directory and remove
    exactly that directory before returning 0 — the only deletion this
    path performs is of the directory this run created.
    ``<path>``: refuse to build when the path exists and is non-empty (exit
    2, clear message, nothing deleted, nothing created); build into a path
    that does not exist or is an empty directory, and leave it in place
    afterwards. Returns 0 on success, 2 on usage or refusal errors.
    """
    if len(argv) > 1:
        print("usage: python tests/scenario_eval.py [path]")
        return 2
    if len(argv) == 1:
        base = Path(argv[0])
        if base.exists() and not base.is_dir():
            print(f"refusing to build at {base}: path exists and is not a directory")
            return 2
        if base.is_dir() and any(base.iterdir()):
            print(
                f"refusing to build at {base}: directory is not empty; "
                "delete its contents first or pass a fresh path"
            )
            return 2
        scenario = build_scenario(base, faulted=True)
        clone = fresh_clone(scenario)
        _plant_fault_12(clone)
        code, rows = run_census_json(clone, scenario.now, scenario.stale_after)
        print(f"faulted variant built at {base}; census exit {code}")
        for finding in normalize_findings(rows):
            print(finding)
        return 0
    base = Path(tempfile.mkdtemp(prefix="noni-scenario-"))
    try:
        scenario = build_scenario(base, faulted=True)
        clone = fresh_clone(scenario)
        _plant_fault_12(clone)
        code, rows = run_census_json(clone, scenario.now, scenario.stale_after)
        print(f"faulted variant built at {base}; census exit {code}")
        for finding in normalize_findings(rows):
            print(finding)
        return 0
    finally:
        # Only the directory this run created is ever removed.
        shutil.rmtree(base, ignore_errors=True)
