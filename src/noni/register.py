"""Register a session: reuse this working copy's session, or allocate a new one.

The session-id is random per working copy (<UTC date>-<6 hex>), allocated when a
working copy registers for the first time. Registration is idempotent: the
working copy carries a marker naming the session it owns, and a re-run that
finds that session alive and matching ``--identity`` reuses it — one session
file per working copy, one writer per file, so re-registering never mints a
second file. A fresh clone and a linked worktree are different working copies
and each gets its own id, which is what keeps two agents on one repository from
sharing a file. The register file's ``identity`` and ``status`` are permanent
(surviving commits, pulls and clones); ``host/worktree``, ``started`` and
``claims`` describe this working copy.

The marker is the file ``noni-session`` inside this working copy's own git
directory (``<repo>/.git/noni-session`` when ``.git`` is a directory; for a
linked worktree, the gitdir its ``gitdir:`` line names, so each worktree marks
itself). It is written by this command and read by no census, and it is never
written under ``noni/`` — it is working-copy state, not committed state. The
helpers that resolve, read, write and restore it live in ``noni._marker``.

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
       or --repo names no directory or is a symlink (refused, never followed),
       or the session file could not be written
    3  git could not commit what this run wrote, or a --push failed after 3
       fetch-rebase-push attempts (also a fetch failure, a detached HEAD, or an
       unresolvable branch)
    4  --status or --identity is not a single token, the session name this run
       allocated is not one file under noni/sessions/ (a name the writer derived
       itself, so the hint names --identity rather than blaming --repo or a
       symlink), or --no-commit was combined with --push (there would be nothing
       committed to push)

The --file rule, in both directions: this run's allocation and the marked
session's file are the only paths the writer admits, and each may name a
different file, so the two are not the same input. A foreign path — neither
this run's allocation nor the marked session's file — is exit 2.

The session id is minted once per run and that one string names the file
written, the pathspec, the marker, the commit subject and the printed line. The
marker's text is read back as an input, not a fact: text that is not a valid
session id is not a marker for a session, so the run says so, treats the working
copy as unmarked, and allocates afresh — it never builds a path from marker text.

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

from . import _marker, _session_git, _session_push, claim, labels

# Where session files live, relative to the state root. The one spelling is the
# primitive's, and a writer's file is always ``_session_git.writer_name(sid)``:
# the write location, the pathspec and every message come from that one name.
SESSIONS_REL = _session_git.SESSIONS_REL

# Every return path names one of these, and the 'Exit codes:' block above
# carries exactly this set.
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


def _warn_unmarked(marker: Path | None) -> None:
    """Say that this run could not mark the working copy, and what that costs.

    An unresolvable or unwritable marker is not a failure — the session was
    allocated and reported — but the next run of this command in the same
    working copy will not find it, so the message names the marker path it
    could not use.

    Called only on a route that meant to mark: ``--no-commit`` opts out of the
    marker as well as the commit, so there the no-op is not a fault.
    """
    named = "<repo>/.git" if marker is None else str(marker.parent)
    print(f"{labels.REGISTER}: no {_marker.MARKER_NAME} was written under {named}, so this "
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


def _reuse(marked_name: str, body: str, args: argparse.Namespace) -> int:
    """The marked session's own file: continue it, or refuse to overwrite it.

    The caller read these bytes once to decide the run is a reuse and hands
    them in: the identity is the whole decision. The same identity continues the
    session (exit 0, nothing written, HEAD unmoved); a different one is exit 1,
    because the only path on which a run can name a file it did not allocate is
    ``--file``, and that is exactly where an identity mismatch is refused.

    ``marked_name`` is the validated name the caller derived, printed as it is:
    the name inside the state root is what the operator has to go and look at.
    """
    existing_identity = _parse_fields(body).get("identity", "")
    if existing_identity != args.identity:
        return _fail(
            EXIT_IDENTITY_MISMATCH,
            f"{marked_name} already exists with identity "
            f"'{existing_identity}' (not '{args.identity}'); refusing to "
            "overwrite another session's file",
            "pass the identity that file carries, or register without --file "
            "so this run allocates its own session",
        )
    print(f"{labels.REGISTER}: {marked_name} already registered "
          f"(identity={existing_identity})")
    return EXIT_OK


def _read_marked_name(repo: Path, marker: Path | None
                      ) -> tuple[str, str | None, Path | None, str | None]:
    """``(name, marked_rel, file, status)``; ``("", None, None, None)`` for no marker.

    The marker is the working copy's own uncommitted file, so its text is an input
    rather than a fact: it names the id this working copy owns, and a name built
    from it is a name nobody validated. It is therefore gated once, on the read,
    by :func:`_session_git.writer_name` -- the same gate a command-line id passes
    -- and the name returned is the only form of the marker the rest of the run
    uses, so no read, pathspec, message or ``--file`` admission is built from
    marker text.

    The documented marker contract is that the marker holds the id this command
    wrote, so text that is not a session id is not a marker for a session at all:
    an invalid marker counts as unmarked, that is said on stderr, and the run
    allocates afresh and re-marks it for the session it actually writes.

    ``marked_rel`` and ``status`` are answered only when a marked file exists (so
    a marker naming a file that is gone answers no status), and the status read is
    the heuristic behind the 'allocating a new session' line: it replaces
    undecodable bytes rather than faulting, while the route that acts on the
    status reads the same bytes strictly and refuses on a decode failure, so a
    file no writer can read is never overwritten.
    """
    marked = _marker.read_marker(marker)
    if marked is None:
        return "", None, None, None
    name = _session_git.writer_name(marked)
    if not name:
        print(f"{labels.REGISTER}: {_marker.MARKER_NAME} names "
              f"{marked!r}, which is not a session id; ignoring it and allocating "
              "a new session", file=sys.stderr)
        return "", None, None, None
    marked_file = repo / name
    if not marked_file.is_file():
        return name, None, None, None
    status = _session_git.session_status(
        marked_file.read_text(encoding="utf-8", errors="replace"))
    return name, name, marked_file, status


def _resolve_target(allocated: str, marked_rel: str | None,
                    args: argparse.Namespace) -> str | int:
    """The name this run writes, or the exit code of the refusal.

    ``--file`` is validated before any marker read or write and before anything
    is written: the writer admits only the name it allocated in this run, or the
    marked session's file. Both are this working copy's own names, and they are
    different names, so a foreign path (neither one) is refused with exit 2 and
    no run reaches another session's file by naming it.

    ``marked_rel`` is the validated marker name from :func:`_read_marked_name`,
    and the caller passes ``None`` whenever this run writes a file of its own.
    ``--file`` is that signal: a run that names a path to write has already said
    it is not continuing the marked session (a reuse writes nothing, so it cannot
    be steered by ``--file``), and the only name it may write is the one this run
    allocated. That is what the docs promise: ``--no-commit`` and an ended marked
    session allocate a fresh file, and the marked file is not their target (see
    the module docstring and ``references/register.md``).

    The answer is a name inside the state root, never a path read against the
    cwd: ``--file`` is normalised by :func:`_session_git.relative_name` first, so
    an absolute argument or a ``..`` walk out of the root is refused here rather
    than resolved against wherever the run happened to be launched from.
    """
    if args.file is None:
        return allocated
    name = _session_git.relative_name(args.file)
    admitted = [allocated] if marked_rel is None else [allocated, marked_rel]
    if name not in admitted:
        return _fail(
            EXIT_USAGE,
            f"refusing to write {args.file}: the writer writes only the name it "
            f"allocated ({allocated})"
            + ("" if marked_rel is None else f" or the marked session's file "
                                             f"({marked_rel})"),
            "drop --file (the writer allocates the path), pass this run's allocation, "
            "or pass the session this working copy is marked for",
        )
    return name


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

    # A state root that is itself a symlink is refused here, before the sessions
    # directory is created and before any marker is read: git works on the
    # resolved path of the tree it is handed while this writer's path arithmetic
    # stays unresolved (a file about to be created cannot be resolved), so the
    # two readings disagree and the marker would be kept against a path nobody
    # named. The refusal is a usage error, the code register.py already uses for
    # a wrong path (docs/PRODUCT.md 7).
    linked, why = _session_git.linked_state_root(repo)
    if linked is not None:
        return _fail(EXIT_USAGE, f"--repo {args.repo}: {why}",
                     "pass the state root itself, not a symlink to it")

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
    # The session id this run owns, minted ONCE here and threaded through every
    # use of it (the name written, the pathspec, the marker's contents, the
    # commit subject, the printed line): two mints would let the printed id and
    # the committed id disagree. The id is the allocator's own, so the guard
    # below is a backstop that keeps the derivation single. It sits ahead of
    # every write because a refusal may never leave a file and a marker behind
    # (the #57 contract).
    session_id = _make_session_id()
    rel = _session_git.writer_name(session_id)
    if not rel:
        # The allocator's own answer is not a name it can commit: register's
        # argument code, because the fault is in a bad argument rather than in
        # git (EXIT_GIT would blame --repo or a symlink for a name the writer
        # derived itself), and the hint names --identity, the argument that
        # decides the session this run allocates.
        headline, hint = _session_git.name_refusal(
            f"{SESSIONS_REL}/{session_id}{_session_git.SESSION_SUFFIX}",
            arg="--identity")
        return _fail(EXIT_BAD_ARGS, headline, hint)

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

    marker = _marker.marker_path(repo)
    # The marker text is gated once, on the read (see _read_marked_name): the name
    # it returns is the only form of the marker this run uses, for the read, the
    # pathspec, the messages and the --file admission, so a marker that reads back
    # ``../../x`` -- hand-edited, or left by an earlier run on a tree that was
    # moved -- cannot put a path outside the state root into any of them.
    marked_name, marked_rel, marked_file, marked_status = _read_marked_name(
        repo, marker)
    # The reuse question, answered only for a marked file that exists and has not
    # ended: a marker naming a file that is gone is no evidence of a session (see
    # the module docstring), and neither is one whose status is terminal -- in both
    # cases this working copy starts a fresh session and the marker is rewritten
    # for it.
    reuse = marked_file is not None and not _session_git.is_terminal_status(
        marked_status or "")
    if marked_file is not None and not reuse:
        print(f"{labels.REGISTER}: marked session {marked_name} is "
              f"{marked_status.strip().lower()}; allocating a new session")

    # The reuse verdict comes from the marker and the marked file alone, before
    # the allocation is consulted. A reuse writes nothing and HEAD does not move.
    #
    # --no-commit opts out: the caller intends to write more than one session
    # here and commit them itself, so it gets a fresh allocation, and the marker
    # stays where it was because an opted-out run marks nothing.
    if reuse and not args.no_commit:
        # Only this route reads the marked bytes, and it reads them strictly: a
        # marked file that cannot be decoded is a refusal, not a fresh allocation,
        # because overwriting bytes this run could not read is what the writer
        # never does. The reason comes from the exception's own words, not from
        # strerror -- that attribute belongs to OSError and a UnicodeDecodeError
        # has none, and naming it here would turn a refusal into a traceback.
        try:
            body = marked_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return _fail(
                EXIT_USAGE,
                f"{marked_name} is marked as this working copy's session but "
                f"cannot be read ({exc.__class__.__name__}: {exc}); refusing to "
                "overwrite it",
                f"repair or remove {marked_file} (and the marker that names "
                "it), then re-run register.py",
            )
        return _reuse(marked_name, body, args)

    # --file may name the marked file only when this run writes no file of its
    # own (a reuse writes nothing, so a run that was given --file is not one):
    # an allocating run -- --no-commit, or a marked session that has ended or is
    # gone -- admits only the name it allocated.
    target = _resolve_target(rel, None if args.file is not None else marked_rel,
                             args)
    if isinstance(target, int):
        return target

    # A new session: write, and only then mark this working copy with the id
    # this run allocated. The name written is the one _resolve_target admitted --
    # this run's allocation, never a name read from the marker.
    target_file = repo / target
    host = args.host or session_id
    # Default to the repo's basename, not an absolute machine-local path:
    # the register file is committed to a public repo, so the worktree field
    # must stay generic (an absolute /home/... path would leak the operator's
    # local layout — see the public-repo hygiene rule in AGENTS.md).
    worktree = args.worktree or repo.resolve().name
    started = _now_utc()
    try:
        _session_git.atomic_write(
            target_file, _session_body(session_id, args.identity, host, worktree,
                                       started, args.status))
    except OSError as exc:
        return _fail(EXIT_USAGE,
                     f"{target_file} could not be written "
                     f"({exc.__class__.__name__}: {exc.strerror or exc})",
                     f"check that {sessions_dir} is writable, then re-run register.py")
    # The marker's bytes before this run touched it, read only when this run is
    # about to write one: reading after the write would hand the restore the
    # bytes this run itself wrote (see _marker.restore_marker for 'back').
    marker_before = _marker.read_marker_raw(marker) if not args.no_commit else None
    marked_ok = _marker.write_marker(marker, session_id) if not args.no_commit else False

    if args.no_commit:
        # Same validation chain and the same write as the committing path, minus
        # every git call: the file stays in the working tree and committing it is
        # the caller's job. No marker warning: this route writes no marker by
        # design, so there is no marker that failed to land.
        print(f"{labels.REGISTER}: {target_file} left uncommitted")
        return EXIT_OK

    if not _session_git.in_git_worktree(repo):
        # Nothing to commit into (the same fault that leaves no marker path):
        # behave as --no-commit rather than pretend a commit happened.
        print(f"{labels.REGISTER}: {target_file} left uncommitted")
        _warn_unmarked(marker)
        return EXIT_OK

    ok, why = _session_git.stage_and_commit(repo, target, f"register: {session_id}")
    if not ok:
        # The file is on disk and the marker was written for it; the marker goes
        # back to what it held before this run, so a working copy is never left
        # marked for a session git never received. When the restore itself could
        # not land, that is said too: a marker still naming this session is the
        # half-applied state the restore exists to prevent, and the commit
        # refusal alone would not tell the operator about it.
        restored = _marker.restore_marker(marker, marker_before)
        marked_ok = False
        headline = f"git could not commit {target} (the file is written): {why}"
        hint = f"commit {target} by hand, or re-run register.py once git answers"
        if not restored:
            headline += (f", and the marker at {marker} could not be restored, so "
                         "this working copy may still be marked for it")
            hint = (f"remove or repair the marker at {marker}, then commit {target} "
                    "by hand or re-run register.py once git answers")
        return _fail(EXIT_GIT, headline, hint)
    print(f"{labels.REGISTER}: registered session {session_id} -> {target_file}")
    if not marked_ok:
        _warn_unmarked(marker)

    if not args.push:
        return EXIT_OK
    branch, why = _session_push.current_branch(repo)
    if branch is None:
        return _fail(EXIT_GIT, f"push refused: {why}",
                     "check out a branch, or run the push by hand once HEAD names one")
    return _session_push.fetch_rebase_push(
        repo, branch, label=labels.REGISTER, exit_push_failed=EXIT_GIT,
        exit_rebase_conflict=EXIT_GIT, exit_rebase_refused=EXIT_GIT,
        # The rebase wording is claim's, published as the shared push contract
        # (references/claim.md): one wording for the same verdict, whichever
        # writer ran it.
        messages=claim._REBASE_MESSAGES,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
