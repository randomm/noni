"""The pi harness hook under integrations/pi/, checked as text and driven.

The hook is the one place in this repository that runs a coding agent's
lifecycle: ``noni.ts`` adds a standing reminder to the prompt every turn and
injects ``noni brief`` at session start and after each compaction. No node
toolchain runs in CI (``.github/workflows/ci.yml`` installs jq, coverage,
pytest, ruff and build), so this module reads the source as text and asserts the
shape the ticket ruled:

- exactly three events are registered, and neither the spawn nor the fetch
  call reaches the per-turn handler, lexically over that handler's body;
- the reminder and the failure line are each within the 300-character bound,
  and the failure line replaces a path with the words "state root";
- the per-turn behaviour is also driven for real: a node harness loads
  ``noni.ts`` under ``node --experimental-strip-types`` and hands it a fake
  ``ExtensionAPI``, which is where the once-per-turn reminder, the empty-output
  arm and the no-shell option are checked (node and the flag are both optional,
  so the suite skips that half rather than failing where node is absent);
- the file is within its 80-line budget, which the size gate does not measure
  (``tests/test_file_size_limit.py`` caps ``.py``, ``.sh``, ``.jq``, workflow
  YAML, ``SKILL.md`` and shebang'd files, and a plain ``.ts`` is exempt);
- no added prose carries an em dash, and the harness is named nowhere outside
  ``integrations/pi/``.

The file holds the assertions only. The readers they share are in
``pi_hook_checks.py``, the node driver in ``pi_hook_driver.py`` and its launcher
in ``pi_hook_launch.py``, because the size gate
(``tests/test_file_size_limit.py``) caps a ``.py`` at 500 lines and this suite
needs more than that of text to say what it rules out.

Both forms of check are load-bearing, and neither is redundant:

- the static assertions catch what a single run cannot see (a rename that drops
  the ``--repo`` flag, an em dash, the harness word escaping ``integrations/``);
- the driven assertions catch what no text scan can: a fetch reached only through
  the fetcher's name inside the per-turn handler, or a reminder guard whose
  deletion leaves the file's text looking correct. Each has been confirmed by
  planting that regression and watching the suite fail.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# The scrub's own tables, so the hook is measured by the patterns CI's scrub step
# runs rather than by a copy of them (the same source tests/test_skill_scrub.py
# and tests/test_purity.py read). No noqa: the import sits where ruff expects it.
from _harness import REPO
from pi_hook_checks import (
    EVENTS,
    FAILURE_LINE,
    SPAWN_CALL,
    handler_body,
    registrations,
    source_text,
    spawn_offsets,
    string_literal,
)
from pi_hook_launch import node_available, run_hook
from public_safety import (
    FIXTURE_HOME_PATH_PATTERNS,
    HOME_PATH_PATTERNS,
    SECRET_PATTERNS,
)

PI_DIR = REPO / "integrations" / "pi"
EXTENSION = PI_DIR / "noni.ts"
HOOK_README = PI_DIR / "README.md"
HOOK_FILES: tuple[Path, ...] = (EXTENSION, HOOK_README)

FORBIDDEN: list[tuple[re.Pattern[str], str]] = [
    *HOME_PATH_PATTERNS,
    *FIXTURE_HOME_PATH_PATTERNS,
    *SECRET_PATTERNS,
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}"), "bearer token"),
]

LINE_LIMIT = 300
FILE_LINE_LIMIT = 80

# U+2014, written as an escape so this file does not carry the character it bans.
EM_DASH = "\u2014"

# The harness's own name as a word, case-insensitively. ``\bpi\b`` is the whole
# matcher: it is what the purity rule confines to integrations/, and a core page
# has no reason to write the word at all.
HARNESS_WORD = re.compile(r"\bpi\b", re.IGNORECASE)

# The core, as the purity rule sees it: the skills, the docs, the readme. Not
# scripts/ or src/ (no hook vocabulary can reach them), and not tests/ -- this
# module names the harness because it is the check over the hook.
CORE_DIRS: tuple[Path, ...] = (REPO / "skills", REPO / "docs")
CORE_FILES: tuple[Path, ...] = (REPO / "README.md",)

def _source() -> str:
    """The hook's source, with its absence reported as a missing file."""
    return source_text(EXTENSION)


def _skip_without_node() -> None:
    """The driven half is optional: the CI image installs no node toolchain.

    The launcher needs a node binary to load a ``.ts`` hook at all, so the
    behavioural checks skip where none exists rather than fail. The static
    assertions over the same file run either way.
    """
    if not node_available():
        pytest.skip("node is not installed, so the hook cannot be driven")


