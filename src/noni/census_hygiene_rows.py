"""How the hygiene class turns a scan's output into rows.

Split from ``census_hygiene.py`` the way the intent readers were split from the
intent class: that module owns the class, its probe-honesty verdicts and the
loader of the checker it runs, and this one owns the three ways a scan's output
becomes a row. Each is small, and each is the answer to a different question the
reporter asks about a string ``public_safety`` handed back:

- :func:`partition_skip_notes` — is this line a finding about a file, or the
  scan's own statement that it could not open some files at all?
- :func:`split_violation` — does this line have the ``path:line: label`` shape a
  finding has, and what are its three parts?
- :func:`denylist_state` — which inactive state did the deny-list half land in?

The three share one rule: a row is built from the fields the producer has, and
refuses to guess at the ones it does not. A shape that does not parse is reported
verbatim rather than garbled, and a status this module has never seen surfaces
under its own name rather than being mapped onto a neighbouring word.

``census.py`` re-exports all three beside the ones it already re-exports from
``census_hygiene``, so the census keeps its single owner of each rule while a
caller (and the census's own tests) still names them through ``census``.
"""

from __future__ import annotations

from typing import Any


def partition_skip_notes(violations: list[str],
                         public_safety: Any) -> tuple[list[str], list[str]]:
    """The scan's skip notes and its findings, given the checker that made them.

    A skipped non-regular path is not a violation of a file: nothing was read,
    so nothing was found, and the finding is that the scan could not look. Such
    a line carries no ``path:line`` and no label, so it must not reach
    :func:`split_violation` (which would refuse it) nor the verbatim branch
    (which would print it under a filename-shaped subject and artifact that no
    file owns). The marker is the constant the checker declares for it — read
    off the module this class actually ran, not a copy, so a seam on the checker
    cannot leave the two halves disagreeing — and it is matched as a prefix, so a
    violating line that merely quotes the phrase still splits as the line it is.
    """
    marker = getattr(public_safety, "NONI_SKIP_NOTE_MARKER", "")
    if not marker:
        # A checker that declares no marker has no skip notes: everything it
        # returned is a finding, which is the behaviour from before the skip
        # row existed and the safe reading for a checker this census cannot ask.
        return [], list(violations)
    notes = [v for v in violations if v.startswith(marker)]
    findings = [v for v in violations if not v.startswith(marker)]
    return notes, findings


def split_violation(violation: str, labels: set[str]) -> tuple[str, int, str] | None:
    """Split a public_safety violation "<path>:<line>: <label>" into parts.

    Returns (path, line, label) or None when the string is not of that shape.

    Splitting cannot be done by counting colons: a tracked path may contain
    one ("x:y/p.txt" is a legal POSIX filename), so splitting at the first
    colon truncates the path and garbles the message — which also breaks the
    documented (artifact, check, subject) sort grouping, because artifact
    becomes the path prefix before the colon. The label is a fixed string from
    public_safety's own tables and contains no colon, so the tail is matched
    against the known label set exactly and everything before ":<line>: " is
    the path.
    """
    if not labels:
        return None
    for label in labels:
        suffix = f": {label}"
        if not violation.endswith(suffix):
            continue
        head = violation[: -len(suffix)]
        path, sep, line_no = head.rpartition(":")
        if sep and path and line_no.isdigit():
            return path, int(line_no), label
        # The suffix matched but the head is not "<path>:<digits>". This label
        # is not the split; a later one in the set may match the same tail with
        # a head that does parse, so keep looking instead of giving up.
        continue
    return None


def denylist_state(denylist: Any) -> str:
    """Render the deny-list's inactive state word from its result.

    public_safety owns the statuses; this only maps them to a word. The mapping
    is three lines of the census's own reporting — `status` for a file that is
    absent or unreadable, and the comments-only case that loaded "ok" with no
    entries. A status public_safety adds later surfaces under its own name here
    rather than being silently mislabelled. The caller has already established
    the class is inactive, so "ok" with entries cannot reach this function.
    """
    status = getattr(denylist, "status", "absent")
    if status != "ok":
        return str(status)
    return "present but empty" if not getattr(denylist, "entries", []) else "ok"
