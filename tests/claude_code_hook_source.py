"""Readers for the Claude Code hook page under ``integrations/claude-code/``.

The adapter is a page and nothing else: it ships no script, so the only things
this suite can check are the copy a reader pastes into their own
``.claude/settings.json`` and the claims the page makes around it. Both are read
here rather than copied into the checks: the block comes out of the page's own
```json fence through the repository's shared fence reader, the reminder comes
out of ``integrations/pi/noni.ts`` through ``pi_extension_source``, and every
event, field and bound below is matched by the exact key the settings file uses
rather than a synonym a page could paraphrase around.

A helper module: never named ``test_*``. The checks that use it live in
``test_claude_code_hook.py``, and the page claims they read are ``PAGE_RULES`` here.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from docs_commands import fenced_pairs
from pi_extension_source import REPO, string_literal

# pi's own bound on one spawn of `noni brief`, read out of the hook rather than
# copied: the Claude Code timeout is the same bound, and a copy here could disagree
# with the number pi ships while both suites stayed green. Written as an
# underscored literal because that is the form the pi suite pins in noni.ts.
PI_TIMEOUT_DECL = "BRIEF_TIMEOUT_MS = 30_000"

CLAUDE_DIR = REPO / "integrations" / "claude-code"
HOOK_PAGE = CLAUDE_DIR / "README.md"
# The page is the whole adapter: the issue rules out a script, a shipped
# ``.claude/settings.json`` and any second file, and a file arriving beside it is
# the failure this tuple reports rather than one nobody reads.
HOOK_FILES: tuple[Path, ...] = (HOOK_PAGE,)

# The fence the block is written in, unprefixed and unindented (ruling 8). A tag
# of ``jsonc`` or a space of indent is still a fence to a renderer and a different
# pair to the reader, so the tag is compared exactly and the indent asserted.
JSON_FENCE = "json"

# The two hook events this adapter wires. The names are the harness's own event
# keys and are matched as keys, never as prose.
SESSION_START = "SessionStart"
USER_PROMPT_SUBMIT = "UserPromptSubmit"
HOOK_EVENTS: tuple[str, ...] = (SESSION_START, USER_PROMPT_SUBMIT)

# When the brief is fetched: a new session, a resumed one, a ``/clear``, a
# compaction, and a fork, which starts a new main session and needs the brief as
# much as the first four (ruling 2).
MATCHER = "startup|resume|clear|compact|fork"

# The state root, anchored at the project directory rather than the session's
# working directory (ruling 1): a hook command runs wherever the session happens
# to sit, and a relative root would resolve against that.
STATE_ROOT = "$CLAUDE_PROJECT_DIR/.noni-state"
BRIEF_COMMAND = f"noni brief --repo \"{STATE_ROOT}\""
# The Claude Code hooks reference counts a command hook's `timeout` in seconds, so
# the block's number and pi's millisecond bound are the same bound in two units.
# The conversion is explicit at the one place it happens, in :func:`pi_timeout_seconds`.
TIMEOUT_UNIT_DIVISOR = 1000
# The page states the absence of a script as its design (ruling 3), and this is
# the sentence the ruling names.
FAILURE_SENTENCE = "the session is not blocked"

# What the page owes a reader, each with the reason its absence is a gap (ruling
# 10). Every entry is text a reader meets on the page, in the page's own words.
PAGE_RULES: tuple[tuple[str, str], ...] = (
    (".claude/settings.json", "the page does not name the file the block goes into"),
    ("alongside", "the page does not say the entries join any hooks the project has"),
    ("the state root rule for the in-project route: `.`", "the page omits the "
     "state-root rule for the project that keeps its state inside itself"),
    ("on your PATH", "the page does not say `noni` must be on PATH"),
    (FAILURE_SENTENCE, "the page does not say a failed brief leaves the session running"),
    ("## Verifying it", "the page states no way to verify the wiring"),
    ("10,000", "the page does not name the harness's cap on hook output"),
    ("every turn", "the page does not say the reminder fires on every turn"),
    ("turn the user did not type", "the page does not state the reminder's limit"),
    ("harness hook", "the page does not say this is a harness hook"),
    ("not a tracker adapter", "the page blurs the two kinds of integration"),
)

# The harness's own name as a word, with the file name the settings file uses and
# the snake_case form a directory or module would carry. The purity rule confines
# all three to integrations/.
HARNESS_WORD = re.compile(r"\bclaude\b|\bclaude[-_]code\b", re.IGNORECASE)


def page() -> str:
    """The page's text, with its absence reported as a missing file."""
    assert HOOK_PAGE.is_file(), f"{HOOK_PAGE} is missing"
    return HOOK_PAGE.read_text(encoding="utf-8")


