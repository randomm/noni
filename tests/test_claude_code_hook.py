"""The Claude Code harness hook under ``integrations/claude-code/``, checked as text.

The adapter is one page: no script, no shipped ``.claude/settings.json``, nothing
but the block a reader pastes into their own project's settings file. So what the
ticket ruled has to be checked by reading that page. This module parses the block
out of the page's own ```json fence and asserts the shape the rulings fixed: two
events, a ``SessionStart`` matcher covering startup, resume, clear, compact and
fork, the brief anchored at ``$CLAUDE_PROJECT_DIR``, an explicit 30 second
timeout on that hook, and one ``UserPromptSubmit`` command whose stdout the suite
runs through a shell and compares byte for byte against the reminder in
``integrations/pi/noni.ts``.

Two things this cannot do, and the reason they are not gaps. There is no Claude
Code in CI and no node toolchain, so the block is parsed rather than executed
against the harness; the page's "Verifying it" section carries the live check a
reader runs. And the reminder is never restated here: it is read from the pi hook
through ``pi_extension_source``, so a reworded reminder fails this suite rather
than quietly diverging from it.

The readers live in ``claude_code_hook_source.py`` so the page, the block and the
pi constant have one definition every check below agrees with.
"""

from __future__ import annotations

from _harness import REPO, _git
from claude_code_hook_source import (
    BRIEF_COMMAND,
    BRIEF_TIMEOUT_MS,
    HARNESS_WORD,
    HOOK_EVENTS,
    HOOK_FILES,
    MATCHER,
    PAGE_RULES,
    SESSION_START,
    STATE_ROOT,
    USER_PROMPT_SUBMIT,
    commands,
    fenced_json,
    hook_entries,
    hooks_block,
    matcher,
    page,
    page_flowed,
    reminder,
    reminder_command,
    reminder_output,
    timeout_of,
)

# The em dash comes from the pi suite's own reader, so both harness pages are gated
# against one character rather than two spellings of it.
from pi_extension_source import EM_DASH

# The core, as the purity rule sees it: the skills, the docs, the readme. Tests
# are excluded because this module is the check over the hook and names it, and
# integrations/ is where the harness is allowed to be named at all.
CORE_GLOBS = ("skills/*", "docs/*", "README.md")

# The only directory the adapter is allowed to be: the page's own line pointing at
# the quickstart's install section, which both harness pages link rather than
# reprint (the pi page's PAGE_RULES pin the same link there).
QUICKSTART_LINK = "docs/QUICKSTART.md#install-noni"


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


def test_the_page_is_the_whole_adapter() -> None:
    """``integrations/claude-code/`` holds the page and nothing else.

    The issue rules out a script, a shipped settings file and a second file of any
    kind, and an adapter that grew a script would no longer be the thing the page
    says it is.
    """
    assert HOOK_FILES[0].is_file(), f"{HOOK_FILES[0]} is missing"
    shipped = sorted(path.name for path in HOOK_FILES[0].parent.iterdir())
    assert shipped == ["README.md"], f"the adapter ships more than its page: {shipped}"


def test_the_block_wires_exactly_the_two_events() -> None:
    """``SessionStart`` and ``UserPromptSubmit``, and no other event.

    A third event would put a second payload in front of the model that the ticket
    never ruled.
    """
    assert list(hooks_block(page())["hooks"]) == list(HOOK_EVENTS)


def test_the_brief_hook_matches_every_start_a_main_session_can_have() -> None:
    """The matcher set of ruling 2, read as one string from the entry itself.

    A fork starts a new main session, so it needs the brief; a set that dropped it
    would leave a forked session running with no direction layer. Each trigger is
    checked against the constant the reader declares, so a set that lost one fails by
    name rather than as a whole string that differs.
    """
    block = hooks_block(page())
    found = matcher(hook_entries(block, SESSION_START))
    assert found == MATCHER
    for trigger in ("startup", "resume", "clear", "compact", "fork"):
        assert trigger in found.split("|"), f"the matcher dropped {trigger}"