def test_the_extension_registers_exactly_the_three_events() -> None:
    """AC/ruled: two start events and the per-turn handler, and nothing else."""
    assert registrations(source_text(EXTENSION)) == list(EVENTS)


def test_the_brief_is_spawned_from_the_start_handlers_only() -> None:
    """The one-shot injection is the whole cost of the brief: never per turn.

    The ticket's token rule is that the reminder is tiny and always on, and the
    full brief is paid for twice per session. A fetch reachable from the per-turn
    handler would bill a census run to every prompt.
    """
    source = source_text(EXTENSION)
    spawns = spawn_offsets(source)
    assert spawns, "the hook spawns no `noni brief`"
    for event in EVENTS[:2]:
        assert "await fetchBrief(ctx.cwd);" in handler_body(source, event), (
            f"{event} does not fetch the brief")
    per_turn = handler_body(source, "before_agent_start")
    # Lexical, over the body of the per-turn handler: a call to the fetcher
    # there carries no `pi.exec` text at all, so a positional check over the
    # spawn offsets alone lets it through.
    assert "fetchBrief" not in per_turn, (
        "the per-turn handler can reach the brief, which bills a census run "
        "to every prompt")
    assert "pi.exec" not in per_turn, (
        "the brief is spawned from the per-turn handler, which bills it per turn")
    per_turn_at = source.index('pi.on("before_agent_start"')
    assert all(at < per_turn_at for at in spawns), (
        "a spawn sits at or after the per-turn registration")


def test_the_brief_argv_names_the_state_root_flag() -> None:
    """`noni brief --repo <root>`: the hook passes --repo itself.

    ``src/noni/brief.py`` makes --repo required and no core module reads the
    environment for a state root (``tests/test_brief_now.py`` pins that), so a
    hook that forgot the flag gets exit 2 and the session gets a failure line.
    """
    assert '"--repo", root' in source_text(EXTENSION)


def test_the_brief_runs_under_a_timeout_and_without_a_shell() -> None:
    """pi.exec with { timeout: 10_000 } and no shell.

    ``session_compact`` fires while pi counts as busy, so a slow brief is a slow
    session; and a shell would be a second way for a path or a name to reach the
    command line.
    """
    source = source_text(EXTENSION)
    assert "pi.exec(" in source
    assert re.search(r"\{\s*timeout:\s*BRIEF_TIMEOUT_MS\s*\}", source), (
        "the spawn carries no timeout")
    assert "BRIEF_TIMEOUT_MS = 10_000" in source
    # The rule is about the options object the command is actually given: a word
    # ban over the file would pass `{ timeout, useShell: true }`.
    options = SPAWN_CALL.findall(source)
    assert options, "no spawn call to read options from"
    for text in options:
        assert "shell" not in text, f"the spawn options mention a shell: {text}"
        assert re.search(r"\btimeout\b", text), f"the spawn options carry no timeout: {text}"


def test_the_reminder_is_within_the_character_bound() -> None:
    """The 300-character reminder is a gate, not prose (ruled finding, MEDIUM).

    The bound is measured on the joined string the model receives; the assertion
    that it is a real sentence is what keeps a reader that found no text at all
    from passing an upper bound vacuously.
    """
    reminder = string_literal(source_text(EXTENSION), "REMINDER")
    assert len(reminder) <= LINE_LIMIT, f"reminder is {len(reminder)} characters"
    assert len(reminder) >= 120, f"no reminder text was read: {reminder!r}"
    assert reminder.startswith("noni "), f"the reminder leads elsewhere: {reminder!r}"
    assert reminder.endswith("command."), f"the reminder is cut short: {reminder!r}"
    assert "noni decide" in reminder, "the reminder no longer routes an undecided"
    for word in ("order", "decisions", "invent"):
        assert word in reminder, f"the reminder dropped {word!r}"


