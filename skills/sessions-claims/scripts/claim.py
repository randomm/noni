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
       so claim.py ran git rebase --abort, which leaves HEAD on the branch it
       was invoked on, at the claim commit this run made (the abort resets
       index and worktree). When the abort itself fails the code is still 5
       and the message says the clone is left mid-rebase and needs cleanup by
       hand
    6  the rebase was refused before it started (a dirty worktree, for
       instance), or its state could not be determined: no abort is run, so
       this run leaves nothing mid-rebase

The 5/6 split is decided by probing both rebase-merge and rebase-apply (the
two directories a stopped rebase can leave behind) via 'git rev-parse
--git-path' and requiring positive evidence that a rebase is genuinely stopped
in one of them: its head-name and onto files both read back non-empty. A
readable pair means the rebase entered and stopped (5, aborted); anything else
means this run aborts nothing (6). A directory an earlier crashed run left
behind belongs to someone else's rebase, so claim.py never aborts it.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

CLAIM_PREFIX = "- claim: "
MAX_PUSH_ATTEMPTS = 3
GIT_TIMEOUT = 60

# subprocess.run(timeout=) reports a killed call with this return code (the
# TimeoutExpired sentinel). Named once so the push loop, the probe and the
# tests all compare against the same value instead of a bare 124.
GIT_TIMEOUT_RC: int = 124

# --- Exit-code table ----------------------------------------------------------
# Every return path in this module names one of these constants, and the
# docstring's 'Exit codes:' block above carries exactly this set of codes
# (asserted by tests/test_claim_validation.py, which reads both).
EXIT_OK: int = 0
EXIT_REGISTER_MISSING: int = 1
EXIT_SESSION_MALFORMED: int = 2
EXIT_PUSH_FAILED: int = 3
EXIT_USAGE: int = 4
EXIT_REBASE_CONFLICT: int = 5
EXIT_REBASE_REFUSED: int = 6

# The two directories a rebase leaves behind while it is stopped mid-flight:
# the merge backend writes rebase-merge/, the am backend writes rebase-apply/.
# Checking only one would misclassify the other backend's conflict as a
# refusal, so the classifier probes both. The tests' post-condition helper
# reads this same constant, so the probe set and the assertion set cannot
# drift apart.
REBASE_STATE_DIRS: tuple[str, ...] = ("rebase-merge", "rebase-apply")

# How much of git's own output the push loop and the classifier echo. These
# streams are not this process's words (a fetch or push against an origin can
# forward remote-side and credential-helper text) and an agent pipes them
# straight into tool output, so they are sanitised and bounded rather than
# printed raw — see _safe().
GIT_OUTPUT_LIMIT: int = 500

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


def _safe(text: str, limit: int = GIT_OUTPUT_LIMIT) -> str:
    """Render git's own output for the terminal: bounded, no control bytes.

    The push loop and the classifier echo what git said, and that text can
    originate outside this process (remote-side error text, credential-helper
    output for the configured origin). Control characters other than newline
    and space are dropped, so an ANSI or OSC sequence cannot reach the
    terminal, and the tail past ``limit`` is dropped so one huge blob cannot
    crowd out everything else. The census handles the same class of untrusted
    bytes by printing fixed wording instead (skills/census/scripts/census.py,
    the malformed-record path); here the wording is the point, so it is
    sanitised rather than replaced.
    """
    kept = []
    for ch in text:
        if ch == "\n" or ch == " " or unicodedata.category(ch)[0] != "C":
            kept.append(ch)
    cleaned = "".join(kept)
    if len(cleaned) > limit:
        return cleaned[:limit] + "... [truncated]"
    return cleaned


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
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
            cmd, returncode=GIT_TIMEOUT_RC, stdout="",
            stderr="git " + args[0] + " timed out after " + str(GIT_TIMEOUT) + "s",
        )


def _append_claim(path: Path, task: str, body: str) -> int:
    """Append a claim row to the register file. Returns an exit code.

    ``body`` is the file content the duplicate-claim check already read: the
    caller holds it, so the write path does not read (and split) the same
    register file a second time.
    """
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


