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
import subprocess
import sys

from conftest import _git_ok, build_bare_origin, push_with_retry, run_claim, run_register
from session_git_support import _pinned_allocation_driver

from noni import census as _census

# The name shape the census accepts for an allocated register file, read off the
# census's own pattern: the id a mint produces has to satisfy the check the census
# applies to it, and a suite that retyped the pattern would keep passing if the two
# drifted apart. The double-claim fixture above asserts distinctness; this is the
# other half of what "distinct" has to mean.
SESSION_SHAPE = _census.SESSION_NAME_RE

# The allocation the collision case pins, and the victim's bytes: see
# test_register_refuses_an_allocation_that_lands_on_an_existing_file.
VICTIM_SID = "2026-01-01-dead07"
VICTIM_BODY = (f"# session {VICTIM_SID}\n\n"
               "- identity: someone-else\n"
               "- host/worktree: host-a (repo-a)\n"
               "- started: 2026-01-01T00:00:00Z\n"
               "- status: active\n"
               "- claims:\n"
               "  - claim: #42\n")


def _run_pinned(driver, repo, session_id: str, *extra: str
                ) -> subprocess.CompletedProcess[str]:
    """One register run whose allocation is ``session_id``, launched as the CLI runs it.

    The shared pinned-allocation driver, with the harness env (which pins
    ``PYTHONPATH`` to this tree's ``src/``) and the id the driver reads from
    ``NONI_TEST_SESSION_ID``.
    """
    from _harness import subprocess_env

    env = subprocess_env()
    env["NONI_TEST_SESSION_ID"] = session_id
    return subprocess.run([sys.executable, str(driver), "--repo", str(repo),
                           "--identity", "developer", *extra],
                          capture_output=True, text=True, env=env, timeout=120)


def _sid_of(stdout: str) -> str:
    """The session id from a ``--no-commit`` register line.

    The line names the file it left in the work tree
    (``... -> <path>/<id>.md left uncommitted``); the id is the stem.
    """
    tail = stdout.strip().split(" -> ")[-1].rsplit(" left uncommitted", 1)[0]
    return tail.rsplit("/", 1)[-1].removesuffix(".md")


def test_two_clones_double_claim_census_flags(tmp_path, run_sessions_census):
    """Two clones commit a claim for the same task on the same branch; both
    land after push-retry; the census exits 30 naming the task."""
    origin = tmp_path / "origin.git"
    clone_a = tmp_path / "clone-a"
    clone_b = tmp_path / "clone-b"

    build_bare_origin(origin, [clone_a, clone_b])

    # Each clone registers its own session (different identity, same task).
    # --no-commit: register.py commits its own file, and this fixture wants to
    # make those two commits itself so each clone's register commit sits on its
    # own side of the race the push-retry test is about.
    reg_a = run_register(clone_a, "developer", host="clone-a",
                         worktree=str(clone_a), **{"no-commit": None})
    reg_b = run_register(clone_b, "reviewer", host="clone-b",
                         worktree=str(clone_b), **{"no-commit": None})
    assert reg_a.returncode == 0, reg_a.stderr
    assert reg_b.returncode == 0, reg_b.stderr

    # Extract the session ids from the register output.
    sid_a = _sid_of(reg_a.stdout)
    sid_b = _sid_of(reg_b.stdout)
    assert sid_a != sid_b, "session-ids must be distinct"

    # Commit each register file.
    _git_ok(clone_a, "add", "noni/sessions/")
    _git_ok(clone_a, "commit", "-q", "-m", "register A")
    _git_ok(clone_b, "add", "noni/sessions/")
    _git_ok(clone_b, "commit", "-q", "-m", "register B")
    # Push both register commits (A first, B second — no conflict expected).
    push_with_retry(clone_a, "main")
    push_with_retry(clone_b, "main")

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
    code, out, err = run_sessions_census(clone_a / "noni" / "sessions",
                                         extra=("--json",))
    assert code == 30, f"expected exit 30, got {code}\nstdout: {out}\nstderr: {err}"
    # NDJSON rows on stdout must name the offending task.
    rows = [json.loads(line) for line in out.strip().splitlines()
            if line.strip().startswith("{")]
    double_rows = [r for r in rows if r.get("check") == "session-double"]
    assert any(r.get("subject") == "#42" or "#42" in str(r.get("message", ""))
               for r in double_rows), f"no session-double row naming #42: {rows}"


def test_register_allocates_distinct_files(tmp_path):
    """Two sessions registering concurrently get distinct session-ids and
    distinct files; the register writer refuses a path it did not allocate."""
    repo = tmp_path / "repo"
    (repo / "noni" / "sessions").mkdir(parents=True)

    reg1 = run_register(repo, "developer", host="h1", **{"no-commit": None})
    reg2 = run_register(repo, "reviewer", host="h2", **{"no-commit": None})
    assert reg1.returncode == 0
    assert reg2.returncode == 0

    sid1 = _sid_of(reg1.stdout)
    sid2 = _sid_of(reg2.stdout)
    assert sid1 != sid2
    # Distinct is the whole promise the writer makes about a random id: the mint is
    # 6 hex characters over one UTC day, so a repeat is rare rather than impossible
    # and the writer confirms the name it got rather than trusting it. The shape a
    # minted id must keep is the census's own -- the census reports every other name
    # as a malformed row -- so it is read off that pattern rather than retyped here.
    assert SESSION_SHAPE.fullmatch(f"{sid1}.md"), sid1
    assert SESSION_SHAPE.fullmatch(f"{sid2}.md"), sid2

    # The files exist and are distinct.
    files = list((repo / "noni" / "sessions").glob("*.md"))
    assert len(files) == 2, f"expected 2 files, got {len(files)}: {files}"

    # Refusal: a session that tries to write to a file it did not allocate is
    # refused (exit 2).
    other_file = str(repo / "noni" / "sessions" / f"{sid1}.md")
    reg3 = run_register(repo, "reviewer", file=other_file)
    assert reg3.returncode == 2, f"expected exit 2 (refused path), got {reg3.returncode}: {reg3.stderr}"


def test_register_refuses_an_allocation_that_lands_on_an_existing_file(tmp_path):
    """The un-marked allocating route refuses a name that is already held.

    The refusal above closes the ``--file`` route, where the operator names the path.
    It cannot close this one: an allocating run names nothing, so the only thing
    standing between a minted id and a committed session file was the mint itself --
    and 6 hex characters over one UTC day repeat. The allocation is pinned onto the
    committed file's name because that collision is what the writer must survive, and
    the file's own bytes are the assertion: overwriting it erased another session's
    identity and claim rows and reported success.
    """
    repo = tmp_path / "repo"
    sessions = repo / "noni" / "sessions"
    sessions.mkdir(parents=True)
    victim = sessions / f"{VICTIM_SID}.md"
    victim.write_text(VICTIM_BODY, encoding="utf-8")
    victim_bytes = victim.read_bytes()

    driver = _pinned_allocation_driver(tmp_path, VICTIM_SID)
    proc = _run_pinned(driver, repo, VICTIM_SID, "--no-commit")

    assert proc.returncode == 2, f"expected exit 2, got {proc.returncode}: {proc.stderr}"
    assert f"{VICTIM_SID}.md" in proc.stderr, proc.stderr
    assert victim.read_bytes() == victim_bytes, (
        "an allocation that landed on a committed session file replaced it")
    assert [p.name for p in sessions.glob("*.md")] == [f"{VICTIM_SID}.md"], (
        "the refused run left a second file beside the one it refused to touch")
