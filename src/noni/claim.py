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
tests/test_claim_validation_parity.py.

Usage:
    claim.py --repo REPO --session-id SID --task TASK
             [--branch BRANCH] [--push] [--no-commit]

Exit codes:
    0  claim committed (and pushed, when --push), or written and left
       uncommitted when --no-commit
    1  the register file for --session-id does not exist (register first)
    2  the session file is malformed and the claim cannot be appended, or
       the session already claims the same task (a task can only be claimed
       once per session), or the session's status is terminal (closed, done,
       superseded or ended) and the run refuses before writing anything
    3  git push failed after 3 fetch-rebase-push attempts (also a fetch
       failure, a detached HEAD, an unresolvable branch, or a git call that
       timed out)
    4  the task reference is not a non-empty token (empty, whitespace-only,
       or with embedded whitespace), --branch is not a safe ref name,
       --no-commit was combined with --push, or --repo is not a directory
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
means this run aborts nothing (6). An abandoned rebase (git rebase --quit, a
killed run) still carries that pair, so it is aborted too and that abort resets
tracked files: clear any leftover rebase before a --push run.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from . import _session_git, _session_push, labels

CLAIM_PREFIX = "- claim: "
# The push loop's bound and attempt count are the session writers' shared
# mechanics (``_session_git``): the loop, the probe and the tests all read the
# one pair of numbers, so a rebase cannot be bounded one way here and another
# way there.
MAX_PUSH_ATTEMPTS = _session_git.MAX_PUSH_ATTEMPTS
GIT_TIMEOUT = _session_git.GIT_TIMEOUT

# subprocess.run(timeout=) reports a killed call with this return code (the
# TimeoutExpired sentinel). Named once so the push loop, the probe and the
# tests all compare against the same value instead of a bare 124.
GIT_TIMEOUT_RC: int = 124

# Every return path in this module names one of these constants, and the
# docstring's 'Exit codes:' block above carries exactly this set of codes
# (asserted by tests/test_claim_validation_parity.py, which reads both).
EXIT_OK: int = 0
EXIT_REGISTER_MISSING: int = 1
EXIT_SESSION_MALFORMED: int = 2
EXIT_PUSH_FAILED: int = 3
EXIT_USAGE: int = 4
EXIT_REBASE_CONFLICT: int = 5
EXIT_REBASE_REFUSED: int = 6

# The two directories a stopped rebase can leave: the merge backend writes
# rebase-merge/, the am backend writes rebase-apply/, so the classifier probes
# both. The tests' post-condition helper reads this same constant.
REBASE_STATE_DIRS: tuple[str, ...] = ("rebase-merge", "rebase-apply")

# How much of git's own output the push loop and the classifier echo. These
# streams are not this process's words (a fetch or push against an origin can
# forward remote-side and credential-helper text) and an agent pipes them
# straight into tool output, so they are sanitised and bounded rather than
# printed raw — see _safe().
GIT_OUTPUT_LIMIT: int = 500

# --task must be a non-empty token: the claim row grammar is "- claim: <task>"
# where <task> is the task reference (an issue number like #42 or a noni row
# id). Whitespace would corrupt the single-line row, so it is refused (exit 4)
# — fullmatch, not match: '$' also matches before a trailing newline, which
# would let a task like '#42\n' write a two-line row.
TASK_RE = re.compile(r"^\S+$")

