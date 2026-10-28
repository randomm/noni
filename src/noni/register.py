"""Register a session: reuse this working copy's session, or allocate a new one.

The session-id is random per working copy (<UTC date>-<6 hex>), allocated when a
working copy registers for the first time. Registration is idempotent: the
working copy carries a marker naming the session it owns, and a re-run that
finds that session alive and matching ``--identity`` reuses it — one session
file per working copy, one writer per file, so re-registering never mints a
second file. A fresh clone and a linked worktree are different working copies
and each gets its own id, which is what keeps two agents on one repository from
sharing a file.

The marker is the file ``noni-session`` inside this working copy's own git
directory (``<repo>/.git/noni-session`` when ``.git`` is a directory; for a
linked worktree, the gitdir its ``gitdir:`` line names, so each worktree marks
itself). It is written by this command and read by no census, and it is never
written under ``noni/`` — it is working-copy state, not committed state.

The file holds two kinds of field:

  identity, status — permanent: they survive across commits, pulls, clones;
  host/worktree, started, claims — ephemeral: they describe this working copy.

Usage:
    register.py --repo REPO --identity IDENTITY [--status STATUS]
                [--host HOST] [--worktree WORKTREE] [--file FILE]
                [--no-commit] [--push]

Exit codes:
    0  registered: this working copy's session file was written, or already
       held this identity and was left alone; a session whose marker could not
       be read or written also exits 0, having allocated a new session and
       named the marker path it could not use
    1  --file names the marked session's file and that file carries a different
       identity (never write into another session's file)
    2  --file names a path this run neither allocated nor found in the marker,
       or --repo names no directory, or the session file could not be written
    3  git could not commit what this run wrote, or a --push failed after 3
       fetch-rebase-push attempts (also a fetch failure, a detached HEAD, or an
       unresolvable branch)
    4  --status or --identity is not a single token, or --no-commit was combined
       with --push (there would be nothing committed to push)

The --file rule, in both directions: this run's allocation and the marked
session's file are the only paths the writer admits, and each may name a
different file, so the two are not the same input. A foreign path — neither
this run's allocation nor the marked session's file — is exit 2.

--no-commit writes through the same validation chain and runs no git at all,
then prints exactly ``register.py: <path> left uncommitted``; --push pushes the
branch ``git rev-parse --abbrev-ref HEAD`` names, and with no commit to push (a
reuse, or a run that found nothing to write) it does nothing. A working copy
with no git directory cannot commit, so it behaves as --no-commit and prints
the same line.

Every failure prints one headline and one fix hint on stderr and no traceback.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import _session_git, labels

# The marker file that names the session this working copy owns. It lives in
# the git directory, never in the work tree: it is this clone's state, not the
# project's, so it is never committed and the census never lists it.
MARKER_NAME = "noni-session"

# Where session files live, relative to the repo. --file is admitted only as a
# file of this directory, which is what makes a foreign path a refusal rather
# than a write somewhere else.
SESSIONS_REL = "noni/sessions"

# Every return path in this module names one of these constants, and the
# docstring's 'Exit codes:' block above carries exactly this set of codes.
EXIT_OK: int = 0
EXIT_IDENTITY_MISMATCH: int = 1
EXIT_USAGE: int = 2
EXIT_GIT: int = 3
EXIT_BAD_ARGS: int = 4


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_session_id() -> str:
    # <UTC date>-<6 hex chars>: 16^6 ≈ 16.7M slots per day, so ids are
    # collision-free by construction (see references/register.md); stable
    # across pulls and clones once committed.
    return f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{uuid.uuid4().hex[:6]}"


def _parse_fields(body: str) -> dict[str, str]:
    """Parse the '- key: value' field lines of a register file.

    A line that does not match the field shape is left for the census to
    flag; registration only needs identity and status to be present.
    """
    fields: dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        key, sep, value = line[2:].partition(":")
        if not sep:
            continue
        fields[key.strip()] = value.strip()
    return fields


def _fail(code: int, headline: str, hint: str) -> int:
    """Print one headline and one fix hint on stderr, and return the exit code.

    The UX bar every noni writer holds: a failure names itself and the remedy,
    and never raises, so nothing here can print a traceback.
    """
    print(f"{labels.REGISTER}: {headline}", file=sys.stderr)
    print(f"{labels.REGISTER}: fix: {hint}", file=sys.stderr)
    return code


def marker_path(repo: Path) -> Path | None:
    """Where this working copy's marker lives, or None when it cannot be resolved.

    The path is built as a literal from ``--repo`` — never through ``git
    rev-parse``, GIT_DIR or GIT_WORK_TREE — so the marker belongs to the tree
    the operator named, whatever environment the caller inherited.

    ``<repo>/.git`` as a directory is the plain clone: the marker sits inside
    it. ``<repo>/.git`` as a file is a linked worktree, and the ``gitdir:`` line
    inside that file names the directory that holds this worktree's own state,
    so each worktree marks itself and two worktrees of one repository never
    share a session. Anything else (no ``.git``, a ``gitdir:`` line that is
    blank, malformed, or names a directory that does not exist) resolves to
    None: the caller mints a new session, writes no marker, and says so.
    """
    dot_git = repo / ".git"
    if dot_git.is_dir():
        return dot_git / MARKER_NAME
    try:
        text = dot_git.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("gitdir:"):
            continue
        named = line.split(":", 1)[1].strip()
        if not named:
            return None
        gitdir = Path(named)
        if not gitdir.is_absolute():
            gitdir = repo / gitdir
        return gitdir / MARKER_NAME if gitdir.is_dir() else None
    return None


def read_marker(marker: Path | None) -> str | None:
    """The session id the marker names, or None when there is nothing to read.

    The first line is the id; a marker that cannot be read, is empty, or whose
    first line is blank answers nothing (the caller allocates afresh), because a
    marker this run cannot trust is no evidence of a session at all.
    """
    if marker is None:
        return None
    try:
        text = marker.read_text(encoding="utf-8")
    except OSError:
        return None
    first = text.split("\n", 1)[0].strip()
    return first or None


def write_marker(marker: Path | None, session_id: str) -> bool:
    """Record that this working copy owns ``session_id``; True when it landed.

    Written only after the session file itself was written, so a working copy
    never wakes up marked for a session whose file is not on disk.
    """
    if marker is None:
        return False
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        _session_git.atomic_write(marker, session_id + "\n")
    except OSError:
        return False
    return True


def _warn_unmarked(marker: Path | None) -> None:
    """Say that this run could not mark the working copy, and what that costs.

    An unresolvable or unwritable marker is not a failure — the session was
    allocated and reported — but the next run of this command in the same
    working copy will not find it, so the message names the marker path it
    could not use.
    """
    named = "<repo>/.git" if marker is None else str(marker.parent)
    print(f"{labels.REGISTER}: no {MARKER_NAME} was written under {named}, so this "
          "session is not marked as this working copy's own", file=sys.stderr)
    print(f"{labels.REGISTER}: fix: run register.py inside a git working copy (a "
          ".git directory, or a .git file whose gitdir: line names a directory "
          "that exists), then re-run", file=sys.stderr)


def _session_body(session_id: str, identity: str, host: str, worktree: str,
                  started: str, status: str) -> str:
    return (
        f"# session {session_id}\n\n"
        f"- identity: {identity}\n"
        f"- host/worktree: {host} ({worktree})\n"
        f"- started: {started}\n"
        f"- status: {status}\n"
        f"- claims:\n"
    )


def _reuse(marked_file: Path, body: str, args: argparse.Namespace) -> int:
    """The marked session's own file: continue it, or refuse to overwrite it.

    The caller read these bytes once to decide the run is a reuse and hands
    them in: the identity is the whole decision. The same identity continues the
    session (exit 0, nothing written, HEAD unmoved); a different one is exit 1,
    because the only path on which a run can name a file it did not allocate is
    ``--file``, and that is exactly where an identity mismatch is refused.
    """
    existing_identity = _parse_fields(body).get("identity", "")
    if existing_identity != args.identity:
        return _fail(
            EXIT_IDENTITY_MISMATCH,
            f"{marked_file.name} already exists with identity "
            f"'{existing_identity}' (not '{args.identity}'); refusing to "
            "overwrite another session's file",
            "pass the identity that file carries, or register without --file "
            "so this run allocates its own session",
        )
    print(f"{labels.REGISTER}: {marked_file.name} already registered "
          f"(identity={existing_identity})")
    return EXIT_OK


def _resolve_target(repo: Path, sessions_dir: Path, allocated: Path,
                    marked: str | None, args: argparse.Namespace) -> Path | int:
    """The file this run writes, or the exit code of the refusal.

    ``--file`` is validated before any marker read or write and before anything
    is written: the writer admits only the path it allocated in this run, or
    the marked session's file. Both are this working copy's own paths, and they
    are different paths — this run's allocation is a name it just minted, the
    marked file is the name an earlier run left — so a foreign path (neither
    one) is refused with exit 2 and no run reaches another session's file by
    naming it.
    """
    if args.file is None:
        return allocated
    target = Path(args.file)
    if not target.is_absolute():
        target = repo / target
    if target == allocated:
        return target
    if marked is not None and target == sessions_dir / f"{marked}.md":
        return target
    return _fail(
        EXIT_USAGE,
        f"refusing to write {target}: the writer writes only the path it "
        f"allocated ({allocated})"
        + ("" if marked is None else f" or the marked session's file "
                                     f"({sessions_dir / f'{marked}.md'})"),
        "drop --file (the writer allocates the path), pass this run's allocation, "
        "or pass the session this working copy is marked for",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=labels.REGISTER,
        description="Register a session file",
    )
    parser.add_argument("--repo", required=True, help="repository root")
    parser.add_argument("--identity", required=True, help="stable identity (role name)")
    parser.add_argument("--status", default="active", help="initial status (default: active)")
    parser.add_argument(
        "--host",
        default=None,
        help="host name (default: the allocated session-id; never a hostname)",
    )
    parser.add_argument(
        "--worktree",
        default=None,
        help="worktree path (default: the repo directory's basename; never an absolute path)",
    )
    parser.add_argument("--file", default=None,
                        help="explicit file path (this run's allocation, or the marked session's file)")
    parser.add_argument("--no-commit", action="store_true",
                        help="write the file and leave it uncommitted (for callers that commit themselves)")
    parser.add_argument("--push", action="store_true", help="push after committing")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    if not repo.is_dir():
        return _fail(EXIT_USAGE, f"--repo {args.repo} is not a directory",
                     "pass the repository root that holds (or will hold) noni/sessions/")

    # Both tokens reach git or the file: the session this run allocates goes
    # into the commit message ("register: <session-id>") and the identity into
    # the file's identity field, so neither may carry whitespace or a path
    # separator. Refused before any write and before any marker read.
    if not _session_git.valid_token(args.identity):
        return _fail(EXIT_BAD_ARGS,
                     f"--identity {args.identity!r} is not a single token "
                     "(no whitespace, no path separator)",
                     "pass a role name such as developer or reviewer")
    if not _session_git.valid_token(args.status):
        return _fail(EXIT_BAD_ARGS,
                     f"--status {args.status!r} is not a single token "
                     "(no whitespace, no path separator)",
                     "pass active, or a terminal state such as closed or done")
    if args.no_commit and args.push:
        return _fail(EXIT_BAD_ARGS,
                     "--no-commit cannot be combined with --push (there would be "
                     "nothing committed to push)",
                     "drop one of the two")

    sessions_dir = repo / SESSIONS_REL
    if not sessions_dir.exists():
        # The sessions dir is created on first registration: a fresh repo has
        # no noni/ state yet. Creating an empty directory is not a protocol
        # violation — it is the first writer allocating its file.
        try:
            sessions_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _fail(EXIT_USAGE,
                         f"{sessions_dir} could not be created "
                         f"({exc.__class__.__name__}: {exc.strerror or exc})",
                         f"check that {repo} is writable, then re-run register.py")

    marker = marker_path(repo)
    marked = read_marker(marker)
    # The reuse question, answered only for a marked file that exists and has
    # not ended: a marker naming a file that is gone is no evidence of a
    # session (see the module docstring), and neither is one whose status is
    # terminal -- in both cases this working copy starts a fresh session and the
    # marker is rewritten for it.
    marked_file = sessions_dir / f"{marked}.md" if marked is not None else None
    reuse = False
    if marked_file is not None and marked_file.is_file():
        try:
            body = marked_file.read_text(encoding="utf-8")
            fields = _parse_fields(body)
        except (OSError, UnicodeDecodeError) as exc:
            # The marked file is there and cannot be read: that is a refusal,
            # not a fresh allocation -- overwriting bytes this run could not
            # read is exactly what the writer never does. The reason is taken
            # from the exception's own words, not from strerror: that attribute
            # belongs to OSError and a UnicodeDecodeError has none, and naming
            # it here would turn a refusal into a traceback.
            return _fail(
                EXIT_USAGE,
                f"{marked_file.name} is marked as this working copy's session but "
                f"cannot be read ({exc.__class__.__name__}: {exc}); refusing to "
                "overwrite it",
                f"repair or remove {marked_file} (and the marker that names "
                "it), then re-run register.py",
            )
        if _session_git.is_terminal_status(fields.get("status", "")):
            print(f"{labels.REGISTER}: marked session {marked} is "
                  f"{fields['status'].strip().lower()}; allocating a new session")
        else:
            reuse = True

    # The reuse decision is made from the marker and the marked file alone, and
    # before the allocation is consulted: a run with no --file names nothing, so
    # its target is by construction a fresh name, and a reuse test written
    # against the target could never fire. The marked session is active and this
    # working copy's own, so this run continues it: nothing is written and HEAD
    # does not move.
    #
    # --no-commit opts out. Asking for a file to be left in the work tree is a
    # caller that intends to write more than one session in this tree and commit
    # them itself — the census's own fixtures, and anything that plants a second
    # identity in one clone — and continuing the marked session instead would
    # leave that caller with nothing to commit. The marker stays where it was:
    # an opted-out run marks nothing, so it cannot steal the working copy's
    # session from the run that owns it.
    if reuse and not args.no_commit:
        return _reuse(marked_file, body, args)

    # --file may still name the marked file (a caller repeating an earlier
    # run's path explicitly); the guard validates it against this run's
    # allocation and the marked path, and refuses anything else.
    target = _resolve_target(repo, sessions_dir,
                             sessions_dir / f"{_make_session_id()}.md", marked, args)
    if isinstance(target, int):
        return target

    # A new session: allocate, write, and only then mark this working copy with
    # the id whose file is on disk.
    session_id = target.name.removesuffix(".md")
    host = args.host or session_id
    # Default to the repo's basename, not an absolute machine-local path:
    # the register file is committed to a public repo, so the worktree field
    # must stay generic (an absolute /home/... path would leak the operator's
    # local layout — see the public-repo hygiene rule in AGENTS.md).
    worktree = args.worktree or repo.resolve().name
    started = _now_utc()
    try:
        _session_git.atomic_write(
            target, _session_body(session_id, args.identity, host, worktree,
                                  started, args.status))
    except OSError as exc:
        return _fail(EXIT_USAGE,
                     f"{target} could not be written "
                     f"({exc.__class__.__name__}: {exc.strerror or exc})",
                     f"check that {sessions_dir} is writable, then re-run register.py")
    marked_ok = write_marker(marker, session_id) if not args.no_commit else False

    if args.no_commit:
        # Same validation chain and the same write as the committing path, minus
        # every git call: the file stays in the working tree and committing it is
        # the caller's job.
        print(f"{labels.REGISTER}: {target} left uncommitted")
        if not marked_ok:
            _warn_unmarked(marker)
        return EXIT_OK

    if not _session_git.in_git_worktree(repo):
        # Nothing to commit into (the same fault that leaves no marker path):
        # behave as --no-commit rather than pretend a commit happened.
        print(f"{labels.REGISTER}: {target} left uncommitted")
        _warn_unmarked(marker)
        return EXIT_OK

    rel = target.relative_to(repo).as_posix()
    ok, why = _session_git.stage_and_commit(repo, target, f"register: {session_id}")
    if not ok:
        return _fail(EXIT_GIT,
                     f"git could not commit {rel} (the file is written): {why}",
                     f"run 'git status --porcelain -- {rel}' and commit that path "
                     "by hand, or re-run register.py once git answers")
    print(f"{labels.REGISTER}: registered session {session_id} -> {target}")
    if not marked_ok:
        _warn_unmarked(marker)

    if not args.push:
        return EXIT_OK
    branch, why = _session_git.current_branch(repo)
    if branch is None:
        return _fail(EXIT_GIT, f"push refused: {why}",
                     "check out a branch, or run the push by hand once HEAD names one")
    return _session_git.fetch_rebase_push(
        repo, branch, label=labels.REGISTER, exit_push_failed=EXIT_GIT,
        exit_rebase_conflict=EXIT_GIT, exit_rebase_refused=EXIT_GIT,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
