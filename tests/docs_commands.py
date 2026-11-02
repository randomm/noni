"""Reading fenced commands out of the product's prose pages, as argv.

The quickstart (``docs/QUICKSTART.md``) promises that a reader can copy its
blocks and get exit 0. The only way to check that promise without re-typing it
is to read the page the way ``tests/readme_support.py`` reads the README: parse
the fences, split each line into argv, and run the result. This module owns the
reading half of that, and nothing else: no promise, no assertion about content.

Two decisions belong here rather than in the test module:

- **Which lines are commands.** A line beginning ``#`` is the page's own prose
  inside a fence, not something the reader runs, so it is dropped before
  splitting. That exemption is safe for the recipe this page carries because a
  shell comment starts with the two-character sequence ``#`` followed by a space
  or end of line, and no non-comment line of a POSIX shell may begin with it
  (the shell reads ``#`` as the start of a comment in command position), so no
  real command can hide behind the rule. The placeholder lines of the quickstart
  are comments for the same reason, which is why they are dropped rather than
  refused: they name a value the reader fills from their own run.
- **What a line must lex as.** A command the test cannot split with
  ``shlex`` is not a command, so the reader refuses it here rather than letting
  a test run something other than what the page printed.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

# A fence opener or closer: three or more backticks or tildes, an optional info
# string, and nothing else on the line. Same shape ``readme_support`` parses.
_FENCE = re.compile(r"(`{3,}|~{3,})\s*(\S*)\s*")

# One command position in a fence: prose (a shell comment) is skipped, and a
# backslash at the end of a line continues the command onto the next.
_COMMENT = "#"


def fenced_pairs(text: str) -> list[tuple[str, list[str]]]:
    """The ``(info string, lines)`` pairs of every fenced block, unfiltered.

    The shared fence reader: :func:`fenced_blocks` filters these by info string,
    and ``readme_support._fenced_blocks`` keeps the pairs so a caller can select
    more than one kind of block from one parse. An unterminated fence is a
    malformed page, raised rather than handed over as a partial read.
    """
    blocks: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    for line in text.splitlines():
        fence = _FENCE.fullmatch(line)
        if fence and current is None:
            current = (fence.group(2), [])
            continue
        if fence and current is not None and line.startswith(fence.group(1)[0]):
            blocks.append(current)
            current = None
            continue
        if current is not None:
            current[1].append(line)
    assert current is None, "page has an unterminated code fence"
    return blocks


def fenced_blocks(text: str, *, info: str | None = "bash") -> list[list[str]]:
    """The lines of every fenced block of the page, one list per block.

    ``info`` selects blocks by fence info string (``"bash"`` is the quickstart's
    convention); None takes every block whatever its info string. An unterminated
    fence is a malformed page, not a partial read: the page that leaves a block
    open would silently hand its whole tail to the caller as commands.
    """
    return [lines for block_info, lines in fenced_pairs(text)
            if info is None or block_info == info]


def comment_lines(lines: list[str]) -> list[str]:
    """The prose lines inside a block: a line whose first character is ``#``.

    A shell never runs such a line (``#`` in command position starts a comment),
    so these are the page talking to the reader rather than a command.
    """
    return [line for line in lines if line.strip().startswith(_COMMENT)]


def non_comment_lines(lines: list[str]) -> list[str]:
    """The lines a reader actually runs: everything ``comment_lines`` excludes."""
    return [line for line in lines if not line.strip().startswith(_COMMENT)]


def block_commands(lines: list[str]) -> list[list[str]]:
    """The commands of one block as argv lists, continuations joined.

    Split with ``posix=True`` so the argv is what a reader's shell hands the
    program, quotes removed. An unbalanced quote fails here rather than running
    something the page never printed.
    """
    commands: list[list[str]] = []
    pending: list[str] = []
    for line in non_comment_lines(lines):
        stripped = line.strip()
        if not stripped:
            continue
        continued = stripped.endswith("\\")
        pending.append(stripped[:-1].rstrip() if continued else stripped)
        if not continued:
            joined = " ".join(pending)
            pending = []
            try:
                commands.append(shlex.split(joined, posix=True))
            except ValueError as exc:
                raise AssertionError(f"page command does not lex: {joined!r} ({exc})") from exc
    assert not pending, "page block ends in a line continuation"
    return commands


def placeholder_words(text: str) -> list[str]:
    """The ``<angle-bracket>`` words the page asks the reader to fill in.

    A token of that shape is a value the page cannot know (a session id, a
    record id), so the test supplies one rather than running the literal.
    """
    return re.findall(r"<[\w./ -]+>", text)


def read(path: Path) -> str:
    """The page's text, with the missing file named as the failure it is."""
    assert path.is_file(), f"{path.name} is missing"
    return path.read_text(encoding="utf-8")
