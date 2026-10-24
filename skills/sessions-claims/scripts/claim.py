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
import subprocess
import sys
from pathlib import Path

CLAIM_PREFIX = "- claim: "
MAX_PUSH_ATTEMPTS = 3


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "git", "-C", str(cwd),
            "-c", "user.name=Replay",
            "-c", "user.email=replay@fixture.invalid",
            "-c", "commit.gpgsign=false",
            *args,
        ],
        capture_output=True,
        text=True,
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
    path.write_text(body, encoding="utf-8")
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

    # Commit the claim.
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
