"""Reading the Codex hook snippet out of its page, for the suite that checks it.

``integrations/codex/README.md`` is the whole adapter: one copyable
``.codex/hooks.json`` and the prose that tells a reader where to paste it and what
has to hold before it runs. There is no script under ``integrations/codex/`` to
read, so the snippet *is* the artifact, and the only honest way to check it is to
parse the bytes the page publishes. A snapshot fixture would let the page and the
checked config drift into two different things.

Three readers, each locating its span by the text that names it, in the repo's
convention for this kind of module (see ``pi_extension_source.py``):

- :func:`page` reads the page itself.
- :func:`snippet` finds the page's one ``json`` fence and parses it, so a page with
  two such blocks or none is named as the malformed page it is rather than answered
  for by whichever block a positional reader happened to pick.
- :func:`command_lines` finds every ``"command":`` declaration in the page's raw
  text, and :func:`command_value` unescapes one of them.

The command lines are read from the page's text and not from the parsed JSON
because a JSON parse normalises ``\\"`` to a plain quote, and the quoting is half of
what is checked: one escaped pair around the reminder is what stops that sentence
reaching the harness as a blocking verdict. A reader that took the parsed value
could not tell the two apart.

A helper module: never named ``test_*``. The checks are in ``test_codex_hook.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CODEX_DIR = REPO / "integrations" / "codex"
HOOK_README = CODEX_DIR / "README.md"
HOOK_FILES: tuple[Path, ...] = (HOOK_README,)

# Where the snippet is copied to. One target, one representation: a page that also
# carried the inline-TOML form Codex accepts would give a reader two files to write
# and two things that can disagree.
INSTALL_TARGET = ".codex/hooks.json"

# The events the page registers, in the order the snippet writes them. SessionStart
# carries the brief (its matcher covers the starts that need one and the compaction)
# and UserPromptSubmit carries the per-prompt reminder; SubagentStart is deliberately
# absent, which is why a subagent gets the reminder and never the brief.
EVENTS = ("SessionStart", "UserPromptSubmit")

# The start sources one SessionStart group matches. A narrower list would leave a
# session that resumed, cleared or compacted without a brief.
START_SOURCES = ("startup", "resume", "clear", "compact")

# pi's bound on one spawn of `noni brief` (tests/pi_extension_source.py holds the
# 30_000 ms). Codex defaults a command hook to 600 seconds, so a snippet that omits
# the timeout would hold session start for ten minutes on a hung noni.
BRIEF_TIMEOUT_SECONDS = 30

# A `"command": "..."` declaration in the page's text, with the escaped inner text
# in group 1. An escaped quote is consumed with the backslash that carries it, so an
# unescaped quote inside the value cannot end the read early.
COMMAND_DECL = re.compile(r'^[ \t]*"command": "(.*?)"[ \t]*,?[ \t]*$', re.MULTILINE)

# U+2014, written as an escape so this file does not carry the character it bans.
EM_DASH = "\u2014"


def page() -> str:
    """The page's text, with its absence reported as a missing file."""
    assert HOOK_README.is_file(), f"{HOOK_README} is missing"
    return HOOK_README.read_text(encoding="utf-8")


def snippet(text: str) -> dict:
    """The page's one ``json`` fence, parsed.

    The fence is found by its own info string rather than by position among the
    page's blocks, so a second fenced block anywhere on the page cannot be read as
    the config. A page with no ``json`` fence, or with two, is the failure it is:
    the reader copying this page needs exactly one thing to paste.
    """
    from docs_commands import fenced_pairs

    blocks = [lines for info, lines in fenced_pairs(text) if info == "json"]
    assert len(blocks) == 1, (
        f"{HOOK_README} must carry exactly one json fence to copy, found "
        f"{len(blocks)}")
    return json.loads("\n".join(blocks[0]))


def command_lines(text: str) -> list[str]:
    """The escaped inner text of every ``"command":`` the page prints.

    In document order, straight from the bytes the reader copies. Values arrive with
    their ``\\"`` still standing, which is what lets a check see how the command is
    quoted rather than only what it says.
    """
    return COMMAND_DECL.findall(text)


def command_value(raw: str) -> str:
    """One command line's text with each escaped double quote brought back.

    ``raw`` is what :func:`command_lines` returns: the value as JSON writes it, where
    a quote the command itself contains stands escaped. A page that wrote such a
    quote bare is a page whose reader pastes a file that will not parse, and the two
    forms are indistinguishable once a JSON parse has eaten the backslashes, which is
    why this reader works on the page's bytes. Decoding goes through ``json.loads``,
    so a value whose backslashes do not form a legal JSON escape is refused here
    rather than quietly unescaped into something the page never printed.
    """
    return json.loads(chr(34) + raw + chr(34))
