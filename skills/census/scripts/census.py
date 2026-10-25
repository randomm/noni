"""The unified census: one read-only entry point over the steering ledger and
the session register.

The census is the arbiter of the noni protocol invariants. It reads the git
history plus the committed files under ``noni/`` (decision records under
``noni/decisions/``, session registers under ``noni/sessions/``), flags
protocol violations, and returns an honest exit code. It never writes
anything: running it leaves ``git status --porcelain`` empty, and no digest
file or report directory is produced — results are recomputed on demand.

The check ids, their codes and their default severities are declared once,
in ``CHECKS`` below: the exit-code table, ``--list``, the ``--strict`` help
string and the tests' expected ids are all derived from it.

The warn classes make a finding without --strict but never move the exit code
on their own: the clean-ledger case (no noni/ at all) is a reported warning,
not a silent clean.

Probe failures never report clean: a probe that cannot read a file or cannot
run git records a probe failure (a warning, or its own code under --strict),
never a silent pass. The same rule covers the checks whose question this run
cannot answer at all — they append a ``cannot-tell`` row naming why, rather
than falling silent and reading as a clean run.

Time comes from ``--now <ISO-8601>`` when given (reproducible output for
tests), otherwise the current UTC time. Every metric in --json mode derives
from git history, file existence, or file sizes — never from a value
written inside an agent-authored field.

Exit codes: 0 clean (warnings allowed), 2 usage error, 3 a required tool is
missing, then the class codes above. The lowest non-zero class code wins;
stderr names every class that fired.
"""

from __future__ import annotations

import argparse
import collections.abc
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

SCHEMA_VERSION = "noni.census/1"

# The ledger checks run as one group: any of the three triggers all three, so
# --only/--skip must be applied at group granularity. ledger-empty (42) is
# reported by the same group and owns the "no ledger to arbitrate" states; it
# no longer exits 10.
LEDGER_CHECKS = frozenset({"ledger-record", "ledger-edited", "ledger-chain"})
# The session register group, likewise: the checks share one read of the
# register, so the group runs together and the row filter decides what is kept.
SESSION_CHECKS = frozenset({
    "session-double", "session-claim", "session-malformed", "session-stalled",
    "session-same-identity", "session-deleted", "probe",
})

# --- Exit-code table ----------------------------------------------------------
# The class codes live in CHECKS below; 0 | 2 | 3 are reserved for non-class
# outcomes (clean, usage error, required tool missing).
EXIT_CLEAN = 0
EXIT_USAGE = 2
EXIT_TOOL_MISSING = 3

# The one declaration of the check contract: id -> (code, default severity,
# fix hint). Everything a caller can read about a class — its exit code, its
# severity with and without --strict, the fix hint on every row, the --list
# output and the --strict help string — is derived from this table, so adding
# a class means one row here rather than five edits that can drift.
CHECKS: dict[str, tuple[int, str, str]] = {
    "ledger-record": (
        10, "fail",
        "repair or remove the offending record, or pass the ledger directory of the right clone",
    ),
    "ledger-edited": (
        12, "fail",
        "supersede the record with a new file; never edit a committed record",
    ),
    "ledger-chain": (
        20, "fail",
        "repair the supersede chain so it resolves to exactly one live record per chain",
    ),
    "session-double": (
        30, "fail",
        "release the claim on the task in one session, or record who keeps it as a ledger decision",
    ),
    "session-claim": (
        31, "fail",
        "register the session (add the identity field) or move the orphan claim into a registered session file",
    ),
    "session-malformed": (
        32, "fail",
        "restore the missing field or add the missing task reference to the claim row",
    ),
    "session-stalled": (
        40, "warn",
        "close the session or commit a fresh register update if the work is still in flight",
    ),
    "probe": (
        41, "warn",
        "fix the unreadable file or the git tree; a census that cannot read its input reports "
        "the probe failure, never clean",
    ),
    "ledger-empty": (
        42, "warn",
        "record at least one dated decision under the ledger directory (steer a question and "
        "commit the record), or pass the ledger directory of the clone that holds the decisions",
    ),
    "session-same-identity": (
        43, "warn",
        "give each session file its own identity, or close the stale session files so only one "
        "non-terminal file carries that identity",
    ),
    "session-deleted": (
        44, "warn",
        "restore the session file (git checkout <commit> -- <path>) — ending a session goes "
        "through its status field, never through deleting the register file",
    ),
    "hygiene": (
        50, "warn",
        "remove the personal path, secret shape or deny-list name from the tracked file (rewrite "
        "history if it was ever committed), and keep the local deny-list present so the deny-list "
        "class stays active",
    ),
}

# Derived views of CHECKS — never edited by hand.
CLASS_CODE = {name: code for name, (code, _sev, _fix) in CHECKS.items()}
CLASS_SEVERITY = {name: sev for name, (_code, sev, _fix) in CHECKS.items()}
CLASS_FIX = {name: fix for name, (_code, _sev, fix) in CHECKS.items()}


def _severity(check: str, strict: bool) -> str:
    """The severity a row of ``check`` carries in this run: warn classes become
    failures under --strict, fail classes are unaffected. The one place that
    rule lives — every reporter derives its severity here."""
    severity = CLASS_SEVERITY[check]
    return "fail" if strict and severity == "warn" else severity


NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.json$")
STALE_AFTER_RE = re.compile(r"^\d+d?$")

REQUIRED_LEDGER_FIELDS = (
    "id",
    "date",
    "asked_by",
    "questions",
    "by",
    "scope",
    "status",
    "supersedes",
)

# The one optional (but validated) ledger field: ``source``. It carries the
# tracker provenance of a record produced from a tracker-sourced answer (an
# adapter's question-legitimacy verdict): an object with ``issue_number``
# (int) and ``comment_id`` (int). ``null`` (or absent) for records that did
# not come from a tracker. A record without it stays valid: the eight
# REQUIRED_LEDGER_FIELDS above are the closed required set, and ``source`` is
# the one extra key the schema admits.

# A UTC ISO-8601 second-resolution timestamp (the record date shape).
DATE_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$"
)

SESSION_REQUIRED_FIELDS = ("identity", "host/worktree", "started", "status", "claims")
INACTIVE_STATUSES = {"closed", "done", "superseded", "ended"}

# Every git subprocess in this module runs under this timeout: a hung git
# (huge or corrupt history, a credential prompt) degrades to the cannot-tell
# probe outcome instead of hanging the census.
GIT_TIMEOUT_SECONDS = 60

# Session register files follow the allocated shape <YYYY-MM-DD>-<6 hex>.md;
# anything else is reported as malformed, never treated as an allocated file.
SESSION_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[0-9a-f]{6}\.md$")

# The five states the ledger probe answers: the four the ledger-empty class
# reports, each in exactly one row's message, plus the silent "ok". The words
# and their wording are pinned by LEDGER_EMPTY_MESSAGES below and the tests
# iterate that table, so renaming a state without updating its wording (and
# tests/test_census_unified.py) is a contract change.
LEDGER_EMPTY_STATES = ("absent", "empty", "not a directory", "symlink", "ok")

