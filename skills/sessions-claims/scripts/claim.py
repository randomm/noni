"""Claim a task for a session: append a claim row to the session's register
file, then push with fetch-rebase-push (at most 3 attempts).

A claim is a committed record referencing the task, written to the session's
own file so merges never fight over one blob. The claim row grammar is:

    - claim: <task>

where <task> is the task reference (an issue number like #42, or a noni row
id). A claim row without a task reference is malformed; the census flags
malformed claim rows (exit 32).

Usage:
    claim.py --repo REPO --session-id SID --task TASK
             [--branch BRANCH] [--push]

Exit codes:
    0  claim committed (and pushed, when --push)
    1  the register file for --session-id does not exist (register first)
    2  the session file is malformed and the claim cannot be appended
    3  git push failed after 3 fetch-rebase-push attempts
    4  the task reference is empty or whitespace-only
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

CLAIM_PREFIX = "- claim: "
MAX_PUSH_ATTEMPTS = 3
GIT_TIMEOUT = 60


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run git with the caller's configured identity.

    The claim is committed under whoever's git config applies to the tree, so
    attribution stays honest — the test harness pins a deterministic identity
    via git config, production uses the operator's. Only GPG signing is
    forced off (a signing requirement in a throwaway or CI tree must not
    wedge the claim). Every call is bounded by GIT_TIMEOUT: a hung fetch or
    push against an unresponsive remote surfaces as a clean failure instead
    of an unbounded hang.
    """
    cmd = ["git", "-C", str(cwd), "-c", "commit.gpgsign=false", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, returncode=124, stdout="",
            stderr=f"git {args[0]} timed out after {GIT_TIMEOUT}s",
        )


def _claim_rows(body: str) -> list[str]:
    rows = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(CLAIM_PREFIX):
            rows.append(stripped)
    return rows


def _append_claim(path: Path, task: str) -> int:
    """Append a claim row to the register file. Returns an exit code."""
    try:
        body = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"claim.py: cannot read {path.name}: {exc}", file=sys.stderr)
        return 2

    lines = body.splitlines()
    # A valid register file must have a '- claims:' marker line. If it is
    # absent the file is malformed for our purposes (exit 32 class).
    if not any(line.strip() == "- claims:" or line.strip().startswith("- claims:") for line in lines):
        print(f"claim.py: {path.name} has no '- claims:' section; cannot append (malformed)", file=sys.stderr)
        return 2

    if not body.endswith("\n"):
        body += "\n"
    body += f"{CLAIM_PREFIX}{task}\n"
    # Atomic replace: a mid-write crash cannot leave a truncated register
    # file (which the census would then flag as malformed, exit 32).
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return 0


def _push_with_retry(repo: Path, branch: str, attempts: int = MAX_PUSH_ATTEMPTS) -> int:
    """fetch-rebase-push with at most `attempts` attempts.

    The losing pusher ends rebased-and-pushed (both claims land); the census
    then flags the double-claim. Returns 0 on success, 3 on failure.
    """
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            # A previous push was rejected: fetch and rebase onto the latest
            # branch tip, then push again.
            fetch = _git(["fetch", "origin"], repo)
            if fetch.returncode != 0:
                print(f"claim.py: fetch failed: {fetch.stderr.strip()}", file=sys.stderr)
                return 3
            rebase = _git(["rebase", f"origin/{branch}"], repo)
            if rebase.returncode != 0:
                print(f"claim.py: rebase failed: {rebase.stderr.strip()}", file=sys.stderr)
                return 3
        push = _git(["push", "origin", branch], repo)
        if push.returncode == 0:
            return 0
        if push.returncode == 124:
            print(f"claim.py: push attempt {attempt}/{attempts} timed out: {push.stderr.strip()}", file=sys.stderr)
            continue
        print(
            f"claim.py: push attempt {attempt}/{attempts} rejected: "
            f"{push.stderr.strip() or push.stdout.strip()}",
            file=sys.stderr,
        )
    return 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Claim a task for a session")
    parser.add_argument("--repo", required=True, help="repository root")
    parser.add_argument("--session-id", required=True, help="session id (file name without .md)")
    parser.add_argument("--task", required=True, help="task reference (issue number or noni row id)")
    parser.add_argument("--branch", default=None, help="branch to push to (default: current branch)")
    parser.add_argument("--push", action="store_true", help="push after committing")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    task = args.task.strip()
    if not task:
        print("claim.py: task reference must not be empty", file=sys.stderr)
        return 4

    session_file = repo / "noni" / "sessions" / f"{args.session_id}.md"
    if not session_file.is_file():
        print(f"claim.py: register file not found: {session_file} (register the session first)", file=sys.stderr)
        return 1

    rc = _append_claim(session_file, task)
    if rc != 0:
        return rc

    # Commit the claim under the caller's configured identity (see _git).
    add = _git(["add", str(session_file.relative_to(repo))], repo)
    if add.returncode != 0:
        print(f"claim.py: git add failed: {add.stderr.strip()}", file=sys.stderr)
        return 2
    commit = _git(["commit", "-q", "-m", f"claim: {task}"], repo)
    if commit.returncode != 0:
        print(f"claim.py: git commit failed: {commit.stderr.strip()}", file=sys.stderr)
        return 2
    print(f"claim.py: committed claim {task} in {session_file.name}")

    if not args.push:
        return 0

    branch = args.branch
    if branch is None:
        result = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
        if result.returncode != 0:
            print(f"claim.py: cannot resolve branch: {result.stderr.strip()}", file=sys.stderr)
            return 3
        branch = result.stdout.strip()
        if branch in ("", "(detached HEAD)"):
            print("claim.py: cannot push from detached HEAD; pass --branch", file=sys.stderr)
            return 3

    return _push_with_retry(repo, branch)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
