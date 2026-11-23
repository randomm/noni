"""The Codex harness hook under integrations/codex/, checked as text.

``integrations/codex/README.md`` is the whole adapter: one copyable
``.codex/hooks.json`` and the prose around it. There is no script beside it, so the
snippet the page publishes is what Codex runs, and this module parses it out of the
page rather than checking a copy of it. What lives here is the snippet's shape:

- one install target (``.codex/hooks.json``) and one ``json`` fence, so a reader has
  one thing to paste;
- the snippet registers the two events and nothing else: ``SessionStart`` with a
  matcher over the four start sources that need a brief, and ``UserPromptSubmit``
  carrying the per-prompt reminder with no matcher (the event ignores one);
- the brief command is the git-root-anchored form the page rules, and the per-turn
  command prints only the reminder: it spawns nothing and has no failure arm;
- the reminder is read through the pi source reader's ``REMINDER``, not restated
  here, so the two adapter pages cannot drift apart;
- both handlers carry their bounds: the brief handler pi's 30 second timeout and a
  positive ``additionalContextLimit`` (Codex's own defaults are 600 seconds and a
  2500 token context cap), and the per-turn handler its own 5 seconds, because for
  that event a non-zero exit blocks the operator's prompt.

The page's prose -- the trust gates, the state-root rule, the PATH rule, what a
wrong state root prints, and the commands "Verifying it" tells the reader to run --
is ``test_codex_hook_page.py``, which reads the same bytes through
``codex_hook_source``. The page's live check (its "Verifying it", run against a real
session) carries the behaviour; these two modules carry the shape.
"""

from __future__ import annotations

import re
import shlex

from _harness import REPO, _git
from codex_hook_source import (
    BRIEF_COMMAND,
    BRIEF_CONTEXT_LIMIT_TOKENS,
    BRIEF_TIMEOUT_SECONDS,
    EVENTS,
    INSTALL_TARGET,
    REMINDER_TIMEOUT_SECONDS,
    START_SOURCES,
    command_lines,
    command_value,
    page,
    snippet,
)
from docs_commands import block_commands, fence_openers, fenced_pairs
from pi_extension_source import string_literal
from quickstart_page import flowed_text

# The harness's own name as a word. The purity rule confines it to integrations/,
# and a core page has no reason to write it at all.
HARNESS_WORD = re.compile(r"\bcodex\b", re.IGNORECASE)

# The core, as the purity rule sees it: the skills, the docs, the readme. Tests are
# excluded because this module is the check over the hook and names it.
CORE_GLOBS = ("skills/*", "docs/*", "README.md")


def _handlers() -> dict[str, dict]:
    """The one handler of each registered event, keyed by event name.

    Located by event rather than by position, so the pairing of a command to the
    event that runs it is part of what is checked.
    """
    handlers = snippet(page())["hooks"]
    found = {}
    for event in EVENTS:
        groups = handlers[event]
        assert len(groups) == 1, f"{event} carries {len(groups)} matcher groups"
        inner = groups[0]["hooks"]
        assert len(inner) == 1, f"{event} carries {len(inner)} handlers"
        found[event] = inner[0]
    return found


def harness_lines(rels: list[str]) -> list[str]:
    """Lines of tracked core files that name the harness as a word."""
    found: list[str] = []
    for rel in rels:
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        found += [
            f"{rel}:{number}: {line.strip()}"
            for number, line in enumerate(text.splitlines(), 1)
            if HARNESS_WORD.search(line)
        ]
    return found


def test_the_snippet_is_the_pages_one_json_fence() -> None:
    """The page carries exactly one ``json`` fence and it is valid config.

    The reader of this page pastes one file, so a page that grew a second ``json``
    fence (a TOML-flavoured twin, a second variant of the same config) is a page that
    no longer says which one to install. :func:`snippet` is what every other check in
    this module reads its config through, so this is the check that makes it mean one
    block rather than whichever one a positional reader reached for.
    """

    tags = [info for info, _ in fenced_pairs(page())]
    assert tags.count("json") == 1, f"the page carries {tags.count('json')} json fences"
    hooks = snippet(page())["hooks"]
    assert isinstance(hooks, dict), "the page's json fence is not a hooks object"


def test_the_page_names_one_install_target_and_carries_no_toml_fence() -> None:
    """One representation of the config. Codex also accepts hooks inline under
    ``[hooks]`` in ``config.toml``; publishing that form as well is how two files
    that disagree about the same hook reach two readers.
    """
    text = page()
    assert INSTALL_TARGET in text, "the page never names where the snippet goes"
    tags = fence_openers(text)
    assert "toml" not in tags, f"the page publishes a toml form as well: {tags}"
    assert INSTALL_TARGET in flowed_text(text)


