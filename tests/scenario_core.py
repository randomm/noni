"""The scenario timeline, the scenario handle, and the fixture-side helpers.

Moved out of ``scenario_eval.py`` for the file-size ratchet (issue #52)
and re-exported from there, so ``from scenario_eval import ...`` keeps
resolving. A helper module: never named ``test_*``. The ``harness_module``
import below is the real bootstrap (``src/`` on ``sys.path`` plus the bare
package aliases), so this layer never depends on a caller having imported
something else first; the launcher helpers keep their own in-body ``_harness``
imports, which is why this file stays importable without ``conftest.py``.

"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import harness_module  # noqa: F401  # bootstrap first: src/ on sys.path + bare package aliases, so no caller's import order matters
from harness_paths import REPO

_CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"

# Fixed scenario timeline. Every commit and the census clock live on this
# scale, so the scenario is identical across builds and hosts.
BASE = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
NOW = (BASE + timedelta(days=3)).isoformat().replace("+00:00", "Z")
STALE_AFTER = "2"  # days: the planted fault (day 0) is 3 days old at --now

# The committed ordering, one entry per worked issue: issue 1 holds position 1
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


def _ts(day: int, hour: int = 0) -> str:
    """A pinned ISO-8601 UTC timestamp on the scenario timeline."""
    return (BASE + timedelta(days=day, hours=hour)).isoformat().replace("+00:00", "Z")


# The commit date every planted fault carries: day 0, hour 4 of the scenario
# timeline, which is the clock the planted faults are read against at --now.
# Named here, beside the timeline it sits on, so the builder and the planters
# cannot drift apart on it.
FAULT_CLOCK = _ts(0, 4)


@dataclass
class Scenario:
    """One built scenario: a bare origin plus its agent clones."""

    base: Path
    origin: Path
    clone_a: Path
    clone_b: Path
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


def _ensure_branch(repo: Path, branch: str) -> None:
    """Ensure the repo is on `branch`, creating it if needed."""
    from _harness import _git_e2

    # Check if we're already on the branch
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip() == branch:
        return
    # Try to create and switch to the branch. _git_e2 does not raise on a
    # non-zero exit, so the fall-back below is reachable when the branch
    # already exists.
    proc = _git_e2(repo, "checkout", "-q", "-b", branch)
    if proc.returncode != 0:
        # Branch might already exist, just switch to it
        proc = _git_e2(repo, "checkout", "-q", branch)
        if proc.returncode != 0:
            raise RuntimeError(f"cannot switch to branch {branch}: {proc.stderr}")