def test_the_failure_line_is_within_the_bound_and_leaks_no_path() -> None:
    """One short failure line, with every path token replaced by "state root".

    ``brief.py`` prints ``--repo <path> is not a directory`` on stderr, so the
    first stderr line can carry the state root's absolute path. The bound is the
    same 300 the reminder carries.

    The redaction is checked twice over. The template must name the fallback, and
    the reason handed to it must be the ``.replace`` output rather than the raw
    stderr: an assertion on the words alone stays green when the replacement is
    dropped and only its result is unused.
    """
    source = source_text(EXTENSION)
    match = FAILURE_LINE.search(source)
    assert match, "the failure line is missing from the hook"
    assert len(match.group(1)) - 2 <= LINE_LIMIT, (
        f"the failure line template is {len(match.group(1)) - 2} characters")
    assert '"state root"' in source, "the failure line no longer redacts paths"
    assert re.search(r'firstLine\.replace\(PATH_TOKEN, "state root"\)', source), (
        "the reason reaches the failure line unredacted")
    assert re.search(r"\.slice\(0, LINE_LIMIT", source), "the cap is not applied"


def test_the_reminder_is_added_as_a_prompt_guideline() -> None:
    """systemPromptOptions.promptGuidelines, never a returned systemPrompt.

    pi diffs the structured options and patches only the changed section;
    returning ``systemPrompt`` or setting ``forceSystemPrompt`` is a provider
    cache miss on every turn that changed, which is the wasted-token cost the
    operator's decision rules out.
    """
    source = source_text(EXTENSION)
    body = handler_body(source, "before_agent_start")
    assert "promptGuidelines" in body, "no prompt guideline is added per turn"
    assert "guidelines.push(REMINDER)" in body, (
        "nothing adds the reminder, so the standing bullet is never in the prompt")
    # Without the guard the push runs on every turn, so the bullet is handed to
    # pi once per turn for the same run.
    assert re.search(r"if \(!guidelines\.includes\(REMINDER\)\)", body), (
        "the reminder is pushed unconditionally, so it can be added twice in a turn")
    for forbidden in ("systemPrompt:", "forceSystemPrompt"):
        assert forbidden not in source, f"{forbidden} would miss the prompt cache"
    assert "sendMessage" not in source, (
        "sendMessage with triggerTurn re-enters before_agent_start")


def test_the_brief_is_returned_once_for_a_user_run() -> None:
    """The pending value is consumed by a run whose messageType is "user".

    The value is read into a local before it is cleared, so a run that returns
    it cannot also leave it pending for the next one.
    """
    body = handler_body(source_text(EXTENSION), "before_agent_start")
    assert 'event.messageType !== "user"' in body, (
        "a run started by a custom message could re-inject the brief")
    assert "const content = pendingBrief;" in body, (
        "the pending brief is not read into the returned message")
    assert "pendingBrief = undefined" in body, "the pending brief is not cleared"
    assert "customType" in body and "message:" in body


def test_the_fetch_needs_an_interactive_session() -> None:
    """Ruling 3: the brief is fetched only when ctx.hasUI, the reminder is not."""
    source = source_text(EXTENSION)
    assert source.count("if (ctx.hasUI) await fetchBrief(ctx.cwd);") == 2, (
        "the brief is not gated on an interactive session in both start events")
    assert "ctx.hasUI" not in handler_body(source, "before_agent_start"), (
        "the reminder must apply in every mode, including a headless one")


def test_the_state_root_resolution_order_is_the_ruled_one() -> None:
    """NONI_STATE_ROOT, then <cwd>/.noni-state holding noni/, then <cwd>.

    The order is read from the code rather than from a list of substrings: a
    resolver that consulted the working directory first would still contain
    every name below, and the env var's precedence is the whole ruling.
    """
    source = source_text(EXTENSION)
    body = source[: source.index("export default")]
    resolver = body[body.index("function stateRoot"):]
    env_at = resolver.index('env["NONI_STATE_ROOT"]')
    assert 'if (fromEnv) return fromEnv;' in resolver, (
        "the env var is not taken whole, so a bad value cannot reach the failure arm")
    candidates = resolver[resolver.index("for (const candidate of"):]
    assert 'join(cwd, ".noni-state")' in candidates, "the pilot layout is not consulted"
    assert candidates.index(".noni-state") < candidates.index("), cwd]"), (
        "the bare working directory is tried before the pilot's state directory")
    assert 'join(candidate, "noni")' in resolver, "a root is taken without its noni/"
    assert "return undefined" in resolver, "with no state root the hook has no arm"
    assert env_at < resolver.index("for (const candidate of"), (
        "the env var is not the first source")


def test_the_hook_registers_two_start_events_and_one_per_turn_event(
    tmp_path: Path,
) -> None:
    """Driven: the three registrations are exactly the three ruled events.

    The static check reads the literal ``pi.on("`` calls; this observes what the
    module actually registers when loaded, which is the only form that catches a
    handler registered through a variable or an alias.
    """
    assert list(run_hook(tmp_path, EXTENSION)["registrations"]["registrations"]) == list(EVENTS)


