"""The readers the pi hook suite shares: pure functions over ``noni.ts`` as text.

tests/test_pi_extension.py holds the assertions; the size gate
(``tests/test_file_size_limit.py``) caps a ``.py`` at 500 lines, so the text
readers those assertions are built on live here alongside the patterns they use.
Nothing in this module reads a path or asserts: each function takes the source
string and returns a slice, an offset, or a value, which is what lets the static
suite and any later check over the same file agree on one definition of "the body
of the per-turn handler".

Python's stdlib has no TypeScript parser, so these are character-shaped scans
rather than ``ast``-based readers of the kind other suites use
(``intent_class_ast.py``, ``fifo_ast_support.py``). Each one is deliberately
strict: a scan that found nothing has to be distinguishable from one that found
the wrong thing, which is why they assert rather than return a default.
"""

from __future__ import annotations

import re
from pathlib import Path

# The three registrations, in the order the ticket rules them.
REGISTERED = re.compile(r'pi\.on\(\s*"([a-z_]+)"')
EVENTS = ("session_start", "session_compact", "before_agent_start")
# The one spawn in the file. The per-turn handler is the last registration, so a
# spawn at or after it is a brief billed to every prompt.
SPAWN = re.compile(r'pi\.exec\("noni", \["brief", "--repo", root\]')
# The spawn as one expression, so the no-shell rule reads the options object the
# command actually carries rather than a word ban over the whole file.
SPAWN_CALL = re.compile(r'pi\.exec\([^)]*\)', re.DOTALL)
# The reminder is one quoted sentence per source line, joined by +. A quoted
# string runs to the next quote, which is why the scan is character-shaped rather
# than a line regex: the text carries an apostrophe.
QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
FAILURE_LINE = re.compile(r'(?:return|const \w+ =)\s*(`noni: could not read[^`]*`)')


def source_text(extension: Path) -> str:
    """The hook's source, with its absence reported as a missing file."""
    assert extension.is_file(), f"{extension} is missing"
    return extension.read_text(encoding="utf-8")


def registrations(source: str) -> list[str]:
    """The event names registered, in registration order."""
    return REGISTERED.findall(source)


def handler_body(source: str, event: str, events: tuple[str, ...] = EVENTS) -> str:
    """The registered handler for ``event``, sliced to the next registration.

    Registration order in the file is the order of ``events``, so the next
    ``pi.on("`` after this one is the handler's end. A check over a slice rather
    than over the whole file is what makes "the brief is never fetched per turn"
    a claim about the per-turn handler instead of a claim about the file.
    """
    starts = [match.start() for match in REGISTERED.finditer(source)]
    assert len(starts) == len(events), f"expected {len(events)} registrations"
    index = registrations(source).index(event)
    end = starts[index + 1] if index + 1 < len(starts) else len(source)
    return source[starts[index]:end]


def spawn_offsets(source: str) -> list[int]:
    """Where each ``noni brief`` spawn begins, as offsets into ``source``."""
    return [match.start() for match in SPAWN.finditer(source)]


def string_literal(source: str, name: str) -> str:
    """The value of ``const NAME = "..." + "...";``, joined.

    The reminder is written across a few lines for readability, so the bound is
    measured on the joined string the model receives, not on one fragment of it.
    The scan stops at the closing semicolon that ends the declaration (the
    sentence itself contains semicolons, so it is the one at the end of a line
    that ends it), and a quoted piece is read quote to quote so an apostrophe
    inside the sentence cannot end it early.

    Three assertions keep a vacuous read out: there has to be a piece, the quote
    count has to match the pieces found (a stray quote means the scan stopped in
    the wrong place), and the joined text has to keep its own spacing (a piece
    dropped by a bad boundary shows up as a lost space).
    """
    head = f"const {name} ="
    start = source.index(head)
    rest = source[start + len(head):]
    end = re.search(r";\s*$", rest[: rest.index("\n\n")], re.MULTILINE)
    assert end, f"const {name} has no terminating semicolon"
    pieces = QUOTED.findall(rest[: end.end()])
    assert pieces and "".join(pieces).strip(), f"const {name} is empty"
    assert len(pieces) * 2 == rest[: end.end()].count('"'), f"const {name} is malformed"
    joined = "".join(pieces)
    assert joined == joined.strip(), f"const {name} lost its spacing"
    return joined
