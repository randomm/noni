"""E5 scenario eval: a deterministic end-to-end harness over the direction layer.

The builder constructs a bare origin plus two agent clones in a throwaway
directory (a tmp_path in the tests; any path when run standalone), drives the
real register.py / claim.py scripts (fetch-rebase-push), and commits a healthy
steering decision chain. In the faulted variant it plants five disjoint faults
(census codes 30, 31, 20, 40 committed to origin, and 12 planted in the fresh
clone's working tree), each in its own artifact. Every commit that the census
reads for time — the baseline and decision commits, and the register/claim
commits that carry the session files — runs with pinned GIT_AUTHOR_DATE /
GIT_COMMITTER_DATE, so the scenario is identical across builds and hosts;
the census runs against a FRESH clone of the bare origin with a fixed --now
and --stale-after.

Determinism is asserted on the normalized finding multiset — the multiset of
(check, code, severity, masked-subject) tuples from the census --json output —
because session ids carry a random 6-hex suffix per build; a session finding
is identified by its build-time-known identity (agent-a / agent-b / agent-c),
which its register file carries, never by the random id.

Standalone: ``python tests/scenario_eval.py <path>`` builds the faulted
variant at <path> and prints the census exit code plus the normalized finding
set.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypedDict

REPO = Path(__file__).resolve().parent.parent
_CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"

# Fixed scenario timeline. Every commit and the census clock live on this
# scale, so the scenario is identical across builds and hosts.
BASE = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
NOW = (BASE + timedelta(days=3)).isoformat().replace("+00:00", "Z")
STALE_AFTER = "2"  # days: agent-c's commit (day 0) is 3 days old at --now

SESSION_ID_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}-[0-9a-f]{6}(?:\.md)?")


def _ts(day: int, hour: int = 0) -> str:
    """A pinned ISO-8601 UTC timestamp on the scenario timeline."""
    return (BASE + timedelta(days=day, hours=hour)).isoformat().replace("+00:00", "Z")


@dataclass
class Scenario:
    """One built scenario: a bare origin plus its agent clones and session ids."""

    base: Path
    origin: Path
    clone_a: Path
    clone_b: Path
    sid_a: str = ""
    sid_b: str = ""
    sid_c: str = ""
    faults: list[str] = field(default_factory=list)

    def assert_stale_invariant(self) -> None:
        """Fail loudly if the census clock would negate the planted staleness.

        The planted 40 finding depends on agent-c's commit (day 0) being
        older than stale_after relative to now; asserting it here (rather
        than letting the healthy-baseline test silently flip) makes a
        broken timeline a builder error, not a confusing test failure."""
        age_days = (datetime.fromisoformat(NOW) - BASE).total_seconds() / 86400
        stale_days = int(STALE_AFTER.rstrip("d"))
        if age_days <= stale_days:
            raise RuntimeError(
                f"scenario timeline broken: now ({NOW}) is only {age_days:g}d "
                f"after the day-0 commit, within stale_after={stale_days}d; "
                f"the planted 40 and the healthy baseline would both flip"
            )


def _git_pinned(repo: Path, *args: str, when: str) -> subprocess.CompletedProcess:
    """git in repo with the identity and both commit timestamps pinned."""
    from conftest import git_pin_date

    return git_pin_date(repo, when, *args)


def _commit(repo: Path, rel: str, content: str, msg: str, when: str) -> None:
    """Write rel in repo and commit it under the pinned identity and date."""
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git_pinned(repo, "add", rel, when=when)
    _git_pinned(repo, "commit", "-q", "-m", msg, when=when)


def _push(repo: Path) -> None:
    """Push with fetch-rebase-push (at most 3 attempts)."""
    from conftest import _push_with_retry
    _push_with_retry(repo, "main")


def _record(rec_id: str, when: str, status: str, supersedes, scope: str, question: str) -> str:
    """A steering-ledger decision record (the eight-field schema)."""
    return json.dumps(
        {
            "id": rec_id,
            "date": when,
            "asked_by": "operator",
            "questions": [
                {
                    "id": "q1",
                    "text": question,
                    "options": ["yes", "no"],
                    "answer": "yes" if status == "decided" else None,
                }
            ],
            "by": "operator",
            "scope": scope,
            "status": status,
            "supersedes": supersedes,
        },
        indent=2,
    )


def _register(repo: Path, identity: str, clone_name: str) -> str:
    """Register a session via the real register.py; return the session id."""
    from conftest import run_register

    proc = run_register(repo, identity, host=clone_name, worktree=str(repo))
    assert proc.returncode == 0, f"register {identity} failed: {proc.stderr}"
    return proc.stdout.strip().split("->")[0].split("registered session ")[1].strip()


def _claim(repo: Path, session_id: str, task: str) -> None:
    """Claim a task via the real claim.py --push (commit plus
    fetch-rebase-push; see build_scenario for why the resulting commits are
    still on the pinned scale)."""
    from conftest import run_claim

    proc = run_claim(repo, session_id, task, push=True)
    assert proc.returncode == 0, f"claim {task} by {session_id} failed: {proc.stderr}"


def build_scenario(base: Path, faulted: bool = False) -> Scenario:
    """Build the healthy baseline (optionally plus the planted faults) under
    base, returning the scenario handle.

    Healthy baseline: a bare origin plus two clones; session A (identity
    "agent-a") in clone 1 and session B (identity "agent-b") in clone 2
    register via the real register.py; A claims task #1 and B claims task #2
    via the real claim.py --push (the claims land serially on origin, so no
    rejected push fires and the claim commits — the only wall-clock-dated
    commits in the baseline — carry no time-relevant signal: the census
    reads commit time only for the session-staleness check); a healthy
    steering decision chain (d1 superseded by d2) sets the ordering between
    the two tasks; every commit the census reads for time is pinned.
    """
    from conftest import _git_ok

    # Clean up any previous run at this path. A cleanup failure must fail the
    # build, not silently rebuild on top of stale state.
    for name in ("origin.git", "clone-a", "clone-b", "fresh"):
        path = base / name
        if path.exists():
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except OSError as e:
                raise RuntimeError(f"cannot clean stale {path!r}: {e}") from e
    base.mkdir(parents=True, exist_ok=True)

    origin = base / "origin.git"
    clone_a = base / "clone-a"
    clone_b = base / "clone-b"

    # Build the bare origin.
    origin.mkdir(parents=True, exist_ok=True)
    _git_ok(origin, "init", "-q", "--bare")

    # Build clone_a from scratch.
    clone_a.mkdir(parents=True, exist_ok=True)
    _git_ok(clone_a, "init", "-q")
    _git_ok(clone_a, "checkout", "-q", "-b", "main")
    (clone_a / "README.md").write_text("test repo\n")
    _git_ok(clone_a, "add", "README.md")
    _git_ok(clone_a, "commit", "-q", "-m", "initial commit")
    _git_ok(clone_a, "remote", "add", "origin", str(origin))
    _git_ok(clone_a, "push", "-q", "-u", "origin", "main")

    # Build clone_b as a clone of origin; the empty origin has no refs yet,
    # so the clone's HEAD has no branch — create main before the first push.
    clone_b.mkdir(parents=True, exist_ok=True)
    _git_ok(base, "clone", "-q", str(origin), str(clone_b))
    _git_ok(clone_b, "checkout", "-q", "-b", "main")

    t_task = _ts(0)
    t_reg = _ts(0, 1)
    t_d1 = _ts(0, 6)
    t_d2 = _ts(0, 8)
    t_c = _ts(0, 4)

    # Baseline commit on origin (pinned date): the shared starting point.
    _commit(clone_a, "tasks/1.md", "# task 1\n", "task: #1", t_task)
    _push(clone_a)

    # Both agents register (real register.py). The register scripts do not
    # commit, so each register file is committed under a pinned date before
    # push — every commit the census reads for time is on the pinned scale.
    sid_a = _register(clone_a, "agent-a", "clone-a")
    sid_b = _register(clone_b, "agent-b", "clone-b")
    _git_pinned(clone_a, "add", "noni/sessions/", when=t_reg)
    _git_pinned(clone_a, "commit", "-q", "-m", "register A", when=t_reg)
    _push(clone_a)
    _git_pinned(clone_b, "add", "noni/sessions/", when=t_reg)
    _git_pinned(clone_b, "commit", "-q", "-m", "register B", when=t_reg)
    _push(clone_b)

    # Distinct-task claims via the real claim.py --push. A and B claim
    # serially (A's claim pushes before B claims), so no rejected push fires
    # and no rebase happens; the claim commits land linearly on origin. They
    # are the only wall-clock-dated commits in the baseline — and they carry
    # no time-relevant signal, because the census reads commit time only for
    # the session-staleness check (last commit of the session file), and the
    # session files' register commits are pinned. Fault 30's claim, by
    # contrast, runs while the other agent's claim commit is unpushed, so its
    # rejected push and rebase are part of the exercise (the double-claim
    # finding does not depend on claim-commit dates).
    _claim(clone_a, sid_a, "#1")
    _claim(clone_b, sid_b, "#2")

    # Healthy steering decision chain: d1 superseded by d2; d2 sets the
    # ordering (task #1 before task #2).
    _commit(clone_a, "noni/decisions/2026-10-01-d1.json",
            _record("2026-10-01-d1", t_d1, "superseded", None,
                    "release ordering", "Order task #1 against task #2?"),
            "decision d1", t_d1)
    _push(clone_a)
    _commit(clone_a, "noni/decisions/2026-10-02-d2.json",
            _record("2026-10-02-d2", t_d2, "decided", "2026-10-01-d1",
                    "release ordering", "Confirm task #1 before task #2?"),
            "decision d2", t_d2)
    _push(clone_a)

    scenario = Scenario(base=base, origin=origin, clone_a=clone_a, clone_b=clone_b,
                        sid_a=sid_a, sid_b=sid_b)

    if faulted:
        _plant_faults(scenario, t_c)

    # The planted 40 (and the healthy baseline) depend on the session commits
    # being older than stale_after relative to now; verify on the scenario
    # itself so a broken timeline fails here, not in the tests.
    scenario.assert_stale_invariant()
    return scenario


def _plant_faults(scenario: Scenario, t_c: str) -> None:
    """The planted faults, each in its own disjoint artifact (30, 31, 20, 40
    committed to origin; 12 is planted in the fresh clone at test time).

    30  session B additionally claims task #1 via the real claim.py --push —
        both claims on #1 sit in origin's linear history;
    31  a separate session file with a claim row but no identity field,
        committed to origin;
    20  a separate decision chain with a dangling supersedes, disjoint from
        the healthy chain, committed to origin;
    40  a third session (identity "agent-c", no claims) whose only commit
        carries a pinned date older than --stale-after relative to --now.
    """
    from conftest import git_pin_date

    # 30: the double claim on #1 (real claim.py --push; the rejected push
    # and rebase are part of the exercise — the finding does not depend on
    # claim-commit dates, only on the committed claim rows in origin).
    _claim(scenario.clone_b, scenario.sid_b, "#1")
    scenario.faults.append("30")

    # 31: a separate session file with a claim row but no identity field.
    orphan_body = (
        "- host/worktree: orphan (plant-31)\n"
        f"- started: {t_c}\n"
        "- status: active\n"
        "- claims:\n"
        "  - claim: #7\n"
    )
    _commit(scenario.clone_a, "noni/sessions/2026-10-01-cccccc.md",
            orphan_body, "plant: claim without identity", t_c)
    _push(scenario.clone_a)
    scenario.faults.append("31")

    # 20: a separate decision chain with a dangling supersedes, disjoint from
    # the healthy chain.
    t_d3 = _ts(0, 7)
    dangling = _record("2026-10-03-d3", t_d3, "decided",
                       "2026-10-99-nonexistent", "release ordering",
                       "Order task #3 against task #4?")
    _commit(scenario.clone_a, "noni/decisions/2026-10-03-d3.json",
            dangling, "plant: dangling supersedes chain", t_d3)
    _push(scenario.clone_a)
    scenario.faults.append("20")

    # 40: a third session (identity "agent-c", no claims) whose only commit
    # is pinned older than --stale-after relative to --now.
    scenario.sid_c = _register(scenario.clone_a, "agent-c", "clone-a")
    git_pin_date(scenario.clone_a, t_c, "add", "noni/sessions/")
    git_pin_date(scenario.clone_a, t_c, "commit", "-q", "-m", "register C (stale)")
    _push(scenario.clone_a)
    scenario.faults.append("40")


def fresh_clone(scenario: Scenario, name: str = "fresh") -> Path:
    """A fresh clone of the scenario's bare origin (local directory clone)."""
    dest = scenario.base / name
    if dest.exists():
        shutil.rmtree(dest)
    subprocess.run(["git", "clone", "-q", "--branch", "main", str(scenario.origin), str(dest)],
                   check=True, capture_output=True, timeout=60)
    return dest


