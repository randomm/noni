"""Public-repo hygiene scrub for every git-tracked file.

noni is published as a fresh public repository, so nothing personal about the
operator (employer names, hostnames, machine-local paths, their other
projects/tools/repos, secrets or credentials) may ever appear in a tracked
file. This module is the enforcing check for that rule: it scans the output of
`git ls-files` and fails naming the file and line of the first violation.

Violation classes:

1. machine-local absolute home paths (``/Users/<user>``, ``/home/<user>``),
   with a short list of well-known build-identity usernames that never belong
   in a public repo;
2. common secret shapes (token prefixes, private key blocks);
3. a deny-list of names, hosts and project identifiers that is never
   committed: it is loaded from an untracked local file (path in .gitignore)
   or an environment variable; when neither exists, the deny-list class is
   skipped with a **prominent** stderr notice while the built-in patterns
   still run. A green run without the deny-list is **not** a scrub-clean
   guarantee — see docs/PUBLISHING.md step 1.

The deny-list file is a plain text file: one entry per line; blank lines and
lines starting with ``#`` are ignored; entries are matched with
``re.escape`` so any entry is a literal.

This module is the canonical home for the shared secret-shape and
home-path patterns; ``test_skill_scrub.py`` and ``test_purity.py`` import
``SECRET_PATTERNS`` and ``HOME_PATH_PATTERNS`` from here rather than
maintaining their own copies.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Default location of the untracked local deny-list. The path is in .gitignore
# so the file can never be committed; the deny-list env var names an
# alternative file and takes precedence when the default file is absent.
DEFAULT_DENYLIST_FILE = REPO / ".noni-scrub-denylist"


def _default_denylist_file() -> Path:
    return DEFAULT_DENYLIST_FILE


DENYLIST_ENV_VAR = "NONI_SCRUB_DENYLIST"

# Well-known, widely-used usernames that must never appear in a machine-local
# home path. Deliberately generic; the operator's own username is never
# matched here — it is carried by the untracked deny-list instead. The pattern
# is anchored at the start of the line, so bare words in prose (e.g. "git
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

SECRET_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), "GitHub classic token"),
    (re.compile(r"\bgho_[A-Za-z0-9]{20,}"), "GitHub OAuth token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained token"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "API secret key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key block"),
)

BUILTIN_PATTERNS: tuple[tuple[re.Pattern, str], ...] = HOME_PATH_PATTERNS + SECRET_PATTERNS

# Files that carry the regex literals defining the built-in patterns must be
# exempt from the scrub, or their own source would self-match. Only the files
# that actually define pattern literals are exempted. The exemption applies to
# all patterns (built-in and deny-list) — this is safe because these files
# contain no real secrets or machine-local paths, only the pattern definitions
# themselves. The test test_scrub_excludes_own_source verifies that a planted
# secret in a *non-exempt* file is still caught.
_SELF_FILES = frozenset(
    {
        Path(__file__).resolve(),
        Path(__file__).resolve().parent.parent / "tests" / "test_public_safety.py",
        Path(__file__).resolve().parent.parent / "tests" / "test_purity.py",
    }
)


def _read_text_lenient(path: Path) -> list[str] | None:
    """Read a tracked file as text, or None when it is binary / non-UTF-8.

    Binary or non-UTF-8 files are skipped gracefully (edge case: the scrub
    must never crash on an untext-readable tracked file).
    """
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return None


def load_denylist() -> tuple[list[str], str | None]:
    """Load the deny-list; return (entries, source path as string or None).

    Load order: the default file (when it exists) takes precedence over the
    env-var-named file; when neither exists the deny-list part is skipped
    (returns ([], None)) and the caller prints a prominent stderr notice.

    A corrupt or non-UTF-8 deny-list file is treated as empty with a visible
    stderr notice rather than crashing the scrub.
    """
    for candidate in (_default_denylist_file(), os.environ.get(DENYLIST_ENV_VAR)):
        if not candidate:
            continue
        path = Path(candidate)
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            print(
                f"public-safety: WARNING — deny-list {path} unreadable ({e}); "
                "treating as empty. Built-in patterns still run, but the "
                "deny-list class is effectively disabled for this run.",
                file=sys.stderr,
            )
            return [], path.as_posix()
        entries = []
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                entries.append(stripped)
        return entries, path.as_posix()
    return [], None


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
        path = repo / rel
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in _SELF_FILES:
            continue
        lines = _read_text_lenient(path)
        if lines is None:
            continue
        for lineno, line in enumerate(lines, 1):
            for pattern, label in patterns:
                if pattern.search(line):
                    violations.append(f"{rel}:{lineno}: {label}")
    return violations


def scrub_tracked_files(repo: Path = REPO) -> tuple[list[str], str | None]:
    """Scan every git-tracked file under repo.

    Returns (violations, denylist_source): violations is a list of
    ``path:line: label`` strings (empty means the repo is clean);
    denylist_source is the deny-list file path that was loaded, or None when
    the deny-list class was skipped (a prominent stderr notice is printed
    either way the deny-list is absent — a green run without the deny-list
    does NOT guarantee scrub-clean, see docs/PUBLISHING.md step 1).
    """
    denylist, source = load_denylist()
    patterns = list(BUILTIN_PATTERNS)
    for entry in denylist:
        patterns.append((re.compile(re.escape(entry)), "deny-list entry"))

    violations = _scan_tracked_files(repo, patterns)

    if source is None:
        print(
            f"public-safety: WARNING — deny-list class SKIPPED (no "
            f"{_default_denylist_file().name} file, no {DENYLIST_ENV_VAR}). "
            "Built-in patterns ran, but operator names, external project/tool "
            "names and hostnames are NOT checked. This run is NOT a scrub-clean "
            "guarantee. See docs/PUBLISHING.md step 1.",
            file=sys.stderr,
        )
    return violations, source


if __name__ == "__main__":
    found, source = scrub_tracked_files()
    if found:
        for v in found:
            print(v, file=sys.stderr)
        sys.exit(1)
    if source is None:
        # Refuse to report clean when the deny-list class was skipped
        print("public-safety: NOT clean — deny-list class was skipped", file=sys.stderr)
        sys.exit(2)
    print("public-safety: clean", file=sys.stderr)
    sys.exit(0)
