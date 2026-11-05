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

# A fence line: three or more backticks or tildes, an optional info string, and
# nothing else on the line, with up to three spaces of leading indentation. The
# indentation is part of the shape because a renderer reads an indented fence as a
# fence too (this repository's own docs/PUBLISHING.md carries three of them inside
# a numbered list), so a reader that missed them would report a clean page for a
# page that opens a block. Group 1 is the indent, group 2 the fence characters and
# group 3 the whole info string -- ``\S*`` would stop at the first space and report
# a fence tagged ``bash title=x`` as untagged. A caller that pairs blocks compares a
# closer against the opener's own indent, so prose indented less than a fence opened
# inside a list cannot close it by accident.
_FENCE = re.compile(r"([ ]{0,3})(`{3,}|~{3,})\s*([^`]*?)\s*")


def fence_openers(text: str) -> list[str]:
    """The leading info token of every fence a page opens, in order, with no pairing.

    ``fenced_pairs`` raises on an unterminated fence, which is the right answer for
    a caller that reads the blocks and the wrong one for a caller that counts them:
    a page whose whole point is that it prints no command-bearing fence is exactly
    the page whose fence count is asserted, and it must be counted whether or not
    the fences pair. The leading token of each opener's info string is what a caller
    compares, so ``test_..._prints_no_command_in_any_fence`` can name the tag it
    refuses.

    Two shapes a rewrite reaches for are read as openers rather than missed:

    - **Indented by one to three spaces**, because a renderer renders it as a
      fence. A census that refused only column-zero fences would be closed by one
      space of indent, which prints the same copyable block.
    - **Carrying an info string with metadata** (`` ```bash title=x ``), because
      the tag is still ``bash``. The whole info string is compared at the pair and
      never against a known tag, so returning it verbatim here would report a
      metadata-bearing fence as untagged and a caller filtering on a non-empty tag
      would let the copyable block through.
    """
    return [(match.group(3).split() or [""])[0]
            for line in text.splitlines()
            if (match := _FENCE.fullmatch(line))]

# One command position in a fence: prose (a shell comment) is skipped, and a
# backslash at the end of a line continues the command onto the next.
_COMMENT = "#"


def fenced_pairs(text: str) -> list[tuple[str, list[str]]]:
    """The ``(info string, lines)`` pairs of every fenced block, unfiltered.

    The shared fence reader: :func:`fenced_blocks` filters these by info string,
    and ``readme_support._fenced_blocks`` keeps the pairs so a caller can select
    more than one kind of block from one parse. An unterminated fence is a
    malformed page, raised rather than handed over as a partial read.

    An opener may be indented up to three spaces (a renderer reads it as a fence
    either way), and its closer then has to carry that same indentation: the closer
    is matched against the opener's own indent, so prose indented less than a fence
    opened inside an ordered list cannot close it by accident. The info string is
    returned whole -- a caller selecting ``"bash"`` blocks gets only fences tagged
    exactly that, which is what the quickstart's runner copies.
    """
    blocks: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    indent = ""
    for line in text.splitlines():
        fence = _FENCE.fullmatch(line)
        if fence and current is None:
            indent, current = fence.group(1), (fence.group(3), [])
            continue
        if current is not None:
            if fence and line.rstrip().startswith(indent + fence.group(2)):
                blocks.append(current)
                current, indent = None, ""
                continue
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