def test_the_snippet_registers_exactly_the_two_events() -> None:
    """The start event and the per-prompt event, and nothing else.

    ``SubagentStart`` is the event a page reaches for when it wants a subagent to
    carry the brief too, and it is not registered: a subagent gets the reminder
    through ``UserPromptSubmit`` and never the brief.
    """
    assert list(snippet(page())["hooks"]) == list(EVENTS)


def test_the_session_start_matcher_covers_every_start_that_needs_a_brief() -> None:
    """The matcher filters the start source, and a start it misses has no brief.

    A resumed, cleared or compacted session that missed the matcher would run with
    the reminder alone, which is the failure this adapter exists to close.
    """
    groups = snippet(page())["hooks"]["SessionStart"]
    matcher = groups[0]["matcher"]
    assert matcher == "|".join(START_SOURCES), f"the matcher is {matcher!r}"
    for source in START_SOURCES:
        assert source in matcher.split("|"), f"{source} is outside the matcher"


def test_the_per_turn_group_carries_no_matcher() -> None:
    """``UserPromptSubmit`` ignores any matcher, so writing one is a page claiming a
    filter Codex does not apply: the reminder reaches every prompt whatever it says.
    """
    groups = snippet(page())["hooks"]["UserPromptSubmit"]
    assert "matcher" not in groups[0], "the per-turn group pretends to filter"


def test_the_brief_command_is_the_ruled_git_rooted_form() -> None:
    """The exact argv the ticket ruled, read off the page's own bytes.

    ``--repo`` is required by ``src/noni/brief.py`` and no core module reads the
    environment for a state root, so a hook that dropped the flag gets exit 2. The
    command is compared as argv, not as a substring, so a quote lost in the page's
    escaping fails here rather than turning into a word nobody typed.
    """
    handler = _handlers()["SessionStart"]
    assert handler["type"] == "command", f"handler type is {handler['type']!r}"
    raw = [line for line in command_lines(page()) if "noni brief" in line]
    assert len(raw) == 1, f"the page prints {len(raw)} brief commands"
    assert command_value(raw[0]) == BRIEF_COMMAND, (
        f"the brief command is {command_value(raw[0])!r}")
    argv = shlex.split(handler["command"])
    assert argv == ["noni", "brief", "--repo",
                    "$(git rev-parse --show-toplevel)/.noni-state"], f"argv: {argv}"
    assert block_commands([handler["command"]]) == [argv], "the command does not lex"


def test_the_brief_handler_caps_the_context_it_hands_the_model() -> None:
    """``additionalContextLimit`` is the page's one bound on the injected payload.

    Codex caps a command hook's additional context at 2500 tokens with the key
    absent, spills the whole of it to a file above whatever limit the handler names,
    and takes ``0`` to mean "send all of it", so the number is the argument the
    page's bounded-payload clause rests on. It is pinned the way the timeout is: a
    handler that dropped it or raised it past the constant is a page whose reader
    pastes an unbounded brief and stays green no other way.
    """
    handler = _handlers()["SessionStart"]
    limit = handler.get("additionalContextLimit")
    assert isinstance(limit, int) and not isinstance(limit, bool), (
        f"the brief handler carries no additionalContextLimit: {limit!r}")
    assert limit > 0, f"additionalContextLimit {limit} asks Codex to pass all of it"
    assert limit == BRIEF_CONTEXT_LIMIT_TOKENS, (
        f"additionalContextLimit is {limit}, not {BRIEF_CONTEXT_LIMIT_TOKENS}")
    assert f'"additionalContextLimit": {limit}' in page(), (
        "the snippet's bound is not the number the page prints")


def test_the_per_turn_handler_bounds_its_own_timeout() -> None:
    """The reminder's bound is checked too, so both handlers are bounded.

    For ``UserPromptSubmit`` a non-zero exit blocks the prompt, so this handler is on
    the operator's input path: the timeout is what turns a per-turn hook that stops
    working into a short wait rather than a session that cannot type. Both handlers'
    bounds are pinned, not just the slow one's.
    """
    handler = _handlers()["UserPromptSubmit"]
    assert handler.get("timeout") == REMINDER_TIMEOUT_SECONDS, (
        f"the per-turn handler's timeout is {handler.get('timeout')!r}, not "
        f"{REMINDER_TIMEOUT_SECONDS} seconds")


def reminder() -> str:
    """The standing reminder, read from the pi hook through the pi source reader.

    The one source of this sentence in the suite. Restating it here is how the two
    adapter pages drift apart: each would stay green while telling the operator
    something different about what noni holds.
    """
    return string_literal(
        (REPO / "integrations" / "pi" / "noni.ts").read_text(encoding="utf-8"),
        "REMINDER")


