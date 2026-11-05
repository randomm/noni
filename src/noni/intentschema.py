"""The standing intent file's shape: the bytes ``intent.py`` writes and validates.

Mechanics, not the writer's contract: what ``noni/direction/intent.md`` looks like
on disk, the four level-2 headings it must carry in order, the one
``Last-confirmed:`` line, and the line cap the file must stay under. ``intent.py``
owns the verb, the exit codes and the commit; this module owns the form, so the
census's arbiter and the writer's refusal are held to one definition rather than
two.

The file is Markdown prose the operator reads first at session start, so there is
no canonical byte form to compare against (unlike ``order.json``, whose keys the
writer renders): the rules here are structural, not textual. A heading inside a
fenced code block is not a heading, which is why the walk tracks fences instead
of matching lines -- and why an unclosed opener is itself refused: a fence that
never closes would otherwise hide everything after it from both rules at once.
"""

from __future__ import annotations

import re
from datetime import date, datetime

# The artifact: one file, one writer. The census reads the same path from its
# own default (``<repo>/noni/direction/intent.md``).
INTENT_DIR = "noni/direction"
INTENT_FILE = "intent.md"
INTENT_REL = f"{INTENT_DIR}/{INTENT_FILE}"

# The four level-2 sections, in this order, each exactly once. The names are the
# contract: the writer refuses a file missing one and the census reports the same
# absence as a `section-missing` row, so a rename has to change both at once.
REQUIRED_SECTIONS: tuple[str, ...] = ("Purpose", "Principles", "Never", "Ask first")

# The line cap. The file is read first at every session start, so it stays a
# page an agent reads rather than a second ledger.
MAX_LINES = 200

# The stamp line: exactly one, of this shape.
LAST_CONFIRMED_PREFIX = "Last-confirmed:"

# The two subjects a structural problem is filed under, written into the problem
# text itself by ``problems`` below. They are the census's row subjects, and they
# live here because the sentences that carry them are written here: one file owns
# the words a refusal and a row both print, so neither can be renamed alone.
SUBJECT_OVER_CAP = "over-cap"
SUBJECT_SECTION_MISSING = "section-missing"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# One fence delimiter: three or more backticks or tildes, and nothing but an
# optional info string after it. Same shape the docs readers of this repository
# accept, so a template nobody could write is not what the rule checks.
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_HEADING = re.compile(r"^##(?!#)\s+(.*?)\s*$")


def is_stamp_line(line: str) -> bool:
    """Whether ``line`` is the ``Last-confirmed: YYYY-MM-DD`` line, prefix included.

    The line starts at column 0 with the prefix: an indented one is prose inside a
    list or a block and is not the stamp, so a draft that hides a second copy of
    it under an indent is refused rather than quietly given a second stamp by the
    writer's restamp (which restamps only a line this recognises).
    """
    if not line.startswith(LAST_CONFIRMED_PREFIX):
        return False
    return bool(DATE_RE.fullmatch(line[len(LAST_CONFIRMED_PREFIX):].strip()))


def stamp_line(day: date) -> str:
    """The one stamp line for ``day``, spelled the way the validator reads it."""
    return f"{LAST_CONFIRMED_PREFIX} {day.isoformat()}"


def parse_stamp(value: str) -> str | None:
    """The ``YYYY-MM-DD`` inside ``value``, or None when it holds no such date.

    ``datetime.fromisoformat`` accepts forms the contract does not (a bare
    ``2026-1-2``, an offset, a time), so the parsed value has to re-spell itself
    as the four-two-two digits the line carries.
    """
    raw = value.strip()
    if not DATE_RE.fullmatch(raw):
        return None
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None
    return parsed.strftime("%Y-%m-%d")


