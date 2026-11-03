"""Close a session: set its status to closed, and commit only its own file.

A session that has finished work must stop counting toward the census's
double-claim check, and the way it does that is one field line: ``- status:
closed``. This command is the whole of it — it never deletes the register file
(the census reads history for the deleted-file check, and the file is the
session's record), and it never touches any file but the one it was pointed at.

Closing is idempotent the same way registration is: a session already in a
terminal state (see _session_git.TERMINAL_STATUSES — closed, done, superseded,
ended) needs no commit, so a second close exits 0, moves no HEAD, and says the
session was already closed.

Usage:
    close.py --repo REPO --session-id SID [--no-commit] [--push]

Exit codes:
    0  the status line was written and committed (and pushed with --push), the
       session was already closed so nothing was written, or the change was
       written and left uncommitted when --no-commit
    1  the session file for --session-id does not exist (register it first)
    2  the file exists but cannot be read, is not UTF-8, or is malformed for
       this writer (no '- status:' field line to set), or --repo names no
       directory or is a symlink (refused, never followed)
    3  git could not commit the change, or --push failed after 3
       fetch-rebase-push attempts (also a fetch failure, a detached HEAD, or an
       unresolvable branch)
    4  --session-id is not a single token with no leading dot (the name of one
       file under noni/sessions/, so a path separator or a '..' walk out of the
       state root is refused here), or --no-commit was combined with
       --push (there would be nothing committed to push), or the session file,
       or any directory from the state root down to it (its noni/sessions
       directory and the noni above it), is not a plain path this writer may
       follow (a symlink is never read or written through, and a refusal writes
       nothing)
    5  the --push rebase started and stopped on a conflict in the session file;
       this run aborts the rebase, so the clone is left on its branch with the
       close commit it made intact
    6  the --push rebase was never started (the hint names committing or
       stashing) or its state could not be read (no abort was run)

--no-commit writes through the same validation chain and runs no git at all,
then prints exactly ``close.py: <path> left uncommitted``. --push pushes the
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

from . import _session_git, _session_guard, _session_push, claim, labels

STATUS_PREFIX = _session_git.STATUS_FIELD
CLOSED_STATUS = "closed"

# Every return path in this module names one of these constants, and the
# docstring's 'Exit codes:' block above carries exactly this set of codes.
EXIT_OK: int = 0
EXIT_SESSION_MISSING: int = 1
EXIT_SESSION_MALFORMED: int = 2
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
    print(f"{labels.CLOSE}: {headline}", file=sys.stderr)
    print(f"{labels.CLOSE}: fix: {hint}", file=sys.stderr)
    return code


def _set_status(body: str) -> str:
    """``body`` with its '- status:' line reading closed, and nothing else changed.

    The line to flip is located by the caller's read of the same body, so the
    writer's promise holds: closing moves one line and the bytes around it stay
    byte-identical.
    """
    lines = body.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.strip().startswith(STATUS_PREFIX):
            indent = line[:len(line) - len(line.lstrip())]
            terminator = "\n" if line.endswith("\n") else ""
            lines[index] = f"{indent}{STATUS_PREFIX} {CLOSED_STATUS}{terminator}"
            return "".join(lines)
    # The shared field reader (``_session_git.session_status``) found this line
    # in the same body; a body with no status line never reaches here.
    raise AssertionError("caller guarantees a status line")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=labels.CLOSE,
        description="Set a session's status to closed",
    )
    parser.add_argument("--repo", required=True, help="repository root")
    parser.add_argument("--session-id", required=True,
                        help="session id (file name without .md)")
    parser.add_argument("--no-commit", action="store_true",
                        help="write the status change and leave it uncommitted")
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

    # The session id is the name of one file under noni/sessions/ and also goes
    # into the commit message ("close: <session-id>"), so it is validated by the
    # one derivation the four writers share, before any read or write: no
    # whitespace, no path separator, no leading dot (a hidden file the census's
    # listing would not report).
    session_id = args.session_id.strip()
    rel = _session_git.writer_name(session_id)
    if not rel:
        headline, hint = _session_git.name_refusal(f"--session-id {args.session_id!r}")
        return _fail(EXIT_USAGE, headline, hint)
    if args.no_commit and args.push:
        return _fail(EXIT_USAGE,
                     "--no-commit cannot be combined with --push (there would be "
                     "nothing committed to push)",
                     "drop one of the two")

    # The write location (``repo / rel``), the pathspec, the failure wording and
    # the hint all name the string derived above, which is relative to the state
    # root and carries no component of a relative --repo. The refusal above ran
    # before the register was looked for, so a refusal never leaves a written
    # file behind.
    session_file = repo / rel
    # Both paths this run would read and replace, refused before either is touched:
    # asked after the name was derived and before is_file(), so a dangling link is
    # this refusal rather than the misleading 'register file not found' below
    # (noni._session_guard).
    refused = _session_guard.session_write(_fail, EXIT_USAGE, session_file.parent,
                                           session_file)
    if refused is not None:
        return refused
    if not session_file.is_file():
        return _fail(EXIT_SESSION_MISSING, f"register file not found: {session_file}",
                     f"register the session first (register.py --repo {repo} "
                     "--identity IDENTITY), then close it")

    try:
        body = session_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # The reason comes from the exception's own words: strerror belongs to
        # OSError and a UnicodeDecodeError has none, so naming it unguarded
        # would turn this refusal into a traceback.
        return _fail(EXIT_SESSION_MALFORMED,
                     f"{session_file.name} is malformed: it exists but cannot be "
                     f"read as UTF-8 ({exc.__class__.__name__}: {exc})",
                     f"repair {rel} or restore it from git (git -C {repo.name} "
                     f"checkout HEAD -- {rel}), then close it")

    fields = _session_git.session_status(body)
    if fields is None:
        return _fail(EXIT_SESSION_MALFORMED,
                     f"{session_file.name} is malformed: it carries no "
                     f"'{STATUS_PREFIX.strip()}' field line, so there is nothing "
                     "to set",
                     # STATUS_PREFIX already carries the colon, so the literal
                     # after it is the value only: '- status:: active' is a line
                     # no parser reads.
                     f"add the '{STATUS_PREFIX.strip()} active' line to {rel} "
                     "(register.py writes it), or restore the file from git, then "
                     "close it")
    if _session_git.is_terminal_status(fields):
        # Nothing to do, said plainly: no write, no commit, HEAD unmoved. The
        # session already excludes its claims from the double-claim check.
        print(f"{labels.CLOSE}: {session_file.name} was already closed "
              f"(status={fields.strip().lower()}); nothing to do")
        return EXIT_OK

    try:
        _session_git.atomic_write(session_file, _set_status(body))
    except OSError as exc:
        return _fail(EXIT_PUSH_FAILED,
                     f"{rel} could not be written ({exc.__class__.__name__}: "
                     f"{exc.strerror or exc})",
                     f"check that {session_file.parent} is writable, then re-run "
                     "close.py")

    if args.no_commit:
        print(f"{labels.CLOSE}: {session_file} left uncommitted")
        return EXIT_OK

    if not _session_git.in_git_worktree(repo):
        # Nothing to commit into (the same fault that leaves no marker path):
        # behave as --no-commit rather than claim a commit that could not
        # happen, and say so in the same words the flag uses.
        print(f"{labels.CLOSE}: {session_file} left uncommitted")
        return EXIT_OK

    ok, why = _session_git.stage_and_commit(repo, rel, f"close: {session_id}")
    if not ok:
        return _fail(EXIT_PUSH_FAILED,
                     f"git could not commit {rel} (the change is written): {why}",
                     f"commit {rel} by hand, or re-run close.py once git answers")
    print(f"{labels.CLOSE}: closed session {session_id} in {session_file.name}")

    if not args.push:
        return EXIT_OK
    branch, why = _session_push.current_branch(repo)
    if branch is None:
        return _fail(EXIT_PUSH_FAILED, f"push refused: {why}",
                     "close.py has no --branch flag: check out a branch and "
                     "re-run with --push, or push this commit by hand")
    return _session_push.fetch_rebase_push(
        repo, branch, label=labels.CLOSE, exit_push_failed=EXIT_PUSH_FAILED,
        exit_rebase_conflict=EXIT_REBASE_CONFLICT,
        exit_rebase_refused=EXIT_REBASE_REFUSED,
        # The rebase wording is claim's, published as the shared push contract
        # (references/claim.md): the three writers that push must tell an agent
        # scripting on rc 5 or 6 the same thing.
        messages=claim._REBASE_MESSAGES,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
