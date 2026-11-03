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
the way git quotes such a name in its own output, so one path is always one line.

This module imports nothing from the package: the text renderers are the bottom of the
dependency order, and both ``_session_git`` and ``_session_paths`` reach them without
importing each other.
"""

from __future__ import annotations

import unicodedata

# How much of any one rendered string reaches the terminal. The limit is a shared
# constant rather than a per-call argument because the operators' constraint is
# shared too: one refusal should not crowd out the rest of a run's output.
TEXT_LIMIT = 500


def _is_control_char(ch: str) -> bool:
    """Whether ``ch`` is a category-C character, which no argv element carries."""
    return unicodedata.category(ch)[0] == "C"


CONTROL_CHARS = frozenset(chr(cp) for cp in range(0x20, 0x100000)
                          if _is_control_char(chr(cp))) | \
    frozenset(map(chr, range(0x20))) | frozenset({"\x7f"})


def safe_text(text: str, limit: int = TEXT_LIMIT) -> str:
    """Render text for the terminal: bounded, no control bytes.

    Control characters other than newline and space are dropped, so an ANSI or OSC
    sequence cannot reach the terminal, and the tail past ``limit`` is dropped so one
    huge blob cannot crowd out everything else. Newlines survive: this is the
    renderer for text that is legitimately multi-line (git's own output).
    """
    kept = []
    for ch in text:
        if ch == "\n" or ch == " " or not _is_control_char(ch):
            kept.append(ch)
    cleaned = "".join(kept)
    if len(cleaned) > limit:
        return cleaned[:limit] + "... [truncated]"
    return cleaned


def safe_path(text: object, limit: int = TEXT_LIMIT) -> str:
    """Render one path for the terminal: one line, no control bytes, bounded.

    :func:`safe_text` keeps newlines, which is right for git's output and wrong for a
    path: a filename may hold a newline, and a refusal is printed as exactly two
    lines (the headline and the fix), so a crafted path would otherwise inject extra
    stderr lines of its own. Newline and carriage return are shown as ``\\n`` and
    ``\\r`` instead -- the way git quotes such a name -- and every other control byte
    is dropped and the tail bounded exactly as :func:`safe_text` does.
    """
    return safe_text(str(text).replace("\n", "\\n").replace("\r", "\\r"), limit)
