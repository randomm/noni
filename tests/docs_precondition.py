"""Reading one skill page for the precondition its script commands depend on.

The promise itself is asserted in ``tests/test_docs_precondition.py``. This module
owns only the reading: which lines of a page put a shipped entry point in command
position, and which words a page has to carry to have stated what must be true before
such a command can work.

Two decisions about the shape of a page live here rather than in the test:

- **Command position is where a shell would read a command: column zero of a fence.**
  A fence line whose first token is a script path, or whose first token is an
  interpreter and whose next token is one. A name inside prose is not a command --
  ``scripts/decide.py`` in a sentence about who may write a record names no run, and a
  name inside backticks in a table cell names no run either. Charging prose would
  push the pages to move their discussion into fences, which the fence censuses of
  ``tests/test_onboarding.py`` and ``tests/test_quickstart.py`` refuse.
- **A line that begins with an interpreter is read past that interpreter, and past
  ``sudo``-style wrappers, to the program actually being run.** That is how a reader's
  shell reads it, so it is how the page is judged: ``python3 <clone>/skills/census/
  scripts/census.py`` and ``bash scripts/census.sh <dir>`` both put an entry point in
  command position, and so does a wrapper in front of either.

No assertion lives here: those stay with the test that makes them.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from docs_commands import fenced_pairs
from docs_promises import QUICKSTART

# A script path: path segments of word characters, dots, dashes and angle brackets
# (the placeholder a page spells an unknown location with), the last one carrying the
# suffix. Angle brackets are in the segment class so ``<clone>/skills/...`` reads as a
# path rather than stopping at the placeholder.
_SCRIPT_PATH = r"[\w.<>-]+(?:/[\w.<>-]+)*\.(?:py|sh)"

# ``-m`` as argparse spells it: the single-dash short form of a long flag. A line whose
# first token is an interpreter and whose next is ``-m`` names a module, which is not a
# script path, so the form is refused here rather than matched and excused later.
_MODULE_FLAG = "-m"

# Words that put another program further along the same line. Read through, never
# excused: a page that printed ``sudo scripts/census.sh <dir>`` still prints a script
# command, and refusing to look past the wrapper would let the most forceful form of a
# copy-and-fail run past the gate written to catch it.
_WRAPPER = r"(?:sudo|env|command|time|NO[A-Z_]+=\S+)"
_INTERPRETER = r"(?:bash|sh|python\d*|uv|uvx|pypy\d*)"

# A fence's own comment line, which the suite's readers already drop before splitting:
# a line beginning ``#`` is the page talking to the reader, not a line to run.
_COMMENT = "#"


def script_entry_points(text: str) -> list[tuple[str, str]]:
    """The ``(entry point, line)`` pairs a page prints as a command.

    One entry per line that puts a shipped entry point in command position inside a
    fence, in the order the page prints them. Fences are read with
    :func:`docs_commands.fenced_pairs` rather than the bash-only helper: every command
    fence under ``skills/`` carries no info string, so a gate that filtered on ``bash``
    would see none of them and pass a page that printed no precondition at all.

    A line the page's own reader cannot lex (an unbalanced quote) is skipped rather
    than raised: ``tests/test_docs_promises.py`` already fails a page for that, and a
    precondition gate that also raised would report one broken fence as two problems.
    """
    found: list[tuple[str, str]] = []
    for _info, lines in fenced_pairs(text):
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(_COMMENT):
                continue
            name = _command_entry_point(stripped)
            if name is not None:
                found.append((name, stripped))
    return found


def _command_entry_point(line: str) -> str | None:
    """The entry point one fence line runs, or ``None`` when it runs none.

    The line is split with ``shlex`` the way the suite's other readers split a page,
    so quotes the page used for a path with a space in it do not hide the script. A
    continuation is judged on the joined command, which is what the shell runs; the
    reader for that is the suite's own, and a page whose line does not lex at all is
    another test's failure.
    """
    tokens = _tokens(line)
    if tokens is None:
        return None
    for token in tokens:
        if token == _MODULE_FLAG:
            return None
        if re.fullmatch(_SCRIPT_PATH, token):
            return token
        if not re.fullmatch(rf"(?:{_WRAPPER}|{_INTERPRETER})", token):
            break
    return None


def _tokens(line: str) -> list[str] | None:
    """A fence line as argv, with a trailing continuation marker gone.

    The reader of the joined command is the suite's own
    (:func:`docs_commands.block_commands`), so the lexing rule is shared rather than
    restated: ``posix=True``, and a line whose quoting does not close is ``None`` here
    because that page is already failing ``test_commands_the_pages_print_are_all_parseable``.
    A line ending in a backslash is continued onto the next fence line by that reader,
    which is why the marker is dropped here instead of becoming a token.
    """
    try:
        return shlex.split(line.rstrip().rstrip("\\").rstrip(), posix=True)
    except ValueError:
        return None


def has_install_precondition(text: str) -> bool:
    """Whether the page states that the package has to be installed or importable.

    Compared against whitespace-flattened text, because every page under ``skills/`` is
    wrapped at ~80 columns and a rewrap is a passing edit, not a dropped promise. Both
    halves have to be there: the page has to name the install and name the
    importability, since the failure the reader actually meets is an unimportable
    package.
    """
    flow = re.sub(r"\s+", " ", text)
    return all(phrase in flow for phrase in _PRECONDITION_PHRASES)


# The two facts the sentence owes, in the product's own vocabulary: the words the
# wrappers' docstrings and ``docs/QUICKSTART.md`` already use, so the gate asks the
# pages for what the product says rather than for a wording it invents.
_PRECONDITION_PHRASES: tuple[str, ...] = ("must be installed", "importable")


def quickstart_install_link(text: str, *, path: Path | None = None) -> bool:
    """Whether the page sends the reader to the quickstart's install section.

    The link is the sentence's target: a page that says the package must be installed,
    without saying where the install is documented, leaves the reader to find the page
    that owns it. The anchor is required as well as the page, so the link lands on the
    section that carries the prose rather than on the top of a long page. Both are
    matched on the raw text: a markdown link is not rewrapped mid-path.

    One page cannot satisfy this and is exempt on that ground alone: the quickstart,
    which cannot link the section it is standing in. It is held instead by
    ``tests/test_docs_precondition.py`` to state the precondition inside that section.
    """
    if path is not None and path.name == QUICKSTART.name:
        return True
    return "docs/QUICKSTART.md" in text and "#install-noni" in text
