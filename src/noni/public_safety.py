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
CLI contract (``python scripts/public_safety.py``: exit 0 clean, exit 1 on
violations, exit 2 when the deny-list class is inactive, and exit 3 when the
gate could not run because this package was not importable), and it is reached
as a subprocess, never imported. Exit 3 is kept distinct from exit 2 because
CI passes on 2: a scan that never ran must not read as the verdict of a scan
that ran and had nothing to refuse.

The tree to audit and the deny-list location are parameters of the scan, never
read from this file's own location: the module ships inside a wheel, so its
``__file__`` says nothing about the repository being scrubbed. See
``scrub_tracked_files`` and ``load_denylist``.
"""

from __future__ import annotations

import os
import re
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


def _read_text_lenient(path: Path) -> list[str] | None:
    """Read a tracked file as text, or None when it is binary / non-UTF-8.

    Binary or non-UTF-8 files are skipped gracefully (edge case: the scrub
    must never crash on an unreadable tracked file).
    """
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
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
    report clean (exit 2). A wrapper whose ``import noni`` failed never reaches
    this: it exits 3, the code reserved for a gate that could not run.
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
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            last_corrupt = path
            print(
                f"public-safety: WARNING — deny-list {path} unreadable ({e}); "
                f"continuing with the next candidate if any. Built-in patterns "
                "still run, but the deny-list class is not active from this file.",
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
