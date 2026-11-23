"""Reading the Codex hook snippet out of its page, for the suite that checks it.

``integrations/codex/README.md`` is the whole adapter: one copyable
``.codex/hooks.json``, the one command the page tells a reader to run by hand to
prove the wiring, and the prose around them. There is no script under
``integrations/codex/`` to read, so those bytes *are* the artifact, and the only
honest way to check them is to parse what the page publishes. A snapshot fixture
would let the page and the checked config drift into two different things.

Four readers, each locating its span by the text that names it, in the repo's
convention for this kind of module (see ``pi_extension_source.py``):

- :func:`page` reads the page itself.
- :func:`snippet` finds the page's one ``json`` fence and parses it, so a page with
  two such blocks or none is named as the malformed page it is rather than answered
  for by whichever block a positional reader happened to pick.
- :func:`command_lines` finds every ``"command":`` declaration in the page's raw
  text, and :func:`command_value` unescapes one of them.
- :func:`verify_commands` finds the ``noni`` commands of the fence the "Verifying
  it" section prints, the same fence whose exit-code claim the suite pins, so a
  change to one of those forms reddens the check that reads the other.

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

# The reminder is one sentence and its timeout only has to cover a shell builtin
# writing it, so this is the bound that keeps a broken per-turn hook off the
# operator's input path: for `UserPromptSubmit` a non-zero exit blocks the prompt.
REMINDER_TIMEOUT_SECONDS = 5

# The page's cap on what the brief handler may hand the model. Codex caps a command
# hook's additional context at 2500 tokens when the key is absent and spills the
# whole of it to disk above the limit the handler names, so the one number the
# snippet carries is what bounds the injected payload; without it the page's
# bounded-payload clause has nothing behind it.
BRIEF_CONTEXT_LIMIT_TOKENS = 8000

# The command the page hands Codex for the brief, and the form its "Verifying it"
# fence prints: the same command, in the one shape the page rules. Anchored at the
# git root, because a hook command runs with the session's cwd and a relative --repo
# would name a different directory from every subdirectory. Both suites read these
# from here, so the snippet's command, the reader's command and the two checks over
# them cannot each carry their own copy of one literal.
BRIEF_COMMAND = 'noni brief --repo "$(git rev-parse --show-toplevel)/.noni-state"'
BRIEF_VERIFY_COMMAND = BRIEF_COMMAND  # the one command, in its one printed form

# The two commands the "Verifying it" fence prints beside the brief, which are the
# repo's own answers to "which `noni` did PATH resolve, and what version is it" --
# the check a reader has to run before trusting a hook that execs a bare PATH name.
PATH_VERIFY_COMMANDS = ("command -v noni", "noni --version")

# The sentences a brief prints when the state root it was handed holds no direction,
# as :mod:`noni.brief` renders them (``brief_page.NOT_READ`` under the Purpose
# header, ``brief.EMPTY_ORDER`` under ``top 10``, NOT_RUN_SUMMARY when the census
# gave no verdict). The page's check tells a reader to look for these rather than a
# non-zero exit, because ``brief`` exits 0 for any directory that exists: only a
# --repo that is no directory at all refuses with 2.
EMPTY_STATE_ROOT_SIGNALS = ("Purpose: not readable", "the order is empty",
                            "summary: not-run")

# The heading of the section that argues the injected payload is bounded, so the
# number the snippet ships has a clause to be found under. A prefix, because the
# heading reader matches on the heading's own words.
LIMIT_SECTION_HEADING = "The limit of that rule"

# A `"command": "..."` declaration in the page's text, with the escaped inner text
# in group 1. An escaped quote is consumed with the backslash that carries it, so an
# unescaped quote inside the value cannot end the read early.
COMMAND_DECL = re.compile(r'^[ \t]*"command": "(.*?)"[ \t]*,?[ \t]*$', re.MULTILINE)

# What the page owes a reader, each literal with the reason its absence is a gap.
# The check that drives them lives in ``test_codex_hook_page.py``, which matches a
# phrase a paragraph may wrap against the flowed page: rewrapping a sentence is then
# a passing edit and dropping the clause it carries is not.
PAGE_RULES: tuple[tuple[str, str], ...] = (
    (INSTALL_TARGET, "the page does not name the file the snippet is copied into"),
    ("trusted", "the page does not name the project trust gate"),
    ("/hooks", "the page does not name where to review or check a hook"),
    ("hash", "the page does not say trust is recorded against the definition"),
    ("first on PATH", "the page does not say which `noni` the hook runs"),
    ("command -v noni", "the page gives no way to tell which `noni` PATH resolves"),
    ("noni --version", "the page gives no version to compare the resolved binary "
                       "against"),
    ("docs/QUICKSTART.md#install-noni",
     "the page drops the quickstart's Install link"),
    ("config.toml", "the page does not name the file that turns hooks off"),
    ("hooks = false", "the page does not say hooks are on unless turned off"),
    ("## Verifying it", "the page states no way to verify the hook"),
    (BRIEF_COMMAND, "the page does not print the command to run by hand"),
    ("no `noni/`", "the page does not say a state root with no noni/ is inert"),
    ("still exits 0", "the page still claims a state root with no noni/ exits nonzero"),
    ("subagent", "the page does not say what a subagent gets"),
    ("never the brief", "the page does not say a subagent gets no brief"),
    ("blocks the prompt", "the page does not say what a failed per-turn hook does to "
                          "the operator's prompt"),
)


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


def verify_commands(text: str) -> list[list[str]]:
    """The commands of the fence under the page's "Verifying it" heading, as argv.

    The fence that section prints is the reader's own check on the wiring, and the
    suite reads it here rather than from a copy: the claim pinned beside it and the
    commands that claim is made about are then the same bytes, so a rewrite of either
    is caught instead of leaving the other one green.
    """
    from docs_commands import block_commands, fenced_pairs

    section = text[text.index("## Verifying it"):]
    for _info, lines in fenced_pairs(section):
        commands = block_commands(lines)
        if commands:
            return commands
    raise AssertionError("the Verifying it section prints no fence to run")


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