def _stopped_state_dir(repo: Path) -> tuple[Path | None, bool]:
    """Locate a rebase this clone is actually stopped in.

    Returns (dir, indeterminate). ``dir`` is the state directory (see
    REBASE_STATE_DIRS) holding a genuinely stopped rebase, or None; it is set
    only when the directory carries positive evidence of being stopped: both
    head-name and onto read back non-empty, which is what a live stopped
    rebase always leaves and what a stray directory does not. ``indeterminate``
    says the question could not be answered: a probe could not run or a state
    file could not be read.

    Existence alone is not evidence. A directory an earlier crashed run, a
    different tool, or a hand-run command left behind is somebody else's
    rebase, and aborting it would reset the caller's worktree and index and
    report the loss as a claim conflict — so claim.py aborts only what it can
    see is stopped. Probes go through 'git rev-parse --git-path', which
    resolves the directories wherever the git dir lives (plain clone, worktree
    or re-written GIT_DIR).
    """
    indeterminate = False
    for name in REBASE_STATE_DIRS:
        probe = _git(["rev-parse", "--git-path", name], repo)
        if probe.returncode != 0:
            # One line, not one per failed probe: outside a repository every
            # probe fails, and git's own 'not a git repository' text repeated
            # twice is noise on a path whose answer is already known.
            indeterminate = True
            print(
                f"claim.py: cannot probe rebase state: {_safe(probe.stderr.strip())}",
                file=sys.stderr,
            )
            break
        state = Path(probe.stdout.strip())
        if not state.is_absolute():
            # --git-path prints a path relative to the working tree git
            # resolved for this call, which is the clone itself.
            state = repo / state
        try:
            head_name = (state / "head-name").read_text(encoding="utf-8", errors="replace")
            onto = (state / "onto").read_text(encoding="utf-8", errors="replace")
        except OSError:
            # Absent is an answer (nothing stopped here); unreadable is not.
            if state.is_dir():
                indeterminate = True
            continue
        if head_name.strip() and onto.strip():
            return state, indeterminate
    return None, indeterminate


def _push_with_retry(repo: Path, branch: str, attempts: int = MAX_PUSH_ATTEMPTS) -> int:
    """fetch-rebase-push with at most `attempts` attempts.

    The losing pusher ends rebased-and-pushed (both claims land); the census
    then flags the double-claim. Returns EXIT_OK on success, EXIT_PUSH_FAILED
    when the attempts run out (or a fetch fails), EXIT_REBASE_CONFLICT when a
    rebase started and stopped on a conflict, and EXIT_REBASE_REFUSED when git
    refused to start the rebase, left its state unreadable, or was killed by
    the timeout with the state left indeterminate. Every path that can have
    entered a rebase attempts an abort, so a timeout that landed mid-rebase
    does not leave the clone wedged.
    """
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            # A previous push was rejected: fetch and rebase onto the latest
            # branch tip, then push again.
            fetch = _git(["fetch", "origin"], repo)
            if fetch.returncode != 0:
                print("claim.py: fetch failed: " + _safe(fetch.stderr.strip()), file=sys.stderr)
                return EXIT_PUSH_FAILED
            rebase = _git(["rebase", "origin/" + branch], repo)
            if rebase.returncode != 0:
                if rebase.returncode == GIT_TIMEOUT_RC:
                    # A killed rebase says nothing about conflicts on its own,
                    # but it may have entered and stopped before it was killed,
                    # so the state is still what decides the report: an
                    # unresolved abort is what wedges the next command.
                    return _classify_rebase_failure(repo, rebase, timed_out=True)
                return _classify_rebase_failure(repo, rebase)
        push = _git(["push", "origin", branch], repo)
        if push.returncode == 0:
            return EXIT_OK
        if push.returncode == GIT_TIMEOUT_RC:
            print(
                "claim.py: push attempt " + str(attempt) + "/" + str(attempts)
                + " timed out: " + _safe(push.stderr.strip()),
                file=sys.stderr,
            )
            continue
        print(
            "claim.py: push attempt " + str(attempt) + "/" + str(attempts) + " rejected: "
            + _safe(push.stderr.strip() or push.stdout.strip()),
            file=sys.stderr,
        )
    return EXIT_PUSH_FAILED


