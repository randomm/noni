"""The unified census: one read-only entry point over the steering ledger and
the session register.

The census is the arbiter of the noni protocol invariants. It reads the git
history plus the committed files under ``noni/`` (decision records under
``noni/decisions/``, session registers under ``noni/sessions/``, and the
ordering artifact at ``noni/direction/order.json``), flags protocol
violations, and returns an honest exit code. It never writes
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
than falling silent and reading as a clean run. The same rule outranks the
``--only`` row filter: a group reports the rows that say *this run could not
read the file it was asked to check* (the artifact, its ``--issue-state``
input, or its ledger) whatever the filter names, because a run that observed
that fault and reported none would be reporting a clean it did not establish.
Rows about one entry inside a file are still dropped when their class is not
named — that is what ``--only`` is for. See ``_row`` and ``WHOLE_ARTIFACT_KEY``.

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
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import labels

SCHEMA_VERSION = "noni.census/1"

# The ledger checks run as one group: any of the three triggers all three, so
# --only/--skip must be applied at group granularity. ledger-empty (42) is
# reported by the same group and adds rows only in the states where no record
# can be read (including a recordless decisions/ directory, which is a warn,
# not the ledger-record failure — operator decision on issue #33); it never
# weakens a malformed-record failure.
LEDGER_CHECKS = frozenset({"ledger-record", "ledger-edited", "ledger-chain"})
# The session register group, likewise: the checks share one read of the
# register, so the group runs together and the row filter decides what is kept.
SESSION_CHECKS = frozenset({
    "session-double", "session-claim", "session-malformed", "session-stalled",
    "session-same-identity", "session-deleted", "probe",
})
WHOLE_ARTIFACT_KEY = "_whole_artifact"

# The ordering group: the three checks share one read of the order artifact, so
# the group runs when any of them was asked for and the row filter keeps what
# the caller named. The fourth row of the group, the `cannot-tell` a run adds
# when --issue-state did not answer an entry's state, is a row of
# `ordering-closed` rather than a class of its own — it answers the closed
# question, so it carries that class's code (46) and, like every cannot-tell row,
# a warn by default that --strict promotes (see _append_cannot_tell).
# A missing order file is not a finding: the ordering layer is optional, so this
# group adds no row at all when the artifact is absent. The code itself lives in
# census_ordering.py beside this file (see the loader under 'Ordering checks').
ORDERING_CHECKS = frozenset({"ordering-malformed", "ordering-stale", "ordering-closed"})

# One threshold flag, two thresholds: --stale-after pins both classes to the
# number the caller named, and without it each class gets the default that
# belongs to it (see the threshold block in main for why the flag's presence
# decides, and _threshold for how a default is parsed).
SESSION_STALE_AFTER_DEFAULT = "7d"
ORDERING_STALE_AFTER_DEFAULT = "30d"

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
    "ordering-malformed": (
        15, "fail",
        "repair noni/direction/order.json to the noni.order/1 shape (schema, a unique positive "
        "issue and a UTC confirmed stamp per entry, decision a live record id or null), or write "
        "it with skills/direction/scripts/order.py, which refuses the shapes this class reports",
    ),
    "ordering-stale": (
        45, "warn",
        "confirm the entry again (order.py confirm ISSUE, or confirm with no issue for the whole "
        "order); an entry nobody has confirmed since --stale-after is the operator's last word "
        "on the order only as far back as that",
    ),
    "ordering-closed": (
        46, "warn",
        "remove the closed issue from the order (order.py remove ISSUE), or reopen it; the order "
        "is what to work on next, so an issue the tracker has closed does not belong in it",
    ),
}

# Derived views of CHECKS — never edited by hand.
CLASS_CODE = {name: code for name, (code, _sev, _fix) in CHECKS.items()}
CLASS_SEVERITY = {name: sev for name, (_code, sev, _fix) in CHECKS.items()}
CLASS_FIX = {name: fix for name, (_code, _sev, fix) in CHECKS.items()}


def _promote(severity: str, strict: bool) -> str:
    """The run-mode half of severity: a warn row is a failure under --strict.
    The one place that rule lives — both derivations below call it, so there is
    no second copy to drift."""
    return "fail" if strict and severity == "warn" else severity


def _severity(check: str, strict: bool) -> str:
    """The severity a row of ``check`` carries in this run: warn classes become
    failures under --strict, fail classes are unaffected."""
    return _promote(CLASS_SEVERITY[check], strict)


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
# reports, each in exactly one row's message, plus the silent "ok". "empty"
# names a tree with no decision record to arbitrate: noni/ present without a
# decisions/ directory, or a decisions/ directory that holds no *.json record.
# The words and their wording are pinned by LEDGER_EMPTY_MESSAGES below and the
# tests iterate that table, so renaming a state without updating its wording
# (and tests/test_census_unified.py) is a contract change.
LEDGER_EMPTY_STATES = ("absent", "empty", "not a directory", "symlink", "ok")

# state word -> the detail the row carries, or None for the state that reports
# nothing. The keys ARE the state vocabulary: _ledger_probe returns one of
# them and _check_ledger_empty looks its message up here, so the contract has
# exactly one owner.
LEDGER_EMPTY_MESSAGES: dict[str, str | None] = {
    "absent": "no decision record is censusable: the ledger directory is absent "
    "(no noni/decisions under this repo — no steering ledger to arbitrate)",
    "empty": "the ledger holds no *.json record: either noni/ has no decisions/ "
    "directory, or that directory exists and holds none",
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
         root: Path, relative_artifact: bool = True, severity: str | None = None,
         whole_artifact: bool = False) -> dict:
    """Build one finding row: the only place a row's shape is written.

    ``code``/``fix`` come from CHECKS and ``severity`` from `_severity`, so a
    new row field (or a change to how those three are derived) is one edit
    here rather than five reporter-by-reporter copies. ``artifact`` is rooted
    into the audited tree by default; a reporter that names an artefact
    outside it passes ``relative_artifact=False`` and supplies its own id.

    ``severity`` overrides the class default for a single row. It exists for
    the probe-honesty case only — a row that reports *this run could not read
    its input* rather than a protocol violation, which is a warn regardless of
    its class. The override goes through `_promote`, so ``--strict`` still
    escalates it and that rule keeps its one owner. A reporter that passes
    ``severity`` must pass the run's ``strict``, not a literal.

    ``whole_artifact`` marks a row as about the file a group was asked to read
    rather than one entry inside it: the marker is ``WHOLE_ARTIFACT_KEY``,
    underscore-keyed so it is stripped at render, and the row filter of ``main``
    never drops such a row. See the module docstring and ``keep`` for the rule
    and why a filtered run must still report it.
    """
    severity = _promote(severity, strict) if severity else _severity(check, strict)
    return {
        "check": check,
        "code": CLASS_CODE[check],
        "severity": severity,
        "subject": subject,
        "artifact": _rel_to_root(root, Path(artifact)) if relative_artifact else artifact,
        "message": message,
        WHOLE_ARTIFACT_KEY: whole_artifact,
    }


def _file_kind(path: Path, kind: str = "file") -> tuple[str, str | None]:
    """Classify a file for the census: ("absent"|"regular"|"symlink"|"nonregular", problem).

    ``kind`` is "file" (default) or "dir". Only a regular, non-symlinked
    entry of the requested kind is readable. Symlinked or non-regular
    artefacts are reported as probe failures (never read through a link), and
    a missing entry is absent (a real state, not an oversight).

    The problem half is the text a row quotes when the classification itself
    faulted, so it comes from ``census_text.fault_text``: a stat that raises
    hands the census an ``OSError`` whose ``str()`` ends in the path it failed
    on, and no row may carry that path. Every other return of this function is a
    fixed sentence this file wrote.
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
        return "nonregular", _text.fault_text(e)
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


