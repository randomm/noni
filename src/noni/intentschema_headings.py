"""The fence-walking level-2 heading reader of the intent file, as a line map.

Split from ``intentschema.py`` for the 500-line source cap and placed beside the module
whose rules it serves. ``intentschema.problems`` already asks this question of a file: which
lines are headings, given that a line inside a fenced code block is prose and a fence that
never closes hides the file's tail. The brief asks the same question one step later -- it
wants the body of the section between two of those headings -- and a second fence walk would
be a second answer about which lines are headings, which is how a template that one of the
two can write and the other cannot comes to exist.

One rule, one owner: the fence walk and the heading pattern live in
:mod:`noni.intentschema` and this module composes them into the shape a reader of a *range*
of lines needs. It holds no rule of its own.

:data:`intentschema._headings` answers headings in order and carries no line numbers, so the
offset of a heading in that list is not the line it stands on -- and a caller that sliced a
body by that offset got the wrong range for any file whose headings are not the first lines
it holds, which is every intent file the writer produces (a title and the stamp line sit
above them). :func:`heading_rows` is the same answer with the line numbers kept, and it is
derived from the schema's own fence walk and heading pattern rather than from a re-reading
of the heading rules.
"""

from __future__ import annotations

from noni.intentschema import _HEADING, _scan_fences


def heading_rows(lines: list[str]) -> list[tuple[int, str]]:
    """The ``(line index, heading text)`` pairs of ``lines``, in order.

    The pairs :func:`noni.intentschema._headings` would answer as a bare list of texts, with
    the line each one stands on kept beside it. Same two rules and the same instances: the
    fence state of a line comes from ``_scan_fences`` over the whole list (so a heading
    inside a worked example stays prose) and the text comes from ``_HEADING`` (so a fourth
    hash is a sub-heading of the section above it and not a section of its own).

    ``lines`` is the split file rather than its text because the fence state of one line
    depends on the lines before it -- the same reason ``problems`` splits once and hands the
    one list to both of its rules.
    """
    fenced, _open_fence = _scan_fences(lines)
    rows: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if fenced[index]:
            continue
        match = _HEADING.match(line)
        if match is not None:
            rows.append((index, match.group(1)))
    return rows
