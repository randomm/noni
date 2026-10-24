"""Conformance test: the scripted two-clone double-claim scenario.

Two clones of one repo each commit a claim for the same task on the same
branch. Each clone uses fetch-rebase-push (at most 3 attempts); both claims
land in git after push-retry, and the census double-claim check exits 30
naming the task.

This is the acceptance criterion from the issue: the census is the
deterministic arbiter, git delays the second claimant but does not lock it
out, and both claims land.
"""

from __future__ import annotations

import json

from conftest import _git_ok, _push_with_retry, build_bare_origin, run_claim, run_register


def test_two_clones_double_claim_census_flags(tmp_path, run_sessions_census):
    """Two clones commit a claim for the same task on the same branch; both
    land after push-retry; the census exits 30 naming the task."""
    origin = tmp_path / "origin.git"
    clone_a = tmp_path / "clone-a"
    clone_b = tmp_path / "clone-b"

    build_bare_origin(origin, [clone_a, clone_b])

    # Each clone registers its own session (different identity, same task).
    reg_a = run_register(clone_a, "developer", host="clone-a", worktree=str(clone_a))
    reg_b = run_register(clone_b, "reviewer", host="clone-b", worktree=str(clone_b))
    assert reg_a.returncode == 0, reg_a.stderr
    assert reg_b.returncode == 0, reg_b.stderr

    # Extract the session ids from the register output.
    sid_a = reg_a.stdout.strip().split("->")[0].split("registered session ")[1].strip()
    sid_b = reg_b.stdout.strip().split("->")[0].split("registered session ")[1].strip()
    assert sid_a != sid_b, "session-ids must be distinct (collision-free by construction)"

    # Commit each register file.
    _git_ok(clone_a, "add", "noni/sessions/")
    _git_ok(clone_a, "commit", "-q", "-m", "register A")
    _git_ok(clone_b, "add", "noni/sessions/")
    _git_ok(clone_b, "commit", "-q", "-m", "register B")
    # Push both register commits (A first, B second — no conflict expected).
    _push_with_retry(clone_a, "main")
    _push_with_retry(clone_b, "main")

    # Both clones claim the same task with --push (fetch-rebase-push). If B
    # loses the race it fetch-rebase-pushes and both claims land.
    claim_a = run_claim(clone_a, sid_a, "#42", push=True)
    claim_b = run_claim(clone_b, sid_b, "#42", push=True)
    assert claim_a.returncode == 0, f"claim A push failed: {claim_a.stderr}"
    assert claim_b.returncode == 0, f"claim B push failed: {claim_b.stderr}"

    # Pull B's claim into A's worktree so the census sees both claims in one
    # tree (the census is read-only and operates on a single worktree).
    _git_ok(clone_a, "fetch", "origin")
    _git_ok(clone_a, "merge", "-q", "origin/main")


    # The census on clone A's sessions dir must exit 30 naming the task.
    code, out, err = run_sessions_census(clone_a / "noni" / "sessions")
    assert code == 30, f"expected exit 30, got {code}\nstdout: {out}\nstderr: {err}"
    # NDJSON rows on stdout must name the offending task.
    rows = [json.loads(line) for line in out.strip().splitlines() if line.strip()]
    double_rows = [r for r in rows if r.get("type") == "double-claim"]
    assert any(r["task"] == "#42" for r in double_rows), f"no double-claim row naming #42: {rows}"


def test_register_allocates_distinct_files(tmp_path):
    """Two sessions registering concurrently get distinct session-ids and
    distinct files; the register writer refuses a path it did not allocate."""
    repo = tmp_path / "repo"
    (repo / "noni" / "sessions").mkdir(parents=True)

    reg1 = run_register(repo, "developer", host="h1")
    reg2 = run_register(repo, "reviewer", host="h2")
    assert reg1.returncode == 0
    assert reg2.returncode == 0

    sid1 = reg1.stdout.split("registered session ")[1].split(" ->")[0].strip()
    sid2 = reg2.stdout.split("registered session ")[1].split(" ->")[0].strip()
    assert sid1 != sid2

    # The files exist and are distinct.
    files = list((repo / "noni" / "sessions").glob("*.md"))
    assert len(files) == 2, f"expected 2 files, got {len(files)}: {files}"

    # Refusal: a session that tries to write to a file it did not allocate is
    # refused (exit 2).
    other_file = str(repo / "noni" / "sessions" / f"{sid1}.md")
    reg3 = run_register(repo, "reviewer", file=other_file)
    assert reg3.returncode == 2, f"expected exit 2 (refused path), got {reg3.returncode}: {reg3.stderr}"
