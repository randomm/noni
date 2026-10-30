"""The census's read-only git access: one ``Git`` view and the calls that build it.

Split from ``census.py`` so each file stays the size one responsibility is
worth: ``census.py`` owns the CLI, the exit-code table, the row shape and the
group wiring, and this module owns the git layer every git-backed check reads
through — the history view, the top-level probe, the content digest, and the
pinned environment and -c overrides carried on every census git call.

Two rules travel with the calls and are the reason they live together: every git
subprocess is bounded by ``GIT_TIMEOUT_SECONDS`` so a hung git degrades to the
cannot-tell probe outcome rather than hanging the run, and every call runs under
the neutralised environment of ``census_hygiene.GIT_ENV_NEUTRAL`` plus
``_git_config_args``, so a repository someone else prepared cannot redirect a
read into execution. The table has one owner in ``census_hygiene`` (the hygiene
scan shares it); this module reads it through that module rather than copying it.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from . import census_hygiene as _helpers

# Every git subprocess in this module runs under this timeout: a hung git
# (huge or corrupt history, a credential prompt) degrades to the cannot-tell
# probe outcome instead of hanging the census.
GIT_TIMEOUT_SECONDS = 60

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


def _repo_sha1(path: Path) -> str | None:
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


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