# state word -> the detail the row carries, or None for the state that reports
# nothing. The keys ARE the state vocabulary: _ledger_state returns one of
# them and _check_ledger_empty looks its message up here, so the contract has
# exactly one owner.
LEDGER_EMPTY_MESSAGES: dict[str, str | None] = {
    "absent": "no decision record is censusable: the ledger directory is absent "
    "(no noni/decisions under this repo — no steering ledger to arbitrate)",
    "empty": "the ledger directory holds no *.json record",
    "not a directory": "noni/ is not a directory, so no ledger can live under it",
    "symlink": "noni/ or the ledger path is a symlink; the census does not read through links",
    "ok": None,
}


class Git:
    """A read-only view over the git history of a repository.

    All history is resolved by commit time, never by wall clock: a session's
    "last commit" is the latest commit whose tree contains the session file,
    taken from ``git log`` output. ``available`` is False when the tree is not
    a git repository or git itself fails: callers then report cannot-tell,
    never a silent pass.
    """

    def __init__(self, top: Path | None) -> None:
        self.top = top
        self.available = False
        self._last_commit: dict[str, tuple[int, str]] = {}
        self._total_commits: int | None = None
        self._commit_author: dict[str, str] = {}
        self._commit_ts: dict[str, int] = {}
        if top is not None and top.is_dir():
            head = self._run(["rev-parse", "HEAD"])
            log = self._run(["log", "--all", "--format=%H%x1f%ct%x1f%an", "--name-only"])
            if head is not None and log is not None:
                self.available = True
                self._parse(log)

    def _run(self, args: list[str]) -> str | None:
        try:
            proc = subprocess.run(
                ["git", "-C", str(self.top), *_git_config_args(), *args],
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
                env=_git_env(),
            )
        except subprocess.TimeoutExpired:
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout

    def _parse(self, log: str) -> None:
        """Resolve per-path last commits from the --all log.

        The log is reverse-chronological, so the first commit parsed for a
        path is its newest; record it only if the path is absent, so that
        same-timestamp commits do not let an older one overwrite the newer.
        _last_commit[relpath] is a (unix ts, commit id) pair keyed by the
        commit id (the second tuple element)."""
        current = None
        for line in log.splitlines():
            if "\x1f" in line:
                commit, ts, author = line.split("\x1f")
                current = commit
                self._commit_author[commit] = author
                if self._total_commits is None:
                    self._total_commits = 0
                self._total_commits += 1
                self._commit_ts[current] = int(ts)
            elif current is not None and line.strip():
                rel = line.strip()
                if rel not in self._last_commit:
                    ts = self._commit_ts.get(current, 0)
                    self._last_commit[rel] = (ts, current)

    def added_paths_under(self, prefix: str) -> set[str]:
        """Every path under ``prefix`` that HEAD-reachable history shows was added.

        Runs ``git log HEAD --diff-filter=A --name-only`` restricted to the
        prefix (through the shared ``_run`` timeout) so the same probe-honesty
        rule applies: a hung or failing git degrades to the empty set (the
        check degrades to disk-only enumeration), never a silent hang.
        Paths that were added on an unmerged branch but never reached the
        current branch are not reported as deleted, because they are not
        reachable from HEAD."""
        prefix = prefix.strip("/").rstrip("/")
        # Guard: if HEAD does not exist (empty repo, no commits yet), git log
        # HEAD will fail and _run returns None, yielding an empty set. This is
        # the correct behaviour — there is no history to check against.
        out = self._run(["log", "HEAD", "--diff-filter=A", "--name-only",
                         "--format=", "--", prefix])
        paths: set[str] = set()
        for line in (out or "").splitlines():
            rel = line.strip()
            if rel.startswith(prefix + "/"):
                paths.add(rel)
        return paths

    def last_commit(self, relpath: str) -> tuple[int, str] | None:
        """(unix ts, commit id) of the latest commit containing relpath, or None."""
        return self._last_commit.get(relpath)

    def total_commits(self) -> int | None:
        return self._total_commits

    def commit_author(self, commit: str) -> str:
        return self._commit_author.get(commit, "")

    def last_author(self, relpath: str) -> str:
        entry = self._last_commit.get(relpath)
        if entry is None:
            return ""
        return self._commit_author.get(entry[1], "")

    def blob_content_sha1(self, commit: str, relpath: str) -> str | None:
        """The sha1 of the committed content bytes of relpath at commit, or None
        when the blob is unreachable (shallow or pruned history) or git times out.

        Uses ``git cat-file blob`` to read the raw bytes and re-hashes them,
        matching the way ``_repo_sha1`` hashes the disk bytes — so the
        comparison is content-sha1 vs content-sha1. (``git rev-parse
        <commit>:<path>`` returns the git object sha, not the content sha1.)"""
        try:
            proc = subprocess.run(
                ["git", "-C", str(self.top), *_git_config_args(), "cat-file", "blob",
                 f"{commit}:{relpath}"],
                capture_output=True,
                timeout=GIT_TIMEOUT_SECONDS,
                env=_git_env(),
            )
        except subprocess.TimeoutExpired:
            return None
        if proc.returncode != 0:
            return None
        # proc.stdout is bytes (no text=True): the digest is over raw blob
        # bytes, matching _repo_sha1's read_bytes(). Do NOT add text=True —
        # it would decode the blob (raising or altering on non-UTF-8) and
        # silently change the digest.
        return hashlib.sha1(proc.stdout).hexdigest()


def _parse_iso(ts: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_now(value: str | None) -> tuple[datetime | None, str | None]:
    if value is None:
        return datetime.now(timezone.utc), None
    parsed = _parse_iso(value)
    if parsed is None:
        return None, f"error: --now {value!r} is not a valid ISO-8601 timestamp"
    return parsed, None


def _git_top(root: Path) -> Path | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *_git_config_args(), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            env=_git_env(),
        )
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    top = Path(proc.stdout.strip())
    return top if top.is_dir() else None