def _scan_fences(lines: list[str]) -> tuple[list[bool], str | None]:
    """Per line whether it sits inside a fenced block, plus a fence left open.

    The one fence-tracking the two rules share: ``_headings`` asks it for the
    heading lines and ``problems`` for the stamp line, so a block that hides a
    heading cannot reveal a stamp (or the other way round) and a change to what
    opens a block is one edit. A line that opens or closes a block is itself
    flagged: it is block syntax, not content either rule may read. The second
    value is the token of a block still open at the end of the file, or None;
    ``problems`` refuses that state, because the flags alone would hide the file's
    tail from both rules at once.
    """
    flags: list[bool] = []
    fence: str | None = None
    for line in lines:
        marker = _FENCE.match(line)
        if marker is not None:
            token = marker.group(1)[0]
            if fence is None:
                fence = token
            elif fence == token:
                fence = None
            flags.append(True)
            continue
        flags.append(fence is not None)
    return flags, fence


def _headings(lines: list[str]) -> list[str]:
    """The level-2 heading texts of ``lines``, in order, outside fenced blocks.

    A line inside a fence is not a heading: the template shows a worked example
    and an example whose headings counted would make the file un-writable. Takes
    the split lines because ``problems`` already has them and the fence state of a
    line depends on the whole list, not on one line at a time.
    """
    return [match.group(1)
            for line, fenced in zip(lines, _scan_fences(lines)[0], strict=True)
            if not fenced for match in [_HEADING.match(line)] if match is not None]


def problems(text: str) -> list[str]:
    """Why ``text`` is not an intent file the writer writes; [] when it is.

    One list, so the refusal the writer prints and the rows the census reports
    come from the same rules. Every entry is a fixed sentence naming a section or
    a rule, never a line read from the file: a row must not echo content the
    operator wrote.
    """
    found: list[str] = []
    lines = text.split("\n")
    fence_flags, open_fence = _scan_fences(lines)
    if len(lines) > MAX_LINES:
        found.append(f"{SUBJECT_OVER_CAP}: the file is {len(lines)} lines, over the "
                     f"{MAX_LINES} line cap")
    # The stamp rule reads the same fenced-block state the heading rule reads:
    # a line inside an example block is prose, whichever rule looks at it. Reading
    # the whole file instead would make the template un-writable the moment it
    # showed a reader what a stamp line looks like.
    stamps = [line for line, fenced in zip(lines, fence_flags, strict=True)
              if not fenced and is_stamp_line(line)]
    if not stamps:
        found.append(f"{SUBJECT_SECTION_MISSING}: no "
                     f"'{LAST_CONFIRMED_PREFIX} YYYY-MM-DD' line")
    elif len(stamps) > 1:
        found.append(f"{SUBJECT_SECTION_MISSING}: {len(stamps)} "
                     f"'{LAST_CONFIRMED_PREFIX}' lines, exactly one is allowed")
    seen = _headings(lines)
    for name in REQUIRED_SECTIONS:
        count = seen.count(name)
        if count == 0:
            found.append(f"{SUBJECT_SECTION_MISSING}: no '## {name}' heading")
        elif count > 1:
            # The subject prefix on every entry of this class, so a reader of one
            # refusal sentence can see which of the four rows the census files it
            # under without holding the whole rule set in its head.
            found.append(f"{SUBJECT_SECTION_MISSING}: '## {name}' appears {count} "
                         "times, exactly once is allowed")
    if not found:
        ordered = [name for name in seen if name in REQUIRED_SECTIONS]
        if ordered != list(REQUIRED_SECTIONS):
            found.append(f"{SUBJECT_SECTION_MISSING}: the four sections are out of "
                         "order: the file must carry "
                         + ", ".join(f"## {name}" for name in REQUIRED_SECTIONS)
                         + " in that order")
    if open_fence is not None:
        # Read last and reported last: a block that never closed is the reason the
        # two rules above may have seen nothing, so the sentence says what an
        # unclosed opener costs rather than leaving the file to look well-shaped.
        found.append(f"{SUBJECT_SECTION_MISSING}: an unclosed code fence (a line "
                     f"starting with 3 or more of '{open_fence}') leaves the rest of "
                     "the file inside it, hidden from the section and stamp rules")
    return found
