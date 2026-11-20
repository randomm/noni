"""Static checks over the pi harness hook under integrations/pi/.

The hook is the one place in this repository that runs a coding agent's
lifecycle: ``noni.ts`` adds a standing reminder to the prompt every turn and
injects ``noni brief`` at session start and after each compaction. No node
toolchain runs in CI (``.github/workflows/ci.yml`` installs jq, coverage,
pytest, ruff and build), so this module reads the source as text and asserts the
shape the ticket ruled:

- exactly three events are registered, and the brief is spawned from the two
  start handlers only, never from the per-turn handler;
- the reminder and the failure line are each within the 300-character bound,
  and the failure line replaces a path with the words "state root";
- the file is within its 80-line budget, which the size gate does not measure
  (``tests/test_file_size_limit.py`` caps ``.py``, ``.sh``, ``.jq``, workflow
  YAML, ``SKILL.md`` and shebang'd files, and a plain ``.ts`` is exempt);
- no added prose carries an em dash, and the harness is named nowhere outside
  ``integrations/pi/``.

Text assertions are the only form available: Python's stdlib has no TypeScript
parser, so the ``ast``-based readers other suites use (``intent_class_ast.py``,
``fifo_ast_support.py``) do not apply here.
"""

from __future__ import annotations

import re
from pathlib import Path

from _harness import REPO

# The scrub's own tables, so the hook is measured by the patterns CI's scrub step
# runs rather than by a copy of them (the same source tests/test_skill_scrub.py
# and tests/test_purity.py read). No noqa: the import sits where ruff expects it.
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

EVENTS = ("session_start", "session_compact", "before_agent_start")
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

_REGISTERED = re.compile(r'pi\.on\(\s*"([a-z_]+)"')
# The one spawn in the file, and where it sits: the per-turn handler is the last
# registration, so a spawn after it is a brief billed to every prompt.
_SPAWN = re.compile(r'pi\.exec\("noni", \["brief", "--repo", root\]')
# The reminder is one quoted sentence per source line, joined by +. A quoted
# string runs to the next quote, which is why the scan is character-shaped rather
# than a line regex: the text carries an apostrophe.
_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
_FAILURE_LINE = re.compile(r'(?:return|const \w+ =)\s*(`noni: could not read[^`]*`)')


def _source() -> str:
    assert EXTENSION.is_file(), f"{EXTENSION} is missing"
    return EXTENSION.read_text(encoding="utf-8")


def _handler_body(source: str, event: str) -> str:
    """The registered handler for ``event``, sliced to the next registration.

    Registration order in the file is the order of ``EVENTS``, so the next
    ``pi.on("`` after this one is the handler's end. A check over a slice rather
    than over the whole file is what makes "the brief is never fetched per turn"
    a claim about the per-turn handler instead of a claim about the file.
    """
    starts = [match.start() for match in _REGISTERED.finditer(source)]
    assert len(starts) == len(EVENTS), f"expected {len(EVENTS)} registrations"
    index = [m.group(1) for m in _REGISTERED.finditer(source)].index(event)
    end = starts[index + 1] if index + 1 < len(starts) else len(source)
    return source[starts[index]:end]


def _string_literal(source: str, name: str) -> str:
    """The value of ``const NAME = "..." + "...";``, joined.

    The reminder is written across a few lines for readability, so the bound is
    measured on the joined string the model receives, not on one fragment of it.
    The scan stops at the closing semicolon that ends the declaration (the
    sentence itself contains semicolons, so it is the one at the end of a line
    that ends it), and a quoted piece is read quote to quote so an apostrophe
    inside the sentence cannot end it early.
    """
    head = f"const {name} ="
    start = source.index(head)
    rest = source[start + len(head):]
    end = re.search(r";\s*$", rest[: rest.index("\n\n")], re.MULTILINE)
    assert end, f"const {name} has no terminating semicolon"
    pieces = _QUOTED.findall(rest[: end.end()])
    assert pieces and "".join(pieces).strip(), f"const {name} is empty"
    assert len(pieces) * 2 == rest[: end.end()].count('"'), f"const {name} is malformed"
    joined = "".join(pieces)
    assert joined == joined.strip(), f"const {name} lost its spacing"
    return joined


def test_the_extension_registers_exactly_the_three_events() -> None:
    """AC/ruled: two start events and the per-turn handler, and nothing else."""
    assert _REGISTERED.findall(_source()) == list(EVENTS)