def _plant_fault_12(fresh: Path) -> None:
    """12: edit the committed decision record d1 in the fresh clone's working
    tree after cloning (never committed) — the ledger-edited finding."""
    path = fresh / "noni" / "decisions" / "2026-10-01-d1.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["date"] = _ts(0, 12)  # any committed-vs-disk byte change triggers 12
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def run_census_json(clone: Path, now: str, stale_after: str) -> tuple[int, list[dict]]:
    """Run the unified census --json --strict on clone; return (exit, rows)."""
    proc = subprocess.run(
        ["python3", str(_CENSUS), "--repo", str(clone), "--json", "--strict",
         "--now", now, "--stale-after", stale_after],
        capture_output=True, text=True, timeout=120,
    )
    rows: list[dict[str, Any]] = [
        json.loads(line) for line in proc.stdout.strip().splitlines() if line.strip()
    ]
    return proc.returncode, rows


class CensusFindingRow(TypedDict):
    """The finding-kind fields of a census --json row (the cross-module
    contract with census._render: finding-kind rows always carry these)."""

    check: str
    code: int
    severity: str
    subject: str


def _mask(value: str) -> str:
    """Mask the random session-id suffix so two builds normalize identically."""
    return SESSION_ID_RE.sub("<session>", value)


def normalize_findings(rows: list[CensusFindingRow]) -> list[tuple[str, int, str, str]]:
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
    """Standalone: build the faulted variant at <path> and report the census."""
    if len(argv) != 1:
        print("usage: python tests/scenario_eval.py <path>")
        return 2
    base = Path(argv[0]).resolve()
    # The builder rmtree's fixed sub-directories under base; refuse the
    # obvious foot-guns for a test-only utility (refuse "/", the home
    # directory, and any path that already holds a non-throwaway tree; a
    # missing base is fine — build_scenario creates it).
    if base == Path("/") or base == Path.home():
        print(f"refusing to build under unsafe path {base}", file=sys.stderr)
        return 2
    if base.exists() and not base.is_dir():
        print(f"path {base} exists and is not a directory", file=sys.stderr)
        return 2
    scenario = build_scenario(base, faulted=True)
    clone = fresh_clone(scenario)
    _plant_fault_12(clone)
    code, rows = run_census_json(clone, NOW, STALE_AFTER)
    print(f"faulted variant built at {base}; census exit {code}")
    for finding in normalize_findings(rows):
        print(finding)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