def test_the_driven_hook_spawns_twice_per_session_and_never_per_turn(
    tmp_path: Path,
) -> None:
    """Driven: two spawns for the session, then zero across three runs.

    This is the ticket's central token rule observed rather than inferred from
    text: a per-turn fetch would show up here as spawns beyond ``afterStarts``,
    which is exactly the regression the static assertion above cannot see when
    the call is hidden behind the fetcher's name.
    """
    _skip_without_node()
    run = run_hook(tmp_path, EXTENSION)["spawns"]
    assert run["afterStarts"] == 2, f"{run['afterStarts']} spawns for the two start events"
    assert run["turns"] == 0, f"{run['turns']} spawns across three runs"
    assert run["spawn"]["command"] == "noni"
    assert run["spawn"]["args"][:2] == ["brief", "--repo"]
    assert run["spawn"]["args"][2].endswith("project")
    # The options object itself, not the word "shell" somewhere in the file.
    assert run["spawn"]["options"] == {"timeout": 10_000}


def test_the_driven_hook_adds_one_reminder_for_the_whole_session(
    tmp_path: Path,
) -> None:
    """Driven: three runs on one options object leave exactly one bullet.

    pi copies the array once per run, so a push without the guard is a second
    copy of the same bullet in the prompt for the run that pushed it. The static
    check pins the guard's shape; this pins what the guard is for.
    """
    _skip_without_node()
    run = run_hook(tmp_path, EXTENSION)["reminder"]
    assert run["copies"] == [1, 1, 1], (
        f"the reminder reached the prompt {run['copies']} times over three runs")
    assert len(run["bullets"]) == 1, f"other bullets appeared: {run['bullets']}"


def test_the_driven_hook_gives_a_headless_session_the_reminder_and_no_brief(
    tmp_path: Path,
) -> None:
    """Driven: hasUI false means no spawn, and the standing bullet still lands."""
    _skip_without_node()
    run = run_hook(tmp_path, EXTENSION)["headless"]
    assert run["spawns"] == 0, "a headless session spawned the brief"
    assert run["once"] == 1, "the reminder is gated on an interactive session"


def test_the_driven_hook_injects_the_brief_once_and_for_a_user_run_only(
    tmp_path: Path,
) -> None:
    """Driven: the first user run gets the message, nothing after it does.

    A run started by a custom message must not consume or re-inject it, which is
    what ``again`` and ``custom`` are for: both are undefined only when the value
    was cleared by the run that returned it.
    """
    _skip_without_node()
    run = run_hook(tmp_path, EXTENSION)["brief"]
    first = run["first"]
    assert first and first["message"]["content"] == "order: 7 then 3"
    assert first["message"]["customType"] == "noni-brief"
    assert first["message"]["display"] is True
    assert run["again"] is False, "the brief was injected on a second run"
    assert run["custom"] is False, "a custom-message run received the brief"


@pytest.mark.parametrize("name, content", [
    ("failure", "brief: --repo state root is not a directory"),
    ("empty", "(exit code 0)"),
])
def test_the_driven_hook_reports_a_failure_without_a_path(
    tmp_path: Path, name: str, content: str,
) -> None:
    """Driven: the failure arm names the reason, capped, with the path scrubbed.

    The exit-2 case carries a home path in stderr; the exit-0-with-no-output case
    must still say something, or the model gets an empty message and no idea the
    census run failed.
    """
    _skip_without_node()
    run = run_hook(tmp_path, EXTENSION)[name]
    message = run["message"]["message"]
    assert message["customType"] == "noni-brief"
    assert content in message["content"], message["content"]
    assert "/" not in message["content"], f"a path reached the model: {message}"
    assert len(message["content"]) <= LINE_LIMIT


def test_the_driven_hook_stays_quiet_with_no_state_root(tmp_path: Path) -> None:
    """Driven: with no root to read, no spawn and no message of any kind.

    The scenario names its own working directory and its own ``NONI_STATE_ROOT``,
    both reported back, so the case cannot pass by running in a tree that happens
    to hold a ``noni/`` directory. The hook then has neither an env root nor a
    candidate to spawn against, and the ticket's rule for that arm is silence:
    the reminder stays, the brief does not appear.
    """
    _skip_without_node()
    run = run_hook(tmp_path, EXTENSION)["no-state"]
    assert run["cwd"] == str(tmp_path / "bare"), f"ran against {run['cwd']}"
    assert run["env"] == "", "the scenario ran without its empty state root"
    assert run["spawned"] == 0, "the hook spawned `noni brief` with no state root"
    assert run["message"] is False, "the hook injected a message with no state root"