# The ledger probe (the state word for `noni/decisions/` and the one row a
# listing that faulted earns) lives in census_ledger.py beside this file, in the
# same shape as the hygiene and ordering splits: an ordinary package import, with
# the row mechanics it uses — the classifier, the row factory and the bound on
# foreign text — handed in at the call, so the row shape and the state vocabulary
# keep their one owner here. The module is loaded with the hygiene split below.
def _ledger_probe(ledger: Path) -> _ledger.LedgerProbe:
    """Classify ``ledger`` once through the ledger module's probe; see LedgerProbe.

    The seam the census's own tests patch (a listing that raises, a probe that
    answers a state the tree does not have), so it stays a name of this module
    rather than a direct call into `census_ledger`. The module itself is loaded
    by the loader under 'Ledger and hygiene splits' below.
    """
    return _ledger.probe_ledger(ledger, _file_kind)


def _check_ledger(ledger: Path, git: Git | None, root: Path, findings: list[dict],
                  strict: bool, probe: _ledger.LedgerProbe) -> None:
    """Check the steering ledger; append findings (each a partial finding row).

    ``probe`` is the run's one classification of ``ledger``, built by ``main``
    before it decided whether this group runs at all: a second probe would be a
    second read of the directory and a second chance to disagree with the first,
    so the group reports from the answer that got it here.

    The composition only: the ledger-empty probe, then record I/O + schema
    validation, the edited check (git-backed), the deleted check (git-backed)
    and the supersede-chain check, in that order. The record pass reads the
    probe's own names, so the group's read of the directory is the probe's
    single readdir (see ``LedgerProbe.names``). ledger-empty only ADDS rows:
    the states where the record pass has nothing to say. The git-backed
    integrity checks run whatever the empty probe found — see the
    deleted-sole-record regression tests in tests/test_census_unified.py.

    The two rows the composition adds itself, both probe honesty:

    * a listing that faulted gets one cannot-tell row of its own and stops the
      group there (`census_ledger.append_listing_fault`, called with this group's
      own ``ledger-edited`` class, noun and question): the probe read nothing, so
      no state word it answered is one this run established and no record pass
      can be trusted either;
    * when the deletion check could not put its question to git and the ledger
      reads as "empty", the run says so (probe honesty, issue #33). "Empty" is
      the only state that can mean "committed records were deleted", and this
      check is the only signal for that, so a silent one here would let a
      gutted ledger read as a plain no-ledger warning — the row is warn by
      default, fail under --strict."""
    if probe.listing_fault is not None:
        # The probe could not list the ledger, so no state word it answered is
        # one this run established: the empty class stays silent, the record
        # pass has nothing trustworthy to read, and the one row the group adds
        # says what the read could not do (`census_ledger.append_listing_fault`).
        _ledger.append_listing_fault(
            ledger, root, findings, strict, probe.listing_fault,
            check="ledger-edited", noun="the ledger directory",
            unknown="so whether a committed record was deleted or edited cannot be "
                    "answered",
            row=_row, rel_to_root=_rel_to_root, bounded=_bounded, clipped=_clipped)
        return
    _check_ledger_empty(probe, ledger, root, findings, strict)
    valid, unparseable = _check_ledger_records(ledger, root, findings, probe)
    _check_ledger_edited(valid, unparseable, git, root, findings, strict)
    could_not_answer = _check_ledger_deleted(ledger, git, root, findings, strict)
    if could_not_answer and probe.state == "empty":
        _append_cannot_tell(
            "ledger-edited",
            "the git-backed deletion check could not run on this empty ledger "
            "(no readable git history), so whether committed records were deleted "
            "from it cannot be answered", strict, findings)
    _check_ledger_chain(valid, ledger, root, findings)


