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
# The scrub's declaration, as one pattern: the constant's name, the body of its regex
# literal, and the global flag that ends it. The body is a run of escape pairs and ordinary
# characters, so the closing slash of the literal is the first unescaped one and an escaped
# slash inside the pattern cannot end the span early. The escape pair has to come first in
# the alternation: read the other way round, the two characters of a doubled backslash are
# two ordinary characters, the class swallows the slash that closes the literal, and a real
# declaration reads as a missing one.
PATH_TOKEN = re.compile("const PATH_TOKEN = /((?:\\\\.|[^/])+)/g;")
# The syntax the scrub's pattern is allowed to be built from, token by token. A pattern
# that compiles under Python re while meaning something else in JavaScript lets the suite
# pass and the hook leak, so the subset is stated positively rather than as a list of
# named bans: an escape pair, a character class, the opening of a non-capturing group, a
# repetition operator, or one character with no special meaning in either engine.
# Lookahead, lookbehind, atomic groups, named groups, inline-flag groups, alternation,
# capturing groups, anchors, braces and ``\p`` classes have no token here, so a pattern
# that used one could not be read as the subset. Each token's own metacharacters are kept
# out of the plain-character class, so a construct cannot hide inside a literal run. The
# escape pair names its three escapes rather than any non-alphanumeric, so ``\u0041`` and
# ``\p{L}`` are refused. The class token admits only class members, and a class member is a
# plain character or one of those three escapes: ``]`` closes a class, so the body cannot
# hold it, and every other escape is outside the subset. An empty class has a body shorter
# than one member (``[]`` holds nothing, ``[^]`` holds only the negation), so both are refused.
# No token covers a brace, so a counted repetition is refused rather than read as a run of
# plain characters, and a brace may not stand as a literal either.
SUBSET_TOKENS = re.compile(
    "(?:"
    + r"\\[s/\\]"  # an escape pair: the three the scrub can carry, and no other
    + "|"
    + r"\[\^?(?:[^\]\\\n]|\\[s/\\]){1,}\]"  # a class, negated or not, over at least one member (an escape may be a member; a body of none is refused)
    + "|"
    + re.escape("(?:")  # the opening of a non-capturing group
    + "|"
    + re.escape(")")  # the close of the group it opened
    + "|"
    + r"[+*?]"  # a repetition operator
    + "|"
    + r"[^\\[(+*?^$*+.?|\])\s{}]"  # one character with no meaning in either engine
    ")")
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


def path_token(text: str, expected: str | None = None) -> str:
    """The body of the hook's ``PATH_TOKEN`` literal, read out of the hook's own text.

    ``expected``, when given, is the pattern text the caller believes is declared, and the
    read-back must equal it character for character. Without that second look a mutation
    that never applied would leave the real pattern in place and its check would still
    pass, which is the opposite of what a mutation is for. A declaration that is missing,
    empty or malformed fails the read rather than leaving a check to scrub with nothing.
    """
    found = PATH_TOKEN.search(text)
    assert found, "the path pattern is missing from the hook"
    body = found.group(1)
    assert body, "the path pattern is empty"
    if expected is not None:
        assert body == expected, f"the hook declares {body!r}, not {expected!r}"
    return body


def path_token_flags(text: str) -> str:
    """The flags on the hook's ``PATH_TOKEN`` literal, read from after its closing slash.

    ``path_token`` returns the body alone, so nothing it hands back can say whether the
    scrub replaces every path in a line or the first one only. The reader requires the same
    ``/g;`` the body reader does, so a declaration that lost the flag fails the read rather
    than answering with an empty flag string.
    """
    found = PATH_TOKEN.search(text)
    assert found, "the path pattern is not declared with the global flag"
    end = text.index("/", found.end(1))
    return text[end + 1: found.end() - 1]


def path_token_is_portable(body: str) -> None:
    """Reject a pattern built from syntax the two engines do not read alike.

    JavaScript runs the pattern in the hook and Python re runs the same text in the
    suite. ``body`` must compile and every token of it must be one the whitelist names,
    so a construct only one engine understands stops the check by name at the position
    where it stands instead of being tested as if both engines agreed. A body Python
    cannot compile is reported the same way: a bare ``re.error`` escaping the reader
    would look like a broken suite rather than like a pattern the hook may not declare.
    """
    try:
        re.compile(body)
    except re.error as error:
        raise AssertionError(f"the pattern does not compile under Python re: {error}") from error
    position = 0
    while position < len(body):
        token = SUBSET_TOKENS.match(body, position)
        assert token, (
            f"the pattern uses syntax outside the shared subset at {body[position:]!r}")
        position = token.end()


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