def test_the_brief_command_is_anchored_at_the_project_directory() -> None:
    """``noni brief --repo "$CLAUDE_PROJECT_DIR/.noni-state"`` (ruling 1).

    A hook command runs wherever the session sits and Claude Code lets the agent
    move that, so a relative state root would resolve against the wrong directory.
    The compare is exact rather than a substring: the whole command is what a reader
    copies.
    """
    block = hooks_block(page())
    assert commands(hook_entries(block, SESSION_START), SESSION_START) == [BRIEF_COMMAND]
    assert STATE_ROOT in BRIEF_COMMAND, "the pinned root is not in the command"


def test_the_brief_hook_carries_the_ruled_timeout() -> None:
    """30 000 ms, explicit (ruling 6), the same bound the pi fetch declares.

    A hook with no timeout is a hung ``noni`` holding a session open; the number is
    compared against the constant in the reader, not a literal in the page.
    """
    block = hooks_block(page())
    assert timeout_of(hook_entries(block, SESSION_START)) == BRIEF_TIMEOUT_MS


def test_the_per_turn_command_prints_pis_reminder_byte_for_byte() -> None:
    """Ruling 7: the reminder is run, not restated.

    The command is executed through ``/bin/sh`` with ``CLAUDE_PROJECT_DIR`` named at
    an empty directory, so the brief cannot be read and the arm that echoes the
    reminder is the one that runs. Its stdout is compared to ``REMINDER`` read from
    ``integrations/pi/noni.ts`` through ``pi_extension_source``. A quoting mistake
    around the apostrophe, a dropped word or a stray prefix fails as a byte
    difference.
    """
    block = hooks_block(page())
    command = reminder_command(hook_entries(block, USER_PROMPT_SUBMIT))
    assert reminder_output(command) == reminder() + "\n"


def test_the_per_turn_command_is_the_brief_with_an_echo_fallback() -> None:
    """One command per turn, and it is the brief or the reminder, never both.

    The brief carries ``2>/dev/null`` so a usage refusal cannot add two stderr lines
    to the model's context, and ``||`` means the echo runs only when the brief did
    not print: a turn gets the page or the one-line reminder, which is the token
    economy the ledger's hooks ruling asks for.
    """
    block = hooks_block(page())
    command = reminder_command(hook_entries(block, USER_PROMPT_SUBMIT))
    assert command.startswith(BRIEF_COMMAND + " 2>/dev/null || echo ")
    assert command.count("||") == 1, "a second arm would run whatever the brief did"


def test_the_page_names_the_install_the_state_root_the_path_and_the_failure() -> None:
    """Ruling 10: the claims a reader needs, pinned the way pi's PAGE_RULES pins its
    page. Each entry carries the reason its absence is a gap.

    Read over the flowed page, so the check is about the sentences a reader reads and
    not about where the page happened to wrap one.
    """
    flowed = page_flowed()
    for wanted, why in PAGE_RULES:
        assert wanted in flowed, why
    assert QUICKSTART_LINK in page(), "the page reprints the install instead of linking it"


def test_the_install_says_the_entries_join_the_projects_own_hooks() -> None:
    """Ruling 11: added alongside, and the other scopes left alone.

    Claude Code merges settings rather than replacing them, so a project that
    already carries a ``hooks`` key has to add to it. A page that said "put this in
    .claude/settings.json" would sell a reader the loss of their own hooks.
    """
    flowed = page_flowed()
    assert "alongside any hooks" in flowed, "the page does not say what joins what"
    for scope in (".claude/settings.local.json", "~/.claude/settings.json"):
        assert scope in page(), f"the page does not name {scope} as a separate file"
    assert "different file" in flowed, "the page does not say the other scopes are separate"