def test_the_reminder_command_prints_the_reminder_the_pi_hook_prints() -> None:
    """The same sentence, in the one form that reaches the model.

    Codex adds a per-turn hook's plain stdout to the model's context, so an ``echo``
    of the sentence is the documented form, and the check pins it whole: the command
    is ``echo`` with one argument, and that argument is the pi hook's own ``REMINDER``.
    """
    handler = _handlers()["UserPromptSubmit"]
    assert handler["type"] == "command", f"handler type is {handler['type']!r}"
    raw = [line for line in command_lines(page()) if "noni holds" in line]
    assert len(raw) == 1, f"the page prints {len(raw)} reminder commands"
    value = command_value(raw[0])
    assert value == f'echo "{reminder()}"', (
        f"the per-turn command is not a plain echo of the pi reminder: {value!r}")


def test_the_per_turn_command_is_one_echo_of_the_reminder_and_nothing_else() -> None:
    """No failure arm, because there is nothing to fail.

    The command is a shell builtin printing one fixed sentence: the argv is ``echo``
    and that same sentence, so it spawns no ``noni``, reads no state root and cannot
    answer a prompt with a refusal. That matters more here than it sounds: for this
    event a non-zero exit blocks the prompt, so a command that reached for a state
    root and got a refusal back would stop the operator's turn instead of reminding
    them. The word "noni" inside the reminder is the reminder talking, so the check
    is on the argv and not on the text.
    """
    handler = _handlers()["UserPromptSubmit"]
    command = handler["command"]
    argv = shlex.split(command)
    assert argv[0] == "echo", f"the per-turn command is not an echo: {argv[0]!r}"
    assert len(argv) == 2, f"the per-turn command is more than one echo: {argv}"
    assert argv[1] == reminder(), "the per-turn argv is not the reminder alone"
    # The reminder is one quoted argument, so a shell operator can only reach the
    # command outside those quotes. Semicolons and colons live inside the sentence.
    outside = command.replace(chr(34) + reminder() + chr(34), "")
    for shape in ("&&", "||", ";", "|", "$(", "`"):
        assert shape not in outside, (
            f"the per-turn command carries {shape!r}, so it has a failure arm")


def test_the_brief_handler_carries_the_pi_bound_as_its_timeout() -> None:
    """Codex's own default for a command hook is 600 seconds.

    pi caps the same spawn at 30 000 ms, and a hook that omitted its timeout would
    hold session start for ten minutes on a hung ``noni``. The bound is pinned to the
    number the pi suite holds, in the seconds this format counts.
    """
    handler = _handlers()["SessionStart"]
    assert handler.get("timeout") == BRIEF_TIMEOUT_SECONDS, (
        f"the brief handler's timeout is {handler.get('timeout')!r}, not "
        f"{BRIEF_TIMEOUT_SECONDS} seconds")


def test_only_the_brief_handler_carries_a_status_message() -> None:
    """The reminder is on screen every prompt; a status line for it would be noise.
    The one that can take thirty seconds is the one worth naming on screen.
    """
    handlers = _handlers()
    assert handlers["SessionStart"].get("statusMessage"), (
        "the slow handler shows the reader nothing while it runs")
    assert not handlers["UserPromptSubmit"].get("statusMessage"), (
        "the per-turn handler announces itself every prompt")


def test_the_page_ships_no_script_and_the_directory_holds_only_the_page() -> None:
    """A copyable config and a README, nothing else.

    A script under ``integrations/codex/`` would be a second artifact to install,
    keep current and trust, for a hook Codex runs as a shell command string.
    """
    shipped = sorted(p.name for p in (REPO / "integrations" / "codex").iterdir())
    assert shipped == ["README.md"], f"integrations/codex/ holds {shipped}"


def test_the_hook_is_not_sold_as_a_tracker_adapter() -> None:
    """integrations/README.md: codex/ named as a harness hook, seams not claimed.

    The two kinds differ in what they owe: a tracker adapter implements the two
    seams of the adapter interface, a harness hook owes them nothing. A page that
    listed codex/ as an adapter would promise a reader a thing that answers a
    steering question, and nothing in this directory does.
    """
    text = (REPO / "integrations" / "README.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    at = [n for n, line in enumerate(lines) if "codex/" in line]
    assert len(at) == 1, f"integrations/README.md lists codex/ {len(at)} times"
    entry = "\n".join(lines[at[0]:at[0] + 5])
    assert "harness hook" in entry, "the list does not call codex/ a harness hook"
    assert "not a tracker adapter" in entry, "the list blurs the two kinds"
    assert "neither seam" in entry, (
        "the list does not say codex/ implements neither seam")


def test_the_harness_is_named_nowhere_outside_integrations() -> None:
    """The purity rule as a check: the harness word is confined to integrations/.

    The list comes from ``git ls-files``, not a filesystem walk, so an untracked
    scratch file adds no offender and a renamed core page cannot drop out silently.
    """
    tracked = _git(REPO, "ls-files", *CORE_GLOBS).stdout.split()
    assert tracked, "expected to run inside a git checkout"
    found = harness_lines(tracked)
    assert not found, f"the harness is named outside integrations/: {found}"
