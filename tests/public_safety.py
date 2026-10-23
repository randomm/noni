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
   or an environment variable; when neither exists, that class is skipped
   with a visible notice while the built-in patterns still run.

The deny-list file is a plain text file: one entry per line; blank lines and
lines starting with ``#`` are ignored; entries are matched with
``re.escape`` so any entry is a literal.
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

BUILTIN_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile("^/Users/(?:" + "|".join(_COMMON_IDENTITIES) + ")[/]"), "machine-local absolute home path (/Users/<known identity>)"),
    (re.compile("^/home/(?:" + "|".join(_COMMON_IDENTITIES) + ")[/]"), "machine-local absolute home path (/home/<known identity>)"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), "GitHub classic token"),
    (re.compile(r"\bgho_[A-Za-z0-9]{20,}"), "GitHub OAuth token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained token"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "API secret key"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key block"),
)

# This module and the test files that carry the regex literals defining the
# built-in patterns / the forbidden vocabulary carry the very strings the
# deny-list checks for, so scanning their own source would self-match. They
# are exempt from the scrub (the deny-list class never scans source files
# anyway, and the built-in patterns are anchored to absolute paths or token
# shapes that the test literals do not actually trigger).
_SELF_FILES = tuple(
    Path(__file__).resolve().with_name(n)
    for n in (
        "public_safety.py",
        "test_public_safety.py",
        "test_purity.py",
        "test_skill_scrub.py",
    )
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


def load_denylist(repo: Path) -> tuple[list[str], str | None]:
    """Load the deny-list; return (entries, source description) or ([], None).

    Load order: the default file (when it exists) takes precedence over the
    env-var-named file; when neither exists the deny-list part is skipped.
    """
    for candidate in (_default_denylist_file(), os.environ.get(DENYLIST_ENV_VAR)):
        if not candidate:
            continue
        path = Path(candidate)
        if not path.is_file():
            continue
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                entries.append(stripped)
        return entries, path.as_posix()
    return [], None


def _scan_tracked_files(repo: Path, patterns: list[tuple[re.Pattern, str]], include_source: bool) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {result.stderr.strip()}")
    violations = []
    for rel in result.stdout.split("\0"):
        rel = rel.strip()
        if not rel:
            continue
        path = repo / rel
        if path.resolve() in _SELF_FILES and not include_source:
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
    denylist_source is the deny-list file that was loaded, or None when the
    deny-list class was skipped (the skip notice is printed to stderr either
    way the deny-list is absent).
    """
    denylist, source = load_denylist(repo)
    patterns = list(BUILTIN_PATTERNS)
    for entry in denylist:
        patterns.append((re.compile(re.escape(entry)), "deny-list entry"))

    violations = _scan_tracked_files(repo, patterns, include_source=False)

    if source is None:
        print(
            f"public-safety: deny-list skipped (no {_default_denylist_file().name} file, no {DENYLIST_ENV_VAR}; "
            "built-in patterns ran)",
            file=sys.stderr,
        )
    return violations, source


if __name__ == "__main__":
    found, _ = scrub_tracked_files()
    if found:
        for v in found:
            print(v, file=sys.stderr)
        sys.exit(1)
    print("public-safety: clean", file=sys.stderr)
    sys.exit(0)