def test_the_brief_is_spawned_from_the_start_handlers_only() -> None:
    """The one-shot injection is the whole cost of the brief: never per turn.

    The ticket's token rule is that the reminder is tiny and always on, and the
    full brief is paid for twice per session. A fetch reachable from the per-turn
    handler would bill a census run to every prompt.
    """
    source = _source()
    spawns = [match.start() for match in _SPAWN.finditer(source)]
    assert spawns, "the hook spawns no `noni brief`"
    for event in EVENTS[:2]:
        assert "await fetchBrief(ctx.cwd);" in _handler_body(source, event), (
            f"{event} does not fetch the brief")
    per_turn_at = source.index('pi.on("before_agent_start"')
    assert all(at < per_turn_at for at in spawns), (
        "the brief is spawned from the per-turn handler, which bills it per turn")


def test_the_brief_argv_names_the_state_root_flag() -> None:
    """`noni brief --repo <root>`: the hook passes --repo itself.

    ``src/noni/brief.py`` makes --repo required and no core module reads the
    environment for a state root (``tests/test_brief_now.py`` pins that), so a
    hook that forgot the flag gets exit 2 and the session gets a failure line.
    """
    assert '"--repo", root' in _source()


def test_the_brief_runs_under_a_timeout_and_without_a_shell() -> None:
    """pi.exec with { timeout: 10_000 } and no shell.

    ``session_compact`` fires while pi counts as busy, so a slow brief is a slow
    session; and a shell would be a second way for a path or a name to reach the
    command line.
    """
    source = _source()
    assert "pi.exec(" in source
    assert re.search(r"\{\s*timeout:\s*BRIEF_TIMEOUT_MS\s*\}", source), (
        "the spawn carries no timeout")
    assert "BRIEF_TIMEOUT_MS = 10_000" in source
    assert "shell" not in source


def test_the_reminder_is_within_the_character_bound() -> None:
    """The 300-character reminder is a gate, not prose (ruled finding, MEDIUM).

    The bound is measured on the joined string the model receives; the assertion
    that it is a real sentence is what keeps a reader that found no text at all
    from passing an upper bound vacuously.
    """
    reminder = _string_literal(_source(), "REMINDER")
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
    source = _source()
    match = _FAILURE_LINE.search(source)
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
    source = _source()
    body = _handler_body(source, "before_agent_start")
    assert "promptGuidelines" in body, "no prompt guideline is added per turn"
    for forbidden in ("systemPrompt:", "forceSystemPrompt"):
        assert forbidden not in source, f"{forbidden} would miss the prompt cache"
    assert "sendMessage" not in source, (
        "sendMessage with triggerTurn re-enters before_agent_start")


def test_the_brief_is_returned_once_for_a_user_run() -> None:
    """The pending value is consumed by a run whose messageType is "user"."""
    body = _handler_body(_source(), "before_agent_start")
    assert 'event.messageType !== "user"' in body, (
        "a run started by a custom message could re-inject the brief")
    assert "pendingBrief = undefined" in body, "the pending brief is not cleared"
    assert "customType" in body and "message:" in body


def test_the_fetch_needs_an_interactive_session() -> None:
    """Ruling 3: the brief is fetched only when ctx.hasUI, the reminder is not."""
    source = _source()
    assert source.count("if (ctx.hasUI) await fetchBrief(ctx.cwd);") == 2, (
        "the brief is not gated on an interactive session in both start events")
    assert "ctx.hasUI" not in _handler_body(source, "before_agent_start"), (
        "the reminder must apply in every mode, including a headless one")


def test_the_state_root_resolution_order_is_the_ruled_one() -> None:
    """NONI_STATE_ROOT, then <cwd>/.noni-state holding noni/, then <cwd>.

    The order is read from the code rather than from a list of substrings: a
    resolver that consulted the working directory first would still contain
    every name below, and the env var's precedence is the whole ruling.
    """
    source = _source()
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


def test_the_extension_file_stays_within_its_line_budget() -> None:
    """80 lines, asserted here because the size gate exempts a plain .ts.

    ``_limit_for`` in tests/test_file_size_limit.py measures .py, .sh, .jq,
    workflow YAML, SKILL.md and anything with a shebang first line; a .ts with
    no shebang is invisible to it, so the ticket's budget needs its own check.
    """
    lines = _source().splitlines()
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