def _check_ledger_empty(probe: _ledger.LedgerProbe, ledger: Path, root: Path,
                        findings: list[dict],
                        strict: bool) -> None:
    """The ledger-empty class: exactly one warn row when there is no ledger.

    A pure reporter: it appends its row and returns. The git-backed integrity
    checks are not gated on the outcome — a ledger that reads as empty today
    may have been emptied by a deletion, and that deletion is reported by
    `_check_ledger_deleted` regardless. The four states of
    LEDGER_EMPTY_MESSAGES (other than the silent "ok") each produce exactly one
    row carrying their own state word, so "no ledger at all" reads as a
    reported warning rather than a silent clean (the state word IS the
    finding: a census that stays quiet here cannot tell "nothing to census"
    apart from "the ledger went missing").

    The class only ADDS rows: it never weakens a failure the group already
    reports. The states it owns are exactly the ones where no record can be
    read: no ``noni/``, ``noni/`` not a directory, a symlink, or no record to
    census (``noni/`` with no ``decisions/``, or a ``decisions/`` directory
    holding no ``*.json`` record). Malformed records remain the ledger-record
    failure: only the absence of records is a warn.

    This class is warn-severity: a run that has only this finding exits 0,
    and --strict promotes it to exit 42. Symlinks are reported, never read
    through (the probe-honesty rule).
    """
    detail = LEDGER_EMPTY_MESSAGES[probe.state]
    if detail is None:
        return
    if probe.problem:
        # Foreign text from this tree, so it gets the bound-and-scrub the
        # listing-fault row applies to its fault text: a row built from someone
        # else's error must not smuggle a host path or run past the length every
        # other row keeps. The sentence around it is this census's own wording.
        detail = f"{detail} (probe error: {_bounded(probe.problem)})"
    artifact = _rel_to_root(root, ledger)
    findings.append(
        _row("ledger-empty", strict, artifact, artifact,
             f"ledger-empty ({probe.state}): {detail}", root)
    )


