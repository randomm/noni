"""The one reader of the standing intent that the brief needs: its Purpose body.

Split from ``brief.py`` for the 500-line source cap (``tests/test_file_size_limit.py``),
along the seam the tool already had: ``brief.py`` owns the command line, the budget, the
blocks and what each prints, and this module owns the single read of
``noni/direction/intent.md`` that is not one line of output. The other artifact reads of
the tool (the order, the item store, the census run) are borrowed from the modules that
own them; this file is the one read the brief had to write itself, so it is the one file
beside the tool that holds it.

One rule keeps the shape of the tool honest: the brief has no verdict of its own about a
file it cannot read. Absent, a symlink, a directory, a device, unreadable bytes,
non-UTF-8 bytes, a file past its line cap, a missing or repeated heading, an unclosed
fence -- every one of those answers ``None`` here and prints the block header and the
one word :data:`brief.NOT_READ` there. The census's ``intent`` class is the arbiter that
names which of those states a tree is in, and it runs a moment later in the same process
to produce the brief's last line; a brief that echoed a fault would be a second report of
it, worded differently.
"""

from __future__ import annotations

from pathlib import Path

from . import intentschema, orderstate
from .intentschema_headings import heading_rows

# The section whose body the brief prints. Named through the schema's own ordered tuple
# rather than restated, so the section the direction skill documents first is the
# section the brief shows first and a rename of the contract moves both.
PURPOSE_SECTION = intentschema.REQUIRED_SECTIONS[0]


def purpose_block(path: Path, limit: int) -> tuple[list[str], int] | None:
    """The ``## Purpose`` body of ``path`` clipped to ``limit`` lines, and the cut, or None.

    The clip happens here rather than at the call site so the ellipsis question is
    answered by the one function that can see both the body and the cap: an ellipsis is
    owed when the block the caller asked for is not the whole body, and a caller holding
    only a list it truncated cannot tell that from a body that was always that long.
    The two halves travel together because they are one fact -- these are the lines, and
    how many of the body's lines the cap took -- and a caller that handled only one of
    them would print a clipped body with no mark that it was clipped.

    ``None`` is the answer for every state where there is no body to print (see this
    module's docstring for the list); a body empty after its blank lines are stripped is
    ``([], 0)``, which is a purpose of one line, not a fault.
    """
    body = purpose_body(path)
    if body is None:
        return None
    # The two halves travel together because they are one fact. A caller holding a list it
    # truncated cannot tell a body of exactly ``limit`` lines from one of ``limit`` + 1 whose
    # tail went missing, and the ellipsis is owed only by the second. The cut is computed from
    # the whole body, which is the only place the difference still exists, so a body of exactly
    # the cap is not a clipped body and owes nothing.
    return body[:limit], max(0, len(body) - limit)


def purpose_body(path: Path) -> list[str] | None:
    """The whole ``## Purpose`` body of ``path``, blank edges stripped, or None.

    The section question is asked through :mod:`noni.intentschema` and nowhere else: the
    fence-walking heading reader of the writer and the arbiter is the one that decides
    what a heading is, so a heading inside a worked example is prose here exactly as it
    is there.

    The body is located by line, not by an offset into a list of heading texts.
    ``heading_rows`` is the schema's own heading rule with the line numbers kept, which is
    what makes the range exact: the fence state of a line is still decided by the whole
    file, and the walk never re-derives what a heading is.
    """
    lines = _read_lines(path)
    if lines is None:
        return None
    rows = heading_rows(lines)
    opens = [index for index, heading in rows if heading == PURPOSE_SECTION]
    if len(opens) != 1:
        # The structural check in :func:`_read_lines` refuses a missing or repeated
        # heading before this is reached, so the only way to reach zero or two openings
        # is a heading the fence walk hid: an unclosed fence hides the file's tail from
        # the heading rule and the stamp rule at once. That state is the census's row.
        return None
    start = opens[0] + 1
    stop = next((index for index, _heading in rows if index >= start), len(lines))
    return _strip_blanks(lines[start:stop])


def _read_lines(path: Path) -> list[str] | None:
    """The lines of ``path`` that validate as an intent file, or None.

    The three questions in the order they are cheap to answer: what the path *is*
    (the ``lstat`` of :func:`noni.orderstate.file_kind`, the classification every reader
    of this family asks first -- never ``is_file()``, which follows a link and reports the
    file at its far end as this artifact), what its bytes say (the UTF-8 decode, which the
    census's own intent class refuses rather than reads), and whether the shape holds
    (``intentschema.problems``, the writer's rules, so a file the writer produced is never
    a file this reader calls broken).

    A declined ``lstat`` or ``read`` is caught beside the decode fault on purpose: both
    are the filesystem not answering, and the brief's contract is that a tree it cannot
    read still prints its sections and its summary line at exit 0. The census, which met
    the same fault a moment ago through its own readers, is the one that words it.
    """
    kind, _why = orderstate.file_kind(path)
    if kind != "regular":
        # Absent, a directory, a link, a device: one answer for all four, because a link
        # is not a file the brief reads through and each state is the census's row to word.
        return None
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        # ``ValueError`` is named because a name too long or an embedded null is what an
        # ``os.stat`` raises for a path the filesystem will not name: a refusal of the
        # path, not a crash of the run.
        return None
    if intentschema.problems(text):
        return None
    return text.splitlines()


def _strip_blanks(body: list[str]) -> list[str]:
    """``body`` without its leading and trailing blank lines.

    The body of a section is the prose under its heading. ``intent.py`` writes a blank
    line after a heading, and a block that printed it would open with an empty line
    under its own name; the trailing blanks are the same layout at the other end.
    """
    start = 0
    while start < len(body) and not body[start].strip():
        start += 1
    stop = len(body)
    while stop > start and not body[stop - 1].strip():
        stop -= 1
    return body[start:stop]
