"""Release a claim: remove one claim row from a session's own file, and commit it.

A claim is a committed signal that a session means to work on a task. When the
session drops the task — it finished, or someone else is better placed — the
row must go, or the census keeps reporting a claim nobody holds. This command
removes exactly one row, the one whose task matches ``--task`` on the stripped
line, and leaves every other row untouched: the claim grammar
(``- claim: <task>``, see references/claim.md) is not changed here.

Releasing is not a lock either. The row is a record this session wrote; the
census is what reports a double-claim, and this command makes that report go
away by removing the row, nothing more. It never touches another session's
file, and it never deletes the register file itself.

Usage:
    release.py --repo REPO --session-id SID --task TASK [--no-commit] [--push]

Exit codes:
    0  the row was removed and committed (and pushed with --push), or removed
       and left uncommitted when --no-commit
    1  the session file for --session-id does not exist (register it first)
    2  the session does not hold that task (the message names both), or the file
       exists but cannot be read, is not UTF-8, or is malformed for this writer
       (no '- claims:' marker), or --repo names no directory or is a symlink
       (refused, never followed)
    3  git could not commit the change, or --push failed after 3
       fetch-rebase-push attempts (also a fetch failure, a detached HEAD, or an
       unresolvable branch)
    4  --task or --session-id is not a single token, or --no-commit was combined
       with --push (there would be nothing committed to push)
    5  the --push rebase started and stopped on a conflict in the session file;
       this run aborts the rebase, so the clone is left on its branch with the
       release commit it made intact
    6  the --push rebase was never started (the hint names committing or
       stashing) or its state could not be read (no abort was run)

On exit 0 one line names the released task and the session file it came out of.
--no-commit writes through the same validation chain and runs no git at all,
then prints exactly ``release.py: <path> left uncommitted``. --push pushes the
branch ``git rev-parse --abbrev-ref HEAD`` names; there is no --branch flag, so
a detached HEAD is refused (exit 3) rather than pushing to a branch named HEAD.
A working copy with no git directory cannot commit, so it behaves as
--no-commit and prints the same line.

Every failure prints one headline and one fix hint on stderr and no traceback.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import _session_git, _session_push, claim, labels

# The claim row grammar, unchanged by this writer: the row is matched on the
# stripped line, so an indented row under '- claims:' and a bare one at EOF
# (which is where claim.py appends) are both released.
CLAIM_PREFIX = "- claim: "
CLAIMS_MARKER = "- claims:"

# Every return path in this module names one of these constants, and the
# docstring's 'Exit codes:' block above carries exactly this set of codes.
EXIT_OK: int = 0
EXIT_SESSION_MISSING: int = 1
EXIT_NOT_HELD: int = 2
EXIT_PUSH_FAILED: int = 3
EXIT_USAGE: int = 4
# 5 and 6 are claim.py's settled split (#22): a rebase that stopped mid-flight
# must be aborted before anything else commits into the clone, and a rebase git
# never started must not be aborted. Collapsing both into exit 3 would tell an
# agent scripting on these codes to retry a push where the real fix is to
# resolve the session file, or to commit or stash before re-running.
EXIT_REBASE_CONFLICT: int = 5
EXIT_REBASE_REFUSED: int = 6


def _fail(code: int, headline: str, hint: str) -> int:
    """Print one headline and one fix hint on stderr, and return the exit code."""
    print(f"{labels.RELEASE}: {headline}", file=sys.stderr)
    print(f"{labels.RELEASE}: fix: {hint}", file=sys.stderr)
    return code


def _has_claims_marker(lines: list[str]) -> bool:
    """Whether the body carries the '- claims:' marker the register file requires."""
    return any(line.startswith(CLAIMS_MARKER) for line in lines)


def _matching(lines: list[str], task: str) -> list[int]:
    """Indexes of the claim rows whose task is exactly ``task``, matched on the
    stripped line the way the census reads rows."""
    wanted = CLAIM_PREFIX + task
    return [index for index, line in enumerate(lines) if line.strip() == wanted]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=labels.RELEASE,
        description="Remove one claim row from a session's register file",
    )
    parser.add_argument("--repo", required=True, help="repository root")
    parser.add_argument("--session-id", required=True,
                        help="session id (file name without .md)")
    parser.add_argument("--task", required=True,
                        help="task reference to release (issue number or noni row id)")
    parser.add_argument("--no-commit", action="store_true",
                        help="remove the row and leave the change uncommitted")
    parser.add_argument("--push", action="store_true", help="push after committing")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    if not repo.is_dir():
        return _fail(EXIT_USAGE, f"--repo {args.repo} is not a directory",
                     "pass the repository root that holds noni/sessions/")

    # A state root that is itself a symlink is refused here, before the register
    # is read or written (see _session_git.linked_state_root for why the two
    # path readings disagree), on this command's own usage code.
    linked, why = _session_git.linked_state_root(repo)
    if linked is not None:
        return _fail(EXIT_USAGE, f"--repo {args.repo}: {why}",
                     "pass the state root itself, not a symlink to it")

    # Both tokens reach git or the file: the task goes into the commit message
    # ("release: <task>") and both name a row and a path, so neither may carry
    # whitespace or a path separator. Refused before any read or write.
    session_id = args.session_id.strip()
    if not _session_git.valid_token(session_id):
        return _fail(EXIT_USAGE,
                     f"--session-id {args.session_id!r} is not a single token "
                     "(no whitespace, no path separator)",
                     "pass the session id, the file name under noni/sessions/ "
                     "without its .md suffix")
    task = args.task.strip()
    if not _session_git.valid_token(task):
        return _fail(EXIT_USAGE,
                     f"--task {args.task!r} is not a single token (no whitespace, "
                     "no path separator)",
                     "pass the task reference the claim row carries, such as #42")
    if args.no_commit and args.push:
        return _fail(EXIT_USAGE,
                     "--no-commit cannot be combined with --push (there would be "
                     "nothing committed to push)",
                     "drop one of the two")

    # The one name this run owns, derived before any read or write: the write
    # location (``repo / name``), the pathspec, the failure wording and the hint
    # all name this string, which is relative to the state root and carries no
    # component of a relative --repo. Refused before the register is looked for,
    # so a refusal never leaves a written file behind.
    rel = _session_git.relative_name(_session_git.session_name(session_id))
    if not rel:
        return _fail(EXIT_USAGE, f"--repo {args.repo}: the session writers commit "
                                 "only a path inside the state root (never an "
                                 "absolute path and never one that leaves it)",
                     "pass the state root itself, not a symlink to it, and a "
                     "session id that is the file name under noni/sessions/ "
                     "without its .md suffix")
    session_file = repo / rel
    if not session_file.is_file():
        return _fail(EXIT_SESSION_MISSING, f"register file not found: {session_file}",
                     f"register the session first (register.py --repo {repo} "
                     "--identity IDENTITY), then release from it")

    try:
        body = session_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # The reason comes from the exception's own words: strerror belongs to
        # OSError and a UnicodeDecodeError has none, so naming it unguarded
        # would turn this refusal into a traceback.
        return _fail(EXIT_NOT_HELD,
                     f"{session_file.name} is malformed: it exists but cannot be "
                     f"read as UTF-8 ({exc.__class__.__name__}: {exc})",
                     f"repair {rel} or restore it from git (git -C {repo.name} "
                     f"checkout HEAD -- {rel}), then release from it")

    lines = body.splitlines()
    if not _has_claims_marker([line.strip() for line in lines]):
        return _fail(EXIT_NOT_HELD,
                     f"{session_file.name} is malformed: it carries no "
                     f"'{CLAIMS_MARKER}' marker, so this writer cannot tell its "
                     "claim rows from its fields",
                     f"add the '{CLAIMS_MARKER}' line to {rel} (register.py "
                     "writes it) or restore the file from git, then release again")

    hits = _matching(lines, task)
    if not hits:
        return _fail(EXIT_NOT_HELD,
                     f"{session_file.name} does not hold {task!r}: the task is "
                     f"not held by this session, which has no '- claim: {task}' "
                     "row, so there is nothing to release",
                     f"check the task reference and the session id, or run the "
                     f"sessions census on {session_file.parent} to see what "
                     f"session {session_id} claims")
    if len(hits) > 1:
        # claim.py refuses a duplicate row, so two identical rows mean the file
        # was edited outside the writers. Removing one of them silently would
        # report a release the census does not agree with.
        return _fail(EXIT_NOT_HELD,
                     f"{session_file.name} is malformed: it holds {len(hits)} "
                     f"'- claim: {task}' rows, so this run cannot tell which one "
                     "to remove",
                     f"leave one row for {task} in {rel} (or restore the file "
                     "from git), then release again")

    kept = [line for index, line in enumerate(lines) if index != hits[0]]
    try:
        _session_git.atomic_write(session_file, "\n".join(kept) + "\n")
    except OSError as exc:
        return _fail(EXIT_PUSH_FAILED,
                     f"{rel} could not be written ({exc.__class__.__name__}: "
                     f"{exc.strerror or exc})",
                     f"check that {session_file.parent} is writable, then re-run "
                     "release.py")

    if args.no_commit:
        print(f"{labels.RELEASE}: {session_file} left uncommitted")
        return EXIT_OK

    if not _session_git.in_git_worktree(repo):
        # Nothing to commit into: behave as --no-commit rather than claim a
        # commit that could not happen.
        print(f"{labels.RELEASE}: {session_file} left uncommitted")
        return EXIT_OK

    ok, why = _session_git.stage_and_commit(repo, rel, f"release: {task}")
    if not ok:
        return _fail(EXIT_PUSH_FAILED,
                     f"git could not commit {rel} (the change is written): {why}",
                     f"commit {rel} by hand, or re-run release.py once git answers")
    print(f"{labels.RELEASE}: released {task} from {session_file.name}")

    if not args.push:
        return EXIT_OK
    branch, why = _session_push.current_branch(repo)
    if branch is None:
        return _fail(EXIT_PUSH_FAILED, f"push refused: {why}",
                     "release.py has no --branch flag: check out a branch and "
                     "re-run with --push, or push this commit by hand")
    return _session_push.fetch_rebase_push(
        repo, branch, label=labels.RELEASE, exit_push_failed=EXIT_PUSH_FAILED,
        exit_rebase_conflict=EXIT_REBASE_CONFLICT,
        exit_rebase_refused=EXIT_REBASE_REFUSED,
        # The rebase wording is claim's, published as the shared push contract
        # (references/claim.md): the three writers that push must tell an agent
        # scripting on rc 5 or 6 the same thing.
        messages=claim._REBASE_MESSAGES,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
