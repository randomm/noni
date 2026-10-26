"""Claim a task for a session: append a claim row to the session's register
file, then (with --push) push with fetch-rebase-push (at most 3 attempts).

A claim is a committed record referencing the task, written to the session's
own file so merges never fight over one blob. The claim row grammar is:

    - claim: <task>

where <task> is the task reference (an issue number like #42, or a noni row
id). A claim row without a task reference is malformed; the census flags
malformed claim rows (exit 32).

Every exit code below is published as a named EXIT_* constant; the 'Exit
codes:' block and the 'Usage:' block below are kept in sync with that code by
tests/test_claim_validation.py.

Usage:
    claim.py --repo REPO --session-id SID --task TASK
             [--branch BRANCH] [--push] [--no-commit]

Exit codes:
    0  claim committed (and pushed, when --push), or written and left
       uncommitted when --no-commit
    1  the register file for --session-id does not exist (register first)
    2  the session file is malformed and the claim cannot be appended, or
       the session already claims the same task (a task can only be claimed
       once per session)
    3  git push failed after 3 fetch-rebase-push attempts (also a fetch
       failure, a detached HEAD, an unresolvable branch, or a git call that
       timed out)
    4  the task reference is not a non-empty token (empty, whitespace-only,
       or with embedded whitespace), --branch is not a safe ref name, or
       --no-commit was combined with --push
    5  the rebase hit a conflict: the rebase started and stopped mid-flight,
       so claim.py ran git rebase --abort and left HEAD on the original
       branch at the pre-attempt tip with the claim commit intact
    6  the rebase was refused before it started (a dirty worktree, for
       instance): no abort is run, so nothing is left mid-rebase

The 5/6 split is decided by probing both rebase-merge and rebase-apply (the
two directories a stopped rebase can leave behind) via 'git rev-parse
--git-path': present means the rebase entered and stopped (5, aborted);
absent means it never started (6, no abort to run).
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

# --- Exit-code table ----------------------------------------------------------
# Every return path in this module names one of these constants, and the
# docstring's 'Exit codes:' block above carries exactly this set of codes
# (asserted by tests/test_claim_validation.py, which reads both).
EXIT_OK = 0
EXIT_REGISTER_MISSING = 1
EXIT_SESSION_MALFORMED = 2
EXIT_PUSH_FAILED = 3
EXIT_USAGE = 4
EXIT_REBASE_CONFLICT = 5
EXIT_REBASE_REFUSED = 6

# The two directories a rebase leaves behind while it is stopped mid-flight:
# the merge backend writes rebase-merge/, the am backend writes rebase-apply/.
# Checking only one would misclassify the other backend's conflict as a
# refusal, so the classifier probes both.
REBASE_STATE_DIRS = ("rebase-merge", "rebase-apply")

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
        return EXIT_SESSION_MALFORMED

    lines = body.splitlines()
    # A valid register file must have a '- claims:' marker line. If it is
    # absent the file is malformed for our purposes (exit 32 class).
    if not any(line.strip() == "- claims:" or line.strip().startswith("- claims:") for line in lines):
        print(f"claim.py: {path.name} has no '- claims:' section; cannot append (malformed)", file=sys.stderr)
        return EXIT_SESSION_MALFORMED

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
    return EXIT_OK


def _rebase_stopped(repo: Path) -> bool:
    """True when a rebase is stopped mid-flight in this clone.

    Probes both directories a stopped rebase can leave behind (see
    REBASE_STATE_DIRS) via 'git rev-parse --git-path', which resolves them
    wherever the git dir actually is (a plain clone, a worktree, or a
    re-written GIT_DIR). A probe that cannot run says so on stderr and
    counts as not-stopped, which routes the caller to the refusal class
    rather than the conflict class.
    """
    for name in REBASE_STATE_DIRS:
        probe = _git(["rev-parse", "--git-path", name], repo)
        if probe.returncode != 0:
            print(
                f"claim.py: cannot probe {name}: {probe.stderr.strip()}",
                file=sys.stderr,
            )
            continue
        state = Path(probe.stdout.strip())
        if not state.is_absolute():
            # --git-path prints a path relative to the working tree git
            # resolved for this call, which is the clone itself.
            state = repo / state
        if state.exists():
            return True
    return False


def _push_with_retry(repo: Path, branch: str, attempts: int = MAX_PUSH_ATTEMPTS) -> int:
    """fetch-rebase-push with at most `attempts` attempts.

    The losing pusher ends rebased-and-pushed (both claims land); the census
    then flags the double-claim. Returns EXIT_OK on success, EXIT_PUSH_FAILED
    when the attempts run out (or a fetch fails), EXIT_REBASE_CONFLICT when a
    rebase started and stopped on a conflict, and EXIT_REBASE_REFUSED when
    git refused to start the rebase at all.
    """
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            # A previous push was rejected: fetch and rebase onto the latest
            # branch tip, then push again.
            fetch = _git(["fetch", "origin"], repo)
            if fetch.returncode != 0:
                print("claim.py: fetch failed: " + fetch.stderr.strip(), file=sys.stderr)
                return EXIT_PUSH_FAILED
            rebase = _git(["rebase", "origin/" + branch], repo)
            if rebase.returncode != 0:
                # A timed-out rebase says nothing about conflicts: it is a
                # push-class failure, so it is reported before the classifier
                # would read the half-written state as a conflict.
                if rebase.returncode == 124:
                    print(
                        "claim.py: rebase timed out after " + str(GIT_TIMEOUT)
                        + "s: " + rebase.stderr.strip(),
                        file=sys.stderr,
                    )
                    return EXIT_PUSH_FAILED
                return _classify_rebase_failure(repo, rebase)
        push = _git(["push", "origin", branch], repo)
        if push.returncode == 0:
            return EXIT_OK
        if push.returncode == 124:
            print("claim.py: push attempt " + str(attempt) + "/" + str(attempts) + " timed out: " + push.stderr.strip(), file=sys.stderr)
            continue
        print(
            "claim.py: push attempt " + str(attempt) + "/" + str(attempts) + " rejected: "
            + (push.stderr.strip() or push.stdout.strip()),
            file=sys.stderr,
        )
    return EXIT_PUSH_FAILED


def _classify_rebase_failure(repo: Path, rebase: subprocess.CompletedProcess) -> int:
    """Turn a failed 'git rebase origin/<branch>' into an exit code.

    The two cases are not the same bug. A rebase that started and stopped
    leaves the clone mid-rebase, so anything the caller runs next (register.py
    above all) commits on top of a half-finished rebase: claim.py aborts it
    and hands back exit 5. A rebase git never started left nothing to clean
    up, so running an abort there would be noise: exit 6 says commit or
    stash and re-run.
    """
    detail = (rebase.stderr.strip() or rebase.stdout.strip()).splitlines()
    quoted = " ".join(detail[:3])
    if _rebase_stopped(repo):
        abort = _git(["rebase", "--abort"], repo)
        if abort.returncode != 0:
            # The clone is still mid-rebase: say so plainly, because the
            # whole point of this branch is that nothing is left wedged.
            print(
                "claim.py: rebase conflict and git rebase --abort failed: "
                + abort.stderr.strip(),
                file=sys.stderr,
            )
            return EXIT_REBASE_CONFLICT
        print(
            "claim.py: rebase conflict: someone else changed the same session "
            "file, so the rebase stopped: " + quoted,
            file=sys.stderr,
        )
        print(
            "claim.py: fix: fetch origin, resolve the conflict in the session "
            "file, then re-run claim; the claim commit is intact on "
            + repo.name,
            file=sys.stderr,
        )
        return EXIT_REBASE_CONFLICT
    print("claim.py: rebase refused (it never started): " + quoted, file=sys.stderr)
    print(
        "claim.py: fix: commit or stash the uncommitted changes in this clone, "
        "then re-run claim; nothing is mid-rebase, so the claim commit is intact",
        file=sys.stderr,
    )
    return EXIT_REBASE_REFUSED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Claim a task for a session")
    parser.add_argument("--repo", required=True, help="repository root")
    parser.add_argument("--session-id", required=True, help="session id (file name without .md)")
    parser.add_argument("--task", required=True, help="task reference (issue number or noni row id)")
    parser.add_argument("--branch", default=None, help="branch to push to (default: current branch; ignored with --no-commit)")
    parser.add_argument("--push", action="store_true", help="push after committing")
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="append the claim row and leave it uncommitted (for callers that commit themselves)",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    task = args.task.strip()
    if not task or not TASK_RE.match(task):
        print(
            "claim.py: task reference must be a non-empty token "
            "(issue number or noni row id; no whitespace)",
            file=sys.stderr,
        )
        return EXIT_USAGE

    branch = args.branch
    if branch is not None and not BRANCH_RE.match(branch):
        print(
            f"claim.py: --branch {branch!r} is not a safe ref name "
            "(expected a single segment of letters, digits, ., _ or -)",
            file=sys.stderr,
        )
        return EXIT_USAGE

    # Refused before anything is written: with --no-commit there is no commit
    # to push, so a run that asked for both cannot mean one thing.
    if args.no_commit and args.push:
        print(
            "claim.py: --no-commit cannot be combined with --push "
            "(there would be nothing committed to push): drop one of the two",
            file=sys.stderr,
        )
        return EXIT_USAGE

    session_file = repo / "noni" / "sessions" / f"{args.session_id}.md"
    if not session_file.is_file():
        print(f"claim.py: register file not found: {session_file} (register the session first)", file=sys.stderr)
        return EXIT_REGISTER_MISSING

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
        return EXIT_SESSION_MALFORMED
    for line in existing.splitlines():
        stripped = line.strip()
        if stripped.startswith(CLAIM_PREFIX) and stripped == CLAIM_PREFIX + task:
            print(
                f"claim.py: {session_file.name} already claims {task!r}; "
                "a session cannot append the same task claim twice",
                file=sys.stderr,
            )
            return EXIT_SESSION_MALFORMED

    rc = _append_claim(session_file, task)
    if rc != EXIT_OK:
        return rc

    if args.no_commit:
        # Same validation chain and the same write as the committing path,
        # minus git add and git commit: the row is left in the worktree for
        # the caller to stage and commit itself.
        print(f"claim.py: appended {task} to {session_file.name}; left uncommitted")
        return EXIT_OK

    # Commit the claim under the caller's configured identity (see _git).
    add = _git(["add", str(session_file.relative_to(repo))], repo)
    if add.returncode != 0:
        print("claim.py: git add failed: " + add.stderr.strip(), file=sys.stderr)
        return EXIT_SESSION_MALFORMED
    commit = _git(["commit", "-q", "-m", "claim: " + task], repo)
    if commit.returncode != 0:
        print("claim.py: git commit failed: " + commit.stderr.strip(), file=sys.stderr)
        return EXIT_SESSION_MALFORMED
    print(f"claim.py: committed claim {task} in {session_file.name}")

    if not args.push:
        return EXIT_OK

    if branch is None:
        result = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
        if result.returncode != 0:
            print("claim.py: cannot resolve branch: " + result.stderr.strip(), file=sys.stderr)
            return EXIT_PUSH_FAILED
        branch = result.stdout.strip()
        # git prints the literal string "HEAD" (not "(detached HEAD)") when
        # HEAD is detached; without this guard the push below would try to
        # push a branch literally named "HEAD" to origin.
        if branch in ("", "HEAD"):
            print("claim.py: cannot push from detached HEAD; pass --branch", file=sys.stderr)
            return EXIT_PUSH_FAILED

    return _push_with_retry(repo, branch)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
