"""The census's session group: the classes over ``noni/sessions/``.

Split from ``census.py`` so each file stays the size one responsibility is
worth: ``census.py`` owns the CLI, the exit-code table, the row shape and the
group wiring, and this module owns the register's per-file loop and the verdicts
built from it — the parse, the claim and identity maps, staleness, and the
append-only deletion question. The register's one readdir itself stays with
``census_sessions_probe``: this module is handed that listing as the probe and
never lists the directory for itself, which is what keeps the run to one read.

Like the other split-outs this is an ordinary package import, and the row
mechanics it needs — ``row``, ``file_kind``, ``rel_to``, ``rel_to_root``,
``append_cannot_tell``, and the faulted-listing and deleted-file checks of the
neighbouring modules — are handed in at the call, so the row shape, its
visibility marker and the machine-local-path rule keep their single owner in
``census.py`` and this module composes no row of its own devising.

The three constants the register's classes are written against stay declared in
``census.py``, the file that owns the check contract, and are read through that
module rather than copied here, so a compiled pattern has one definition no
second copy can drift from. That read goes through the module object, taken at
first use, because ``census.py`` imports this module: at this module's import
time the census's own body is still executing, so the names are not yet bound.

Nothing here prints or exits: every answer is appended to the caller's
``findings`` list.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from . import census_text as _text

if TYPE_CHECKING:  # pragma: no cover - typing only, nothing imported at runtime
    from .census import Git

_census = None


def _constants():
    """The census module the register's constants are read from.

    Late, and through the module object rather than ``from ... import``: the
    census imports this module, so at import time ``SESSION_NAME_RE`` and the
    other two are not yet bound on a half-built module. Resolving the reference
    per use also means the census may rebind them (a test seam) and this module
    sees the rebinding, the way it would if the code still lived there.
    """
    global _census
    if _census is None:
        from . import census
        _census = census
    return _census


def parse_session(body: str) -> tuple[dict[str, str], list[str], list[str]]:
    """Parse a session register body into (fields, claims, problems)."""
    fields: dict[str, str] = {}
    claims: list[str] = []
    problems: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line.startswith("- "):
            continue
        key, sep, value = line[2:].partition(":")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if key in _constants().SESSION_REQUIRED_FIELDS:
            fields[key] = value
        elif key == "claim":
            if not value:
                problems.append("claim row with no task reference")
            else:
                claims.append(value)
    for field in _constants().SESSION_REQUIRED_FIELDS:
        if field not in fields:
            problems.append(f"missing field: {field}")
    return fields, claims, problems


def is_non_terminal(fields: dict[str, str]) -> bool:
    """True when a parsed session file is still open: its status is none of
    INACTIVE_STATUSES. The one definition of "non-terminal" the register
    reports use (claims, staleness, same-identity)."""
    return fields.get("status", "").strip().lower() not in _constants().INACTIVE_STATUSES


def check_sessions(
    sessions: Path, git: "Git | None", root: Path, now: datetime, stale_after: timedelta,
    strict: bool, findings: list[dict], probe, *,
    row: Callable[..., dict],
    file_kind: Callable[..., tuple[str, str | None]],
    rel_to: Callable[[Path, Path], str | None],
    append_listing_fault: Callable[[Path, Path, bool, list[dict], str], None],
    check_sessions_deleted: Callable[..., None],
) -> None:
    """Check the session register; append its findings to ``findings``.

    ``probe`` is the run's one listing of ``sessions``, built by ``main`` before
    it decided whether this group runs at all: a second listing would be a second
    read of the directory and a second chance to disagree with the first, so the
    group reports from the answer that got it here (see :class:`SessionsProbe`).

    A missing sessions directory is a clean state (no sessions registered);
    an unreadable or non-directory path is a probe failure, never clean.
    Stalled sessions and probe failures are warnings by default and failures
    under --strict.

    A directory that stats fine and cannot be *listed* is neither of those
    states, so it is not answered with a state word: the group reports the one
    probe-honesty row of :func:`_append_sessions_listing_fault` and stops,
    because a register this run could not enumerate has no files to check and
    its git-backed deletion question cannot have been answered either.

    The row factory, the classifier a probe row is built from, the root-relative
    identifier, the faulted-listing row and the deletion check are the census's
    own and are handed in at the call, so the row shape keeps its single owner
    there and the group's per-file code stays its own size here.
    """
    def add(check: str, subject: str, artifact: str, message: str) -> None:
        findings.append(row(check, strict, subject, artifact, message, root))

    kind, problem = file_kind(sessions, kind="dir")
    if kind == "absent":
        return
    if kind != "regular":
        add("probe", str(sessions), str(sessions), f"sessions path is not a readable directory: {problem}")
        return

    if probe.fault is not None:
        # The register is there and is a directory, and readdir refused it: the
        # read answered nothing, so nothing but the fault is reportable, and no
        # session row of a directory this run never saw is honest either.
        append_listing_fault(sessions, root, strict, findings, probe.fault)
        return
    # One fault path only: SessionsProbe cannot be built any other way, so a
    # probe handed neither a listing nor a fault raised at construction rather
    # than being answered as a register this run read and found empty.
    assert probe.names is not None
    files = list(probe.names)
    claim_map: dict[str, dict[str, list[str]]] = {}
    # One read + parse per register file; both the claim map and the
    # same-identity map below are built from these results, so a file is never
    # classified twice by two loops that could drift.
    by_files: dict[str, list[str]] = {}
    for path in files:
        name = path.name
        if not _constants().SESSION_NAME_RE.match(name):
            add("session-malformed", name, str(path), "filename is not the allocated <YYYY-MM-DD>-<6 hex>.md shape")
            continue
        fkind, fproblem = file_kind(path)
        if fkind != "regular":
            add("probe", name, str(path), f"session file unreadable: {fproblem}")
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # The bytes of an undecodable file are hostile content, so the row
            # names the class and echoes none of them.
            add("session-malformed", name, str(path), "file unreadable: not valid UTF-8")
            continue
        except OSError as e:
            add("session-malformed", name, str(path),
                f"file unreadable: {_text.fault_text(e)}")
            continue
        fields, claims, problems = parse_session(body)
        if problems:
            missing_identity = "missing field: identity" in problems
            if missing_identity and claims:
                add(
                    "session-claim",
                    name,
                    str(path),
                    "claim row committed without a register file: " + "; ".join(problems),
                )
            else:
                add("session-malformed", name, str(path), "; ".join(problems))
            continue
        non_terminal = is_non_terminal(fields)
        if non_terminal:
            for task in claims:
                claim_map.setdefault(task, {}).setdefault(fields.get("identity", ""), []).append(name)
            # session-same-identity (warn 43): identity is the key the whole
            # protocol keys on — the register writer and the claim writer both
            # refuse to write into a file someone else allocated — so two
            # non-terminal register files carrying one identity mean the
            # allocation was hand-edited or copied. The legacy per-epic shim
            # reports the narrower claim-overlap case separately; this class is
            # the unified census's own (warn-only) view of shared identity, and
            # it does not change what session-double fires on.
            identity = fields.get("identity", "").strip()
            if identity:
                by_files.setdefault(identity, []).append(name)

        # Staleness: the signals are the register file itself and the git
        # history that last touched it. Both must say stale (agreement); any
        # signal missing or unreadable is cannot-tell (warn), never stalled.
        if fields.get("status", "").strip().lower() == "active":
            if git is not None and git.available:
                rel = rel_to(git.top, path)
                entry = None if rel is None else git.last_commit(rel)
                if entry is None:
                    add(
                        "session-stalled",
                        name,
                        str(path),
                        "cannot-tell: no commit history for this session file in this tree (shallow clone, or never committed)",
                    )
                else:
                    age = now - datetime.fromtimestamp(entry[0], tz=timezone.utc)
                    if age > stale_after:
                        commit = entry[1]
                        add(
                            "session-stalled",
                            name,
                            str(path),
                            f"stalled: status is active and no commit for this file in the last {stale_after} "
                            f"(last commit {commit[:7]})",
                        )
            else:
                add(
                    "session-stalled",
                    name,
                    str(path),
                    "cannot-tell: git history unavailable in this tree; staleness cannot be computed",
                )

    for task in sorted(claim_map):
        by_identity = claim_map[task]
        if len(by_identity) > 1:
            details = "; ".join(f"{ident}: {', '.join(sorted(sess))}" for ident, sess in sorted(by_identity.items()))
            add(
                "session-double",
                task,
                str(sessions),
                f"double-claim: task {task} is actively claimed by {len(by_identity)} identities ({details})",
            )

    # session-same-identity (warn 43) is answered from the same single pass:
    # by_files was filled with exactly the non-terminal, parseable files.
    for identity in sorted(by_files):
        names = sorted(by_files[identity])
        if len(names) > 1:
            add(
                "session-same-identity",
                identity,
                str(sessions),
                f"session-same-identity: {len(names)} non-terminal session files share identity "
                f"{identity!r} ({', '.join(names)}); identity is the key the protocol keys on — "
                "one identity should hold one open register file",
            )

    check_sessions_deleted(sessions, git, root, strict, findings)


def check_sessions_deleted(
    sessions: Path, git: "Git | None", root: Path, strict: bool, findings: list[dict], *,
    row: Callable[..., dict],
    rel_to_root: Callable[[Path, Path], str],
    append_cannot_tell: Callable[[str, str, bool, list[dict]], None],
) -> None:
    """The deleted-session-file check (warn 44).

    A session register file that HEAD-reachable history shows was added, but
    that is gone from the working tree, is reported here. Ending a session
    goes through its ``status`` field; deleting the register file destroys the
    attribution and the claim history the census reads, so it is a violation
    (unlike the legacy shim, which stays silent on deletions).

    Only paths shaped like an allocated register file (``SESSION_NAME_RE``)
    are considered — anything else under noni/sessions/ is not a register
    file and its removal is not this class's business. When the question
    cannot be answered the class says so rather than leaving a filtered run to
    read "no rows" as "nothing was deleted": see the two guards below for who
    gets the cannot-tell row and who does not, and why.

    The row factory, the root-relative identifier and the cannot-tell row are
    the census's own and are handed in at the call, so the row shape and the
    cannot-tell severity rule keep their single owner there.
    """
    if git is None or not git.available or git.top is None:
        # No history to answer from — and this is NOT reported as a cannot-tell
        # here, deliberately: a --repo that is simply not a git repository has
        # no register history to speak of, and hygiene (not-run) plus
        # session-stalled ("cannot-tell: git history unavailable", once per
        # active file) already own that state. This class's cannot-tell is
        # reserved for the case where the census *was* reading a git tree and
        # the --sessions override moved the register out of it: that is the
        # one configuration in which the append-only check stops running.
        return
    top = git.top
    try:
        prefix = sessions.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        # The register lives outside this git tree, so the append-only question
        # cannot be answered from its history: reported, not swallowed.
        append_cannot_tell(
            "session-deleted",
            f"the sessions path ({rel_to_root(root, sessions)}) is outside the audited git "
            "tree, so whether a committed register file was deleted cannot be answered",
            strict, findings)
        return
    for rel in sorted(git.added_paths_under(prefix)):
        name = rel.rsplit("/", 1)[-1]
        if not _constants().SESSION_NAME_RE.match(name):
            continue
        if (top / rel).is_file():
            continue
        findings.append(
            row("session-deleted", strict, name, str(top / rel),
                f"deleted: session file {name} is in git history but missing from the "
                "working tree; sessions end via their status field, never by deleting the "
                "register file", root)
        )
