"""The two renderers every noni refusal prints its caller-supplied text through.

A refusal is two lines on stderr -- ``label: headline`` and ``label: fix: hint`` --
and both lines carry bytes somebody else chose: a path from a command line, git's own
output, a name from a working-copy marker. Two rules follow from that, and they are
not the same rule, which is why there are two functions rather than one with a flag.

Control bytes are dropped in both: an ANSI or OSC sequence must not reach the
terminal from a string the program did not write, and the tail past the limit is
dropped so one huge blob cannot crowd out everything else.

:func:`safe_text` keeps newlines, because the text it was written for is git's, and
git's output is multi-line by nature -- a status block, a hook's complaint. A path
must not keep them: a filename may legally hold a newline, so a crafted name would add
lines to a two-line refusal and could make them read like noni's own messages.
:func:`safe_path` shows newline and carriage return as ``\\n`` and ``\\r`` instead,
the way git quotes such a name in its own output, so one path is always one line --
and escapes a backslash the name itself carries as ``\\\\``, so that one path can
never print as another path's escape.

This module imports nothing from the package: the text renderers are the bottom of the
dependency order, and both ``_session_git`` and ``_session_paths`` reach them without
importing each other.
"""

from __future__ import annotations

import functools
import unicodedata

# How much of any one rendered string reaches the terminal. The limit is a shared
# constant rather than a per-call argument because the operators' constraint is
# shared too: one refusal should not crowd out the rest of a run's output.
TEXT_LIMIT = 500


def is_control_char(ch: str) -> bool:
    """Whether ``ch`` is a character no argv element may carry: any Unicode category C.

    The predicate, not a materialised set. The same question once answered by a
    893k-entry ``frozenset`` built at import -- about a quarter of a second spent on
    every writer start to enumerate code points nobody passes -- is answered here by
    one ``unicodedata.category`` call, which is what the enumeration asked in the
    first place. The answer covers C0 (``\x00``-``\x1f``) and DEL (``\x7f``), the C1
    range (``\x85`` NEL), the format characters (``\u202e`` RIGHT-TO-LEFT OVERRIDE,
    zero-width joiners, ``\ufeff``) and the surrogates: the C1 and format cases are
    the interesting ones, since neither is an ASCII control byte and both survive
    ``str.strip()``.
    """
    return unicodedata.category(ch)[0] == "C"


@functools.lru_cache(maxsize=1)
def control_chars() -> frozenset[str]:
    """Every code point :func:`is_control_char` admits, built on first call.

    The set form exists for exactly one caller: a test that sweeps a refused name
    against every control byte in turn wants a container to iterate. Building it at
    import bought nothing -- no product path enumerates the code points -- and cost
    about a quarter of a second on every writer start. The cache makes the sweep
    cost what the sweep costs, once, and costs an ordinary import nothing.
    """
    return frozenset(chr(cp) for cp in range(0x110000) if is_control_char(chr(cp)))


# The name a caller may import, resolved the first time it is read rather than at
# import: reading the module attribute is what builds the set.
def __getattr__(name: str) -> object:
    if name == "CONTROL_CHARS":
        return control_chars()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def safe_text(text: str, limit: int = TEXT_LIMIT) -> str:
    """Render text for the terminal: bounded, no control bytes.

    Control characters other than newline and space are dropped, so an ANSI or OSC
    sequence cannot reach the terminal, and the tail past ``limit`` is dropped so one
    huge blob cannot crowd out everything else. Newlines survive: this is the
    renderer for text that is legitimately multi-line (git's own output).
    """
    kept = []
    for ch in text:
        if ch == "\n" or ch == " " or not is_control_char(ch):
            kept.append(ch)
    cleaned = "".join(kept)
    if len(cleaned) > limit:
        return cleaned[:limit] + "... [truncated]"
    return cleaned


def safe_path(text: object, limit: int = TEXT_LIMIT) -> str:
    """Render one path for the terminal: one line, no control bytes, bounded, and
    one-to-one.

    :func:`safe_text` keeps newlines, which is right for git's output and wrong for a
    path: a filename may hold a newline, and a refusal is printed as exactly two
    lines (the headline and the fix), so a crafted path would otherwise inject extra
    stderr lines of its own. Newline and carriage return are shown as ``\\n`` and
    ``\\r`` instead -- the way git quotes such a name -- and every other control byte
    is dropped and the tail bounded exactly as :func:`safe_text` does.

    A backslash the name itself carries is escaped FIRST, before the two above, and
    that order is what makes the rendering one-to-one. Without it a name holding a
    backslash and an ``n`` (``a\\nb`` is a legal POSIX filename) prints exactly as a
    name holding a real newline does, and the operator who follows the path in the
    refusal reads -- or replaces -- a file nobody named. Backslash is also the one
    character that makes the two orders of a refusal differ, which is why the guard
    renders every path through this function once and composes its sentences with it,
    never with :func:`safe_text` over a line that already holds a rendered path (see
    :func:`noni._session_paths._answer`).
    """
    backslashed = str(text).replace("\\", "\\\\")
    return safe_text(backslashed.replace("\n", "\\n").replace("\r", "\\r"), limit)