def test_the_extension_file_stays_within_its_line_budget() -> None:
    """80 lines, asserted here because the size gate exempts a plain .ts.

    ``_limit_for`` in tests/test_file_size_limit.py measures .py, .sh, .jq,
    workflow YAML, SKILL.md and anything with a shebang first line; a .ts with
    no shebang is invisible to it, so the ticket's budget needs its own check.
    """
    lines = source_text(EXTENSION).splitlines()
    assert len(lines) <= FILE_LINE_LIMIT, f"noni.ts is {len(lines)} lines"


def test_no_em_dash_in_the_hook_or_its_page() -> None:
    """The repo's plain-prose convention, gated for integrations/pi/ itself.

    No dash gate exists anywhere in the suite for prose, so the bound the ticket
    states has to be asserted where the added prose lives.
    """
    for path in HOOK_FILES:
        assert path.is_file(), f"{path} is missing"
        assert EM_DASH not in path.read_text(encoding="utf-8"), (
            f"{path.name} carries an em dash")


def test_the_hook_files_pass_the_scrub_read_by_ci() -> None:
    """The two files under integrations/pi/ carry no path, name or token shape.

    CI's scrub step (``scripts/public_safety.py``) reads every tracked file of
    the checkout, so it is the gate that covers a ``.ts`` the purity and skill
    suites never open. It needs the files to be committed to see them, which the
    commit is for; this check runs the same pattern tables against the working
    copy, so a machine-local path or a token reaches the tree as a test failure
    rather than as a CI job that has not run yet.
    """
    for path in HOOK_FILES:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern, label in FORBIDDEN:
                assert not pattern.search(line), (
                    f"{path.relative_to(REPO)}:{lineno}: {label}")


def test_the_page_names_the_state_root_the_install_and_the_check() -> None:
    """What a reader needs from the page: the env var, the install target, the
    PATH prerequisite linked to the quickstart, the main-agent rule, and how to
    verify it."""
    text = HOOK_README.read_text(encoding="utf-8")
    assert "NONI_STATE_ROOT" in text, "the page does not name the state root source"
    assert ".pi/extensions" in text, "the page does not name the install target"
    assert "docs/QUICKSTART.md#install-noni" in text, (
        "the page does not link the quickstart's Install section for the PATH step")
    assert "on your PATH" in text, "the page omits the noni-on-PATH prerequisite"
    assert "no reliable way to tell a child session" in text, (
        "the page must state the main-agent rule's limit, not invent a signal")
    assert "## Verifying it" in text, "the page states no way to verify the hook"


def test_the_hook_is_not_sold_as_a_tracker_adapter() -> None:
    """integrations/README.md: pi/ named as a harness hook, seams not claimed."""
    text = (REPO / "integrations" / "README.md").read_text(encoding="utf-8")
    assert "harness hook" in text, "the page does not name pi/ as a harness hook"
    assert "not a tracker adapter" in text, "the page blurs the two kinds"
    assert "Tracker adapters for any other tool" in text, (
        "the closing sentence still claims every adapter implements the two seams")


def test_the_harness_is_named_nowhere_outside_integrations() -> None:
    """The purity rule as a check: the harness word is confined to integrations/.

    tests/test_purity.py reads the skill pages and docs/*.md against the
    untracked deny-list, and tests/test_skill_scrub.py reads the skill dirs and
    the fixtures; neither reaches a .ts under integrations/, and neither would
    notice the harness word appearing in a core page. The scan is the complement:
    every tracked file outside integrations/ and this suite.
    """
    tracked = (REPO / ".git").exists()
    assert tracked, "expected to run inside a git checkout"
    offenders: list[str] = []
    for base in CORE_DIRS:
        for path in sorted(base.rglob("*")):
            if path.is_file():
                offenders += _name_lines(path)
    for path in CORE_FILES:
        offenders += _name_lines(path)
    assert not offenders, f"the harness is named outside integrations/: {offenders}"


def _name_lines(path: Path) -> list[str]:
    """Lines of a core file that name the harness as a word."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return [f"{path.relative_to(REPO)}:{number}: {line.strip()}"
            for number, line in enumerate(text.splitlines(), 1)
            if HARNESS_WORD.search(line)]
