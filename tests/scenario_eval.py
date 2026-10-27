"""E5 scenario eval: a deterministic end-to-end harness over the direction layer.

The builder constructs a bare origin plus two agent clones in a throwaway
directory (a tmp_path in the tests; its own temp dir when run standalone
with no argument), drives the real register.py / claim.py scripts
(fetch-rebase-push), the real order.py writer for the ordering artifact, and
commits a healthy steering decision chain. In the faulted variant it plants
five disjoint faults (census codes 30, 31, 20, 40 committed to origin, and 12
planted in the fresh clone's working tree), each in its own artifact. Every
commit runs with pinned GIT_AUTHOR_DATE / GIT_COMMITTER_DATE, so a rebuilt
scenario is identical, and the census runs against a FRESH clone of the bare
origin with a fixed --now and --stale-after.

The ordering layer is exercised through its real entry points on both sides:
the artifact is written by order.py (``add`` for each position, then one
whole-file ``confirm`` that stamps every entry with the writer's own clock),
and the census is handed ``--ordering`` / ``--issue-state`` explicitly, so the
scenario measures the ordering group against the paths it names rather than
whatever the census would have guessed.

Determinism is asserted on the normalized finding multiset — the multiset of
(check, code, severity, masked-subject) tuples from the census --json output —
because session ids carry a random 6-hex suffix per build; a session finding
is identified by its build-time-known identity (agent-a / agent-b / agent-c),
which its register file carries, never by the random id.

Deletion is confined to what this run created: the builder and the standalone
no-arg path create their own directories and remove only those; a directory
that exists and is not empty is refused (exit 2, nothing deleted, nothing
created), never cleaned. The only other removal is of the ``fresh`` clone
under the scenario base, which ``fresh_clone`` itself created on an earlier
call.

Standalone: ``python tests/scenario_eval.py`` builds the faulted variant in
its own ``tempfile.mkdtemp(prefix="noni-scenario-")`` directory, prints the
census exit code plus the normalized finding set, and removes exactly that
directory before exiting 0. ``python tests/scenario_eval.py <path>`` refuses
an explicit path that exists and is non-empty (exit 2, clear message, no
deletion); an explicit path that does not exist or is an empty directory is
used as-is and left behind for the operator.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"

# Fixed scenario timeline. Every commit and the census clock live on this
# scale, so the scenario is identical across builds and hosts.
BASE = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
NOW = (BASE + timedelta(days=3)).isoformat().replace("+00:00", "Z")
STALE_AFTER = "2"  # days: agent-c's commit (day 0) is 3 days old at --now

# The committed ordering, one entry per claimed task: issue 1 holds position 1
# and issue 2 position 2, each citing the decision record that set its position.
# Both cite d2, the one live record of the healthy chain (d1 stands superseded,
# so citing it would be an ``ordering-malformed`` row, not a healthy entry). One
# whole-file ``order.py confirm`` run then stamps every entry with the writer's
# own clock, which is the healthy state the census must read as clean.
ORDER_PLANS = ((1, "2026-10-02-d2"), (2, "2026-10-02-d2"))
ORDER_ISSUES = tuple(issue for issue, _decision in ORDER_PLANS)
ISSUE_STATE_REL = "issue-state.json"


def _issue_state() -> str:
    """The --issue-state map the census is handed: every ordered issue open.

    The census never contacts a tracker, so the scenario plays the adapter: a
    map that names each ordered issue and says it is open, which is the only
    way the closed check can answer at all (an issue the map omits is a
    cannot-tell row, not a clean entry).
    """
    return json.dumps({str(issue): "open" for issue in ORDER_ISSUES}, indent=2) + "\n"


def _order_healthier(clone: Path) -> None:
    """The healthy ordering, produced by the real writer, plus its state map.

    Two positions written by ``order.py add`` (each citing d2, the live record
    of the healthy chain), then one whole-file ``order.py confirm``. The writer
    stamps each entry's ``confirmed`` with this run's UTC time and commits the
    one artifact path itself, so the entry reads healthy against the census
    clock (--now NOW, three days after every other commit on the scenario
    timeline) and the ordering layer is exercised through its real entry point
    on both sides. The writer owns those commits: this fixture never restages
    what it wrote.
    """
    for issue, decision in ORDER_PLANS:
        _run_order(clone, "add", str(issue), "--decision", decision)
    _run_order(clone, "confirm")
    _push(clone, NOW)
    # The adapter's side of the closed question, committed so a fresh clone
    # carries it and the census can be pointed at it explicitly.
    _commit(clone, ISSUE_STATE_REL, _issue_state(), "issue state", NOW)
    _push(clone, NOW)


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

    @property
    def now(self) -> str:
        return NOW

    @property
    def stale_after(self) -> str:
        return STALE_AFTER


def _git_pinned(repo: Path, *args: str, when: str) -> subprocess.CompletedProcess:
    """git in repo with the identity and both commit timestamps pinned."""
    from _harness import git_pin_date

    return git_pin_date(repo, when, *args)


def _commit(repo: Path, rel: str, content: str, msg: str, when: str) -> None:
    """Write rel in repo and commit it under the pinned identity and date."""
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git_pinned(repo, "add", rel, when=when)
    _git_pinned(repo, "commit", "-q", "-m", msg, when=when)


def _push(repo: Path, when: str) -> None:
    """Push with fetch-rebase-push (at most 3 attempts)."""
    from _harness import push_with_retry
    push_with_retry(repo, "main")


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


def _run_order(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the real order.py writer in repo; returns the completed process.

    Goes through the harness launcher (deterministic git identity, coverage
    hook). The writer stamps ``confirmed`` from its own UTC clock and commits
    the one artifact path itself, which is what makes the fixture's ordering a
    writer product rather than something this file rendered by hand.
    """
    from _harness import run_order

    proc = run_order(repo, *args)
    assert proc.returncode == 0, (
        f"order.py {' '.join(args)} failed ({proc.returncode}):\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    return proc


def _register(repo: Path, identity: str, clone_name: str) -> str:
    """Register a session via the real register.py; return the session id."""
    from _harness import run_register

    proc = run_register(repo, identity, host=clone_name, worktree=str(repo))
    assert proc.returncode == 0, f"register {identity} failed: {proc.stderr}"
    return proc.stdout.strip().split("->")[0].split("registered session ")[1].strip()


def _claim(repo: Path, session_id: str, task: str) -> None:
    """Claim a task via the real claim.py --push (fetch-rebase-push)."""
    from _harness import run_claim

    proc = run_claim(repo, session_id, task, push=True)
    assert proc.returncode == 0, f"claim {task} by {session_id} failed: {proc.stderr}"


def _ensure_branch(repo: Path, branch: str) -> None:
    """Ensure the repo is on `branch`, creating it if needed."""
    from _harness import _git_ok

    # Check if we're already on the branch
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip() == branch:
        return
    # Try to create and switch to the branch
    proc = _git_ok(repo, "checkout", "-q", "-b", branch)
    if proc.returncode != 0:
        # Branch might already exist, just switch to it
        proc = _git_ok(repo, "checkout", "-q", branch)
        if proc.returncode != 0:
            raise RuntimeError(f"cannot switch to branch {branch}: {proc.stderr}")


def build_scenario(base: Path, faulted: bool = False) -> Scenario:
    """Build the healthy baseline (optionally plus the planted faults) under
    base, returning the scenario handle.

    base must not exist, or must exist as an empty directory: the builder
    never deletes anything. It creates only its own entries (``origin.git``,
    ``clone-a``, ``clone-b``) directly under base — a path outside the
    given base is never touched. Callers that need a rebuild at a
    pre-existing, non-empty base must clean it up themselves, and only if
    they know the contents are their own.

    Healthy baseline: a bare origin plus two clones; session A (identity
    "agent-a") in clone 1 and session B (identity "agent-b") in clone 2
    register via the real register.py; A claims task #1 and B claims task #2
    via the real claim.py --push (fetch-rebase-push; both commits land
    linearly on origin); a healthy steering decision chain (d1 superseded by
    d2) sets the ordering between the two tasks; the ordering artifact itself is
    written by the real order.py writer and stamped healthy by one confirm run;
    every commit uses a pinned recent date.
    """
    from _harness import _git_ok

    if base.exists():
        if not base.is_dir():
            raise RuntimeError(f"refusing to build at {base}: path exists and is not a directory")
        if any(base.iterdir()):
            raise RuntimeError(
                f"refusing to build at {base}: directory is not empty; "
                "it must not exist or be an empty directory"
            )
    else:
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

    # Build clone_b as a clone of origin.
    clone_b.mkdir(parents=True, exist_ok=True)
    _git_ok(base, "clone", "-q", str(origin), str(clone_b))
    _ensure_branch(clone_b, "main")

    t_task = _ts(0)
    t_reg = _ts(0, 1)
    t_d1 = _ts(0, 6)
    t_d2 = _ts(0, 8)
    t_c = _ts(0, 4)

    # Baseline commit on origin (pinned date): the shared starting point.
    _commit(clone_a, "tasks/1.md", "# task 1\n", "task: #1", t_task)
    _push(clone_a, t_task)

    # Both agents register (real register.py); pin the register commits.
    sid_a = _register(clone_a, "agent-a", "clone-a")
    sid_b = _register(clone_b, "agent-b", "clone-b")
    _git_pinned(clone_a, "add", "noni/sessions/", when=t_reg)
    _git_pinned(clone_a, "commit", "-q", "-m", "register A", when=t_reg)
    _push(clone_a, t_reg)
    _git_pinned(clone_b, "add", "noni/sessions/", when=t_reg)
    _git_pinned(clone_b, "commit", "-q", "-m", "register B", when=t_reg)
    _push(clone_b, t_reg)

    # Distinct-task claims via the real claim.py --push (fetch-rebase-push).
    _claim(clone_a, sid_a, "#1")
    _claim(clone_b, sid_b, "#2")

    # Healthy steering decision chain: d1 superseded by d2; d2 sets the
    # ordering (task #1 before task #2).
    _commit(clone_a, "noni/decisions/2026-10-01-d1.json",
            _record("2026-10-01-d1", t_d1, "superseded", None,
                    "release ordering", "Order task #1 against task #2?"),
            "decision d1", t_d1)
    _push(clone_a, t_d1)
    _commit(clone_a, "noni/decisions/2026-10-02-d2.json",
            _record("2026-10-02-d2", t_d2, "decided", "2026-10-01-d1",
                    "release ordering", "Confirm task #1 before task #2?"),
            "decision d2", t_d2)
    _push(clone_a, t_d2)

    # The ordering artifact, written by the real writer and stamped healthy by
    # one confirm run, then the issue-state map the census is handed.
    _order_healthier(clone_a)
    scenario = Scenario(base=base, origin=origin, clone_a=clone_a, clone_b=clone_b,
                        sid_a=sid_a, sid_b=sid_b)

    if faulted:
        _plant_faults(scenario, t_c)
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
    from _harness import git_pin_date, run_register

    # 30: the double claim on #1 (real claim.py --push, fetch-rebase-push).
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
    _push(scenario.clone_a, t_c)
    scenario.faults.append("31")

    # 20: a separate decision chain with a dangling supersedes, disjoint from
    # the healthy chain.
    t_d3 = _ts(0, 7)
    dangling = _record("2026-10-03-d3", t_d3, "decided",
                       "2026-10-99-nonexistent", "release ordering",
                       "Order task #3 against task #4?")
    _commit(scenario.clone_a, "noni/decisions/2026-10-03-d3.json",
            dangling, "plant: dangling supersedes chain", t_d3)
    _push(scenario.clone_a, t_d3)
    scenario.faults.append("20")

    # 40: a third session (identity "agent-c", no claims) whose only commit
    # is pinned older than --stale-after relative to --now.
    reg_c = run_register(scenario.clone_a, "agent-c", host="clone-a",
                         worktree=str(scenario.clone_a))
    assert reg_c.returncode == 0, reg_c.stderr
    scenario.sid_c = reg_c.stdout.strip().split("->")[0].split("registered session ")[1].strip()
    git_pin_date(scenario.clone_a, t_c, "add", "noni/sessions/")
    git_pin_date(scenario.clone_a, t_c, "commit", "-q", "-m", "register C (stale)")
    _push(scenario.clone_a, t_c)
    scenario.faults.append("40")


def fresh_clone(scenario: Scenario, name: str = "fresh") -> Path:
    """A fresh clone of the scenario's bare origin (local directory clone).

    The destination must sit directly under the scenario base and must be
    the builder's own ``fresh`` clone for anything to be removed: a
    pre-existing, non-empty, foreign destination is refused, never deleted.
    """
    dest = scenario.base / name
    if dest.exists():
        if name != "fresh" or not dest.is_dir():
            raise RuntimeError(f"refusing to remove {dest}: not this run's own clone directory")
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
    """Run the unified census --json --strict on clone; return (exit, rows).

    The hygiene class (50) is skipped for this fixture. The scenario is
    self-contained on purpose — it asserts on the planted protocol faults, not
    on public-repo hygiene — and a throwaway clone of a bare origin has no
    deny-list, so hygiene would report its inactive class on every build and
    --strict would turn that always-report into an exit 50 that masks the
    planted codes. The hygiene class has its own tests in
    tests/test_census_unified.py::TestHygiene; this fixture measures the
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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
