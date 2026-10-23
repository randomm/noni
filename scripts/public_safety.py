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
   guarantee — see docs/PUBLISHING.md step 1.

The deny-list file is a plain text file: one entry per line; blank lines and
lines starting with ``#`` are ignored; entries are matched with
``re.escape`` so any entry is a literal.

This module is the canonical home for the shared secret-shape and
home-path patterns; ``test_skill_scrub.py`` and ``test_purity.py`` import
``SECRET_PATTERNS``, ``HOME_PATH_PATTERNS`` and
``FIXTURE_HOME_PATH_PATTERNS`` from here rather than maintaining their own
copies.

Import contract: this module is not part of an installed package
(``packages = []`` in pyproject.toml); tests import it with a
``sys.path.insert(0, <repo>/scripts)`` in each test file (tests/
test_public_safety.py, test_purity.py, test_skill_scrub.py).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_self_path = Path(__file__).resolve()
REPO = _self_path.parent.parent

# Default location of the untracked local deny-list. The path is in .gitignore
# so the file can never be committed; the deny-list env var names an
# alternative file and takes precedence when the default file is absent.
DEFAULT_DENYLIST_FILE = REPO / ".noni-scrub-denylist"


def _default_denylist_file() -> Path:
    return DEFAULT_DENYLIST_FILE


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

BUILTIN_PATTERNS: tuple[tuple[re.Pattern, str], ...] = HOME_PATH_PATTERNS + SECRET_PATTERNS

# Files exempt from the scrub, because they carry built-in pattern literals
# that would otherwise be flagged by their own patterns. Two distinct classes:
#   - scripts/public_safety.py defines the built-in pattern literals
#     (home-path regexes, token prefixes, the private key block marker);
#   - tests/test_public_safety.py plants those literals as fixture strings
#     to verify the scrub flags them.
# No tracked file may carry real external tool/project names — that is
# exactly what the scrub enforces (see issue #8), so no file is exempted for
# *name* literals: the purity vocabulary check loads its banned vocabulary
# from the untracked deny-list instead, and every planted name in the tests
# is synthetic. Exempting the files above is safe: they contain no real
# secrets or machine-local paths, only the literals that make them
# self-match. A planted violation in any *other* tracked file is still caught
# (see test_scrub_exemption_does_not_hide_planted_secret).
#
# Exemptions are matched against the repository-relative path from
# `git ls-files` (plus this module's own __file__), so no per-file path
# resolution is needed and symlinked worktrees cannot change the decision.
_SELF_FILES = frozenset({"scripts/public_safety.py", "tests/test_public_safety.py"})


def _is_self_file(rel: str) -> bool:
    # The relative paths from `git ls-files` match _SELF_FILES directly; the
    # __file__ fallback covers being invoked with the module's own absolute
    # path (not expected, but cheap to check).
    return rel in _SELF_FILES or _self_path == REPO / rel


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
    report clean (exit 2).
    """

    entries: list[str]
    source: str | None
    status: Literal["ok", "corrupt", "absent"]


def load_denylist() -> DenylistResult:
    """Load the deny-list and classify the outcome.

    Load order: the default file (when it exists) takes precedence over the
    env-var-named file; when neither exists the deny-list part is skipped
    (status "absent") and the caller prints a prominent stderr notice.

    An unreadable or non-UTF-8 deny-list file is classified as corrupt (with
    a visible stderr notice) — but loading does NOT stop at the corrupt file:
    it continues to the next candidate, so an env-var-named deny-list still
    takes effect when the default file is corrupt (or absent). If no later
    candidate is usable, the run ends with status "corrupt" (or "absent" if
    no candidate existed at all); the caller treats both like an inactive
    deny-list class.
    """
    last_corrupt: Path | None = None
    for candidate in (_default_denylist_file(), os.environ.get(DENYLIST_ENV_VAR)):
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
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z"],
            capture_output=True,
            text=True,
            timeout=30,
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
        if _is_self_file(rel):
            continue
        lines = _read_text_lenient(repo / rel)
        if lines is None:
            continue
        for lineno, line in enumerate(lines, 1):
            for pattern, label in patterns:
                if pattern.search(line):
                    violations.append(f"{rel}:{lineno}: {label}")
                    break  # one violation label per line is enough
    return violations


def scrub_tracked_files(repo: Path = REPO) -> tuple[list[str], str | None, DenylistResult]:
    """Scan every git-tracked file under repo.

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
    denylist = load_denylist()
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


if __name__ == "__main__":
    found, _source, denylist = scrub_tracked_files()
    if found:
        for v in found:
            print(v, file=sys.stderr)
        sys.exit(1)
    if not _denylist_active(denylist):
        # Refuse to report clean when the deny-list class was not active:
        # skipped (absent), corrupt, or present but empty.
        state = denylist.status if denylist.status != "ok" else "present but empty"
        print(f"public-safety: NOT clean — deny-list class inactive ({state})", file=sys.stderr)
        sys.exit(2)
    print("public-safety: clean", file=sys.stderr)
    sys.exit(0)
