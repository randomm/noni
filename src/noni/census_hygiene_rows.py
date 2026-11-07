"""How a hygiene finding is parsed and worded: the split, and the state words.

Split out of ``census_hygiene.py`` along the seam the committed allowlist opened (the
500-line cap of ``tests/test_file_size_limit.py`` has no override, and the class needed
room for the allowlist's verdict). ``census_hygiene`` owns the scan it runs and the rows
it appends; this module owns the two questions asked of a finding once the scan handed it
over: is this string a ``path:line: label`` row the checker can have emitted, and what
word does the report use for the state the checker found.

Both are read by the class beside this file, and re-bound there as its own names: the
census re-exports ``_split_violation`` for its tests, and a re-export of one object is
how the seam stays one object rather than two that can drift.

The label vocabulary is never hard-coded here either. ``_hygiene_labels`` reads the
tables off the live checker module and this module only consumes the set, so a label
public_safety adds shows up in the split without an edit on this side -- and a label it
never emitted stays a verbatim row, which is the honest answer about a finding the
checker does not recognise.
"""

from __future__ import annotations


def _split_violation(violation: str, labels: set[str]) -> tuple[str, int, str] | None:
    """Split a public_safety violation into (path, line, label-as-emitted), or None.

    The third field is the row's tail verbatim, so a row that names a fault keeps it in
    the report: the unreadable-file class spells the refusing syscall's class and errno
    words after its label, and those words are the finding.

    Splitting cannot count colons: a tracked path may contain one ("x:y/p.txt" is legal),
    so splitting at the first truncates the path and garbles the message -- which also
    breaks the documented (artifact, check, subject) grouping. The label is a fixed
    string from public_safety's own tables and holds no colon, so the tail is matched
    against the known label set exactly and everything before ":<line>: " is the path. A
    label match is only the start of the check: the head must still parse as
    "<path>:<digits>", which stops a shorter label appearing partway through a longer one
    from claiming the row.
    """
    if not labels:
        return None
    for label in labels:
        suffix = f": {label}"
        # A label that is not the tail of the row is not the split, unless the row is a
        # fault row: "<path>:<line>: <label> (<fault>)".
        if violation.endswith(suffix):
            head, tail = violation[: -len(suffix)], label
        else:
            head, tail = _fault_row_head(violation, suffix)
        if head is None:
            continue
        path, sep, line_no = head.rpartition(":")
        if sep and path and line_no.isdigit():
            return path, int(line_no), tail
        # The tail matched but the head is not "<path>:<digits>": this label is not the
        # split, and a later one may match the same tail with a head that parses.
        continue
    return None


def _fault_row_head(violation: str, suffix: str) -> tuple[str | None, str]:
    """The head and label tail of "<path>:<line>: <label> (<fault>)", or (None, "").

    The one shape where a label is not the last thing in the row. A paren alone is not
    enough to claim it: the tail must read as one fault -- "Class: errno words" or the
    bare class, so at most one colon -- or it stays a verbatim row.
    """
    marker = suffix + " ("
    if not violation.endswith(")") or marker not in violation:
        return None, ""
    head, _, fault = violation.partition(marker)
    if not fault.endswith(")") or fault.count(":") > 1:
        return None, ""
    return head, f"{suffix[2:]} ({fault}"