def _classify_rebase_failure(
    repo: Path, rebase: subprocess.CompletedProcess[str], timed_out: bool = False
) -> int:
    """Turn a failed 'git rebase origin/<branch>' into an exit code.

    The two cases are not the same bug. A rebase that started and stopped
    leaves the clone mid-rebase, so anything the caller runs next (register.py
    above all) commits on top of a half-finished rebase: claim.py aborts it
    and hands back exit 5. A rebase git never started left nothing to clean
    up, so running an abort there would be noise: exit 6 says commit or
    stash and re-run.

    ``timed_out`` marks a rebase that was killed by GIT_TIMEOUT rather than
    refused by git. Its wording keeps the timeout visible (a slow remote is
    not a conflict) and it is reported as the push class, because that is what
    a killed call proves; the state probe still decides whether an abort has
    to run first.
    """
    detail = _safe(rebase.stderr.strip() or rebase.stdout.strip()).splitlines()
    quoted = " ".join(detail[:3])
    state, indeterminate = _stopped_state_dir(repo)
    if state is None and indeterminate:
        # The probe could not answer, so this run claims no knowledge of the
        # clone's state and asserts nothing about it: an unrunnable probe must
        # not become "not stopped", because a real conflict would then be
        # reported as a refusal whose hint cannot resolve it.
        print(
            "claim.py: rebase failed and its state cannot be read, so no abort "
            "was attempted: " + quoted,
            file=sys.stderr,
        )
        print(
            "claim.py: fix: run 'git status' and 'git rebase --abort' by hand in "
            + repo.name + ", then re-run claim",
            file=sys.stderr,
        )
        return EXIT_REBASE_REFUSED
    if state is not None:
        abort = _git(["rebase", "--abort"], repo)
        if abort.returncode != 0:
            # The clone is still mid-rebase: say so plainly, and keep git's own
            # rebase output, because this is the one path where the caller most
            # needs to know the clone is wedged and what git said about it.
            print(
                "claim.py: rebase conflict and git rebase --abort failed: "
                + _safe(abort.stderr.strip()),
                file=sys.stderr,
            )
            print("claim.py: git said: " + quoted, file=sys.stderr)
            print(
                "claim.py: the clone is still mid-rebase in " + repo.name
                + "; run git rebase --abort by hand",
                file=sys.stderr,
            )
            return EXIT_REBASE_CONFLICT
        if timed_out:
            print(
                "claim.py: rebase timed out after " + str(GIT_TIMEOUT)
                + "s and was stopped in a conflict, so it was aborted: " + quoted,
                file=sys.stderr,
            )
            return EXIT_PUSH_FAILED
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
    if timed_out:
        # Nothing was stopped, so there was nothing to abort: this is the push
        # class the timeout belongs to.
        print(
            "claim.py: rebase timed out after " + str(GIT_TIMEOUT)
            + "s: " + quoted,
            file=sys.stderr,
        )
        return EXIT_PUSH_FAILED
    print("claim.py: rebase refused (it never started): " + quoted, file=sys.stderr)
    print(
        "claim.py: fix: commit or stash the uncommitted changes in this clone, "
        "then re-run claim; this run started no rebase, so the claim commit is intact",
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

    rc = _append_claim(session_file, task, existing)
    if rc != EXIT_OK:
        return rc

    if args.no_commit:
        # Same validation chain and the same write as the committing path,
        # minus git add and git commit: the row is left in the worktree for
        # the caller to stage and commit itself. The line says so on stdout
        # because it is the success message for this mode; the caller's
        # obligation to commit the row is the contract of the flag (see
        # references/claim.md) — no census check reads an uncommitted row.
        committed_to = "" if branch is None else f" (target branch {branch})"
        print(
            f"claim.py: appended {task} to {session_file.name}; "
            f"left uncommitted for the caller to commit{committed_to}"
        )
        return EXIT_OK

    # Commit the claim under the caller's configured identity (see _git).
    # A git refusal here is not a malformed session (exit 2 means the file is
    # malformed or already claims the task, and this file passed both checks),
    # so it is reported as the failure-to-advance class it is: exit 3, with the
    # row's staged state named so the caller knows what to clean up.
    add = _git(["add", str(session_file.relative_to(repo))], repo)
    if add.returncode != 0:
        print(
            "claim.py: git add failed (the claim row is in the worktree, unstaged): "
            + _safe(add.stderr.strip()),
            file=sys.stderr,
        )
        return EXIT_PUSH_FAILED
    commit = _git(["commit", "-q", "-m", "claim: " + task], repo)
    if commit.returncode != 0:
        print(
            "claim.py: git commit failed (the claim row is left staged in the "
            "index, uncommitted): " + _safe(commit.stderr.strip()),
            file=sys.stderr,
        )
        return EXIT_PUSH_FAILED
    print(f"claim.py: committed claim {task} in {session_file.name}")

    if not args.push:
        return EXIT_OK

    if branch is None:
        result = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
        if result.returncode != 0:
            print("claim.py: cannot resolve branch: " + _safe(result.stderr.strip()), file=sys.stderr)
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
