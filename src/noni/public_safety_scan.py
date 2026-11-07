"""The scan half of the hygiene check: the listing, the per-line match, the exemption.

Split out of ``public_safety.py`` along the seam the committed allowlist opened: the
size cap (``tests/test_file_size_limit.py``, 500 lines per tracked ``.py``, no override
flag) is why this is a file and not another block there, on the precedent of the
``public_safety_io`` split of #91.

What lives here is everything the scan does to a *tracked path*, plus the one rule the
allowlist adds to it. The tables, the self-file exemption, the deny-list loader and the
verdict stay in ``public_safety``, which re-binds the two entry points below so the
module that owns the scan keeps owning the seam its tests bend:
``tests/test_census_hygiene.py`` replaces ``_scan_tracked_files`` on that module and the
census must run the object the test bent, not a copy.

Three rules are load-bearing and each is stated where it is enforced:

- :func:`_scan_lines` tests the exemption per (path, label) pair and does *not* stop a
  line's scan at an allowlisted match, so an exemption cannot hide a second label on
  the same line -- the break that used to end the line is what an exemption would have
  quietly become.
- the unreadable-file row is emitted by :func:`_scan_tracked_files`, outside the
  per-line loop, so it sits outside the exemption's reach by construction: an allowlist
  answers "may this path carry this label?", never "may this path go unread?".
- :func:`_tracked_listing` is the one listing both the scan and the stale-entry check
  ask, so the two cannot disagree about whether an allowlisted path exists.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import public_safety_io as _io
from .public_safety_allowlist import exempted_pairs

# The scan's own names for the two guards it applies to a tracked path. Bound here, and
# defined again in ``public_safety`` for the AST pins, so both modules of the scan answer
# to one guarded opener and one lenient reader.
_open_regular = _io.open_regular
_read_text_lenient = _io.read_text_lenient


def _scan_lines(rel: str, lines: list[str], patterns: list[tuple[object, str]],
                exempt: frozenset[tuple[str, str]] = frozenset(),
                is_self: bool = False) -> list[str]:
    """The ``path:line: label`` rows one file's lines earn, at most one per line.

    ``exempt`` is the set of (path, label) pairs the audited tree's committed allowlist
    permits, asked once per scan by the caller and tested here per pair -- never per file
    and never per line. The pair is the unit precisely so the one-label-per-line rule
    below cannot be turned into a hiding place: a line whose first match is allowlisted
    keeps being tested, so a second, non-allowlisted label on that same line is still
    reported.

    ``is_self`` arrives as a parameter rather than being looked up here: the self-file
    exemption is ``public_safety``'s rule and the caller owns it, so this module asks for
    the answer instead of reaching back into the module that imports it.
    """
    from .public_safety import _self_file_exempt

    rows = []
    for lineno, line in enumerate(lines, 1):
        # ``shown`` records the label this line already earned a row for. The loop no
        # longer stops at the first match -- an allowlisted match must not end the line's
        # scan -- and without this the break would have moved to the wrong place and one
        # line could earn two rows where before it earned one.
        shown = None
        for pattern, label in patterns:
            if shown is not None:
                break
            if _self_file_exempt(pattern, label, is_self):
                continue
            if not pattern.search(line):
                continue
            if (rel, label) in exempt:
                continue
            rows.append(f"{rel}:{lineno}: {label}")
            shown = label
    return rows


def _tracked_listing(repo: Path) -> list[str]:
    """The hardened ``git ls-files`` names of ``repo``, as ``git`` spells them.

    The scan's listing is a contract: run under the null-pinned host config, with
    fsmonitor, hooks and external transports disabled, and bounded at 30s, so a tree
    somebody else prepared cannot turn a read-only listing into execution or a hang.

    Extracted from the scan so the allowlist's stale-entry check asks the *same* listing
    the scan matched against: read through a second Git view, the two entry points could
    disagree about whether an allowlisted path exists, and a live exemption would report
    as stale (or a stale one as live) depending on which caller answered first.
    """
    # The tree being scanned is someone else's, so its config may not turn a read-only
    # listing into execution: core.fsmonitor names a helper git execs, core.hooksPath
    # redirects hooks, protocol.ext.allow enables external transport helpers, and a
    # repo-embedded config carrying any of them would otherwise run under the
    # scanner's privileges. The two config files a host may carry are pinned to the
    # null device for the same reason.
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
    return [rel.strip() for rel in result.stdout.split("\0") if rel.strip()]


def _scan_tracked_files(repo: Path, patterns: list[tuple[object, str]],
                        exempt: frozenset[tuple[str, str]] = frozenset()) -> list[str]:
    """The violations of every readable tracked file of ``repo``, as ``path:line: label``.

    ``exempt`` is the allowlisted (path, label) set, threaded to :func:`_scan_lines`
    unchanged; the default is the empty set, which is the pre-allowlist behaviour and
    what a caller that loaded no file gets.

    The self-file decision is asked of ``public_safety`` per path, so the exemption's
    own list stays where it was.
    """
    from .public_safety import UNREADABLE_TRACKED_FILE_LABEL, _is_self_file

    violations = []
    for rel in _tracked_listing(repo):
        result = _read_text_lenient(repo / rel)
        if result is None:
            continue
        lines, fault = result
        if lines is None:
            # A regular tracked file the scan could not open or read: reported, not
            # skipped, because a scan that never held the bytes cannot certify them. Line
            # 0 is the file itself, and the fault is named by its class and its errno
            # words -- never its message, which carries a path.
            detail = f"{fault[0]}: {fault[1]}" if fault[1] else fault[0]
            violations.append(f"{rel}:0: {UNREADABLE_TRACKED_FILE_LABEL} ({detail})")
            continue
        violations += _scan_lines(rel, lines, patterns, exempt, _is_self_file(rel))
    return violations


# The public spellings ``public_safety`` re-binds: patch targets and test seams, each the
# moved function re-exported rather than copied, so bending one bends the other.
scan_tracked_files = _scan_tracked_files
scan_lines = _scan_lines
tracked_listing = _tracked_listing

__all__ = [
    "exempted_pairs",
    "scan_lines",
    "scan_tracked_files",
    "tracked_listing",
]
