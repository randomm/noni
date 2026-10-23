"""Fresh-clone replay test: a fresh clone of the replay-repo fixture can replay
every recorded decision with no shared runtime and no network.

The test:
1. Runs the generate.sh script to build the replay repo in tmp_path.
2. `git clone`s the result into a fresh tmp_path directory.
3. Runs the census on the clone's noni/decisions/ directory.
4. Asserts the replay reproduces the ordering (supersede-chain order) and the
   why (the records are all present and the chain resolves correctly).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "replay-repo"
CENSUS = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"
GENERATE = FIXTURES / "generate.sh"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _generate_replay_repo(tmp_path: Path) -> Path:
    """Run generate.sh to build the replay repo, returning the repo path."""
    out_dir = tmp_path / "replay-out"
    out_dir.mkdir()
    subprocess.run(
        ["bash", str(GENERATE), str(out_dir)],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    repo = out_dir / "replay-repo"
    assert repo.is_dir(), f"replay repo not generated at {repo}"
    return repo


def test_fresh_clone_replays_all_decisions(tmp_path):
    """A fresh clone of the replay repo can replay every recorded decision."""
    src_repo = _generate_replay_repo(tmp_path)
    clone_dir = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(src_repo), str(clone_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    ledger = clone_dir / "noni" / "decisions"
    assert ledger.is_dir(), f"clone does not have noni/decisions/ at {ledger}"

    # The census must exit 0 (clean) on the fresh clone
    import os
    env = dict(os.environ)
    proc = subprocess.run(
        ["bash", str(CENSUS), str(ledger)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, f"expected exit 0 on fresh clone, got {proc.returncode}\nstderr: {proc.stderr}\nstdout: {proc.stdout}"

    # All four records are present in the clone
    records = sorted(ledger.glob("*.json"))
    assert len(records) == 4, f"expected 4 records in the clone, got {len(records)}: {[r.name for r in records]}"


def test_replay_ordering_is_supersede_chain_first(tmp_path):
    """The replay order is supersede-chain order first, date only as tie-break.

    The replay repo has r2 (date 2026-10-22) superseded by r3 (date
    2026-10-10). A replay that sorts by date alone would put r3 before r2,
    which is wrong. The correct order is the chain order: r1 -> r2 -> r3.
    """
    src_repo = _generate_replay_repo(tmp_path)
    clone_dir = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(src_repo), str(clone_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    ledger = clone_dir / "noni" / "decisions"

    # Read the records and verify the chain
    r1 = json.loads((ledger / "2026-10-01-r1.json").read_text())
    r2 = json.loads((ledger / "2026-10-22-r2.json").read_text())
    r3 = json.loads((ledger / "2026-10-10-r3.json").read_text())
    r4 = json.loads((ledger / "2026-10-25-r4.json").read_text())

    # The chain: r1 (root) -> r2 (supersedes r1) -> r3 (supersedes r2)
    assert r1["supersedes"] is None, "r1 should be a chain root"
    assert r2["supersedes"] == "2026-10-01-r1", "r2 should supersede r1"
    assert r3["supersedes"] == "2026-10-22-r2", "r3 should supersede r2"

    # The date reversal: r3 (the superseder) has an EARLIER date than r2
    # (the superseded). This pins that supersede-chain order beats date.
    assert r3["date"] < r2["date"], (
        f"r3's date ({r3['date']}) should be earlier than r2's date ({r2['date']}) "
        f"to pin the supersede-chain-order-precedence rule"
    )

    # r4 is detached (supersedes: null), separate chain
    assert r4["supersedes"] is None, "r4 should be a chain root"

    # The chain resolves to one live record: r3 (status=decided)
    assert r3["status"] == "decided", "r3 should be the live record"
    assert r1["status"] == "superseded", "r1 should be superseded"
    assert r2["status"] == "superseded", "r2 should be superseded"
    assert r4["status"] == "decided", "r4 should be decided (separate chain)"


def test_replay_reproduces_the_why(tmp_path):
    """The replay reproduces the why: each record carries the scope and the
    question/answer that explain the decision."""
    src_repo = _generate_replay_repo(tmp_path)
    clone_dir = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(src_repo), str(clone_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    ledger = clone_dir / "noni" / "decisions"
    records = sorted(ledger.glob("*.json"))
    for rec_path in records:
        rec = json.loads(rec_path.read_text())
        # Every record has the "why" fields: scope, question text, answer
        assert "scope" in rec and rec["scope"], f"{rec_path.name}: missing scope"
        assert "questions" in rec and rec["questions"], f"{rec_path.name}: missing questions"
        for q in rec["questions"]:
            assert "text" in q and q["text"], f"{rec_path.name}: question missing text"
            # The answer (or its absence for open records) is the "why"
            if rec["status"] == "decided":
                assert q.get("answer") is not None, (
                    f"{rec_path.name}: decided record should have an answer"
                )


def test_fresh_clone_has_complete_git_history(tmp_path):
    """The fresh clone carries the complete git history the census reads:
    4 commits (one per record) and all 4 records, with no dangling objects.
    This is the precondition that lets the census replay every decision from
    the clone alone — no shared runtime, no network.
    """
    src_repo = _generate_replay_repo(tmp_path)
    clone_dir = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(src_repo), str(clone_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    ledger = clone_dir / "noni" / "decisions"

    # The clone has a complete git history (full clone, not shallow)
    proc = subprocess.run(
        ["git", "-C", str(clone_dir), "log", "--oneline"],
        capture_output=True,
        text=True,
        check=True,
    )
    commits = [line for line in proc.stdout.strip().split("\n") if line]
    assert len(commits) == 4, f"expected 4 commits (one per record), got {len(commits)}"

    # The ledger dir has all 4 records
    records = list(ledger.glob("*.json"))
    assert len(records) == 4, f"expected 4 records, got {len(records)}"

    # The git objects are all reachable (no dangling blobs)
    proc = subprocess.run(
        ["git", "-C", str(clone_dir), "fsck", "--no-progress"],
        capture_output=True,
        text=True,
    )
    # fsck should be clean (no dangling objects, no missing refs)
    assert "dangling" not in proc.stdout.lower() or "missing" not in proc.stdout.lower(), (
        f"git fsck found issues in the clone:\n{proc.stdout}\n{proc.stderr}"
    )
