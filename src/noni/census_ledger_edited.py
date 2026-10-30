"""The census's git-backed ledger integrity checks: post-commit edit and deletion.

Split from ``census.py`` beside ``census_ledger_checks.py``, and kept apart from
it for the same reason they are both kept apart from the census: these are the
two questions only git can answer about ``noni/decisions/``, and each is the
sole reporter of its own rule. ``check_ledger_edited`` compares the committed
bytes of every record (valid or unparseable) against the bytes on disk;
``check_ledger_deleted`` asks HEAD-reachable history which paths were ever added
and reports the ones the working tree no longer holds — the append-only rule of
the steering ledger. ``check_ledger_chain`` settles the supersede chain, and
``append_cannot_tell`` is the one cannot-tell row both the ledger and the
session group's deletion check borrow.

Everything a row is built from — the census's own ``row`` factory, its
root-relative identifier, its content digest — is handed in at the call, so the
row shape keeps its single owner there; the class table is looked up through
``census_report`` rather than copied. Both checks read through the run's one
``Git`` view, built once by ``main``. Nothing here prints or exits.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .census_report import CLASS_CODE, CLASS_SEVERITY, _promote

if TYPE_CHECKING:  # pragma: no cover - typing only, nothing imported at runtime
    from .census_git import Git


def check_ledger_edited(
    valid: list[tuple[str, Path, dict]],
    unparseable: list[tuple[str, Path]],
    git: Git | None,
    root: Path,
    findings: list[dict],
    strict: bool,
    *,
    row: Callable[..., dict],
    rel_to: Callable[[Path, Path], str | None],
    repo_sha1: Callable[[Path], str | None],
) -> None:
    """The post-commit edit check (git vs disk bytes).

    Runs for every valid record AND every record that failed parsing: a
    parse-time rejection must not silence the integrity check. The newest
    commit per path is a dict lookup over the git log already parsed at
    construction time (not a second `git log` subprocess), and the disk sha
    is one in-memory hash per file. A record whose committed bytes are
    unreachable degrades to a cannot-verify warning (probe honesty), never a
    silent pass."""
    # ledger-edited is a fail class, so an ordinary row of it is a failure with
    # or without --strict. The one exception is the unreachable-blob row below:
    # the census could not read the committed bytes, which is an unreadable
    # environment, not a protocol violation — so it overrides its severity to
    # warn (exit 0) and is escalated only under --strict, matching origin/main
    # and the cannot-tell rule in _append_cannot_tell.
    def add(check: str, subject: str, artifact: str, message: str,
            cannot_verify: bool = False) -> None:
        findings.append(row(check, strict, subject, artifact, message, root,
                             severity="warn" if cannot_verify else None))

    if git is None:
        return
    entries: list[tuple[str, str, Path]] = []
    for rid, path, _obj in valid:
        entries.append((rid, rid, path))
    for name, path in unparseable:
        entries.append((name, name, path))
    if not entries:
        return
    rels = [rel_to(git.top, p) for _s, _rid, p in entries]
    for idx, (_subject, rid, path) in enumerate(entries):
        rel = rels[idx]
        entry = git.last_commit(rel) if rel is not None else None
        if entry is None:
            continue  # never committed: nothing to compare against
        blob = git.blob_content_sha1(entry[1], rel)
        disk = repo_sha1(path)
        if blob is None:
            add("ledger-edited", rid, str(path),
                "cannot verify: committed blob is unreachable in this tree (shallow or pruned history)",
                cannot_verify=True)
        elif disk is not None and blob != disk:
            add("ledger-edited", rid, str(path), "record was edited after commit (working tree differs from git)")

def append_cannot_tell(check: str, reason: str, strict: bool,
                       findings: list[dict]) -> None:
    """Append the cannot-tell row of a check whose question this run cannot
    answer. One row saying so is the probe-honesty rule: a check that fell
    silent would read as a clean run of a check that never ran.

    Cannot-tell severity is derived, never inherited from the class: a fail
    class's cannot-tell is a warn by default (an environment that cannot be
    read is not itself a protocol violation) and --strict escalates it, while a
    warn class keeps its own default — which is why session-deleted's
    cannot-tell exits 44 under --strict and ledger-edited's exits 41. The
    unreachable-blob row of the edit check follows the same rule through
    ``_row``'s explicit ``severity`` argument rather than through this helper,
    because it names the record it could not verify instead of the check.
    """
    base = CLASS_SEVERITY[check]
    severity = "warn" if base == "fail" else base
    findings.append({
        "check": check,
        "code": CLASS_CODE[check],
        "severity": _promote(severity, strict),
        "subject": "cannot-tell",
        "artifact": check,
        "message": f"cannot-tell: {reason}",
    })

def check_ledger_deleted(ledger: Path, git: Git | None, root: Path, findings: list[dict],
                         strict: bool, *,
                         row: Callable[..., dict],
                         rel_to_root: Callable[[Path, Path], str],
                         cannot_tell: Callable[[str, str, bool, list[dict]], None],
                         ) -> bool:
    """The deleted-record check (append-only ledger rule).

    Decision records are append-only: a record is superseded by a new record,
    never removed. A record that HEAD-reachable git history shows was added
    but is absent from the working tree — deleted or renamed — is reported
    here, whether the change is uncommitted or itself committed. A record that
    was only ever added on an unmerged branch (never reachable from HEAD) is
    not a deletion — it is not part of this branch's history. It is a
    sub-reason ("deleted")
    of the ledger-edited class (exit 12): both are violations of the same
    "never change committed record state" rule.

    Returns True when this run could not put the question to git at all — no
    git tree named, or the history read could not answer — and False when it
    did (including the paths it reported). ``_check_ledger`` turns a True into
    a cannot-tell row when the ledger reads as "empty", the one state where a
    deletion is what the tree looks like, so the check cannot fall silent on a
    state it never answered. A path that was never committed is not a deletion —
    there is nothing in history to have been removed, and the ledger's own
    record pass is what reports a record that exists on disk: this check only
    reports paths history shows and the working tree does not hold. Session
    files are intentionally NOT checked here: ending a session via its status
    field is the protocol, and deleting a session file is not a violation.

    Unlike `_check_sessions_deleted`, this check asks git even when the ledger
    directory is gone: records are append-only, so a committed ``decisions/``
    directory deleted whole is the deletion the operator must be told about,
    while a session register is expected to hold no file at all for a project
    that has never opened a session."""
    if git is None:
        # No git tree was named at all (not a repository, or rev-parse could
        # not answer): there is nothing to ask.
        return True
    if not git.available or git.top is None:
        # A tree is named but git could not answer: the history read failed or
        # timed out (available False), or the object carries no tree.
        return True
    top = git.top
    try:
        prefix = ledger.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        # The append-only question cannot be answered for an --ledger override
        # that points outside the audited tree. Unlike the sessions layer, the
        # ledger group's cannot-tell is the only row this run produces about
        # the override, so it is reported here — at the cannot-tell severity,
        # not the class's fail severity, because the same condition is a
        # perfectly normal state for a legitimate out-of-tree override.
        cannot_tell(
            "ledger-edited",
            f"the ledger path ({rel_to_root(root, ledger)}) is outside the audited git tree, "
            "so whether a committed record was deleted cannot be answered", strict, findings)
        return False
    for rel in sorted(git.added_paths_under(prefix)):
        if (top / rel).is_file():
            continue
        subject = rel.rsplit("/", 1)[-1]
        findings.append(
            row("ledger-edited", False, subject, str(top / rel),
                 f"deleted: record {subject} is missing from the working tree because it was "
                 "deleted or renamed (in git history but absent now; the change is uncommitted "
                 "or committed); decision records are append-only: restore the original path "
                 "(git checkout <commit> -- <path>) and record any change as a new superseding "
                 "record instead of deleting or renaming", root)
        )
    return False

def check_ledger_chain(
    valid: list[tuple[str, Path, dict]], ledger: Path, root: Path, findings: list[dict],
    *, row: Callable[..., dict],
) -> None:
    """Supersede-chain analysis: dangling, duplicate, orphan, cycle, and the
    single-live-record-per-chain rule.

    Only records that parsed cleanly (valid) can contribute to chain
    analysis: an unparseable record's supersedes field is unreadable, so its
    chain state is genuinely unknowable."""
    # ledger-chain is a fail class: --strict does not change its severity.
    def add(check: str, subject: str, artifact: str, message: str) -> None:
        findings.append(row(check, False, subject, artifact, message, root))

    ids = {rid for rid, _p, _o in valid}
    supers = {rid: o["supersedes"] for rid, _p, o in valid}
    status = {rid: o["status"] for rid, _p, o in valid}
    succ: dict[str, list[str]] = {}
    for rid, sup in supers.items():
        if sup is not None:
            succ.setdefault(sup, []).append(rid)
    for target, children in sorted(succ.items()):
        if len(children) > 1:
            add(
                "ledger-chain",
                target,
                str(ledger),
                f"duplicate: {target} is superseded by more than one record ({', '.join(sorted(children))})",
            )
    for rid in sorted(ids):
        sup = supers[rid]
        if sup is not None and sup not in ids:
            add("ledger-chain", rid, str(ledger), f"dangling: {rid} supersedes {sup} (no such record)")
        if sup is None and status[rid] == "superseded" and rid not in succ:
            add("ledger-chain", rid, str(ledger), f"orphan: {rid} is marked superseded but no record supersedes it")
    for rid in sorted(ids):
        seen = set()
        t: str | None = rid
        cycle = False
        while t is not None and t in supers and t in ids:
            if t in seen:
                cycle = True
                break
            seen.add(t)
            t = supers[t]
        if cycle:
            add("ledger-chain", rid, str(ledger), f"cycle: {rid} is in a supersedes cycle")
    chains: dict[str, list[str]] = {}
    for rid in ids:
        root_id = rid
        t = rid
        seen = set()
        while supers.get(t) is not None and supers[t] in ids and t not in seen:
            seen.add(t)
            t = supers[t]
            root_id = t
        chains.setdefault(root_id, []).append(rid)
    for root_id, members in sorted(chains.items()):
        live = [m for m in members if status[m] != "superseded"]
        if root_id not in ids:
            continue
        if len(live) == 0:
            add("ledger-chain", root_id, str(ledger), f"zero-live: chain {root_id} resolves to no live record")
        elif len(live) > 1:
            add("ledger-chain", root_id, str(ledger), f"multi-live: chain {root_id} resolves to more than one live record")