def page_flowed() -> str:
    """The page with its markdown line wrapping collapsed.

    The page wraps at its own column budget and a reader reads the words, not the
    bytes between them, so a locator that spans a sentence reads this. Same
    collapse :func:`quickstart_page.flowed_text` applies to the quickstart's page.
    """
    return re.sub(r"\s+", " ", page())


def pi_brief_timeout_ms() -> int:
    """The millisecond bound of pi's brief fetch, read out of ``integrations/pi/noni.ts``.

    The pi hook is the one place this bound is written, so it is read from its source
    through the pi reader module rather than copied: a bound pi changed (or wrote in a
    form this reader does not recognise) stops this suite rather than leaving it
    comparing a number pi no longer ships. The digits come from the declaration's own
    text, so no second copy of the bound lives in this file.
    """
    declaration = pi_constant_declaration(pi_hook_source(), "BRIEF_TIMEOUT_MS")
    assert PI_TIMEOUT_DECL in declaration, (
        f"pi's brief timeout is not declared as {PI_TIMEOUT_DECL!r}: {declaration!r}")
    digits = declaration.partition("=")[2].strip().rstrip(";").replace("_", "")
    assert digits.isdigit(), f"pi's brief timeout is not a plain number: {declaration!r}"
    return int(digits)


def pi_constant_declaration(text: str, name: str) -> str:
    """One ``const NAME = ...;`` declaration of the pi hook, head to semicolon.

    The reader keeps the rule the shared pi reader keeps: locate the declaration by
    its own head, and end it at the semicolon closing it, so a value can only reach
    the end of its line and a missing terminator is a failure rather than a read of
    the rest of the file. A quoted or templated value is refused: the bound this
    reader exists for is one number, and a check over a string is not that check.
    """
    from pi_extension_source import QUOTED, TEMPLATE

    head = f"const {name} ="
    assert head in text, f"const {name} is not declared in the pi hook"
    rest = text[text.index(head) + len(head):]
    end = re.search(r";\s*$", rest[: rest.index("\n\n")], re.MULTILINE)
    assert end, f"const {name} has no terminating semicolon"
    body = TEMPLATE.sub("", rest[: end.end()])
    assert not QUOTED.findall(body), (
        f"const {name} is not a plain numeric declaration: {body.strip()!r}")
    return head + rest[: end.end()]


def pi_timeout_seconds() -> int:
    """pi's bound expressed the way this settings file counts it: whole seconds.

    The milliseconds-to-seconds conversion, named. The check compares the snippet
    against this rather than a literal, so the page can only be right by agreeing with
    pi, and a bound that does not divide into whole seconds is refused here rather than
    rounded into an agreement with a page.
    """
    ms = pi_brief_timeout_ms()
    assert ms % TIMEOUT_UNIT_DIVISOR == 0, (
        f"pi's brief timeout of {ms} ms is not a whole number of seconds, so no "
        "value in this file's units states that bound")
    return ms // TIMEOUT_UNIT_DIVISOR


def fenced_json(text: str) -> tuple[list[str], int]:
    """The page's one ```json fence: its lines, and the indent of its opener.

    The single fence read of the page, so the block a check parses and the fence a
    check measures its indent on are the same fence. An unterminated fence is the
    malformed page it is, raised by the shared reader rather than handed over as a
    partial read.
    """
    openers = [line for line in text.splitlines()
               if line.strip().startswith("```" + JSON_FENCE)]
    assert len(openers) == 1, f"the page carries {len(openers)} json fences, not one"
    pairs = [(info, lines) for info, lines in fenced_pairs(text) if info == JSON_FENCE]
    assert len(pairs) == 1, f"the page carries {len(pairs)} json blocks, not one"
    return pairs[0][1], len(openers[0]) - len(openers[0].lstrip())


def hooks_block(text: str) -> dict:
    """The settings block the page tells a reader to copy, parsed.

    Read through :func:`docs_commands.fenced_pairs` at the page's own info string,
    so what is parsed is the block as printed rather than a copy beside it. The
    block is ruled unindented (ruling 8), so the indent is refused here: an indented
    fence renders as a block and is not the copy a reader selects.
    """
    lines, indent = fenced_json(text)
    assert indent == 0, f"the block's fence is indented by {indent} spaces"
    body = "\n".join(lines).strip()
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"the page's json block does not parse: {exc}") from exc
    assert isinstance(parsed, dict), "the block is not a JSON object"
    assert "$schema" not in parsed, (
        "the block carries a $schema key, which the issue rules out")
    return parsed


