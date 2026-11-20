"""Reading the hook under integrations/pi/ and its page, for the suite that checks them.

The hook is a harness file the suite reads as text: CI installs no node toolchain, so
the page's live check carries behaviour and ``test_pi_extension.py`` carries shape.
This module holds the constants those checks measure against (paths, event names, line
bounds, compiled readers) and the readers themselves, so "the body of the per-turn
handler" has one definition. A helper module: never named ``test_*``.

Every reader locates its span by the text that names it: an event name for a
registration, a declaration for a function, a name at a word boundary for a value. A
reader that counted occurrences instead would answer for the wrong span the first time
two of its anchors sat in one clause, and a check over the wrong span is a check that
passes whatever the code does.
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
# The declarations the suite reads: the module-level helpers, the entry point, and the
# two fetch halves inside it. A name listed here and never read is an assertion nobody
# wrote, so this tuple and the callers in the suite are one list.
FUNCTIONS = ("stateRoot", "failureLine", "failureReason", "noniHook",
             "fetchBrief", "startBrief")
REGISTERED = re.compile(r'pi\.on\(\s*"([a-z_]+)"')
QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
# A whole template literal, so a check can take the literal's own characters apart
# rather than copy the sentence inside it. Backtick-delimited, as the hook writes them.
TEMPLATE = re.compile("```(?:\\\\\\\\.|[^`\\\\\\\\])*```".replace("```", "`"))
FAILURE_LINE = re.compile(r"(?:return|const \w+ =)\s*(`noni: could not read[^`]*`)")
# The clip expression itself, as one pattern: the cap's name, the value it compares,
# the value it shortens and the expression it shortens by, with the tail text after
# the plus. A check rebuilds the line from these parts and from the template literal,
# so neither the bound's value nor its arithmetic is copied here.
CLIP = re.compile(r"line\.length <= (\w+) \? (\w+) : (\w+)\.slice\(0, ([^)]+)\) \+ ([^;]+);")
# Every form of the spawn call, so the timeout rule reads the options object the
# command actually carries rather than the word "timeout" somewhere in the file.
SPAWN_CALL = re.compile(r"pi\.exec\((.*?)\)", re.DOTALL)

LINE_LIMIT = 300
FILE_LINE_LIMIT = 80

# U+2014, written as an escape so this file does not carry the character it bans.
EM_DASH = "\u2014"
# U+2026, the one character the hook itself writes as an escape.
ELLIPSIS = "\u2026"


def source() -> str:
    """The hook's source, with its absence reported as a missing file."""
    assert EXTENSION.is_file(), f"{EXTENSION} is missing"
    return EXTENSION.read_text(encoding="utf-8")


def registrations(text: str) -> list[str]:
    """The event names registered, in registration order."""
    return REGISTERED.findall(text)


def registration_head(text: str, event: str) -> int:
    """Where ``event`` is registered, found by its own event-name string.

    The event name is what makes the span the handler for that event. Counting
    ``pi.on(`` matches cannot: the gate both start events share holds two of them, so
    a count shifts a slice onto a neighbouring handler, and a check over the wrong
    handler answers a question nobody asked.
    """
    found = re.search('pi\\.on\\(\\s*"' + re.escape(event) + '"', text)
    assert found, f"{event} is not registered"
    return found.start()


def handler_body(text: str, event: str) -> str:
    """The registered handler for ``event``, sliced to the next registration.

    The span starts at the event's own registration and ends at the next registration
    anywhere in the file, so it holds one handler and nothing else. A check over such
    a slice is what makes "the brief is never fetched per turn" a claim about the
    per-turn handler, not about the file.
    """
    head = registration_head(text, event)
    later = [m.start() for m in REGISTERED.finditer(text) if m.start() > head]
    return text[head: min(later) if later else len(text)]


def function_body(text: str, name: str) -> str:
    """The declaration of ``name`` through its own closing brace.

    The declaration is matched at a word boundary, so a name that is the tail of a
    longer name cannot answer for it, and the end is the position where the brace
    depth returns to zero: a nested ``catch`` clause cannot end the span early and the
    file's final brace cannot extend it. A TypeScript parameter annotation may hold
    braces, so the count starts at the body's own opening brace, past the parameter
    list. Braces inside a template literal are skipped, which is all the hook needs;
    a brace in a single-quoted string would miscount, and the hook has none.
    """
    declaration = "(?:^|\\W)(?:async\\s+)?function\\s+" + re.escape(name) + "\\s*\\("
    found = re.search(declaration, text)
    assert found, f"function {name} is not declared"
    literals = [(m.start(), m.end()) for m in TEMPLATE.finditer(text)]
    depth = 0
    for index in range(text.index(")", found.start()) + 1, len(text)):
        if any(start <= index < end for start, end in literals):
            continue
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[found.start(): index + 1]
    raise AssertionError(f"function {name} never closes")


def start_gate(text: str) -> str:
    """The shared start gate and the two registrations that call it.

    Both start events run the same gate, so a check over this slice is a check over
    both handlers rather than over one of them, and the mode rule cannot be satisfied
    by a string sitting somewhere else in the file. The end is the per-turn handler's
    own registration, found by its event name, so the gate cannot grow into it.
    """
    start = text.index("const start = (")
    return text[start: registration_head(text, "before_agent_start")]


def template_parts(text: str) -> tuple[str, str]:
    """The failure template's own head and close, read from the hook.

    Both halves come from the template literal the cap applies to, so an expected
    line length is the reason's length plus what the hook itself wraps around it. A
    literal with no hole, or one that does not close its parenthesis, is not the
    failure line: the reader is what stops a check measuring the wrong string.
    """
    found = FAILURE_LINE.search(text)
    assert found, "the failure line is missing from the hook"
    literal = TEMPLATE.search(found.group(1))
    assert literal, "the failure line is not a template literal"
    hole = chr(36) + "{scrubbed}"
    head, gap, tail = literal.group(0)[1:-1].partition(hole)
    assert gap == hole and tail == ")", (
        f"the template is not head, reason, close: {literal.group(0)!r}")
    return head, tail


def string_literal(text: str, name: str) -> str:
    """The value of ``const NAME = "..." + "...";``, joined.

    The bound is measured on the joined string the model receives, so the scan
    stops at the semicolon ending the declaration and reads quoted pieces quote
    to quote, where an apostrophe in the sentence cannot end a piece early. The
    piece count must match the quote count, or a malformed read would pass the
    bound checks on half the sentence. Template literals are dropped first, so a
    sentence elsewhere in the file cannot answer for this one.
    """
    head = f"const {name} ="
    rest = text[text.index(head) + len(head):]
    end = re.search(r";\s*$", rest[: rest.index("\n\n")], re.MULTILINE)
    assert end, f"const {name} has no terminating semicolon"
    body = TEMPLATE.sub("", rest[: end.end()])
    pieces = QUOTED.findall(body)
    assert pieces and "".join(pieces).strip(), f"const {name} is empty"
    assert len(pieces) * 2 == body.count('"'), f"const {name} is malformed"
    joined = "".join(pieces)
    assert joined == joined.strip(), f"const {name} lost its spacing"
    return joined
