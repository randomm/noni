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
    2  the session file is malformed and the claim cannot be appended, or
       the session already claims the same task (a task can only be claimed
       once per session)
    3  git push failed after 3 fetch-rebase-push attempts
    4  the task reference is not a non-empty token (empty, whitespace-only,
       or with embedded whitespace), or --branch is not a safe ref name
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CLAIM_PREFIX = "- claim: "
MAX_PUSH_ATTEMPTS = 3
GIT_TIMEOUT = 60

# --task must be a non-empty token: the claim row grammar is "- claim: <task>"
# where <task> is the task reference (an issue number like #42 or a noni row
# id). A task with embedded whitespace or newlines would corrupt the
# single-line claim row, so it is refused here (exit 4).
TASK_RE = re.compile(r"^\S+$")

# --branch must be a safe ref name: what a push targets is whatever git takes
# as a branch name here, so the ref must be a single path segment with no
# slashes, no "..", and no ref-name specials. (What git would actually push
# is the ref that the refspec resolves to; the guard here keeps a malformed
# --branch from ever reaching git.)
BRANCH_RE = re.compile(r"^[A-Za-z0-9._-]+$")


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
            stderr="git " + args[0] + " timed out after " + str(GIT_TIMEOUT) + "s",
        )


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
    body += CLAIM_PREFIX + task + "\n"
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
                print("claim.py: fetch failed: " + fetch.stderr.strip(), file=sys.stderr)
                return 3
            rebase = _git(["rebase", "origin/" + branch], repo)
            if rebase.returncode != 0:
                print("claim.py: rebase failed: " + rebase.stderr.strip(), file=sys.stderr)
                return 3
        push = _git(["push", "origin", branch], repo)
        if push.returncode == 0:
            return 0
        if push.returncode == 124:
            print("claim.py: push attempt " + str(attempt) + "/" + str(attempts) + " timed out: " + push.stderr.strip(), file=sys.stderr)
            continue
        print(
            "claim.py: push attempt " + str(attempt) + "/" + str(attempts) + " rejected: "
            + (push.stderr.strip() or push.stdout.strip()),
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
    if not task or not TASK_RE.match(task):
        print(
            "claim.py: task reference must be a non-empty token "
            "(issue number or noni row id; no whitespace)",
            file=sys.stderr,
        )
        return 4

    branch = args.branch
    if branch is not None and not BRANCH_RE.match(branch):
        print(
            f"claim.py: --branch {branch!r} is not a safe ref name "
            "(expected a single segment of letters, digits, ., _ or -)",
            file=sys.stderr,
        )
        return 4

    session_file = repo / "noni" / "sessions" / f"{args.session_id}.md"
    if not session_file.is_file():
        print(f"claim.py: register file not found: {session_file} (register the session first)", file=sys.stderr)
        return 1

    # A session cannot claim the same task twice: the second claim is
    # refused (exit 2) rather than appended, so the register cannot carry
    # two identical claim rows (which the census would read as two active
    # claims from the same identity).
    try:
        existing = session_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(
            f"claim.py: {session_file.name} is not readable as UTF-8 "
            f"({exc.__class__.__name__}); cannot check for a duplicate claim",
            file=sys.stderr,
        )
        return 2
    for line in existing.splitlines():
        stripped = line.strip()
        if stripped.startswith(CLAIM_PREFIX) and stripped == CLAIM_PREFIX + task:
            print(
                f"claim.py: {session_file.name} already claims {task!r}; "
                "a session cannot append the same task claim twice",
                file=sys.stderr,
            )
            return 2

    rc = _append_claim(session_file, task)
    if rc != 0:
        return rc

    # Commit the claim under the caller's configured identity (see _git).
    add = _git(["add", str(session_file.relative_to(repo))], repo)
    if add.returncode != 0:
        print("claim.py: git add failed: " + add.stderr.strip(), file=sys.stderr)
        return 2
    commit = _git(["commit", "-q", "-m", "claim: " + task], repo)
    if commit.returncode != 0:
        print("claim.py: git commit failed: " + commit.stderr.strip(), file=sys.stderr)
        return 2
    print(f"claim.py: committed claim {task} in {session_file.name}")

    if not args.push:
        return 0

    if branch is None:
        result = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
        if result.returncode != 0:
            print("claim.py: cannot resolve branch: " + result.stderr.strip(), file=sys.stderr)
            return 3
        branch = result.stdout.strip()
        # git prints the literal string "HEAD" (not "(detached HEAD)") when
        # HEAD is detached; without this guard the push below would try to
        # push a branch literally named "HEAD" to origin.
        if branch in ("", "HEAD"):
            print("claim.py: cannot push from detached HEAD; pass --branch", file=sys.stderr)
            return 3

    return _push_with_retry(repo, branch)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
