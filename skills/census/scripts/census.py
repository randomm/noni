"""The unified census: one read-only entry point over the steering ledger and
the session register.

The census is the arbiter of the noni protocol invariants. It reads the git
history plus the committed files under ``noni/`` (decision records under
``noni/decisions/``, session registers under ``noni/sessions/``), flags
protocol violations, and returns an honest exit code. It never writes
anything: running it leaves ``git status --porcelain`` empty, and no digest
file or report directory is produced — results are recomputed on demand.

Checks (all always run; the exit code is the aggregate of the classes that
fired, lowest class code winning):

  ledger-record    10  a decision record is missing or malformed, or the
                       ledger is unusable (missing/empty dir, bad filename,
                       git history unreadable)
  ledger-edited    12  a record was edited after commit
  ledger-chain     20  the supersede chain is broken
  session-double   30  two active claims on the same task from different
                       identities (the arbiter check)
  session-claim    31  a claim row committed without a register file
  session-malformed 32 a session file is malformed
  session-stalled  40  an active session with no commit for --stale-after
                       (warn by default; failure only under --strict)

Probe failures never report clean: a probe that cannot read a file or cannot
run git records a probe failure (a warning, or code 41 under --strict),
never a silent pass.

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

SCHEMA_VERSION = "noni.census/1"

# --- Exit-code table ----------------------------------------------------------
# 0 clean | 2 usage error | 3 required tool missing | 10 record/ledger unusable
# | 12 edited after commit | 20 supersede chain broken | 30 double-claim
# | 31 claim without a register file | 32 malformed session file
# | 40 stalled session (--strict) | 41 probe failure (--strict)
EXIT_CLEAN = 0
EXIT_USAGE = 2
EXIT_TOOL_MISSING = 3
EXIT_LEDGER_RECORD = 10
EXIT_LEDGER_EDITED = 12
EXIT_LEDGER_CHAIN = 20
EXIT_SESSION_DOUBLE = 30
EXIT_SESSION_CLAIM = 31
EXIT_SESSION_MALFORMED = 32
EXIT_SESSION_STALLED = 40
EXIT_PROBE = 41

CLASS_CODE = {
    "ledger-record": EXIT_LEDGER_RECORD,
    "ledger-edited": EXIT_LEDGER_EDITED,
    "ledger-chain": EXIT_LEDGER_CHAIN,
    "session-double": EXIT_SESSION_DOUBLE,
    "session-claim": EXIT_SESSION_CLAIM,
    "session-malformed": EXIT_SESSION_MALFORMED,
    "session-stalled": EXIT_SESSION_STALLED,
    "probe": EXIT_PROBE,
}
CLASS_SEVERITY = {name: "fail" for name in CLASS_CODE}
CLASS_SEVERITY["session-stalled"] = "warn"
CLASS_SEVERITY["probe"] = "warn"
CLASS_FIX = {
    "ledger-record": "repair or remove the offending record, or pass the ledger directory of the right clone",
    "ledger-edited": "supersede the record with a new file; never edit a committed record",
    "ledger-chain": "repair the supersede chain so it resolves to exactly one live record per chain",
    "session-double": "release the claim on the task in one session, or record who keeps it as a ledger decision",
    "session-claim": "register the session (add the identity field) or move the orphan claim into a registered session file",
    "session-malformed": "restore the missing field or add the missing task reference to the claim row",
    "session-stalled": "close the session or commit a fresh register update if the work is still in flight",
    "probe": "fix the unreadable file or the git tree; a census that cannot read its input reports the probe failure, never clean",
}

NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.json$")

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
                ["git", "-C", str(self.top), *args],
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
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
        _last_commit[relpath] is a (unix ts, commit id) pair."""
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
                ["git", "-C", str(self.top), "cat-file", "blob", f"{commit}:{relpath}"],
                capture_output=True,
                timeout=GIT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return None
        if proc.returncode != 0:
            return None
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
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
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
    extra = [k for k in obj if k not in REQUIRED_LEDGER_FIELDS]
    if extra:
        problems.append("unknown field(s): " + ", ".join(sorted(extra)))
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


def _check_ledger(ledger: Path, git: Git | None, root: Path, findings: list[dict]) -> None:
    """Check the steering ledger; append findings (each a partial finding row).

    Composition only: record I/O + schema validation, then the edited check
    (git-backed) and the supersede-chain check, in that order."""
    valid, unparseable = _check_ledger_records(ledger, root, findings)
    _check_ledger_edited(valid, unparseable, git, root, findings)
    _check_ledger_chain(valid, ledger, root, findings)


