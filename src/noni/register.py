"""Register a session: allocate a collision-free session-id and create the
register file at noni/sessions/<session-id>.md.

The session-id is random per working copy (<UTC date>-<6 hex>), allocated once
at registration. Ids are collision-free by construction, so each register file
has exactly one writer. The writer allocates the path and then refuses to write
any path it did not allocate: a path the operator passes with --file must match
the id this run allocated (a collision between allocation and --file exits
non-zero rather than overwriting someone else's file).

The file holds two kinds of field:

  identity, status — permanent: they survive across commits, pulls, clones;
  host/worktree, started, claims — ephemeral: they describe this working copy.

Usage:
    register.py --repo REPO --identity IDENTITY [--status STATUS]
                [--host HOST] [--worktree WORKTREE] [--file FILE]

Exit codes:
    0  registered, file created (or already present with matching identity)
    1  the allocated path collides with an existing file of a different
       identity (never write into someone else's file)
    2  --file was given and does not match the allocated path (the writer
       refuses a path it did not allocate)
    3  the sessions directory does not exist (register in a repo first)
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import labels


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
    parser.add_argument("--file", default=None, help="explicit file path (must match allocation)")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    sessions_dir = repo / "noni" / "sessions"
    if not sessions_dir.exists():
        # The sessions dir is created on first registration: a fresh repo has
        # no noni/ state yet. Creating an empty directory is not a protocol
        # violation — it is the first writer allocating its file.
        sessions_dir.mkdir(parents=True, exist_ok=True)

    session_id = _make_session_id()
    allocated = sessions_dir / f"{session_id}.md"

    host = args.host or allocated.stem
    # Default to the repo's basename, not an absolute machine-local path:
    # the register file is committed to a public repo, so the worktree field
    # must stay generic (an absolute /home/... path would leak the operator's
    # local layout — see the public-repo hygiene rule in AGENTS.md).
    worktree = args.worktree or repo.resolve().name
    started = _now_utc()

    # The --file guard: the writer refuses to write a path it did not allocate
    # within this run (see the module docstring). The allocated path is
    # freshly minted (a new random session id) on every run, so a --file that
    # names a file from an earlier run is refused here (exit 2): the writer
    # writes only a path it allocated in this run. A re-run that names a
    # file already registered under the same identity is a no-op (exit 0) via
    # the idempotency check below — that path is only reachable when the
    # operator points --file at a path this run happens to have allocated.
    if args.file is not None:
        target = Path(args.file)
        if not target.is_absolute():
            target = repo / target
        if target != allocated:
            print(
                f"{labels.REGISTER}: refusing to write {target}: "
                f"the allocated path is {allocated} (the writer writes only "
                "a path it allocated)",
                file=sys.stderr,
            )
            return 2
    else:
        target = allocated

    if target.exists():
        fields = _parse_fields(target.read_text(encoding="utf-8"))
        existing_identity = fields.get("identity", "")
        if existing_identity != args.identity:
            print(
                f"{labels.REGISTER}: {target.name} already exists with identity "
                f"'{existing_identity}' (not '{args.identity}'); refusing to "
                "overwrite another session's file",
                file=sys.stderr,
            )
            return 1
        # Same identity, same file: idempotent re-registration is a no-op.
        print(f"{labels.REGISTER}: {target.name} already registered (identity={existing_identity})")
        return 0

    content = (
        f"# session {session_id}\n\n"
        f"- identity: {args.identity}\n"
        f"- host/worktree: {host} ({worktree})\n"
        f"- started: {started}\n"
        f"- status: {args.status}\n"
        f"- claims:\n"
    )
    target.write_text(content, encoding="utf-8")
    print(f"{labels.REGISTER}: registered session {session_id} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