# --branch must be a safe ref name that the push loop itself would accept.
# The check lives in ``_session_push.unsafe_branch_reason`` -- the one validator
# every path into the push passes through -- so the explicit ``--branch`` here
# and the name discovered from the tree cannot be guarded by two patterns that
# drift apart. The single-segment rule below is this command's own addition on
# top of the shared validator.
BRANCH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _safe(text: str, limit: int = GIT_OUTPUT_LIMIT) -> str:
    """Render git's own output for the terminal: bounded, no control bytes.

    The mechanic is the session writers' shared one (``_session_git``): the
    push loop and the classifier echo what git said, and that text can
    originate outside this process (remote-side error text, credential-helper
    output for the configured origin), so it is sanitised and bounded rather
    than printed raw. The census prints fixed wording for the same
    class of bytes; here the wording is the point, so it is sanitised.
    """
    return _session_git.safe_text(text, limit)


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run git with the caller's configured identity.

    The claim is committed under whoever's git config applies to the tree, so
    attribution stays honest — the test harness pins a deterministic identity
    via git config, production uses the operator's. Only GPG signing is
    forced off (a signing requirement in a throwaway or CI tree must not
    wedge the claim). Every call is bounded by GIT_TIMEOUT so a hung fetch or
    push fails cleanly instead of hanging.

    The call is the session writers' shared hardened one (``_session_git``), so
    this push loop runs with no repository hooks, no external transports and no
    file-system monitor helper, and under the environment ``gitenv.child_env()``
    gives: every ``GIT_*`` variable but the identity, config and transport names
    on the allowlist is removed, so an inherited ``GIT_DIR``, ``GIT_INDEX_FILE``
    or ``GIT_OBJECT_DIRECTORY`` cannot retarget the push or the rebase.
    """
    return _session_git.git(cwd, "-c", "commit.gpgsign=false", *args)


def _append_claim(path: Path, task: str, body: str) -> int:
    """Append a claim row to the register file. Returns an exit code.

    ``body`` is the file content the duplicate-claim check already read: the
    caller holds it, so the write path does not read (and split) the same
    register file a second time.
    """
    lines = body.splitlines()
    # Without the '- claims:' marker the file is malformed for our purposes.
    if not any(line.strip() == "- claims:" or line.strip().startswith("- claims:") for line in lines):
        print(f"{labels.CLAIM}: {path.name} has no '- claims:' section; cannot append (malformed)", file=sys.stderr)
        return EXIT_SESSION_MALFORMED

    if not body.endswith("\n"):
        body += "\n"
    body += CLAIM_PREFIX + task + "\n"
    # Atomic replace (the session writers' shared helper): a mid-write crash
    # cannot leave a truncated register.
    _session_git.atomic_write(path, body)
    return EXIT_OK


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """This command's git seam, in the shape ``_session_push`` injects.

    The shared rebase verdict takes one callable for every git call it makes (its
    state probes and its abort alike) and hands it the repo as its first
    argument; claim.py's own git helper takes the argument list first, so this
    adapter is what lets the verdict drive claim.py's git and nobody else's.
    """
    return _git(list(args), repo)


def _push_with_retry(repo: Path, branch: str, attempts: int = MAX_PUSH_ATTEMPTS) -> int:
    """fetch-rebase-push with at most `attempts` attempts, via the shared loop.

    The losing pusher ends rebased-and-pushed (both claims land); the census
    then flags the double-claim. Returns EXIT_OK on success, EXIT_PUSH_FAILED
    when the attempts run out (or a fetch fails), EXIT_REBASE_CONFLICT when a
    rebase started and stopped on a conflict, and EXIT_REBASE_REFUSED when git
    refused to start the rebase, left its state unreadable, or was killed by
    the timeout with the state left indeterminate. Every path that can have
    entered a rebase attempts an abort, so a timeout that landed mid-rebase
    does not leave the clone wedged.

    The loop itself is ``_session_push.fetch_rebase_push``'s (its docstring
    states the attempts, the branch validation and the three verdicts), driven
    through ``_run_git`` so every call it makes is this command's own git and
    nothing else: claim.py keeps one git seam, not a copy of the loop. The
    wording is this command's own table, so the operator reads claim's voice.
    """
    return _session_push.fetch_rebase_push(
        repo, branch, attempts, label=labels.CLAIM,
        exit_push_failed=EXIT_PUSH_FAILED,
        exit_rebase_conflict=EXIT_REBASE_CONFLICT,
        exit_rebase_refused=EXIT_REBASE_REFUSED,
        messages=_REBASE_MESSAGES,
        run_git=_run_git,
    )


def _report(code: int, *lines: str) -> int:
    """Print one report to stderr and return its exit code.

    Every failure report here is a headline plus a fix line, and the code is
    the constant the caller returns, so the three stay together at the call
    site instead of being repeated per outcome.
    """
    for line in lines:
        print(line, file=sys.stderr)
    return code


# The wording this command's rebase reports carry, handed to the shared verdict
# so delegating the reading of the state changes nothing an operator reads. The
# {name} slot is the repository's directory name, as in every other hint here.
_REBASE_MESSAGES = {
    "state_unreadable": (
        "rebase failed and its state cannot be read, so no abort was attempted: "
        "{quoted}",
        "fix: run 'git status' and 'git rebase --abort' by hand in {name}, then "
        "re-run claim",
        "note: 'git rev-parse --git-path' could not probe the rebase state, so "
        "this run reports no knowledge of it",
    ),
    "abort_failed": (
        "rebase conflict and git rebase --abort failed: {abort}",
        "git said: {quoted}",
        "the clone is still mid-rebase in {name}; run git rebase --abort by hand",
    ),
    "timeout_stopped": (
        "rebase timed out after {seconds}s and was stopped in a conflict, so it "
        "was aborted: {quoted}",
    ),
    "conflict": (
        "rebase conflict: someone else changed the same session file, so the "
        "rebase stopped: {quoted}",
        "fix: fetch origin, resolve the conflict in the session file, then re-run "
        "claim; the claim commit is intact on {name}",
    ),
    "timeout": ("rebase timed out after {seconds}s: {quoted}",),
    "refused": (
        "rebase refused (it never started): {quoted}",
        "fix: commit or stash the uncommitted changes in this clone, then re-run "
        "claim; this run started no rebase, so the claim commit is intact",
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=labels.CLAIM,
        description="Claim a task for a session",
    )
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
    # The state root is checked before the register file is looked for: a
    # --repo naming no directory is a usage error, not a missing session, and
    # the message names the argument the caller got wrong (the shape
    # register.py, close.py and release.py already use).
    if not repo.is_dir():
        return _report(
            EXIT_USAGE,
            f"{labels.CLAIM}: --repo {args.repo} is not a directory",
            "pass the repository root that holds noni/sessions/",
        )
    task = args.task.strip()
    if not task or not TASK_RE.fullmatch(task):
        print(
            f"{labels.CLAIM}: task reference must be a non-empty token "
            "(issue number or noni row id; no whitespace)",
            file=sys.stderr,
        )
        return EXIT_USAGE

    branch = args.branch
    if branch is not None:
        # The shared validator first (the one the push loop itself applies, so
        # no --branch value can be refused here and admitted there, or the
        # reverse), then this command's own single-segment rule.
        reason = _session_push.unsafe_branch_reason(branch)
        if not reason and not BRANCH_SEGMENT_RE.fullmatch(branch):
            reason = "not a single path segment (no slashes) of letters, digits, ., _ or -"
        if reason:
            print(
                f"{labels.CLAIM}: --branch {branch!r} is {reason} "
                "(expected a single segment of letters, digits, ., _ or -)",
                file=sys.stderr,
            )
            return EXIT_USAGE

    # Refused before anything is written: with --no-commit there is no commit
    # to push, so a run that asked for both cannot mean one thing.
    if args.no_commit and args.push:
        print(
            f"{labels.CLAIM}: --no-commit cannot be combined with --push "
            "(there would be nothing committed to push): drop one of the two",
            file=sys.stderr,
        )
        return EXIT_USAGE

    session_file = repo / "noni" / "sessions" / f"{args.session_id}.md"
    if not session_file.is_file():
        print(f"{labels.CLAIM}: register file not found: {session_file} (register the session first)", file=sys.stderr)
        return EXIT_REGISTER_MISSING

    # A session cannot claim the same task twice: the second claim is
    # refused (exit 2) rather than appended, so the register cannot carry
    # two identical claim rows (which the census would read as two active
    # claims from the same identity).
    try:
        existing = session_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(
            f"{labels.CLAIM}: {session_file.name} is not readable as UTF-8 "
            f"({exc.__class__.__name__}); cannot check for a duplicate claim",
            file=sys.stderr,
        )
        return EXIT_SESSION_MALFORMED
    # A session that has ended claims nothing further. The check is a write-time
    # refusal only: it reads this file's own status field, and claim rows an
    # earlier session left in a file that has since gone terminal are the
    # census's business, not this command's. The status is read after the UTF-8
    # check (so a file no parser can read is still reported as malformed, not as
    # terminal) and before the duplicate-row check (so a terminal session is
    # reported as terminal whichever task is named), and nothing is written
    # before it passes. TERMINAL_STATUSES is the census's own set, shared with
    # close.py rather than copied.
    status = _session_git.session_status(existing)
    if status is not None and _session_git.is_terminal_status(status):
        settled = status.strip().lower()
        print(
            f"{labels.CLAIM}: {session_file.name} is {settled}; a session whose "
            "status is terminal cannot claim a new task (close is final: the "
            "census ignores a terminal session's claims)",
            file=sys.stderr,
        )
        print(
            f"{labels.CLAIM}: fix: claim from a session whose status is active, "
            f"or re-register (--repo {args.repo} --identity IDENTITY) and claim "
            "from the new session",
            file=sys.stderr,
        )
        return EXIT_SESSION_MALFORMED
    for line in existing.splitlines():
        stripped = line.strip()
        if stripped.startswith(CLAIM_PREFIX) and stripped == CLAIM_PREFIX + task:
            print(
                f"{labels.CLAIM}: {session_file.name} already claims {task!r}; "
                "a session cannot append the same task claim twice",
                file=sys.stderr,
            )
            return EXIT_SESSION_MALFORMED

    rc = _append_claim(session_file, task, existing)
    if rc != EXIT_OK:
        return rc

    if args.no_commit:
        # Same validation chain and the same write as the committing path,
        # minus git add and git commit: the row stays in the working tree and
        # committing it is the caller's job. With --branch the line says
        # plainly that the flag had no effect, so it cannot be read as proof of
        # a targeted push.
        if branch is None:
            print(
                f"{labels.CLAIM}: appended {task} to {session_file.name}; "
                f"left uncommitted for the caller to commit"
            )
        else:
            print(
                f"{labels.CLAIM}: appended {task} to {session_file.name}; "
                f"left uncommitted for the caller to commit "
                f"(--branch {branch} was validated but nothing was committed or pushed)"
            )
        return EXIT_OK

    # Commit the claim under the caller's configured identity, and only this
    # session's own file: the three-step primitive in ``_session_git`` resets
    # this path's index entry, adds it, and commits it with --only, so a path
    # somebody else had staged is neither swept in nor unstaged. A git refusal
    # here is not a malformed session (exit 2 means the file is malformed or
    # already claims the task, and this file passed both checks), so it is
    # reported as the failure-to-advance class it is: exit 3, with the row's
    # staged state named so the caller knows what to clean up.
    rel = session_file.relative_to(repo).as_posix()
    ok, why = _session_git.stage_and_commit(repo, session_file, "claim: " + task)
    if not ok:
        print(
            f"{labels.CLAIM}: git could not commit the claim row "
            f"({rel}, which this run staged): {why}",
            file=sys.stderr,
        )
        return EXIT_PUSH_FAILED
    print(f"{labels.CLAIM}: committed claim {task} in {session_file.name}")

    if not args.push:
        return EXIT_OK

    if branch is None:
        result = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
        if result.returncode != 0:
            print(f"{labels.CLAIM}: cannot resolve branch: " + _safe(result.stderr.strip()), file=sys.stderr)
            return EXIT_PUSH_FAILED
        branch = result.stdout.strip()
        # git prints the literal string "HEAD" (not "(detached HEAD)") when
        # HEAD is detached; without this guard the push below would try to
        # push a branch literally named "HEAD" to origin.
        if branch in ("", "HEAD"):
            print(f"{labels.CLAIM}: cannot push from detached HEAD; pass --branch", file=sys.stderr)
            return EXIT_PUSH_FAILED

    return _push_with_retry(repo, branch)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