def _check_ledger_records(
    ledger: Path, root: Path, findings: list[dict]
) -> tuple[list[tuple[str, Path, dict]], list[tuple[str, Path]]]:
    """I/O + schema validation. Returns (valid, unparseable) where each entry
    of unparseable is (name, path) of a file that exists on disk but failed
    parsing — it still gets the git edited check."""
    def add(check: str, severity: str, subject: str, artifact: str, message: str) -> None:
        findings.append(
            {
                "check": check,
                "code": CLASS_CODE[check],
                "severity": severity,
                "subject": subject,
                "artifact": _rel_to_root(root, Path(artifact)),
                "message": message,
            }
        )

    kind, _problem = _file_kind(ledger, kind="dir")
    if kind == "absent":
        add("ledger-record", "fail", str(ledger), str(ledger), "ledger directory does not exist")
        return [], []
    if kind != "regular":
        add("ledger-record", "fail", str(ledger), str(ledger), "ledger path is not a readable directory")
        return [], []

    names = sorted(p.name for p in ledger.glob("*.json"))
    valid: list[tuple[str, Path, dict]] = []
    unparseable: list[tuple[str, Path]] = []
    for name in names:
        path = ledger / name
        if not NAME_RE.match(name):
            add("ledger-record", "fail", name, str(path), "filename is not a plain <name>.json path segment")
            continue
        fkind, fproblem = _file_kind(path)
        if fkind != "regular":
            add("ledger-record", "fail", name, str(path), f"record is unreadable: {fproblem}")
            continue
        try:
            raw = path.read_bytes()
            body = raw.decode("utf-8")
        except (UnicodeDecodeError, OSError) as e:
            add("ledger-record", "fail", name, str(path), f"record is unreadable: {e}")
            unparseable.append((name, path))
            continue
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            add("ledger-record", "fail", name, str(path), "record is not valid JSON")
            unparseable.append((name, path))
            continue
        problems = _validate_record(obj)
        if problems:
            add("ledger-record", "fail", obj.get("id", name) if isinstance(obj, dict) else name, str(path), "; ".join(problems))
            continue
        valid.append((obj["id"], path, obj))

    if not names:
        add("ledger-record", "fail", str(ledger), str(ledger), "no *.json records under the ledger directory")

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
    parse-time rejection must not silence the integrity check. The committed
    blob set is resolved in one `git log` over the whole ledger directory
    (not one `rev-parse` per record), and the disk sha is one in-memory hash
    per file. A record whose committed bytes are unreachable degrades to a
    cannot-verify warning (probe honesty), never a silent pass."""

    def add(check: str, severity: str, subject: str, artifact: str, message: str) -> None:
        findings.append(
            {
                "check": check,
                "code": CLASS_CODE[check],
                "severity": severity,
                "subject": subject,
                "artifact": _rel_to_root(root, Path(artifact)),
                "message": message,
            }
        )

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
    if any(r is None for r in rels):
        return
    # One `git log --name-only` call over the ledger files: every commit that
    # touched any of them, each commit block followed by the paths it touched.
    # No per-record subprocess.
    log = git._run(["log", "--all", "--name-only", "--format=%H", "--", *[r for r in rels if r is not None]])
    if log is None:
        for _subject, rid, path in entries:
            add(
                "ledger-edited",
                "warn",
                rid,
                str(path),
                "cannot verify: git history for the ledger is unreadable in this tree",
            )
        return
    # Parse the log: commit-hash lines are followed by the paths they touched,
    # separated by blank lines. `git log` is newest-first, so the first commit
    # that touches a given path is its newest commit. Record only the first
    # (newest) commit per path.
    newest_per_rel: dict[str, str] = {}
    current_commit: str | None = None
    for line in log.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # A 40-char hex string is a commit hash line.
        if len(stripped) == 40 and all(c in "0123456789abcdef" for c in stripped):
            current_commit = stripped
        elif current_commit is not None and stripped not in newest_per_rel:
            newest_per_rel[stripped] = current_commit
    for idx, (_subject, rid, path) in enumerate(entries):
        rel = rels[idx]
        commit = newest_per_rel.get(rel) if rel is not None else None
        if commit is None:
            continue  # never committed: nothing to compare against
        blob = git.blob_content_sha1(commit, rel)
        disk = _repo_sha1(path)
        if blob is None:
            add(
                "ledger-edited",
                "warn",
                rid,
                str(path),
                "cannot verify: committed blob is unreachable in this tree (shallow or pruned history)",
            )
        elif disk is not None and blob != disk:
            add("ledger-edited", "fail", rid, str(path), "record was edited after commit (working tree differs from git)")


def _check_ledger_chain(
    valid: list[tuple[str, Path, dict]], ledger: Path, root: Path, findings: list[dict]
) -> None:
    """Supersede-chain analysis: dangling, duplicate, orphan, cycle, and the
    single-live-record-per-chain rule."""
    def add(check: str, severity: str, subject: str, artifact: str, message: str) -> None:
        findings.append(
            {
                "check": check,
                "code": CLASS_CODE[check],
                "severity": severity,
                "subject": subject,
                "artifact": _rel_to_root(root, Path(artifact)),
                "message": message,
            }
        )

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
                "fail",
                target,
                str(ledger),
                f"duplicate: {target} is superseded by more than one record ({', '.join(sorted(children))})",
            )
    for rid in sorted(ids):
        sup = supers[rid]
        if sup is not None and sup not in ids:
            add("ledger-chain", "fail", rid, str(ledger), f"dangling: {rid} supersedes {sup} (no such record)")
        if sup is None and status[rid] == "superseded" and rid not in succ:
            add("ledger-chain", "fail", rid, str(ledger), f"orphan: {rid} is marked superseded but no record supersedes it")
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
            add("ledger-chain", "fail", rid, str(ledger), f"cycle: {rid} is in a supersedes cycle")
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
            add("ledger-chain", "fail", root_id, str(ledger), f"zero-live: chain {root_id} resolves to no live record")
        elif len(live) > 1:
            add("ledger-chain", "fail", root_id, str(ledger), f"multi-live: chain {root_id} resolves to more than one live record")


def _repo_sha1(path: Path) -> str | None:
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


# --- Session checks -------------------------------------------------------------

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
    sessions: Path, git: Git | None, root: Path, now: datetime, stale_after: timedelta, strict: bool
) -> list[dict]:
    """Check the session register; return the findings.

    A missing sessions directory is a clean state (no sessions registered);
    an unreadable or non-directory path is a probe failure, never clean.
    Stalled sessions and probe failures are warnings by default and failures
    under --strict.
    """
    findings: list[dict] = []

    def add(check: str, subject: str, artifact: str, message: str) -> None:
        severity = CLASS_SEVERITY[check]
        if severity == "warn" and strict:
            severity = "fail"
        findings.append(
            {
                "check": check,
                "code": CLASS_CODE[check],
                "severity": severity,
                "subject": subject,
                "artifact": _rel_to_root(root, Path(artifact)),
                "message": message,
            }
        )

    kind, problem = _file_kind(sessions, kind="dir")
    if kind == "absent":
        return findings
    if kind != "regular":
        add("probe", str(sessions), str(sessions), f"sessions path is not a readable directory: {problem}")
        return findings

    files = sorted(sessions.glob("*.md"))
    claim_map: dict[str, dict[str, list[str]]] = {}
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
        if fields.get("status", "").strip().lower() not in INACTIVE_STATUSES:
            for task in claims:
                claim_map.setdefault(task, {}).setdefault(fields.get("identity", ""), []).append(name)

        # Staleness: the signals are the register file itself and the git
        # history that last touched it. Both must say stale (agreement); any
        # signal missing or unreadable is cannot-tell (warn), never stalled.
        status = fields.get("status", "").strip().lower()
        if status == "active":
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

    return findings


# --- CLI -----------------------------------------------------------------------

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
    parser.add_argument("--strict", action="store_true", help="treat stalled sessions and probe failures as failures")
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
    raw_days = args.stale_after.rstrip("dD")
    if not re.fullmatch(r"\d+", raw_days):
        print(
            f"error: --stale-after {args.stale_after!r} must be positive whole days (e.g. 7 or 7d)",
            file=sys.stderr,
        )
        return EXIT_USAGE
    days = int(raw_days)
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
    # A missing noni/decisions/ is clean (nothing to census); a present but
    # empty or broken ledger directory is a violation. The ledger and the
    # sessions layer are independent: a repo with sessions but no ledger is
    # clean for ledger checks (and vice versa).
    if "ledger-record" in checks or "ledger-edited" in checks or "ledger-chain" in checks:
        if ledger.is_dir():
            _check_ledger(ledger, git, root, findings)

    if any(c.startswith("session-") for c in checks):
        s_findings = _check_sessions(sessions, git, root, now, stale_after, args.strict)
        findings.extend(f for f in s_findings if f["check"] in checks)

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
FINDING_SORT_KEY = lambda f: (f["artifact"], f["check"], f["subject"])


def _render(
    findings: list[dict], counts: dict[str, int], ok: bool, exit_code: int, json_out: bool
) -> None:
    """Emit the results in either NDJSON (--json) or human-readable form."""
    if json_out:
        for f in sorted(findings, key=FINDING_SORT_KEY):
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
            for f in sorted(findings, key=FINDING_SORT_KEY):
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
