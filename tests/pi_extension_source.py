"""Reading the hook under integrations/pi/ and its page, for the suite that checks them.

The hook is a harness file the suite reads as text: CI installs no node toolchain, so
the page's live check carries behaviour and ``test_pi_extension.py`` carries shape.
This module holds the constants those checks measure against (paths, event names, line
bounds, compiled readers) and the readers themselves, so "the body of the per-turn
handler" has one definition. A helper module: never named ``test_*``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PI_DIR = REPO / "integrations" / "pi"
EXTENSION = PI_DIR / "noni.ts"
HOOK_README = PI_DIR / "README.md"
HOOK_FILES: tuple[Path, ...] = (EXTENSION, HOOK_README)

EVENTS = ("session_start", "session_compact", "before_agent_start")
REGISTERED = re.compile(r'pi\.on\(\s*"([a-z_]+)"')
QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
FAILURE_LINE = re.compile(r"(?:return|const \w+ =)\s*(`noni: could not read[^`]*`)")
# Every form of the spawn call, so the timeout rule reads the options object the
# command actually carries rather than the word "timeout" somewhere in the file.
SPAWN_CALL = re.compile(r"pi\.exec\((.*?)\)", re.DOTALL)

LINE_LIMIT = 300
FILE_LINE_LIMIT = 80

# U+2014, written as an escape so this file does not carry the character it bans.
EM_DASH = "\u2014"


def source() -> str:
    """The hook's source, with its absence reported as a missing file."""
    assert EXTENSION.is_file(), f"{EXTENSION} is missing"
    return EXTENSION.read_text(encoding="utf-8")


def registrations(text: str) -> list[str]:
    """The event names registered, in registration order."""
    return REGISTERED.findall(text)


def handler_body(text: str, event: str) -> str:
    """The registered handler for ``event``, sliced to the next registration.

    Registration order is the order of ``EVENTS``, so the next ``pi.on("`` is the
    handler's end. A check over a slice is what makes "the brief is never fetched
    per turn" a claim about the per-turn handler, not about the file.
    """
    starts = [m.start() for m in REGISTERED.finditer(text)]
    assert len(starts) == len(EVENTS), f"expected {len(EVENTS)} registrations"
    index = registrations(text).index(event)
    return text[starts[index]: starts[index + 1] if index + 1 < len(starts) else len(text)]


def function_body(text: str, name: str) -> str:
    """The body of ``function name(`` up to its closing brace at column 4.

    The scan starts inside the body, so a nested ``catch`` clause (whose brace sits
    at column 4 too) cannot end the slice early: the position searched is the one
    after the body's own opening brace, at column 2.
    """
    start = text.index(f"function {name}(")
    stop = text.index("\n  }", text.index("{", start))
    return text[start:stop]


def start_gate(text: str) -> str:
    """The shared start gate and the two registrations that call it.

    Both start events run the same gate, so a check over this slice is a check over
    both handlers rather than over one of them, and the mode rule cannot be satisfied
    by a string sitting somewhere else in the file.
    """
    start = text.index("const start = (")
    return text[start: text.index('pi.on("before_agent_start"', start)]


def string_literal(text: str, name: str) -> str:
    """The value of ``const NAME = "..." + "...";``, joined.

    The bound is measured on the joined string the model receives, so the scan
    stops at the semicolon ending the declaration and reads quoted pieces quote
    to quote, where an apostrophe in the sentence cannot end a piece early. The
    piece count must match the quote count, or a malformed read would pass the
    bound checks on half the sentence.
    """
    head = f"const {name} ="
    rest = text[text.index(head) + len(head):]
    end = re.search(r";\s*$", rest[: rest.index("\n\n")], re.MULTILINE)
    assert end, f"const {name} has no terminating semicolon"
    body = rest[: end.end()]
    pieces = QUOTED.findall(body)
    assert pieces and "".join(pieces).strip(), f"const {name} is empty"
    assert len(pieces) * 2 == body.count('"'), f"const {name} is malformed"
    joined = "".join(pieces)
    assert joined == joined.strip(), f"const {name} lost its spacing"
    return joined
