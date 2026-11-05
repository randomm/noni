"""Public-repo hygiene scrub for every git-tracked file.

noni is published as a fresh public repository, so nothing personal about the
operator (employer names, hostnames, machine-local paths, their other
projects/tools/repos, secrets or credentials) may ever appear in a tracked
file. This module is the enforcing check for that rule: it scans the output of
`git ls-files` and fails naming the file and line of the first violation.

Violation classes:

1. machine-local absolute home paths of well-known build identities
   (``/Users/<user>``, ``/home/<user>``);
2. machine-local absolute home paths of *any* user — fixture guards only, not
   part of the scrub (see ``FIXTURE_HOME_PATH_PATTERNS``);
3. common secret shapes (token prefixes, private key blocks);
4. a deny-list of names, hosts and project identifiers that is never
   committed: it is loaded from an untracked local file (path in .gitignore)
   or an environment variable; when neither exists the deny-list class is
   skipped with a **prominent** stderr notice while the built-in patterns
   still run. A green run without the deny-list is **not** a scrub-clean
   guarantee — see docs/PUBLISHING.md step 1. The default file is always the
   one inside the tree being audited, never the one in the process's current
   directory.

The deny-list file is a plain text file: one entry per line; blank lines and
lines starting with ``#`` are ignored; entries are matched with
``re.escape`` so any entry is a literal.

This module is the canonical home for the shared secret-shape and
home-path patterns; ``test_skill_scrub.py`` and ``test_purity.py`` import
``SECRET_PATTERNS``, ``HOME_PATH_PATTERNS`` and
``FIXTURE_HOME_PATH_PATTERNS`` from here rather than maintaining their own
copies.

Import contract: this module is part of the installed ``noni`` package and is
imported as ``noni.public_safety`` — by the census's hygiene class in-process,
and by every test that reads its tables. Nothing puts a directory on
``sys.path`` to reach it. ``scripts/public_safety.py`` is the repository script
form of the same check: a thin wrapper over this module that keeps the gate's
CLI contract (``python scripts/public_safety.py``, exit 1 on violations, exit 2
when the deny-list class is inactive), and it is reached as a subprocess, never
imported.

The tree to audit and the deny-list location are parameters of the scan, never
read from this file's own location: the module ships inside a wheel, so its
``__file__`` says nothing about the repository being scrubbed. See
``scrub_tracked_files`` and ``load_denylist``.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Default location of the untracked local deny-list, relative to the tree being
# audited. The path is in .gitignore so the file can never be committed; the
# deny-list env var names an alternative file, used when the tree carries no
# default file of its own. The default is derived from the audited tree, never
# from this file's own location: the wheel copy of this module has no tree
# beside it.
DENYLIST_FILENAME = ".noni-scrub-denylist"


def default_denylist_file(repo: Path) -> Path:
    """The untracked deny-list path of the tree being audited."""
    return Path(repo).resolve() / DENYLIST_FILENAME


def _default_denylist_file(repo: Path) -> Path:
    """The default deny-list path of the tree being audited.

    The tree is a parameter, never ``Path.cwd()``: the wheel copy of this module
    is installed anywhere on the machine and the publishing gate may be invoked
    from any directory, so a cwd-derived default finds the operator's deny-list
    only by accident and silently drops the operator-name half of the check.
    The seam tests patch.
    """
    return default_denylist_file(repo)


DENYLIST_ENV_VAR = "NONI_SCRUB_DENYLIST"

# Well-known, widely-used usernames that must never appear in a machine-local
# home path. Deliberately generic; the operator's own username is never
# matched here — it is carried by the untracked deny-list instead. The
# pattern requires a leading slash, so bare words in prose (e.g. "git
# history") are not matched — only absolute paths.
_COMMON_IDENTITIES = ("root", "admin", "builder", "nobody", "daemon", "www-data")

# ---------------------------------------------------------------------------
# Shared pattern registry — imported by test_skill_scrub.py and test_purity.py
# so that a new secret shape or path pattern is added in exactly one place.
# ---------------------------------------------------------------------------

HOME_PATH_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (
        re.compile(r"/Users/(?:" + "|".join(_COMMON_IDENTITIES) + ")[/]"),
        "machine-local absolute home path (/Users/<known identity>)",
    ),
    (
        re.compile(r"/home/(?:" + "|".join(_COMMON_IDENTITIES) + ")[/]"),
        "machine-local absolute home path (/home/<known identity>)",
    ),
)

# Fixture guards only: any machine-local absolute home path, regardless of
# username. Kept out of HOME_PATH_PATTERNS because the scrub's home-path class
# is intentionally limited to well-known identities (any-user names are the
# deny-list class's job, and matching every home path in tracked files would
# false-positive on examples in docs).
FIXTURE_HOME_PATH_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"/Users/[A-Za-z0-9._-]+/"), "machine-local absolute home path (/Users/<user>)"),
    (re.compile(r"/home/[A-Za-z0-9._-]+/"), "machine-local absolute home path (/home/<user>)"),
)

SECRET_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), "GitHub classic token"),
    (re.compile(r"\bgho_[A-Za-z0-9]{20,}"), "GitHub OAuth token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained token"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "API secret key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key block"),
)

# Self-file exemption: which built-in patterns are skipped on _SELF_FILES.
#
# The self files carry the built-in pattern literals (this file defines the
# home-path regexes and token prefixes; tests/test_public_safety.py plants
# them as fixture strings). Those fixture literals are not real violations,
# so the patterns whose fixture literals live in the self files are exempted
# there. In practice: all home-path patterns (the test file plants
# /home/admin/ etc.) and the ghp_ GitHub classic token pattern (the test
# file plants ghp_synthsynth...). The deny-list class is never exempted: a
# deny-list name planted in a self file IS a violation. Secret-shape
# patterns other than ghp_ are not exempted: a gho_, github_pat_, sk-, AKIA
# or private-key literal planted in a self file IS a violation (see
# test_scrub_exemption_does_not_hide_planted_secret_in_exempt_file).
_EXEMPT_BUILTIN_PATTERNS: frozenset[re.Pattern] = frozenset(
    p for p, _ in HOME_PATH_PATTERNS + SECRET_PATTERNS[:1]
)


def _is_self_file_exempt_pattern(pattern: re.Pattern) -> bool:
    """True when the pattern is a built-in pattern that is exempted on
    self files. The deny-list class is never exempted."""
    return pattern in _EXEMPT_BUILTIN_PATTERNS


BUILTIN_PATTERNS: tuple[tuple[re.Pattern, str], ...] = HOME_PATH_PATTERNS + SECRET_PATTERNS

# Self files: files whose built-in pattern checks are narrowed (per-pattern
# exemption, see _EXEMPT_BUILTIN_PATTERNS above). They carry the built-in
# pattern literals (this file defines the home-path regexes and token
# prefixes; tests/test_public_safety.py plants them as fixture strings). The
# fixture literals are not real violations, so the patterns whose fixtures
# live here are exempted on these files. The deny-list class and all other
# secret-shape patterns are NOT exempted: a deny-list name or a real
# secret-shaped token planted in a self file IS a violation.
#
# Exemptions are matched against the repository-relative path from
# `git ls-files` only (exact path match), so no per-file path resolution is
# needed and symlinked worktrees cannot change the decision. The three paths
# are the checker's homes and its test: the package module, the repository
# wrapper that keeps the gate's CLI contract, and the test that plants the
# literals.
_SELF_FILES = frozenset({
    "src/noni/public_safety.py",
    "scripts/public_safety.py",
    "tests/test_public_safety.py",
})


def _is_self_file(rel: str) -> bool:
    return rel in _SELF_FILES


# The bytes one tracked file may be read into memory. The bound is not a
# performance knob: it is what a read of someone else's tree is willing to hold,
# and a file past it is skipped exactly as an unreadable one is.
_MAX_SCAN_FILE_BYTES = 8 << 20

# A pipe with no writer has nothing to say, so an open without O_NONBLOCK never
# returns: the hygiene scan of #91 blocked inside ``path.read_text`` forever,
# outside every timeout and every handler the module has (a blocked read raises
# nothing, so `except OSError` cannot rescue it). The guard therefore sits at the
# open, and on the descriptor the open returned:
#
#   os.open(O_RDONLY | O_NONBLOCK)  ->  stat.S_ISREG(os.fstat(fd))  ->  read
#
# ``O_NOFOLLOW`` is deliberately absent: a tracked symlink is legitimate content,
# and the flag would raise ELOOP on it and skip the file silently. The link is
# followed and scanned when its target is a regular file, and refused by the
# same-fd check when it is not. Checking the mode of a separate ``lstat`` of the
# path instead would leave the interval in which a regular file is swapped for a
# pipe after the check, which is the window this ordering closes.
#
# This is the idiom ``census_intent_readers.read_record`` uses; public_safety
# mirrors it rather than inventing a second one for the same fault.
_SCAN_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)


# The one answer a caller may not close: the path opened but was not a regular
# file, and this module already gave that descriptor back. Negative, so no real
# descriptor can be mistaken for it. Distinct from None ("could not be opened at
# all") because load_denylist must classify an unopenable deny-list and a
# non-regular one the same way, and neither of them as "absent".
_NOT_REGULAR = -1


def _open_regular(path: Path) -> int | None:
    """An open fd on ``path`` if it is a regular file; ``_NOT_REGULAR`` or None.

    An fd comes back only when the path is regular and readable, so the caller
    closes exactly the one it was handed: every other answer means nothing is left
    to close, because this function closes what it opened before returning. Nothing
    is read on any path either way: a pipe, socket or device is refused, not read as
    the empty string its immediate EOF would have produced. O_NONBLOCK is on the
    open itself because that open, not a later read, is what blocks on a pipe with
    no writer; the ``fstat`` runs on the very descriptor that was opened, so a path
    swapped for a non-regular one between a pre-open check and this call is refused
    too.

    Closing here rather than handing the descriptor to a caller is what keeps the
    leak out of them: the scan used to leave one descriptor open per non-regular
    path for the life of the process, and the census scans in-process, so a tree
    with more pipes than the table allows dies on the next open with EMFILE instead
    of returning a verdict.
    """
    try:
        fd = os.open(path, _SCAN_OPEN_FLAGS)
    except OSError:
        # Absent, unreadable, or a link loop: the caller treats it as the
        # unreadable tracked file the lenient read always skipped.
        return None
    try:
        mode = os.fstat(fd).st_mode
    except OSError:
        _close(fd)
        return None
    if not stat.S_ISREG(mode):
        # The kind is reported rather than swallowed because the two lenient
        # callers answer differently for it: a tracked file that is not a file is
        # skipped as if it were not there, while a deny-list that is not a file
        # must still classify the run as corrupt ("absent" would tell the operator
        # to go write one). The descriptor goes back first: the decision is already
        # made, no caller needs it, and reading a pipe is the fault.
        _close(fd)
        return _NOT_REGULAR
    return fd


def _close(fd: int) -> None:
    """Close a descriptor the caller is finished with, swallowing a bad one.

    The swallow is not tidiness: the scan's contract is that it never crashes on a
    path it cannot read, so a descriptor closed underneath the scan or revoked by a
    device going away must not raise EBADF out of a run. ``_open_regular`` closes
    what it opened and hands back only a descriptor it is done with, so a caller
    holding an fd has exactly one to give back, and the sentinel is never one.
    """
    try:
        os.close(fd)
    except OSError:
        pass


def _read_bytes_capped(fd: int, limit: int = _MAX_SCAN_FILE_BYTES) -> bytes | None:
    """Every byte of an open regular descriptor, or None when it exceeds ``limit``.

    The loop is not decoration: ``os.read`` is free to return fewer bytes than
    were asked for even on a regular file, and a body truncated that way would
    scan clean on the part nobody held. Past the bound the read stops and
    answers None, so a file this scan will not hold is skipped the way an
    unreadable one is.
    """
    chunks = bytearray()
    while True:
        chunk = os.read(fd, min(1 << 16, limit + 1 - len(chunks)))
        if not chunk:
            return bytes(chunks)
        chunks += chunk
        if len(chunks) > limit:
            return None


def _read_text_lenient(path: Path) -> list[str] | None:
    """Read a tracked file as text, or None when it must be skipped.

    Skipped means: binary or non-UTF-8 (the original lenient contract: never
    crash on an unreadable tracked file); not a regular file — a fifo, socket,
    device or directory, or a symlink to one; unreadable (absent, no permission,
    a link loop); or bigger than ``_MAX_SCAN_FILE_BYTES``. A non-regular path is
    closed by the open that classified it and never read, so a pipe is never waited
    on and never read as the empty file O_NONBLOCK's EOF would have made of it. The
    only descriptor this function closes is the one it was handed.
    """
    fd = _open_regular(path)
    if fd is None or fd == _NOT_REGULAR:
        return None
    try:
        raw = _read_bytes_capped(fd)
    except OSError:
        return None
    finally:
        _close(fd)
    if raw is None:
        return None
    try:
        return raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None


@dataclass
class DenylistResult:
    """Outcome of load_denylist: entries plus an explicit status.

    ``status`` is one of:
      - "ok" — a deny-list file was read successfully (entries may still be
        empty for a comments-only file);
      - "corrupt" — a deny-list file existed but was unreadable (non-UTF-8
        or an I/O error), so the deny-list class is effectively disabled for
        this run;
      - "absent" — no deny-list file exists anywhere (class skipped).

    The CLI treats "ok" with zero entries, "corrupt" and "absent" identically:
    a run whose deny-list class is not active with a non-empty list refuses to
    report clean (exit 2).
    """

    entries: list[str]
    source: str | None
    status: Literal["ok", "corrupt", "absent"]


def load_denylist(repo: Path) -> DenylistResult:
    """Load the deny-list for the tree ``repo`` and classify the outcome.

    Load order: the audited tree's own untracked default file first, then the
    env-var-named file; when neither exists the deny-list part is skipped
    (status "absent") and the caller prints a prominent stderr notice. The env
    var is honoured in full for a tree that carries no deny-list of its own (or
    whose default file is unreadable), which is the route the publishing
    checklist uses.

    An unreadable or non-UTF-8 deny-list file is classified as corrupt (with
    a visible stderr notice) — but loading does NOT stop at the corrupt file:
    it continues to the next candidate, so an env-var-named deny-list still
    takes effect when the default file is corrupt (or absent). If no later
    candidate is usable, the run ends with status "corrupt" (or "absent" if
    no candidate existed at all); the caller treats both like an inactive
    deny-list class.
    """
    last_corrupt: Path | None = None
    for candidate in (_default_denylist_file(repo), os.environ.get(DENYLIST_ENV_VAR)):
        if not candidate:
            continue
        path = Path(candidate)
        # ``is_file()`` follows links and answers True for a fifo, so it is not
        # the guard: the deny-list read gets the same open-and-classify as every
        # tracked file, and a non-regular candidate is skipped (closed by the
        # open, never read) rather than waited on. A pipe at the deny-list path is
        # as inactive as a corrupt one: the notice below names it.
        fd = _open_regular(path)
        if fd is None:
            # Nothing to read at this candidate and nothing to be angry about:
            # absent, or a path the scan cannot open at all. The next candidate
            # gets its chance and, if none is usable, the run is "absent".
            continue
        try:
            raw_bytes = None if fd == _NOT_REGULAR else _read_bytes_capped(fd)
            raw = raw_bytes.decode("utf-8") if raw_bytes is not None else None
        except (OSError, UnicodeDecodeError) as e:
            raw = None
            reason = str(e)
        else:
            reason = ("opened, but it is not a regular file" if fd == _NOT_REGULAR
                      else "past the scan's size bound" if raw is None else "")
        finally:
            # The sentinel was closed by the open that classified it, so only the
            # descriptor the read took is this arm's to give back.
            if fd != _NOT_REGULAR:
                _close(fd)
        if raw is None:
            # Unreadable: a read fault, a body past the scan's size bound, or
            # non-UTF-8 bytes. Either way the class is not active from this file
            # and the next candidate gets its chance.
            last_corrupt = path
            print(
                f"public-safety: WARNING — deny-list {path} unreadable"
                f"{f' ({reason})' if reason else ''}; continuing with the next "
                "candidate if any. Built-in patterns still run, but the deny-list "
                "class is not active from this file.",
                file=sys.stderr,
            )
            continue
        entries = []
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                entries.append(stripped)
        return DenylistResult(entries, path.as_posix(), "ok")
    if last_corrupt is not None:
        # No candidate could be read: the deny-list class is inactive, and the
        # last (highest-precedence existing) unreadable file classifies the run.
        return DenylistResult([], last_corrupt.as_posix(), "corrupt")
    return DenylistResult([], None, "absent")


def _scan_tracked_files(repo: Path, patterns: list[tuple[re.Pattern, str]]) -> list[str]:
    # The tree being scanned is someone else's, so its config may not turn a
    # read-only listing into execution: core.fsmonitor names a helper git execs,
    # core.hooksPath redirects hooks, protocol.ext.allow enables external
    # transport helpers, and a repo-embedded config carrying any of them would
    # otherwise run under the scanner's privileges. The two config files a host
    # may carry are pinned to the null device for the same reason.
    try:
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        result = subprocess.run(
            ["git", "-C", str(repo),
             "-c", "core.fsmonitor=false",
             "-c", f"core.hooksPath={os.devnull}",
             "-c", "protocol.ext.allow=never",
             "ls-files", "-z"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("git ls-files timed out (30s); a stuck index lock or fs hang is likely") from e
    if result.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {result.stderr.strip()}")
    violations = []
    for rel in result.stdout.split("\0"):
        rel = rel.strip()
        if not rel:
            continue
        lines = _read_text_lenient(repo / rel)
        if lines is None:
            continue
        is_self = _is_self_file(rel)
        for lineno, line in enumerate(lines, 1):
            for pattern, label in patterns:
                if is_self and label != "deny-list entry" and _is_self_file_exempt_pattern(pattern):
                    continue
                if pattern.search(line):
                    violations.append(f"{rel}:{lineno}: {label}")
                    break  # one violation label per line is enough
    return violations


def scrub_tracked_files(repo: Path) -> tuple[list[str], str | None, DenylistResult]:
    """Scan every git-tracked file under repo.

    ``repo`` is required: the tree to audit is always named by the caller (the
    census passes the git top level it already read, the CLI passes the
    repository it was run from), so a wheel-installed copy of this module can
    never scan the wrong tree by locating itself.

    Returns (violations, denylist_source, denylist): violations is a list of
    ``path:line: label`` strings (empty means the repo is clean);
    denylist_source is the deny-list file path that was loaded, or None when
    the deny-list class was not active (absent or corrupt — a prominent
    stderr notice is printed either way, and a green run without the
    deny-list does NOT guarantee scrub-clean; see docs/PUBLISHING.md
    step 1); denylist carries the full outcome (entries, source, status)
    for callers that need to tell a comments-only file apart from a missing
    one.
    """
    denylist = load_denylist(repo)
    patterns = list(BUILTIN_PATTERNS)
    for entry in denylist.entries:
        patterns.append((re.compile(re.escape(entry)), "deny-list entry"))

    violations = _scan_tracked_files(repo, patterns)

    if denylist.status != "ok":
        reason = "unreadable/corrupt" if denylist.status == "corrupt" else "absent"
        source_note = f" file: {denylist.source}" if denylist.source else ""
        print(
            f"public-safety: WARNING — deny-list class SKIPPED ({reason}{source_note}). "
            "Built-in patterns ran, but operator names, external project/tool "
            "names and hostnames are NOT checked. This run is NOT a scrub-clean "
            "guarantee. See docs/PUBLISHING.md step 1.",
            file=sys.stderr,
        )
    return violations, denylist.source if denylist.status == "ok" else None, denylist


def _denylist_active(denylist: DenylistResult) -> bool:
    """True when the deny-list class actually ran with at least one entry."""
    return denylist.status == "ok" and len(denylist.entries) > 0