def _rel_to(top: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        return None


def _rel_to_root(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _row(check: str, strict: bool, subject: str, artifact: str, message: str,
         root: Path, relative_artifact: bool = True) -> dict:
    """Build one finding row: the only place a row's shape is written.

    ``code``/``fix`` come from CHECKS and ``severity`` from `_severity`, so a
    new row field (or a change to how those three are derived) is one edit
    here rather than five reporter-by-reporter copies. ``artifact`` is rooted
    into the audited tree by default; a reporter that names an artefact
    outside it passes ``relative_artifact=False`` and supplies its own id.
    """
    return {
        "check": check,
        "code": CLASS_CODE[check],
        "severity": _severity(check, strict),
        "subject": subject,
        "artifact": _rel_to_root(root, Path(artifact)) if relative_artifact else artifact,
        "message": message,
    }


def _rel_to_census(path: Path) -> str:
    """A path relative to the census script's own skills/census/scripts/ dir.

    Used for the artifacts the hygiene class names when it could not run: the
    census never prints a machine-local absolute path, so the scan's own module
    is named from where the census lives (``../../../scripts/...``). These rows
    therefore live in a different artifact namespace from the root-relative
    ones — see skills/census/SKILL.md, "The hygiene artifact namespace".
    """
    try:
        return Path(os.path.relpath(path.resolve(), Path(__file__).resolve().parent)).as_posix()
    except OSError:
        return str(path)


def _file_kind(path: Path, kind: str = "file") -> tuple[str, str | None]:
    """Classify a file for the census: ("absent"|"regular"|"symlink"|"nonregular", problem).

    ``kind`` is "file" (default) or "dir". Only a regular, non-symlinked
    entry of the requested kind is readable. Symlinked or non-regular
    artefacts are reported as probe failures (never read through a link), and
    a missing entry is absent (a real state, not an oversight).
    """
    try:
        if path.is_symlink():
            return "symlink", "path is a symlink; the census does not read through links"
        if not path.exists():
            return "absent", None
        if kind == "dir":
            if not path.is_dir():
                return "nonregular", "path is not a directory"
        else:
            if not path.is_file():
                return "nonregular", "path is not a regular file"
    except OSError as e:
        return "nonregular", str(e)
    return "regular", None


# --- Ledger checks ------------------------------------------------------------

def _validate_record(obj: object) -> list[str]:
    """Schema-check a parsed decision record; return the list of problems
    (empty = valid). Mirrors the eight-field shape of the steering-ledger
    record, including the closed-set rule (exactly the eight fields)."""
    if not isinstance(obj, dict):
        return ["record is not a JSON object"]
    problems: list[str] = []
    missing = [f for f in REQUIRED_LEDGER_FIELDS if f not in obj]
    if missing:
        problems.append("missing field(s): " + ", ".join(missing))
    extra = [k for k in obj if k not in REQUIRED_LEDGER_FIELDS and k != "source"]
    if extra:
        problems.append("unknown field(s): " + ", ".join(sorted(extra)))
    if "source" in obj:
        src = obj["source"]
        if src is not None:
            if not isinstance(src, dict):
                problems.append("source must be null or an object with issue_number and comment_id")
            else:
                if not isinstance(src.get("issue_number"), int) or isinstance(src.get("issue_number"), bool):
                    problems.append("source.issue_number must be an integer")
                if not isinstance(src.get("comment_id"), int) or isinstance(src.get("comment_id"), bool):
                    problems.append("source.comment_id must be an integer")
                src_extra = [k for k in src if k not in ("issue_number", "comment_id")]
                if src_extra:
                    problems.append("source unknown field(s): " + ", ".join(sorted(src_extra)))
    date = obj.get("date")
    if isinstance(date, str):
        if not DATE_RE.match(date):
            problems.append("date is not a valid UTC ISO-8601 string")
        else:
            month, day = int(date[5:7]), int(date[8:10])
            hour, minute, second = int(date[11:13]), int(date[14:16]), int(date[17:19])
            if not 1 <= month <= 12:
                problems.append("date month out of range")
            if not 1 <= day <= 31:
                problems.append("date day out of range")
            if not 0 <= hour <= 23:
                problems.append("date hour out of range")
            if not 0 <= minute <= 59:
                problems.append("date minute out of range")
            if not 0 <= second <= 60:
                problems.append("date second out of range")
    elif "date" in obj:
        problems.append("date is not a string")
    questions = obj.get("questions")
    if "questions" in obj:
        if not isinstance(questions, list) or not 1 <= len(questions) <= 4:
            problems.append("questions must be an array of 1-4 entries")
        else:
            for q in questions:
                if not isinstance(q, dict):
                    problems.append("question entry is not an object")
                    continue
                if not ({"id", "text", "options"} <= set(q)):
                    problems.append("question missing id/text/options")
                options = q.get("options")
                if not isinstance(options, list) or not 2 <= len(options) <= 4:
                    problems.append("question options must be an array of 2-4 strings")
                elif not all(isinstance(o, str) for o in options):
                    problems.append("question options must be strings")
                if "answer" in q and q["answer"] is not None and not isinstance(q["answer"], str):
                    problems.append("question answer must be a string or null")
    status = obj.get("status")
    if "status" in obj and status not in ("decided", "open", "superseded"):
        problems.append("status not one of decided|open|superseded")
    for field in ("id", "by", "asked_by", "scope"):
        value = obj.get(field)
        if field in obj and (not isinstance(value, str) or not value):
            problems.append(f"{field} must be a non-empty string")
    sup = obj.get("supersedes")
    if "supersedes" in obj and sup is not None and (not isinstance(sup, str) or not sup):
        problems.append("supersedes must be null or a non-empty string")
    return problems


@dataclass(frozen=True)
class LedgerProbe:
    """The ledger path's classification, answered once by `_ledger_probe`.

    ``state`` is a key of LEDGER_EMPTY_MESSAGES; ``problem`` is the OSError
    text when a filesystem fault forced that state, or None when the state is
    what the tree actually is. Carrying both keeps the probe honest (an I/O
    error is never reported as a symlink that is not there) and lets
    `_check_ledger` hand one answer to every reporter instead of letting each
    re-classify the same path and drift.
    """

    state: str
    problem: str | None = None


def _check_ledger(ledger: Path, git: Git | None, root: Path, findings: list[dict],
                  strict: bool) -> None:
    """Check the steering ledger; append findings (each a partial finding row).

    Composition only: the ledger-empty probe, then record I/O + schema
    validation, the edited check (git-backed), the deleted check (git-backed)
    and the supersede-chain check, in that order. The git-backed integrity
    checks run whatever the empty probe found — see the deleted-sole-record
    regression tests in tests/test_census_unified.py."""
    probe = _ledger_probe(ledger)
    _check_ledger_empty(probe, ledger, root, findings, strict)
    valid, unparseable = _check_ledger_records(ledger, root, findings, probe.state)
    _check_ledger_edited(valid, unparseable, git, root, findings)
    _check_ledger_deleted(ledger, git, root, findings, strict)
    _check_ledger_chain(valid, ledger, root, findings)


def _ledger_probe(ledger: Path) -> LedgerProbe:
    """Classify ``ledger`` once; see LedgerProbe for the fields.

    One `_file_kind` classification per path — the ledger itself and its parent
    (``noni/``) — mapped to a state word, so the vocabulary is derived once and
    never disagrees with the other readers of the same filesystem facts:
    "symlink" — either level is a symlink (refused, never followed; a link is
    never read through even when its target holds records); "not a directory"
    — ``noni/`` exists but is not a directory, so no ledger can live under it
    (or the ledger entry itself is not a directory); "absent" — there is no
    noni/ at all (which is what "no noni/" means for the ledger checks) or no
    ledger entry under it; "empty" — a real ledger directory holding no
    ``*.json`` record; "ok" — a ledger with at least one record (the silent
    state, reported by no class).

    The child is classified before the parent: ``noni`` committed as a plain
    file must read as "not a directory", not "absent".
    """
    kind, problem = _file_kind(ledger, kind="dir")
    if kind == "symlink":
        return LedgerProbe("symlink")
    parent_kind, parent_problem = _file_kind(ledger.parent, kind="dir")
    if parent_kind == "symlink":
        return LedgerProbe("symlink")
    if parent_kind == "nonregular":
        # noni/ exists but is not a directory (a plain file, a fifo), so no
        # ledger can live under it. A fault on the parent keeps its text; "no
        # noni/ at all" is "absent" below, the ledger being absent together
        # with its parent.
        return LedgerProbe("not a directory", parent_problem)
    # A filesystem fault keeps its OSError text (a genuine I/O fault must not
    # be reported under a state word that did not occur) and is rendered under
    # the closest documented state word, so the row's word always comes from
    # LEDGER_EMPTY_MESSAGES.
    if kind == "nonregular":
        return LedgerProbe("not a directory", problem)
    if parent_kind == "absent":
        return LedgerProbe("absent")
    if kind == "absent":
        return LedgerProbe("absent")
    try:
        records = list(ledger.glob("*.json"))
    except OSError as e:
        # A directory that exists and stats fine but cannot be listed (a mount
        # or permission fault on readdir) is not an empty ledger.
        return LedgerProbe("not a directory", str(e))
    return LedgerProbe("empty" if not records else "ok")


def _check_ledger_empty(probe: LedgerProbe, ledger: Path, root: Path, findings: list[dict],
                        strict: bool) -> None:
    """The ledger-empty class: exactly one warn row when the ledger holds none.

    A pure reporter: it appends its row and returns. The git-backed integrity
    checks are not gated on the outcome — a ledger that reads as empty today
    may have been emptied by a deletion, and that deletion is reported by
    `_check_ledger_deleted` regardless. The four states of
    LEDGER_EMPTY_MESSAGES (other than the silent "ok") each produce exactly one
    row carrying their own state word, so "no ledger at all" reads as a
    reported warning rather than a silent clean (the state word IS the
    finding: a census that stays quiet here cannot tell "nothing to census"
    apart from "the ledger went missing").

    This class is warn-severity: a run that has only this finding exits 0,
    and --strict promotes it to exit 42. Symlinks are reported, never read
    through (the probe-honesty rule).
    """
    detail = LEDGER_EMPTY_MESSAGES[probe.state]
    if detail is None:
        return
    if probe.problem:
        detail = f"{detail} (probe error: {probe.problem})"
    artifact = _rel_to_root(root, ledger)
    findings.append(
        _row("ledger-empty", strict, artifact, artifact,
             f"ledger-empty ({probe.state}): {detail}", root)
    )


def _check_ledger_records(ledger: Path, root: Path, findings: list[dict],
                          state: str) -> tuple[list[tuple[str, Path, dict]], list[tuple[str, Path]]]:
    """I/O + schema validation. Returns (valid, unparseable) where each entry
    of unparseable is (name, path) of a file that exists on disk but failed
    parsing — it still gets the git edited check.

    ``state`` is the ledger path's state word as answered by `_ledger_state`
    (via `_check_ledger`): this pass only reads records, so any other state is
    ledger-empty's finding and adds no row here."""
    def add(check: str, subject: str, artifact: str, message: str) -> None:
        findings.append(_row(check, False, subject, artifact, message, root))

    if state != "ok":
        # ledger-empty owns every unusable ledger state (absent, empty, not a
        # directory, symlink, and any probe fault folded into one of them) as a
        # warn that names the state; this pass keeps only the malformed-record
        # failures, so an unusable ledger adds no ledger-record row here.
        return [], []

    names = sorted(p.name for p in ledger.glob("*.json"))
    valid: list[tuple[str, Path, dict]] = []
    unparseable: list[tuple[str, Path]] = []
    for name in names:
        path = ledger / name
        if not NAME_RE.match(name):
            add("ledger-record", name, str(path), "filename is not a plain <name>.json path segment")
            continue
        fkind, fproblem = _file_kind(path)
        if fkind != "regular":
            add("ledger-record", name, str(path), f"record is unreadable: {fproblem}")
            continue
        try:
            raw = path.read_bytes()
            body = raw.decode("utf-8")
        except UnicodeDecodeError:
            # The exception message embeds the offending bytes, which are
            # untrusted record content (a record that contains raw NULs or
            # other control bytes would smuggle them into stderr); the fixed
            # wording below names the class without echoing the bytes.
            add("ledger-record", name, str(path), "record is not valid UTF-8")
            unparseable.append((name, path))
            continue
        except OSError as e:
            add("ledger-record", name, str(path), f"record is unreadable: {e}")
            unparseable.append((name, path))
            continue
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            add("ledger-record", name, str(path), "record is not valid JSON")
            unparseable.append((name, path))
            continue
        problems = _validate_record(obj)
        if problems:
            add("ledger-record", obj.get("id", name) if isinstance(obj, dict) else name, str(path), "; ".join(problems))
            continue
        valid.append((obj["id"], path, obj))

    return valid, unparseable


def _check_ledger_edited(
    valid: list[tuple[str, Path, dict]],
    unparseable: list[tuple[str, Path]],
    git: Git | None,
    root: Path,
    findings: list[dict],
) -> None:
    """The post-commit edit check (git vs disk bytes).

    Runs for every valid record AND every record that failed parsing: a
    parse-time rejection must not silence the integrity check. The newest
    commit per path is a dict lookup over the git log already parsed at
    construction time (not a second `git log` subprocess), and the disk sha
    is one in-memory hash per file. A record whose committed bytes are
    unreachable degrades to a cannot-verify warning (probe honesty), never a
    silent pass."""
    # ledger-edited is a fail class: its rows are failures with or without
    # --strict, so no run-mode flag is needed to build them.
    def add(check: str, subject: str, artifact: str, message: str) -> None:
        findings.append(_row(check, False, subject, artifact, message, root))

    if git is None:
        return
    entries: list[tuple[str, str, Path]] = []
    for rid, path, _obj in valid:
        entries.append((rid, rid, path))
    for name, path in unparseable:
        entries.append((name, name, path))
    if not entries:
        return
    rels = [_rel_to(git.top, p) for _s, _rid, p in entries]
    for idx, (_subject, rid, path) in enumerate(entries):
        rel = rels[idx]
        entry = git.last_commit(rel) if rel is not None else None
        if entry is None:
            continue  # never committed: nothing to compare against
        blob = git.blob_content_sha1(entry[1], rel)
        disk = _repo_sha1(path)
        if blob is None:
            add("ledger-edited", rid, str(path),
                "cannot verify: committed blob is unreachable in this tree (shallow or pruned history)")
        elif disk is not None and blob != disk:
            add("ledger-edited", rid, str(path), "record was edited after commit (working tree differs from git)")


def _append_cannot_tell(check: str, reason: str, strict: bool, findings: list[dict]) -> None:
    """Append the cannot-tell row of a check whose question this run cannot
    answer. One row saying so is the probe-honesty rule: a check that fell
    silent would read as a clean run of a check that never ran.

    Cannot-tell severity is derived, never inherited from the class: a fail
    class's cannot-tell is a warn by default (an environment that cannot be
    read is not itself a protocol violation) and --strict escalates it, while a
    warn class keeps its own default — which is why session-deleted's
    cannot-tell exits 44 under --strict and ledger-edited's exits 41.
    """
    base = CLASS_SEVERITY[check]
    severity = "warn" if base == "fail" else base
    findings.append({
        "check": check,
        "code": CLASS_CODE[check],
        "severity": "fail" if strict else severity,
        "subject": "cannot-tell",
        "artifact": check,
        "message": f"cannot-tell: {reason}",
    })


def _check_ledger_deleted(ledger: Path, git: Git | None, root: Path, findings: list[dict],
                          strict: bool) -> None:
    """The deleted-record check (append-only ledger rule).

    Decision records are append-only: a record is superseded by a new record,
    never removed. A record that HEAD-reachable git history shows was added
    but is absent from the working tree — deleted or renamed — is reported
    here, whether the change is uncommitted or itself committed. A record that
    was only ever added on an unmerged branch (never reachable from HEAD) is
    not a deletion — it is not part of this branch's history. It is a
    sub-reason ("deleted")
    of the ledger-edited class (exit 12): both are violations of the same
    "never change committed record state" rule. A path that was never
    committed is not a deletion — it is a missing record, covered by
    ledger-record. Session files are intentionally NOT checked here: ending a
    session via its status field is the protocol, and deleting a session file
    is not a violation."""
    if git is None or not git.available or git.top is None:
        # Nothing to compare against: no commits, or no git tree at all. A
        # ledger that never existed cannot have had a record deleted from it,
        # and ledger-empty owns the "no ledger to arbitrate" states — so a
        # cannot-tell row here would only make "I ran no git" look like a
        # protocol finding.
        return
    top = git.top
    try:
        prefix = ledger.resolve().relative_to(top.resolve()).as_posix()
    except ValueError:
        # The append-only question cannot be answered for an --ledger override
        # that points outside the audited tree. Unlike the sessions layer, the
        # ledger group's cannot-tell is the only row this run produces about
        # the override, so it is reported — at the cannot-tell severity, not
        # the class's fail severity, because the same condition is a perfectly
        # normal state for a legitimate out-of-tree override.
        _append_cannot_tell(
            "ledger-edited",
            f"the ledger path ({_rel_to_root(root, ledger)}) is outside the audited git tree, "
            "so whether a committed record was deleted cannot be answered", strict, findings)
        return
    if ledger.is_dir() is False:
        return  # a missing ledger dir is ledger-record's business, not deletion
    for rel in sorted(git.added_paths_under(prefix)):
        if (top / rel).is_file():
            continue
        subject = rel.rsplit("/", 1)[-1]
        findings.append(
            _row("ledger-edited", False, subject, str(top / rel),
                 f"deleted: record {subject} is missing from the working tree because it was "
                 "deleted or renamed (in git history but absent now; the change is uncommitted "
                 "or committed); decision records are append-only: restore the original path "
                 "(git checkout <commit> -- <path>) and record any change as a new superseding "
                 "record instead of deleting or renaming", root)
        )


def _check_ledger_chain(
    valid: list[tuple[str, Path, dict]], ledger: Path, root: Path, findings: list[dict]
) -> None:
    """Supersede-chain analysis: dangling, duplicate, orphan, cycle, and the
    single-live-record-per-chain rule.

    Only records that parsed cleanly (valid) can contribute to chain
    analysis: an unparseable record's supersedes field is unreadable, so its
    chain state is genuinely unknowable."""
    # ledger-chain is a fail class: --strict does not change its severity.
    def add(check: str, subject: str, artifact: str, message: str) -> None:
        findings.append(_row(check, False, subject, artifact, message, root))

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


def _repo_sha1(path: Path) -> str | None:
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


# --- Session checks -------------------------------------------------------------

# scripts/public_safety.py lives at <repo-root>/scripts relative to this file
# (this file is skills/census/scripts/census.py — four levels below the repo
# root). The census loads it by path rather than importing it by name: scripts/
# is not a package, tests add their own sys.path entries, and a path load is
# what lets the census verify the file it is about to execute.
SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"


class PublicSafetyModule(Protocol):
    """The slice of scripts/public_safety.py the census depends on.

    The scanner is loaded dynamically, so this is the only checked description
    of the contract between the arbiter and the checker it runs: a signature
    drift on public_safety's side is a type error against this Protocol rather
    than an AttributeError at census time. ``_denylist_active`` is a private
    helper of that module; the census calls it because public_safety is a gate
    file whose surface this release may not widen, and `_trusted_public_safety`
    requires it at runtime precisely so the coupling is detected as a not-run
    row rather than an AttributeError.
    """

    def scrub_tracked_files(self, repo: Path) -> tuple[list[str], str | None, Any]: ...

    def _denylist_active(self, denylist: Any) -> bool: ...


# A census-owned registry key, never the shared "public_safety" name: the
# census is a read-only arbiter and must not replace a host application's
# module (or a second census instance's) while it runs its scan.
CENSUS_PS_MODULE_KEY = "noni_census_public_safety"


def _load_public_safety() -> PublicSafetyModule | None:
    """Import scripts/public_safety.py for the in-process hygiene scan.

    Returns None when the module cannot be imported (a stripped checkout that
    carries the skill without scripts/) or is not the file the census expects
    to find at SCRIPTS_DIR: the caller then reports that the scan did not run
    instead of reporting clean.

    The module is taken from the census's own ``sys.modules`` slot when that
    entry already points at this tree's ``SCRIPTS_DIR`` — the seams tests
    monkeypatch (``_default_denylist_file``, ``DENYLIST_ENV_VAR``) live on that
    one object, and a fresh load would silently run the scan past a patched
    deny-list. An entry from a different tree is not this census's checker, so
    the file is then loaded by path from ``SCRIPTS_DIR`` and re-verified before
    it is executed.
    """
    existing = sys.modules.get(CENSUS_PS_MODULE_KEY)
    if _trusted_public_safety(existing):
        return existing
    path = (SCRIPTS_DIR / "public_safety.py").resolve()
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(CENSUS_PS_MODULE_KEY, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    # Register under the census's own key before exec (the canonical importlib
    # recipe): a module body that imports itself would otherwise find no entry
    # in sys.modules. The shared "public_safety" name is never written.
    sys.modules[CENSUS_PS_MODULE_KEY] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        # The scan could not be loaded: the caller reports the scan as not run
        # (never a clean), and the half-built module must not stay registered.
        sys.modules.pop(CENSUS_PS_MODULE_KEY, None)
        return None
    # Executing a module is executing the tree's code: only keep it when it is
    # still the file we asked for and exposes the contract above.
    if not _trusted_public_safety(module):
        sys.modules.pop(CENSUS_PS_MODULE_KEY, None)
        return None
    return module


def _trusted_public_safety(module: object) -> bool:
    """True when ``module`` is the checker at SCRIPTS_DIR/public_safety.py and
    carries the members `_check_hygiene` calls. The resolved path is re-checked
    on every call, so a module registered under the census's key from elsewhere
    (or a sibling sys.path shadow) is not executed or trusted.

    The name "trusted" is scoped honestly: public_safety is a committed, editable
    file of the very tree being audited, so this is a *consistency* check (the
    census ran the checker it intends to report about, not a stale or foreign
    module), not a defence against a repository that rewrites its own gate. The
    gate that cannot be satisfied by editing the audited tree is
    `scripts/public_safety.py` run from a clean operator checkout before
    publishing — see skills/census/SKILL.md, "census exit 50 is not the
    public_safety gate".
    """
    if module is None:
        return False
    if Path(getattr(module, "__file__", "")).resolve() != (SCRIPTS_DIR / "public_safety.py").resolve():
        return False
    return all(callable(getattr(module, name, None))
               for name in ("scrub_tracked_files", "_denylist_active", "load_denylist"))


def _hygiene_labels(public_safety) -> set[str]:
    """The label set public_safety can emit, from its own pattern tables.

    Read from the live module rather than duplicated here: the census must not
    hard-code vocabulary that public_safety owns. All of its pattern tables are
    scanned (built-in, fixture home-path, and any other ``*_PATTERNS`` it
    exposes) plus the deny-list label, because the deny-list label is not in
    BUILTIN_PATTERNS — scrub_tracked_files appends it per entry. Tables are
    iterables of ``(pattern, label)`` tuples (the contract public_safety
    declares next to their annotations); anything else contributes no label.
    The census never crashes on a table it cannot walk: the whole walk is
    defensive, so a table whose iteration protocol raises contributes nothing
    and the caller falls back to verbatim rows instead of a traceback that
    would discard every finding this run already collected.

    Compute this once per scan and pass the set to `_split_violation`: it is
    invariant for the whole run, and walking ``vars()`` per violation row buys
    nothing.
    """
    labels: set[str] = {"deny-list entry"}
    try:
        # One guard for the whole walk: the tables are public_safety's data and
        # no shape of them may take the census down.
        items = list(vars(public_safety).items())
    except Exception:
        return labels
    for attr, value in items:
        if not attr.endswith("_PATTERNS"):
            continue
        try:
            if not isinstance(value, collections.abc.Iterable):
                continue
            entries = list(value)
        except Exception:
            # A truthy non-iterable, or a table whose __iter__ / __len__ /
            # __bool__ raises: it contributes no labels.
            continue
        for entry in entries:
            try:
                _pattern, label = entry
            except (TypeError, ValueError):
                continue
            if isinstance(label, str):
                labels.add(label)
    return labels


def _split_violation(violation: str, labels: set[str]) -> tuple[str, int, str] | None:
    """Split a public_safety violation "<path>:<line>: <label>" into parts.

    Returns (path, line, label) or None when the string is not of that shape.

    Splitting cannot be done by counting colons: a tracked path may contain
    one ("x:y/p.txt" is a legal POSIX filename), so splitting at the first
    colon truncates the path and garbles the message — which also breaks the
    documented (artifact, check, subject) sort grouping, because artifact
    becomes the path prefix before the colon. The label is a fixed string from
    public_safety's own tables and contains no colon, so the tail is matched
    against the known label set exactly and everything before ":<line>: " is
    the path.
    """
    if not labels:
        return None
    for label in labels:
        suffix = f": {label}"
        if not violation.endswith(suffix):
            continue
        head = violation[: -len(suffix)]
        path, sep, line_no = head.rpartition(":")
        if sep and path and line_no.isdigit():
            return path, int(line_no), label
        return None
    return None


def _check_hygiene(top: Path | None, strict: bool, findings: list[dict]) -> None:
    """The public-repo hygiene class (warn 50): the tracked-file scan, run
    in-process (an import, never a subprocess) over the census's own git tree.

    Scope follows the git tree the census already reads (``top``), never the
    ``--ledger``/``--sessions`` overrides: the hygiene rule is about tracked
    files of a repository, which is what the other git-backed checks use too.

    The class always reports, a clean tree included: when the deny-list class
    is not active (absent, corrupt, or present with no entries) exactly one
    warn row says so, so a run that never checked operator names or external
    project names is never mistaken for a hygiene-clean one. Built-in
    violations (machine-local home paths, secret shapes, active deny-list
    entries) get one row each.

    A scan that cannot run (no git tree, or public_safety raising on a failing
    or hung ``git ls-files``) is probe honesty: one warn row naming the scan
    as not run, never a clean.

    The two families of row are told apart by ``subject``, not by prose:
    ``hygiene scan`` = the scan itself, ``deny-list`` = the deny-list half of
    the scan, anything else = ``path:line`` of a violating tracked file (whose
    artifact is that file, root-relative, while the first two name the checker
    from the skill directory — see SKILL.md, "The hygiene artifact
    namespace"). The deny-list read follows public_safety's own precedence, so
    this class reports the same verdict the operator's own
    ``scripts/public_safety.py`` gate gives.
    """
    def add(subject: str, artifact: str, message: str) -> None:
        # The artifact is already the string the row must carry: either the
        # violating file's path as public_safety reported it (already
        # tree-relative) or the checker's id in the skill-relative hygiene
        # namespace. It is never a path to be re-rooted into --repo.
        findings.append(_row("hygiene", strict, subject, artifact, message, Path(),
                             relative_artifact=False))

    scan_artifact = _rel_to_census(SCRIPTS_DIR / "public_safety.py")

    if top is None:
        add(
            "hygiene scan",
            scan_artifact,
            "hygiene scan did not run: --repo is not a git repository, so no tracked-file "
            "scan was possible — this run is not a hygiene-clean guarantee",
        )
        return

    public_safety = _load_public_safety()
    if public_safety is None:
        # The skill is installed on its own, without the repo's scripts/ dir:
        # name the path that was probed relative to this file, because a path
        # outside the audited tree has no root-relative form (and the census
        # never prints a machine-local absolute path).
        add(
            "hygiene scan",
            scan_artifact,
            "hygiene scan did not run: public_safety is not importable from the repo's "
            f"scripts directory ({_rel_to_census(SCRIPTS_DIR)}) — this run is not a "
            "hygiene-clean guarantee",
        )
        return

    # The deny-list is operator config, not tree content: the env-named file is
    # the authoritative route, and a deny-list sitting inside the audited tree
    # is not trusted to supply the vocabulary the publishing gate checks.
    # Without it the class reports itself inactive below rather than pretending
    # the operator-name half ran.
    with _pinned_hygiene_env():
        try:
            violations, _source, denylist = public_safety.scrub_tracked_files(top)
        except Exception as e:
            # "Report, never crash": any exception from the scan (a failing or
            # hung git ls-files, an unreadable deny-list store, a malformed
            # pattern table) becomes the not-run row, never a traceback that
            # discards every finding already collected in this run. A public
            # safety scan must not be able to take the whole census down.
            add(
                "hygiene scan",
                scan_artifact,
                _bounded(f"hygiene scan did not run: {e} — this run is not a "
                         "hygiene-clean guarantee"),
            )
            return

    labels = _hygiene_labels(public_safety)
    for violation in sorted(violations):
        parsed = _split_violation(violation, labels)
        if parsed is None:
            # Not the documented shape: report the violation verbatim rather
            # than mis-split it (probe honesty — a row that names the whole
            # finding beats a row that garbles it).
            add(violation, violation, f"public hygiene: {violation}")
            continue
        rel, line_no, label = parsed
        add(f"{rel}:{line_no}", rel,
            f"public hygiene: {rel}:{line_no}: {label}")

    if not public_safety._denylist_active(denylist):
        add(
            "deny-list",
            scan_artifact,
            f"deny-list class inactive ({_denylist_state(denylist)}): no deny-list "
            "entry was checked, so operator names, external project/tool names and hostnames "
            "are NOT covered — this run is not a hygiene-clean guarantee",
        )


def _denylist_state(denylist: Any) -> str:
    """Render the deny-list's inactive state word from its result.

    public_safety owns the statuses; this only maps them to a word. The mapping
    is three lines of the census's own reporting — `status` for a file that is
    absent or unreadable, and the comments-only case that loaded "ok" with no
    entries. A status public_safety adds later surfaces under its own name here
    rather than being silently mislabelled. The caller has already established
    the class is inactive, so "ok" with entries cannot reach this function.
    """
    status = getattr(denylist, "status", "absent")
    if status != "ok":
        return str(status)
    return "present but empty" if not getattr(denylist, "entries", []) else "ok"


# The git environment every census git call runs under. The census reads a
# repository someone else may have prepared, with its own privileges, so the
# host's git config must not be able to redirect those read-only calls:
# core.hooksPath and protocol.ext.allow are the two that turn a read into
# arbitrary execution, and an alternate object directory or a rewritten
# objects dir points the reads somewhere else entirely. GIT_CONFIG_GLOBAL /
# GIT_CONFIG_SYSTEM are pinned to the null device rather than merely removed,
# so a system config baked into the image cannot leak back in either.
#
# GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE and friends are deliberately NOT
# touched: clearing them would break the census's honest answer for a git
# worktree, where the tree's .git file is a pointer and the ambient (or
# per-invocation) git environment is what makes `git -C <worktree>` resolve at
# all — and worktree-based callers are exactly who runs the census. A hostile
# GIT_DIR can only make the census read a *different* repository, which every
# class then reports about that tree; it cannot execute anything.
GIT_ENV_NEUTRAL = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _git_config_args() -> list[str]:
    """The -c overrides carried on every census git invocation.

    Passed on the command line rather than only through the environment:
    command-line config wins over every file, including one a hostile
    GIT_CONFIG_GLOBAL would still name if the environment were inherited
    unchanged by a library call that bypasses `_git_env`."""
    return [
        "-c", "protocol.ext.allow=never",
        "-c", "core.hooksPath=" + os.devnull,
    ]


def _git_env() -> dict[str, str]:
    """The environment for every census git call (see GIT_ENV_NEUTRAL)."""
    env = dict(os.environ)
    env.update(GIT_ENV_NEUTRAL)
    return env


@contextlib.contextmanager
def _pinned_hygiene_env():
    """Run the in-process scan with the git environment pinned.

    The census runs public_safety's read-only git calls with its own privileges
    and environment, so the operator's global/system config must not be able to
    redirect them (core.hooksPath, protocol.ext.allow, an alternate object
    store) and no ambient GIT_DIR / GIT_WORK_TREE may move them off the tree
    being audited.

    The deny-list is deliberately NOT pinned here: public_safety's own
    precedence governs (see scripts/public_safety.py, "Deny-list sources"), so
    the census reports the same deny-list verdict the operator's own
    ``scripts/public_safety.py`` gate would — an untracked deny-list left next
    to the checker, or named by NONI_SCRUB_DENYLIST, is the vocabulary the
    publish-before-push rule expects there. One owner for that rule.
    """
    saved = {k: os.environ.get(k) for k in GIT_ENV_NEUTRAL}
    os.environ.update(GIT_ENV_NEUTRAL)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _bounded(message: str, limit: int = 300) -> str:
    """Bound an exception-derived message and strip machine-local absolute
    paths from it: a row built from someone else's error text must not smuggle
    a host path into a report that promises not to print one."""
    collapsed = " ".join(message.split())
    collapsed = re.sub(r"(?:/[A-Za-z0-9._-]+)+", "<path>", collapsed)
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 3] + "..."
    return collapsed


def _parse_session(body: str) -> tuple[dict[str, str], list[str], list[str]]:
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
        if key in SESSION_REQUIRED_FIELDS:
            fields[key] = value
        elif key == "claim":
            if not value:
                problems.append("claim row with no task reference")
            else:
                claims.append(value)
    for field in SESSION_REQUIRED_FIELDS:
        if field not in fields:
            problems.append(f"missing field: {field}")
    return fields, claims, problems


def _check_sessions(
    sessions: Path, git: Git | None, root: Path, now: datetime, stale_after: timedelta,
    strict: bool, findings: list[dict]
) -> None:
    """Check the session register; append its findings to ``findings``.

    A missing sessions directory is a clean state (no sessions registered);
    an unreadable or non-directory path is a probe failure, never clean.
    Stalled sessions and probe failures are warnings by default and failures
    under --strict.
    """
    def add(check: str, subject: str, artifact: str, message: str) -> None:
        findings.append(_row(check, strict, subject, artifact, message, root))

    kind, problem = _file_kind(sessions, kind="dir")
    if kind == "absent":
        return
    if kind != "regular":
        add("probe", str(sessions), str(sessions), f"sessions path is not a readable directory: {problem}")
        return

    files = sorted(sessions.glob("*.md"))
    claim_map: dict[str, dict[str, list[str]]] = {}
    # One read + parse per register file; both the claim map and the
    # same-identity map below are built from these results, so a file is never
    # classified twice by two loops that could drift.
    by_files: dict[str, list[str]] = {}
    for path in files:
        name = path.name
        if not SESSION_NAME_RE.match(name):
            add("session-malformed", name, str(path), "filename is not the allocated <YYYY-MM-DD>-<6 hex>.md shape")
            continue
        fkind, fproblem = _file_kind(path)
        if fkind != "regular":
            add("probe", name, str(path), f"session file unreadable: {fproblem}")
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            add("session-malformed", name, str(path), f"file unreadable: {e}")
            continue
        fields, claims, problems = _parse_session(body)
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
        non_terminal = _is_non_terminal(fields)
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
                rel = _rel_to(git.top, path)
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

    _check_sessions_deleted(sessions, git, root, strict, findings)


def _check_sessions_deleted(
    sessions: Path, git: Git | None, root: Path, strict: bool, findings: list[dict]
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
        _append_cannot_tell(
            "session-deleted",
            f"the sessions path ({_rel_to_root(root, sessions)}) is outside the audited git "
            "tree, so whether a committed register file was deleted cannot be answered",
            strict, findings)
        return
    for rel in sorted(git.added_paths_under(prefix)):
        name = rel.rsplit("/", 1)[-1]
        if not SESSION_NAME_RE.match(name):
            continue
        if (top / rel).is_file():
            continue
        findings.append(
            _row("session-deleted", strict, name, str(top / rel),
                 f"deleted: session file {name} is in git history but missing from the "
                 "working tree; sessions end via their status field, never by deleting the "
                 "register file", root)
        )


def _is_non_terminal(fields: dict[str, str]) -> bool:
    """True when a parsed session file is still open: its status is none of
    INACTIVE_STATUSES. The one definition of "non-terminal" the register
    reports use (claims, staleness, same-identity)."""
    return fields.get("status", "").strip().lower() not in INACTIVE_STATUSES


# --- CLI -----------------------------------------------------------------------

def _warn_class_names() -> str:
    """The comma-separated ids of every warn class, derived from CHECKS — the
    --strict contract is written once, in the table, and appears here and in
    SKILL.md as a rendering of it rather than a fourth copy that can drift."""
    return ", ".join(name for name, (_code, sev, _fix) in CHECKS.items() if sev == "warn")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="census.py",
        description="The unified noni census: read-only checks over the steering "
        "ledger and the session register, with an honest exit code.",
    )
    parser.add_argument("--repo", default=".", help="the repository (or directory) to audit (default: current directory)")
    parser.add_argument("--ledger", default=None, help="ledger directory (default: <repo>/noni/decisions)")
    parser.add_argument("--sessions", default=None, help="sessions directory (default: <repo>/noni/sessions)")
    parser.add_argument("--now", default=None, metavar="ISO-8601", help="fixed timestamp for time-based checks (reproducible output)")
    parser.add_argument("--stale-after", default="7d", metavar="DAYS", help="staleness threshold for active sessions (default: 7 days)")
    parser.add_argument("--strict", action="store_true",
                        help=f"treat warn classes ({_warn_class_names()}) as failures")
    parser.add_argument("--json", action="store_true", dest="json_out", help="emit NDJSON records on stdout (noni.census/1)")
    parser.add_argument("--only", action="append", default=None, metavar="CHECK", help="run only the named check(s); repeatable")
    parser.add_argument("--skip", action="append", default=None, metavar="CHECK", help="skip the named check(s); repeatable")
    parser.add_argument("--list", action="store_true", dest="list_checks", help="print the check ids and exit")
    return parser


def _known_checks(only: list[str] | None, skip: list[str] | None) -> list[str] | tuple[str, str]:
    known = list(CLASS_CODE)
    bad_only = [c for c in (only or []) if c not in known]
    bad_skip = [c for c in (skip or []) if c not in known]
    if bad_only:
        return ("error", f"unknown check: {', '.join(sorted(bad_only))} (known: {', '.join(known)})")
    if bad_skip:
        return ("error", f"unknown check: {', '.join(sorted(bad_skip))} (known: {', '.join(known)})")
    excluded = set(skip or [])
    if only:
        return [c for c in known if c in set(only) - excluded]
    return [c for c in known if c not in excluded]


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(sys.argv[1:] if argv is None else argv)

    checks = _known_checks(args.only, args.skip)
    if isinstance(checks, tuple):
        print(checks[1], file=sys.stderr)
        return EXIT_USAGE

    if args.list_checks:
        for name in checks:
            print(name)
        return EXIT_CLEAN

    now, err = _parse_now(args.now)
    if err:
        print(err, file=sys.stderr)
        return EXIT_USAGE
    raw_days = args.stale_after
    if not STALE_AFTER_RE.fullmatch(raw_days):
        print(
            f"error: --stale-after {args.stale_after!r} must be positive whole days (e.g. 7 or 7d)",
            file=sys.stderr,
        )
        return EXIT_USAGE
    days = int(raw_days.rstrip("dD"))
    if days <= 0:
        print(
            f"error: --stale-after {args.stale_after!r} must be positive whole days (e.g. 7 or 7d)",
            file=sys.stderr,
        )
        return EXIT_USAGE
    stale_after = timedelta(days=days)

    if shutil.which("git") is None:
        print("census: git not found on the reading machine", file=sys.stderr)
        return EXIT_TOOL_MISSING

    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"error: repo path does not exist: {args.repo}", file=sys.stderr)
        return EXIT_USAGE
    ledger = Path(args.ledger) if args.ledger else root / "noni" / "decisions"
    sessions = Path(args.sessions) if args.sessions else root / "noni" / "sessions"
    ledger = Path(os.path.expanduser(str(ledger)))
    sessions = Path(os.path.expanduser(str(sessions)))

    top = _git_top(root)
    git = Git(top) if top is not None else None

    findings: list[dict] = []
    # One --only/--skip rule for all three groups: a group runs when any class
    # of its reporting set was asked for, and keeps only the rows of the
    # classes actually named. The ledger group is reported as a unit (the
    # empty-ledger probe owns states the record pass must not duplicate), so
    # the filter is applied to its rows rather than skipped; no group runs work
    # whose rows it will discard.
    requested = set(checks)
    if (LEDGER_CHECKS | {"ledger-empty"}) & requested:
        _check_ledger(ledger, git, root, findings, args.strict)
        findings[:] = [f for f in findings if f["check"] in requested]

    if SESSION_CHECKS & requested:
        _check_sessions(sessions, git, root, now, stale_after, args.strict, findings)
        findings[:] = [f for f in findings if f["check"] in requested]

    # hygiene is its own check group: it scans the tracked files of the census's
    # own git tree (never the --ledger/--sessions overrides).
    if "hygiene" in requested:
        _check_hygiene(top, args.strict, findings)

    # --- Aggregate -----------------------------------------------------------
    # Warnings never set the exit code on their own: clean means exit 0 even
    # with cannot-tell or probe warnings. A warning-class check can only lift
    # the exit when --strict promotes it to a failure.
    fired = {f["check"] for f in findings}
    fail_classes = {c for c in fired if next(f for f in findings if f["check"] == c)["severity"] == "fail"}
    exit_code = 0
    for c in sorted(fail_classes, key=lambda c: CLASS_CODE[c]):
        exit_code = CLASS_CODE[c]
        break

    counts = {c: 0 for c in CLASS_CODE}
    for f in findings:
        counts[f["check"]] += 1
    ok = exit_code == EXIT_CLEAN

    _render(findings, counts, ok, exit_code, args.json_out)
    return exit_code


# One shared sort key for every finding row, in both the --json (NDJSON) and
# human-readable branches: (artifact, check, subject). Both modes therefore
# emit the same findings in the same order.
def _finding_sort_key(f: dict) -> tuple[str, str, str]:
    """One shared sort key for every finding row, in both the --json (NDJSON)
    and human-readable branches: (artifact, check, subject)."""
    return (f["artifact"], f["check"], f["subject"])


def _render(
    findings: list[dict], counts: dict[str, int], ok: bool, exit_code: int, json_out: bool
) -> None:
    """Emit the results in either NDJSON (--json) or human-readable form."""
    if json_out:
        for f in sorted(findings, key=_finding_sort_key):
            row = {
                "schema": SCHEMA_VERSION,
                "kind": "finding",
                "check": f["check"],
                "code": f["code"],
                "severity": f["severity"],
                "subject": f["subject"],
                "artifact": f["artifact"],
                "message": f["message"],
                "fix": CLASS_FIX[f["check"]],
            }
            print(json.dumps(row, sort_keys=True))
        counts_row = {k: v for k, v in counts.items() if v}
        print(
            json.dumps(
                {"schema": SCHEMA_VERSION, "kind": "summary", "ok": ok, "exit": exit_code, "counts": counts_row},
                sort_keys=True,
            )
        )
    else:
        fired = {f["check"] for f in findings}
        if not findings:
            print("census: no findings; all checks passed")
        else:
            for f in sorted(findings, key=_finding_sort_key):
                tag = {"fail": "FAIL", "warn": "WARN"}.get(f["severity"], "?")
                print(f"{f['check']:<16} {tag:<4} {f['subject']}: {f['message']}")
                print(f"{'':<16} fix: {CLASS_FIX[f['check']]}")
        if ok:
            verdict_text = "clean"
        else:
            verdict_text = f"{exit_code} ({', '.join(sorted(fired))})"
        print(f"summary: {verdict_text}; {sum(counts.values())} finding(s); verdict {'ok' if ok else 'fail'}")
        if not ok:
            print(
                f"census: exit {exit_code}; the lowest class code wins — every check ran and "
                "every finding is reported above",
                file=sys.stderr,
            )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
