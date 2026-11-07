"""Public-repo hygiene scrub for every git-tracked file.

noni is published as a fresh public repository, so nothing personal about the
operator (employer names, hostnames, machine-local paths, their other
projects/tools/repos, secrets or credentials) may ever appear in a tracked file.
This module is the enforcing check for that rule: it scans the output of
`git ls-files` and fails naming the file and line of the first violation.

Violation classes:

1. machine-local absolute home paths of well-known build identities
   (``/Users/<user>``, ``/home/<user>``);
2. machine-local absolute home paths of *any* user — fixture guards only, not part of
   the scrub (see ``FIXTURE_HOME_PATH_PATTERNS``);
3. common secret shapes (token prefixes, private key blocks);
4. a deny-list of names, hosts and project identifiers that is never committed: loaded
   from an untracked local file (path in .gitignore) or an environment variable; when
   neither exists the class is skipped with a **prominent** stderr notice while the
   built-in patterns still run. A green run without the deny-list is **not** a
   scrub-clean guarantee — see docs/PUBLISHING.md step 1. The default file is always the
   one inside the tree being audited, never the one in the process's cwd;
5. a tracked regular file the scan could not read at all (an open refused with EACCES, a
   read that faults with EIO): a scan that never held the bytes cannot certify them, so
   the file is named as a violation at line 0 rather than skipped, with the fault's class
   and errno words and never the path the exception carried.

The deny-list file is plain text: one entry per line; blank lines and lines starting with
``#`` are ignored; entries are matched with ``re.escape`` so any entry is a literal.

This module is the canonical home for the shared secret-shape and home-path patterns;
``test_skill_scrub.py`` and ``test_purity.py`` import ``SECRET_PATTERNS``,
``HOME_PATH_PATTERNS`` and ``FIXTURE_HOME_PATH_PATTERNS`` from here rather than
maintaining their own copies.

Import contract: this module is part of the installed ``noni`` package and is imported as
``noni.public_safety`` — by the census's hygiene class in-process, and by every test that
reads its tables. Nothing puts a directory on ``sys.path`` to reach it.
``scripts/public_safety.py`` is the repository script form of the same check: a thin
wrapper over this module that keeps the gate's CLI contract
(``python scripts/public_safety.py``: exit 0 clean, exit 1 on violations, exit 2 when the
deny-list class is inactive, and exit 3 when the gate could not run because this package
was not importable), and it is reached as a subprocess, never imported. Exit 3 is kept
distinct from exit 2 because CI passes on 2: a scan that never ran must not read as the
verdict of a scan that ran and had nothing to refuse.

The tree to audit and the deny-list location are parameters of the scan, never read from
this file's own location: the module ships inside a wheel, so its ``__file__`` says
nothing about the repository being scrubbed. See ``scrub_tracked_files`` and
``load_denylist``.

Intentional fixtures are the exemption this module cannot carry: a tracked file written
to prove the secret shapes catch something trips the check it documents, and the only
built-in allowance is the narrow ``_SELF_FILES`` list below. The general form is the
audited tree's committed allowlist, which lives in ``public_safety_allowlist`` and is
re-bound here as ``load_allowlist`` and its helpers so the scan keeps one entry point
(see that module for the file's format and its three narrowings: exact paths, one label
per path, and neither config file exemptable).
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# The committed allowlist's reader lives one module deeper, split for the same reason
# ``public_safety_io`` was (the 500-line cap has no override) and bound here as the names
# the scan and its tests use, so ``public_safety`` keeps owning the whole exemption
# contract: binding, not copying -- the functions are one object, in one place.
from . import public_safety_io as _io
from . import public_safety_scan as _scan

# The re-export is deliberate: these are this module's published vocabulary (the tests,
# the census and the gate reach the exemption contract through here), so the names are
# bound rather than reached through the package attribute.
from .public_safety_allowlist import (  # noqa: F401  (re-export: this module owns the exemption vocabulary)
    ALLOWLIST_FILENAME,
    ALLOWLIST_PATTERNS,
    ALLOWLIST_REFUSED_LABEL,
    ALLOWLIST_STALE_LABEL,
    AllowlistEntry,
    AllowlistResult,
    allowlist_exempt,
    allowlist_reason,
    default_allowlist_file,
    load_allowlist,
)

# The guarded open and the read built on it live one module deeper, split along the seam
# #91 created. Bound here as the private names the scan and its tests already use, so
# ``public_safety`` keeps owning them: the tests bend ``os.open``/``os.read``/``os.close``
# through this module's ``os``, and the deny-list loader below calls these names. Binding,
# not copying -- the functions are one object, in one place. ``_open_regular`` is the one
# exception: it is defined below, once, as the thin wrapper the AST pins read.
_MAX_SCAN_FILE_BYTES = _io.MAX_SCAN_FILE_BYTES
_NOT_REGULAR = _io.NOT_REGULAR
_close = _io.close
_fault_pair = _io.fault_pair
_read_bytes_capped = _io.read_bytes_capped

# Default location of the untracked local deny-list, relative to the tree being
# audited. The path is in .gitignore so the file can never be committed; the
# deny-list env var names an alternative file, used when the tree carries no
# default file of its own.
DENYLIST_FILENAME = ".noni-scrub-denylist"


def default_denylist_file(repo: Path) -> Path:
    """The untracked deny-list path of the tree being audited."""
    return Path(repo).resolve() / DENYLIST_FILENAME


def _default_allowlist_file(repo: Path) -> Path:
    """The default allowlist path of the tree being audited. The seam tests patch.

    A name of this module's own, mirroring ``_default_denylist_file``: the scan reaches
    its config default through a spelling the module that owns the scan declares, so one
    test seam covers both config files. The loader's own copy of the rule is a fallback
    for a caller that imports only the loader.
    """
    return default_allowlist_file(repo)


def _default_denylist_file(repo: Path) -> Path:
    """The default deny-list path of the tree being audited. The seam tests patch.

    The tree is a parameter, never ``Path.cwd()``: the wheel copy of this module is
    installed anywhere and the gate may be invoked from any directory, so a cwd-derived
    default finds the operator's deny-list only by accident and silently drops the
    operator-name half of the check.
    """
    return default_denylist_file(repo)


DENYLIST_ENV_VAR = "NONI_SCRUB_DENYLIST"

# Well-known, widely-used usernames that must never appear in a machine-local home
# path. Deliberately generic; the operator's own username is carried by the untracked
# deny-list instead. The pattern requires a leading slash, so bare words in prose
# (e.g. "git history") are not matched -- only absolute paths.
_COMMON_IDENTITIES = ("root", "admin", "builder", "nobody", "daemon", "www-data")

# Shared pattern registry -- test_skill_scrub.py and test_purity.py import these
# tables rather than keeping their own copies, so a new shape is added once.
HOME_PATH_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    ((re.compile(r"/Users/(?:" + "|".join(_COMMON_IDENTITIES) + ")[/]")),
     "machine-local absolute home path (/Users/<known identity>)"),
    ((re.compile(r"/home/(?:" + "|".join(_COMMON_IDENTITIES) + ")[/]")),
     "machine-local absolute home path (/home/<known identity>)"),
)

# Fixture guards only: any machine-local absolute home path, whatever the username.
# Kept out of HOME_PATH_PATTERNS because the scrub's home-path class is limited to
# well-known identities (any-user names are the deny-list class's job, and matching
# every home path in tracked files would false-positive on examples in docs).
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

# Self-file exemption: which built-in patterns are skipped on _SELF_FILES. The self
# files carry the built-in pattern literals (this file defines the home-path regexes
# and token prefixes; tests/test_public_safety.py plants them as fixture strings), and
# those literals are not real violations. In practice: all home-path patterns and the
# ghp_ pattern are exempted there. The deny-list class is never exempted, and neither
# is any other secret shape: a deny-list name or a gho_, github_pat_, sk-, AKIA or
# private-key literal planted in a self file IS a violation (see
# test_scrub_exemption_does_not_hide_planted_secret_in_exempt_file).
_EXEMPT_BUILTIN_PATTERNS: frozenset[re.Pattern] = frozenset(
    p for p, _ in HOME_PATH_PATTERNS + SECRET_PATTERNS[:1]
)

# The label of a tracked file the scan was refused, published as a ``*_PATTERNS`` table so
# the census reads it from here (``census_hygiene._hygiene_labels``) rather than hard-
# coding a label it had never seen, which would report the row verbatim instead of split.
# The entry's first slot is unused: this class reports the whole file, so no pattern
# selects it.
UNREADABLE_TRACKED_FILE_LABEL = "tracked file could not be read"
UNREADABLE_TRACKED_FILE_PATTERNS: tuple[tuple[None, str], ...] = (
    (None, UNREADABLE_TRACKED_FILE_LABEL),
)

BUILTIN_PATTERNS: tuple[tuple[re.Pattern, str], ...] = HOME_PATH_PATTERNS + SECRET_PATTERNS

# Self files: files whose built-in pattern checks are narrowed (per-pattern exemption, see
# _EXEMPT_BUILTIN_PATTERNS). The path is matched against the repository-relative name from
# `git ls-files` only, so no per-file path resolution is needed and symlinked worktrees
# cannot change the decision. The three paths are the checker's homes and its test: the
# package module, the repository wrapper that keeps the gate's CLI contract, and the test
# that plants the literals.
_SELF_FILES = frozenset({
    "src/noni/public_safety.py",
    "scripts/public_safety.py",
    "tests/test_public_safety.py",
})


def _is_self_file(rel: str) -> bool:
    return rel in _SELF_FILES


def _open_regular(path: Path) -> tuple[int | None, tuple[str, str] | None]:
    """The guarded open of one path: see ``public_safety_io.open_regular``.

    Kept as the scan's own name, and defined only here, because the AST pins of
    ``test_public_safety_non_regular`` and the deny-list loader below both reach the guard
    through it, so the promise "every blocking open in this package goes through one
    guarded opener" stays checkable in the module that owns the scan.
    """
    return _io.open_regular(path)


def _read_text_lenient(path: Path) -> tuple[list[str], None] | tuple[None, tuple[str, str]] | None:
    """Read a tracked file as text: its lines, a fault, or None for a skip.

    The three answers are the three things a scan may learn about a path it was told to
    audit, and the middle one is the one #91 lost: a regular file the scan was refused
    (EACCES, EIO, an ``fstat`` that faulted) is a finding, because a scan that cannot
    read a tracked file cannot certify it. ``None`` is a skip -- binary or non-UTF-8, not
    a regular file, gone from the listing, or past the size bound; ``public_safety_io``
    owns the guard and says which path answers what.
    """
    return _io.read_text_lenient(path)


@dataclass
class DenylistResult:
    """Outcome of load_denylist: entries plus an explicit status.

    ``status`` is "ok" (a file was read; entries may still be empty for a comments-only
    file), "corrupt" (a file existed but was unreadable, so the class is disabled for this
    run) or "absent" (no file exists anywhere). The CLI treats "ok" with zero entries,
    "corrupt" and "absent" identically: a run whose class did not run with a non-empty
    list refuses to report clean (exit 2). A wrapper whose ``import noni`` failed never
    reaches this: it exits 3, the code reserved for a gate that could not run.
    """

    entries: list[str]
    source: str | None
    status: Literal["ok", "corrupt", "absent"]


def load_denylist(repo: Path) -> DenylistResult:
    """Load the deny-list for the tree ``repo`` and classify the outcome.

    Load order: the audited tree's own untracked default file first, then the env-var-named
    file; when neither exists the class is skipped ("absent") and the caller prints a
    prominent stderr notice. The env var is honoured in full for a tree that carries no
    deny-list of its own (or whose default file is unreadable): the route the publishing
    checklist uses.

    An unreadable or non-UTF-8 deny-list is corrupt (with a stderr notice) -- but loading
    does NOT stop there: it continues to the next candidate, so an env-var-named deny-list
    still takes effect when the default file is corrupt or absent. If no later candidate is
    usable the run ends "corrupt" (or "absent"), and the caller treats both like an
    inactive class. An unreadable deny-list is never a tracked-file violation: it is
    operator config outside the listing, and the caller's row already names it.
    """
    last_corrupt: Path | None = None
    for candidate in (_default_denylist_file(repo), os.environ.get(DENYLIST_ENV_VAR)):
        if not candidate:
            continue
        path = Path(candidate)
        # ``is_file()`` follows links and answers True for a fifo, so it is not the
        # guard: the deny-list read gets the same open-and-classify as every tracked
        # file, and a non-regular candidate is closed by the open and never waited
        # on. A pipe at the deny-list path is as inactive as a corrupt one.
        fd, fault = _open_regular(path)
        if fd is None and fault is None:
            # Nothing at this candidate and nothing to report: the open faulted with
            # ENOENT or ENOTDIR, so this path is simply not there. Absence stays a
            # silent skip -- the operator is not warned about a file they never wrote --
            # and the next candidate gets its chance.
            continue
        # The deny-list class never turns a fault into a tracked-file finding: an
        # unopenable or unreadable candidate is the class being inactive, and the reason
        # words only go into the stderr notice this caller prints.
        if fd is None:
            # The filesystem refused the open (EACCES on a 000-mode file, ELOOP on a
            # link loop). Reporting this as absence would leave the operator's deny-list
            # silently inactive, so it degrades like every other unreadable arm.
            raw, reason = None, ": ".join(filter(None, fault))
        elif fd == _NOT_REGULAR:
            raw, reason = None, "opened, but it is not a regular file"
        else:
            try:
                raw_bytes = _read_bytes_capped(fd)
            except OSError as e:
                raw, reason = None, ": ".join(filter(None, _fault_pair(e)))
            else:
                if raw_bytes is None:
                    raw, reason = None, "past the scan's size bound"
                else:
                    try:
                        raw, reason = raw_bytes.decode("utf-8"), ""
                    except UnicodeDecodeError:
                        raw, reason = None, "not valid UTF-8"
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


def _self_file_exempt(pattern: re.Pattern, label: str, is_self: bool) -> bool:
    """True when a self file is exempt from this pattern; the deny-list class never is.

    Lets the checker's own source and its test carry the literal shapes they detect. Keys
    on the pattern, so a planted secret literal in a self file is still a violation.
    """
    return is_self and label != DENYLIST_LABEL and pattern in _EXEMPT_BUILTIN_PATTERNS


def scrub_tracked_files(
    repo: Path,
) -> tuple[list[str], str | None, DenylistResult, AllowlistResult]:
    """Scan every git-tracked file under ``repo``.

    ``repo`` is required: the tree is always named by the caller (the census passes the
    git top level it already read, the CLI the repository it was run from), so a
    wheel-installed copy of this module can never scan the wrong tree by locating itself.

    Returns (violations, denylist_source, denylist, allowlist): violations is a list of
    ``path:line: label`` strings (empty means the repo is clean); denylist_source is the
    deny-list file path that was loaded, or None when the class was not active (absent or
    corrupt — a prominent stderr notice is printed either way, and a green run without the
    deny-list does NOT guarantee scrub-clean; see docs/PUBLISHING.md step 1); denylist
    carries the full outcome for callers that need to tell a comments-only file apart from
    a missing one; allowlist carries the committed allowlist's outcome, including the
    ``path:line: label`` rows its own stale and refused entries earn, which travel in
    ``violations`` beside the scan's.

    ``allowlist.status`` is what the two entry points read to decide their verdict: the
    gate exits 3 and the census reports the class as not run on "malformed" or
    "unreadable", because a scan that could not read the exemptions it was told to
    honour did not run. The fourth tuple member is part of the scan's contract: the
    callers that unpack it are ``scripts/public_safety.py`` and the census's hygiene
    class, and both name it.
    """
    denylist = load_denylist(repo)
    allowlist = load_allowlist(repo)
    patterns = list(BUILTIN_PATTERNS)
    for entry in denylist.entries:
        patterns.append((re.compile(re.escape(entry)), DENYLIST_LABEL))
    # The state check comes first, and before any scan: a run that could not read the
    # exemptions it was told to honour did not run, so it reports the allowlist's own rows
    # and nothing else. Scanning anyway and returning the result would dress an unknown
    # exemption set up as a verdict, and the loader's stderr line (which the CLI prints
    # and the census silences) would be the only trace of why.
    if allowlist.status in ("malformed", "unreadable"):
        return list(allowlist.findings), None, denylist, allowlist

    exempt = exempted_pairs(allowlist)
    # The scan call goes through this module's own name, not ``_scan``'s: it is the seam
    # ``tests/test_census_hygiene.py`` bends, and the census must run what the test bent.
    violations = _scan_tracked_files(repo, patterns, exempt)
    # The allowlist's own rows (a stale entry, a refused file) are carried by
    # ``allowlist.findings``, which the loader filled -- they are not recomputed here, so
    # the loader is the one place that decides what the file itself is accused of.
    violations += list(allowlist.findings)
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
    return violations, denylist.source if denylist.status == "ok" else None, \
        denylist, allowlist


# The scan's entry points, re-bound as this module's own: they are patch targets, and
# each is the moved function re-exported under the spelling its callers and tests name.
_scan_tracked_files = _scan.scan_tracked_files
_scan_lines = _scan.scan_lines
_tracked_listing = _scan.tracked_listing
exempted_pairs = _scan.exempted_pairs

# The row label the deny-list class gives a hit, published because the allowlist's rules
# are stated against it (a committed file may never exempt it) and because a test that
# plants a deny-list hit needs the same spelling the scan writes.
DENYLIST_LABEL = "deny-list entry"


# The gate's word for the state the CLI reports as exit 3 because of the allowlist. The
# number carries the verdict; this is the phrase the CLI line and the census row agree on,
# and the docs test reads it out of this module rather than a copy in a page.
GATE_COULD_NOT_RUN_WORD = "the gate could not run"


def _denylist_active(denylist: DenylistResult) -> bool:
    """True when the deny-list class ran with at least one entry."""
    return denylist.status == "ok" and len(denylist.entries) > 0