def test_the_page_states_the_reminders_limit_in_one_sentence() -> None:
    """Ruling 4: the per-turn hook fires on turns nobody typed, and the page says so.

    A JSON block cannot select the human's turns, so the limit is the page's to
    state; a reader who was told "every user turn" and got billed a subagent's turns
    would debug the hook.
    """
    flowed = page_flowed()
    assert "every turn" in flowed, "the page does not say the reminder is per turn"
    assert "turn the user did not type" in flowed, "the page hides the limit"
    assert "subagent" in flowed, "the page does not say the reminder runs in subagents"


def test_the_page_names_the_harness_cap_on_hook_output() -> None:
    """Ruling 5: 10,000 characters, stated, with brief's own budget as the bound.

    No new check is added on the brief side, so the page is where a reader learns
    what happens above the cap.
    """
    flowed = page_flowed()
    assert "10,000" in flowed, "the page does not name the output cap"
    assert "bounds its own page" in flowed, "the page names no bound under the cap"


def test_the_verifying_section_runs_the_blocks_own_command() -> None:
    """Ruling 3: with no script there is no failure line, so the hand check is the
    reader's only proof the wiring works.

    The section is pinned to carry the block's own brief command, so what a reader
    verifies is the command they installed rather than a paraphrase of it.
    """
    body = page()
    assert "## Verifying it" in body, "the page states no way to verify the wiring"
    verify = body[body.index("## Verifying it"):]
    assert BRIEF_COMMAND in verify, "the check does not run the block's own command"


def test_the_block_is_one_unindented_json_fence_without_a_schema_key() -> None:
    """Ruling 8: the copy a reader selects is one unindented ```json fence, and it
    carries no ``$schema`` key.

    The indent is measured on the opener itself, so a block pushed into a list is
    refused rather than rendered as a block the reader cannot copy. ``$schema`` is
    refused because the issue rules it out, and a page that added it would be selling
    editor validation the ticket did not ask for.
    """
    _lines, indent = fenced_json(page())
    assert indent == 0, f"the block's fence is indented by {indent} spaces"
    assert "$schema" not in page(), "the page carries a $schema key"


def test_no_em_dash_in_the_page() -> None:
    """The repo's plain-prose convention, gated for this adapter as it is for pi."""
    for path in HOOK_FILES:
        assert path.is_file(), f"{path} is missing"
        assert EM_DASH not in path.read_text(encoding="utf-8"), f"{path.name} has a dash"


def test_the_page_is_listed_as_a_harness_hook_in_the_index() -> None:
    """Ruling 12: claude-code/ joins the index under pi's own wording.

    The three phrases the pi suite pins must stay intact, and the new entry has to
    say the same thing about the new directory: a harness hook, not a tracker
    adapter. A page that sold the block as an adapter would put it under a contract
    it implements neither seam of.
    """
    text = (REPO / "integrations" / "README.md").read_text(encoding="utf-8")
    for pinned in ("harness hook", "not a tracker adapter",
                   "Tracker adapters for any other tool"):
        assert pinned in text, f"the index lost the phrase {pinned!r}"
    listing = text[text.index("## Existing directories"):text.index("Tracker adapters for")]
    assert "claude-code/" in listing, "the index does not list claude-code/"
    entry = listing[listing.index("claude-code/"):]
    entry = entry[:entry.index("\n\n")] if "\n\n" in entry else entry
    assert "harness hook" in entry, "the new entry does not call it a harness hook"
    assert "not a tracker adapter" in entry, "the new entry blurs the two kinds"


def test_the_harness_is_named_nowhere_outside_integrations() -> None:
    """The purity rule as a check: the harness word is confined to integrations/.

    The list comes from ``git ls-files``, not a filesystem walk, so an untracked
    scratch file adds no offender and a renamed core page cannot drop out silently.
    The check is this harness's own: the pi suite's ``HARNESS_WORD`` is ``\\bpi\\b``
    and would not match the name a second adapter brings in.
    """
    tracked = _git(REPO, "ls-files", *CORE_GLOBS).stdout.split()
    assert tracked, "expected to run inside a git checkout"
    found = harness_lines(tracked)
    assert not found, f"the harness is named outside integrations/: {found}"