def hook_entries(block: dict, event: str) -> list[dict]:
    """The entries the block wires to ``event``, by its exact key.

    The key match is what makes this a claim about the hook rather than about a
    sentence carrying the event's name: a block that spelled the key ``sessionStart``
    would reach no entries.
    """
    assert "hooks" in block, "the block has no hooks key"
    hooks = block["hooks"]
    assert isinstance(hooks, dict), "hooks is not an object"
    assert event in hooks, f"the block wires no {event} hook"
    entries = hooks[event]
    assert isinstance(entries, list) and entries, f"{event} is not a non-empty list"
    return entries


def command_hooks(entries: list[dict], where: str) -> list[dict]:
    """The command hooks of one entry list, each type checked where it is read.

    An entry is a matcher group holding its own ``hooks`` list, which is the shape
    the settings file uses, so the walk goes two levels and refuses an entry that
    carries none or holds a hook of another type.
    """
    found: list[dict] = []
    for position, entry in enumerate(entries):
        assert isinstance(entry, dict), f"{where} entry {position} is not an object"
        inner = entry.get("hooks")
        assert isinstance(inner, list) and inner, (
            f"{where} entry {position} has no hooks list")
        for hook in inner:
            assert isinstance(hook, dict), f"{where} entry {position} holds a non-object"
            assert hook.get("type") == "command", (
                f"{where} entry {position} is not a command hook")
            command = hook.get("command")
            assert isinstance(command, str) and command.strip(), (
                f"{where} entry {position} carries no command")
            found.append(hook)
    return found


def commands(entries: list[dict], where: str) -> list[str]:
    """The command strings of every command hook under ``entries``, in order."""
    return [hook["command"] for hook in command_hooks(entries, where)]


def matcher(entries: list[dict]) -> str:
    """The matcher string of a single-entry list, read from the entry itself.

    A matcher is a plain string in the settings file; a block that made it a list
    or omitted it fails here rather than at the comparison.
    """
    assert len(entries) == 1, f"the block carries {len(entries)} entries, not one"
    value = entries[0].get("matcher")
    assert isinstance(value, str) and value, "the entry carries no matcher string"
    return value


def timeout_of(entries: list[dict]) -> int:
    """The explicit timeout on the brief hook, in seconds (ruling 6).

    Seconds, because that is the unit the Claude Code hooks reference gives the field
    ("Seconds before canceling"). The check compares against :func:`pi_timeout_seconds`
    rather than a literal, and the falsifier runs this same reader over a page it did
    not read from disk, so an off-by-1000 snippet is reported rather than green.
    """
    hooks = command_hooks(entries, SESSION_START)
    assert len(hooks) == 1, "the brief hook carries more than one command"
    value = hooks[0].get("timeout")
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"the brief hook carries no integer timeout: {value!r}")
    return value


def reminder_command(entries: list[dict]) -> str:
    """The per-turn command, with exactly one command behind it.

    Two commands under ``UserPromptSubmit`` would bill the model two payloads a
    turn and make "the reminder is the whole per-turn output" mean nothing.
    """
    found = commands(entries, USER_PROMPT_SUBMIT)
    assert len(found) == 1, f"{len(found)} commands run per turn, not one"
    return found[0]


def reminder_output(command: str) -> str:
    """The stdout of the per-turn command, run through a shell (ruling 7).

    ``CLAUDE_PROJECT_DIR`` names an empty directory so the brief cannot be read and
    the arm that echoes the reminder is the one that runs. The byte compare happens
    in the check, over these bytes and pi's constant, so a shell that mangles the
    apostrophe or drops a word fails as a byte difference rather than as a
    substring that happened to appear.
    """
    with tempfile.TemporaryDirectory() as empty:
        proc = subprocess.run(["/bin/sh", "-c", command], capture_output=True,
                              text=True, timeout=60,
                              env={"CLAUDE_PROJECT_DIR": empty, "PATH": _path()})
    assert proc.returncode == 0, (
        f"the per-turn command exited {proc.returncode}: {proc.stderr!r}")
    return proc.stdout


def _path() -> str:
    """A PATH holding a ``noni`` the shell can find, or the interpreter's own bin.

    The command's failure arm is what is exercised, so a missing binary is a
    legitimate run; naming one directory rather than inheriting the caller's keeps
    the run from depending on which ``noni`` the developer's shell has first.
    """
    found = shutil.which("noni")
    if found:
        return str(Path(found).resolve().parent)
    return str(Path(sys.executable).parent)


def reminder() -> str:
    """pi's per-turn reminder, read out of the hook rather than restated.

    ``pi_extension_source.string_literal`` stops at the semicolon that ends the
    declaration and reads the quoted pieces whole, so the sentence's apostrophe
    cannot end a piece early and a reworded reminder is read rather than missed.
    """
    return string_literal(pi_hook_source(), "REMINDER")


def pi_hook_source() -> str:
    """The pi hook's source, through the reader that owns it."""
    from pi_extension_source import source

    return source()