def _check_ledger_records(ledger: Path, root: Path, findings: list[dict],
                          probe: _ledger.LedgerProbe
                          ) -> tuple[list[tuple[str, Path, dict]], list[tuple[str, Path]]]:
    """I/O + schema validation. Returns (valid, unparseable) where each entry
    of unparseable is (name, path) of a file that exists on disk but failed
    parsing — it still gets the git edited check.

    ``probe`` is the run's one classification of ``ledger``, and this pass reads
    both of its answers and asks neither again: ``probe.state`` for whether a
    record pass is warranted at all, and ``probe.names`` for the records
    themselves. The names are the probe's because the probe's readdir is the
    only one this run performs — a second listing was a second read of a tree
    that can change under the run, and one that faulted after the probe's had
    succeeded raised out of ``main`` as a traceback rather than a row.

    ``state`` other than "ok" means this pass reads no records at all, so any
    state other than "ok" is ledger-empty's finding and adds no row here. "ok"
    means the directory holds at least one ``*.json`` name, so every row this
    pass adds is a malformed-record failure.
    """
    def add(check: str, subject: str, artifact: str, message: str) -> None:
        findings.append(_row(check, False, subject, artifact, message, root))

    if probe.state != "ok" or probe.names is None:
        # ledger-empty owns every no-ledger state (absent, not a directory,
        # symlink, and any probe fault folded into one of them) as a warn that
        # names the state; this pass keeps only the malformed-record failures,
        # so a ledger that is not there adds no ledger-record row here. The
        # ``names is None`` arm is belt and braces: no state of "ok" is ever
        # built without the names that produced it.
        return [], []

    names = sorted(probe.names)
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
            # The filename is the path of the record itself, which this row
            # already carries in ``artifact``: the fault contributes its class
            # and its errno words, nothing else.
            add("ledger-record", name, str(path),
                f"record is unreadable: {_text.fault_text(e)}")
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
    strict: bool,
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
        findings.append(_row(check, strict, subject, artifact, message, root,
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
                "cannot verify: committed blob is unreachable in this tree (shallow or pruned history)",
                cannot_verify=True)
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


def _check_ledger_deleted(ledger: Path, git: Git | None, root: Path, findings: list[dict],
                          strict: bool) -> bool:
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
        _append_cannot_tell(
            "ledger-edited",
            f"the ledger path ({_rel_to_root(root, ledger)}) is outside the audited git tree, "
            "so whether a committed record was deleted cannot be answered", strict, findings)
        return False
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
    return False


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


# --- Ledger, sessions-probe and hygiene splits ---------------------------------
# The ledger probe, the sessions register's probe and the hygiene class, with the
# checker hygiene imports, live in census_ledger.py, census_sessions_probe.py and
# census_hygiene.py beside this file. All are ordinary package imports: inside an
# installed wheel there is no sibling file to load by path, and the census's trust
# in its checker is module identity (see census_hygiene._trusted_public_safety),
# not a resolved filesystem path. The row mechanics each one uses are handed in
# at the call, so the row shape keeps its one owner here. The aliases are
# `_ledger`, `_sessions_probe` and so on in the house style of the sibling
# split-outs (`_helpers`, `_ordering`, `_ordering_readers`): the `_` prefix marks
# the module and the group's own Path argument, `ledger`, stays a name no alias
# takes.
from . import census_hygiene as _helpers  # noqa: E402
from . import census_ledger as _ledger  # noqa: E402
from . import census_text as _text  # noqa: E402

# The probe's type stays reachable as a member of this census, re-exported as the
# one object rather than a copy, so a caller (and the census's own tests) still
# names it through the module it already imports.
LedgerProbe = _ledger.LedgerProbe

# The sessions probe lives in census_sessions_probe.py beside this file, with the
# same split census_ledger made: the module owns the register's one readdir and
# the one row a faulted listing earns, and the row mechanics it uses are handed
# in at the call so the row shape keeps its one owner here. The census's
# `_sessions_listing` below is the sibling's `sessions_listing` one call site, so
# the run's gate and its rows are the answer of one readdir.
from . import census_sessions_probe as _sessions_probe  # noqa: E402

# Re-exported as the one object, not a copy, so a caller (and the census's own
# tests) still names the probe's type through the module it already imports.
SessionsProbe = _sessions_probe.SessionsProbe


def _sessions_listing(sessions: Path) -> SessionsProbe:
    """The register's one listing, taken by the census exactly once per run.

    The census's own `_ledger_probe` twin: the body is the sibling's, this is the
    seam the census's tests patch and the one place `main` asks for the register.
    """
    return _sessions_probe.sessions_listing(sessions)


def _append_sessions_listing_fault(
    sessions: Path, root: Path, strict: bool, findings: list[dict], fault: str
) -> None:
    """The register's one faulted-listing row, composed in ``census_sessions_probe``.

    The row mechanics are the census's own and are handed in at the call, so the
    row shape keeps its single owner here (see the sibling's docstring for the
    row itself and ``census_ledger.append_listing_fault`` for its composition).
    """
    _sessions_probe.append_sessions_listing_fault(
        sessions, root, strict, findings, fault,
        row=_row, rel_to_root=_rel_to_root, bounded=_bounded, clipped=_clipped)


# The hygiene class's own parts stay reachable as members of the census: they are
# re-exports of one object, not copies, so the census keeps its single owner of
# the checker and its loader while a caller (and the census's own tests) still
# names them through the module it already imports.
PublicSafetyModule = _helpers.PublicSafetyModule
CENSUS_PS_MODULE_KEY = _helpers.CENSUS_PS_MODULE_KEY
HYGIENE_SCAN_ARTIFACT = _helpers.HYGIENE_SCAN_ARTIFACT
_load_public_safety = _helpers._load_public_safety
_trusted_public_safety = _helpers._trusted_public_safety
_hygiene_labels = _helpers._hygiene_labels
_split_violation = _helpers._split_violation
# The message scrub's own parts stay reachable as members of the census for the
# same reason: one object, not a copy, so the text rules keep their single owner
# in ``census_text`` while a caller (and the census's own tests) still names them
# through the module it already imports.
_bounded = _text._bounded
_stripped = _text._stripped
_clipped = _text._clipped
# The census's own git calls and public_safety's in-process scan share one
# pinned environment, so the table of variables to pin has one owner: here.
GIT_ENV_NEUTRAL = _helpers.GIT_ENV_NEUTRAL


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


# --- Session checks -------------------------------------------------------------
# The register's classes live in census_sessions_checks.py beside this file, the
# way the ledger's live in census_ledger.py and the ordering's in
# census_ordering.py: this file keeps the CLI, the exit-code table, the row shape
# and the group wiring, and the sibling keeps the per-file loop of the register
# and the verdicts built from it. Its register constants (SESSION_NAME_RE and the
# two tables beside it above) stay declared here, the file that owns the check
# contract, and the sibling reads them through this module rather than copying
# them, so a compiled pattern has one definition. The row mechanics are handed in
# at the call, exactly as the ordering group's are, so no second file composes a
# row.
from . import census_sessions_checks as _sessions_checks  # noqa: E402


def _parse_session(body: str) -> tuple[dict[str, str], list[str], list[str]]:
    """The register body parse, composed in ``census_sessions_checks``.

    Re-exported as the one function, not a copy, so a caller (and the census's
    own tests) still names it through the module it already imports.
    """
    return _sessions_checks.parse_session(body)


def _is_non_terminal(fields: dict[str, str]) -> bool:
    """The register's one "still open" test, composed in ``census_sessions_checks``
    and re-exported as the one function for the same reason as `_parse_session`."""
    return _sessions_checks.is_non_terminal(fields)


def _check_sessions(
    sessions: Path, git: Git | None, root: Path, now: datetime, stale_after: timedelta,
    strict: bool, findings: list[dict], probe: SessionsProbe
) -> None:
    """The session group, run by the module beside this file.

    The row factory, the classifier a probe row is built from, the root-relative
    identifier, the faulted-listing row and the deletion check are passed in
    rather than imported, so the row shape, its visibility marker and the
    machine-local-path rule stay written in exactly one place: this file (see the
    sibling's docstring for the group's own rules).
    """
    _sessions_checks.check_sessions(
        sessions, git, root, now, stale_after, strict, findings, probe,
        row=_row, file_kind=_file_kind, rel_to=_rel_to,
        append_listing_fault=_append_sessions_listing_fault,
        check_sessions_deleted=_check_sessions_deleted)


def _check_sessions_deleted(
    sessions: Path, git: Git | None, root: Path, strict: bool, findings: list[dict]
) -> None:
    """The deleted-session-file check, composed in ``census_sessions_checks``.

    The row factory, the root-relative identifier and the cannot-tell row are the
    census's own and are handed in at the call, so the row shape and the
    cannot-tell severity rule keep their single owner here.
    """
    _sessions_checks.check_sessions_deleted(
        sessions, git, root, strict, findings,
        row=_row, rel_to_root=_rel_to_root, append_cannot_tell=_append_cannot_tell)


# --- Ordering checks -----------------------------------------------------------
# The three ordering classes live in census_ordering.py beside this file, their
# reads in census_ordering_readers.py (which obeys the strict JSON rule of
# census_json.py). All three are package imports: inside the wheel there is no
# sibling file to load by path, and no directory of the package ever goes on
# sys.path, so a lookalike earlier on the path still cannot be trusted as the
# census's own code. The strict reader and the row mechanics are handed to the
# group at the call, so each group's code stays its own size and this file keeps
# one owner of the row shape.
from . import census_json as _census_json  # noqa: E402
from . import census_ordering as _ordering  # noqa: E402
from . import census_ordering_readers as _ordering_readers  # noqa: E402


def _check_ordering(
    order: Path, ledger: Path, root: Path, now: datetime, ordering_stale_after: timedelta,
    issue_state: _ordering_readers.IssueState, strict: bool, findings: list[dict],
    names: tuple[str, ...] | None,
) -> None:
    """The ordering group, run by the module beside this file.

    The row factory, the two helpers a row is built from and the readers module
    are passed in rather than imported, so the row shape, its visibility marker
    and the machine-local-path rule stay written in exactly one place: this file.

    ``names`` is the run's one ledger listing, the probe's, handed down for the
    group's record lookups: the ordering group reads the ledger the census
    already read and never walks the directory again (see
    ``LedgerProbe.names``).
    """
    _ordering.check_ordering(order, ledger, root, now, ordering_stale_after, issue_state,
                            strict, findings, row=_row, rel_to_root=_rel_to_root,
                            file_kind=_file_kind, bounded=_bounded, parse_iso=_parse_iso,
                            clipped=_clipped, names=names,
                            readers=_ordering_readers,
                            load_json_strict=_census_json.load_json_strict,
                            names_zone=_ordering_readers.names_zone,
                            ledger_name=_ledger.ledger_name)


# --- CLI -----------------------------------------------------------------------

def _threshold(raw: str) -> timedelta:
    """The timedelta a `--stale-after`-shaped value names.

    The module's own defaults go through the same parse the flag's value does,
    so a default that stopped parsing would fail here rather than at the one
    caller that uses it. Both defaults are written in this file, so a bad value
    here is a bug, never hostile input; the ValueError is the assertion.
    """
    if not STALE_AFTER_RE.fullmatch(raw):
        raise AssertionError(f"census default {raw!r} is not a stale-after threshold")
    return timedelta(days=int(raw.rstrip("dD")))


def _warn_class_names() -> str:
    """The comma-separated ids of every warn class, derived from CHECKS — the
    --strict contract is written once, in the table, and appears here and in
    SKILL.md as a rendering of it rather than a fourth copy that can drift."""
    return ", ".join(name for name, (_code, sev, _fix) in CHECKS.items() if sev == "warn")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=labels.CENSUS,
        description="The unified noni census: read-only checks over the steering "
        "ledger, the session register and the ordering artifact, with an honest "
        "exit code.",
    )
    parser.add_argument("--repo", default=".", help="the repository (or directory) to audit (default: current directory)")
    parser.add_argument("--ledger", default=None, help="ledger directory (default: <repo>/noni/decisions)")
    parser.add_argument("--sessions", default=None, help="sessions directory (default: <repo>/noni/sessions)")
    parser.add_argument("--ordering", default=None,
                        help="ordering artifact (default: "
                             "<repo>/noni/direction/order.json)")
    parser.add_argument("--issue-state", default=None, metavar="FILE",
                        help='JSON map {"<issue>": "open"|"closed"} produced by an adapter '
                             "or the operator; without it the ordering-closed check is not "
                             "evaluated (the census never contacts a tracker)")
    parser.add_argument("--now", default=None, metavar="ISO-8601", help="fixed timestamp for time-based checks (reproducible output)")
    parser.add_argument("--stale-after", default=SESSION_STALE_AFTER_DEFAULT, metavar="DAYS",
                        help=f"staleness threshold in positive whole days as `<N>` or `<N>d` "
                             f"(e.g. `7` or `7d`); default {SESSION_STALE_AFTER_DEFAULT} for active "
                             f"sessions and {ORDERING_STALE_AFTER_DEFAULT} for order entries, or this "
                             "value for both when given")
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
    # The two thresholds this run applies. --stale-after was given: both classes
    # use the number the caller named, which is what keeps a census run
    # reproducible from its command line alone. It was not: each class gets the
    # default that belongs to it, and the run records which one it used in the
    # row's own wording (the stale row names the threshold it compared against).
    # The flag's *presence* decides, not its value: an argparse default cannot
    # tell a caller who typed the number from one who did not, and treating the
    # literal `7d` as absent would quietly run the ordering check at 30 days on
    # a command line that promises 7. The sessions group keeps the one default
    # the flag has always carried, and the ordering group gets its own when the
    # flag was not used.
    supplied = [a for a in (sys.argv[1:] if argv is None else argv)
                if a == "--stale-after" or a.startswith("--stale-after=")]
    ordering_stale_after = (stale_after if supplied
                            else _threshold(ORDERING_STALE_AFTER_DEFAULT))

    if shutil.which("git") is None:
        print("census: git not found on the reading machine", file=sys.stderr)
        return EXIT_TOOL_MISSING

    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"error: repo path does not exist: {args.repo}", file=sys.stderr)
        return EXIT_USAGE
    ledger = Path(args.ledger) if args.ledger else root / "noni" / "decisions"
    sessions = Path(args.sessions) if args.sessions else root / "noni" / "sessions"
    ordering = (Path(args.ordering) if args.ordering
                else root / "noni" / "direction" / "order.json")
    issue_state_path = Path(args.issue_state) if args.issue_state else None
    ledger = Path(os.path.expanduser(str(ledger)))
    sessions = Path(os.path.expanduser(str(sessions)))
    ordering = Path(os.path.expanduser(str(ordering)))
    if issue_state_path is not None:
        issue_state_path = Path(os.path.expanduser(str(issue_state_path)))

    top = _git_top(root)
    git = Git(top) if top is not None else None

    findings: list[dict] = []
    # One --only/--skip rule for all four groups: a group runs when any class
    # of its reporting set was asked for, and keeps only the rows of the
    # classes actually named. The ledger group is reported as a unit (the
    # empty-ledger probe owns states the record pass must not duplicate), so
    # the filter is applied to its rows rather than skipped; no group runs work
    # whose rows it will discard.
    requested = set(checks)

    def keep(group_findings: list[dict]) -> list[dict]:
        """The rows of one group the run reports: those of a class the caller
        named, plus every row marked ``WHOLE_ARTIFACT_KEY`` — a row about the
        file a group was asked to read, not one entry inside it.

        The first half is the --only contract. The second is the probe-honesty
        rule: a group that could not read its input must say so even under a
        filter that named none of its classes, or a run that observed a fault
        would report the same clean verdict as a run that found none.
        """
        return [f for f in group_findings
                if f["check"] in requested or f.get(WHOLE_ARTIFACT_KEY)]

    # The ledger is classified once per run, here, before the group is gated on
    # the answer: `main` reads `listing_fault` off this one probe to decide
    # whether the group runs at all, and the same probe goes into
    # `_check_ledger` for the rows.
    ledger_probe = _ledger_probe(ledger)

    if (LEDGER_CHECKS | {"ledger-empty"}) & requested or ledger_probe.listing_fault:
        # The group runs whenever one of its classes was asked for, and also
        # whenever the probe could not list the ledger: that row is the
        # probe-honesty one `keep` never drops, so a run whose filter named no
        # ledger class must still reach the read that faulted rather than
        # report the clean verdict of a group that never ran.
        _check_ledger(ledger, git, root, findings, args.strict, ledger_probe)
        findings[:] = keep(findings)

    # One readdir of the register per run, taken here before the group is gated
    # on its answer, so the gate and the rows are the same read. It is
    # unconditional, and so costs one readdir plus its sort even on a run whose
    # filter named no session class: a register the run could not list must be
    # reportable whatever the filter asked for, and one read is what keeps the
    # gate and the rows from disagreeing about whether that read happened.
    sessions_probe = _sessions_listing(sessions)

    # The same field, tested the same way as `_check_sessions` tests it, so the
    # gate cannot open a group whose reporter would say nothing, nor leave a
    # faulted read unreported.
    if (SESSION_CHECKS & requested) or sessions_probe.fault is not None:
        _check_sessions(sessions, git, root, now, stale_after, args.strict, findings,
                        sessions_probe)
        findings[:] = keep(findings)

    if ORDERING_CHECKS & requested:
        _check_ordering(ordering, ledger, root, now, ordering_stale_after,
                        _ordering_readers.load_issue_state(
                            issue_state_path, _ordering.ISSUE_STATE_STATES,
                            _file_kind, _bounded, _census_json.load_json_strict),
                        args.strict, findings, ledger_probe.names)
        findings[:] = keep(findings)
        # The closed check's question comes only from --issue-state, which an
        # adapter or the operator produces. Without it the class is not run, and
        # the run says so once rather than letting "no ordering-closed rows"
        # read as "every ordered issue is open". Text mode only, on stdout
        # beside the report: the --json stream is findings, and a notice about a
        # class that did not run is not one, so the NDJSON stays byte-exact.
        if (issue_state_path is None and "ordering-closed" in requested
                and not args.json_out):
            print("note: ordering-closed was not evaluated: no --issue-state FILE was "
                  "given, so whether an ordered issue is closed is not asked "
                  "(the census never contacts a tracker)")

    # hygiene is its own check group: it scans the tracked files of the census's
    # own git tree (never the --ledger/--sessions overrides).
    if "hygiene" in requested:
        _helpers.check_hygiene(top, args.strict, findings, row=_row, bounded=_bounded)

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
