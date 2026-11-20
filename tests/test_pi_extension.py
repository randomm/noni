"""The pi harness hook under integrations/pi/, checked as text.

``noni.ts`` is the one place in this repository that runs a coding agent's
lifecycle: a standing reminder in the prompt every turn, and ``noni brief``
injected at session start and after each compaction. CI installs no node
toolchain (``.github/workflows/ci.yml`` installs jq, coverage, pytest, ruff and
build), so this module reads the source as text and asserts the shape the
ticket ruled: the spawn lives only inside ``fetchBrief`` and the start events
start it without awaiting; the per-turn handler awaits the in-flight fetch and
returns ``{message}`` only for a run whose ``messageType`` is "user"; the
reminder is one deduplicated ``promptGuidelines`` push within 300 characters and
never a returned or forced ``systemPrompt``; the fetch runs under a 30 000 ms
timeout inside a ``try``/``catch`` and its failure line is capped and
path-scrubbed; the file is within its 80-line budget, its prose carries no em
dash, the harness is named nowhere in the core, and the page names the trust
step, the state root, the install target and the PATH rule.

The live check (the page's "Verifying it", run against a real session) carries
the behaviour; these assertions carry the shape. The readers below are shared so
"the body of the per-turn handler" has one definition every check agrees with.
"""

from __future__ import annotations

import re
from pathlib import Path

from _harness import REPO, _git

PI_DIR = REPO / "integrations" / "pi"
EXTENSION = PI_DIR / "noni.ts"
HOOK_README = PI_DIR / "README.md"
HOOK_FILES: tuple[Path, ...] = (EXTENSION, HOOK_README)

EVENTS = ("session_start", "session_compact", "before_agent_start")
REGISTERED = re.compile(r'pi\.on\(\s*"([a-z_]+)"')
QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
FAILURE_LINE = re.compile(r"(?:return|const \w+ =)\s*(`noni: could not read[^`]*`)")
# Every form of the spawn call, so the timeout rule reads the options object the
# command actually carries rather than the word "timeout" somewhere in the file.
SPAWN_CALL = re.compile(r"pi\.exec\((.*?)\)", re.DOTALL)

LINE_LIMIT = 300
FILE_LINE_LIMIT = 80

# U+2014, written as an escape so this file does not carry the character it bans.
EM_DASH = "\u2014"

# The harness's own name as a word. The purity rule confines it to
# integrations/, and a core page has no reason to write it at all.
HARNESS_WORD = re.compile(r"\bpi\b", re.IGNORECASE)

# The core, as the purity rule sees it: the skills, the docs, the readme. Tests
# are excluded because this module is the check over the hook and names it.
CORE_GLOBS = ("skills/*", "docs/*", "README.md")


def source() -> str:
    """The hook's source, with its absence reported as a missing file."""
    assert EXTENSION.is_file(), f"{EXTENSION} is missing"
    return EXTENSION.read_text(encoding="utf-8")


def registrations(text: str) -> list[str]:
    """The event names registered, in registration order."""
    return REGISTERED.findall(text)


def handler_body(text: str, event: str) -> str:
    """The registered handler for ``event``, sliced to the next registration.

    Registration order is the order of ``EVENTS``, so the next ``pi.on("`` is the
    handler's end. A check over a slice is what makes "the brief is never fetched
    per turn" a claim about the per-turn handler, not about the file.
    """
    starts = [m.start() for m in REGISTERED.finditer(text)]
    assert len(starts) == len(EVENTS), f"expected {len(EVENTS)} registrations"
    index = registrations(text).index(event)
    return text[starts[index]: starts[index + 1] if index + 1 < len(starts) else len(text)]


def function_body(text: str, name: str) -> str:
    """The body of ``function name(`` up to its closing brace at column 4."""
    start = text.index(f"function {name}(")
    return text[start:text.index("\n  }", start)]


def string_literal(text: str, name: str) -> str:
    """The value of ``const NAME = "..." + "...";``, joined.

    The bound is measured on the joined string the model receives, so the scan
    stops at the semicolon ending the declaration and reads quoted pieces quote
    to quote, where an apostrophe in the sentence cannot end a piece early. Three
    assertions keep a vacuous read out.
    """
    head = f"const {name} ="
    rest = text[text.index(head) + len(head):]
    end = re.search(r";\s*$", rest[: rest.index("\n\n")], re.MULTILINE)
    assert end, f"const {name} has no terminating semicolon"
    pieces = QUOTED.findall(rest[: end.end()])
    assert pieces and "".join(pieces).strip(), f"const {name} is empty"
    assert len(pieces) * 2 == rest[: end.end()].count('"'), f"const {name} is malformed"
    joined = "".join(pieces)
    assert joined == joined.strip(), f"const {name} lost its spacing"
    return joined


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


def test_the_extension_registers_exactly_the_three_events() -> None:
    """Two start events and the per-turn handler, and nothing else."""
    assert registrations(source()) == list(EVENTS)


def test_the_brief_is_spawned_only_from_the_fetcher() -> None:
    """One spawn in the file, inside ``fetchBrief``: a spawn reachable from a
    handler would bill a census run per turn instead of twice per session.
    """
    text = source()
    spawns = [match.start() for match in SPAWN_CALL.finditer(text)]
    assert len(spawns) == 1, f"{len(spawns)} spawns of `noni brief`"
    assert spawns[0] > text.index("function fetchBrief"), (
        "the brief is spawned outside the fetcher")
    assert "pi.exec" not in handler_body(text, "before_agent_start"), (
        "the per-turn handler spawns the brief")


def test_the_start_handlers_start_the_fetch_without_awaiting_it() -> None:
    """The start events store the in-flight promise; they do not await it.
    ``session_compact`` fires while pi counts as busy, so an awaited fetch there
    delays the session for a result no handler needs yet.
    """
    text = source()
    for event in EVENTS[:2]:
        body = handler_body(text, event)
        assert "inflight = fetchBrief(ctx.cwd);" in body, f"{event} does not start the fetch"
        assert "await" not in body, f"{event} awaits the fetch, so it blocks the session"
        assert "ctx.hasUI" in body, f"{event} fetches in a headless session"


def test_the_per_turn_handler_awaits_the_in_flight_fetch() -> None:
    """The run that needs the brief waits for it. The guard decides on the message
    type alone and sits before the await: a guard that also tests the promise lets
    a stale brief past, and an await before it blocks a non-user run.
    """
    body = handler_body(source(), "before_agent_start")
    assert "await inflight" in body, "no run waits for the in-flight fetch"
    guard = re.search(r'if \(event\.messageType !== "user"\) return undefined;', body)
    assert guard, "the user-run guard is not a plain messageType check"
    assert guard.start() < body.index("await inflight"), (
        "the fetch is awaited before the user-run guard")


def test_the_brief_is_returned_once_for_a_user_run_only() -> None:
    """``{message}`` comes back once: read into a local before it is cleared, so
    the run that returns it cannot leave it pending for the next one.
    """
    body = handler_body(source(), "before_agent_start")
    assert re.search(r'return \{\s*message:', body), "the handler returns no message"
    assert "const content = pendingBrief;" in body, (
        "the pending brief is not read into the returned message")
    assert "pendingBrief = undefined" in body, "the pending brief is not cleared"
    assert "customType" in body


def test_the_brief_argv_names_the_state_root_flag() -> None:
    """``noni brief --repo <root>``: ``src/noni/brief.py`` makes --repo required
    and no core module reads the environment for a root, so a hook that forgot
    the flag gets exit 2.
    """
    assert '"--repo", root' in source()


def test_the_brief_runs_under_a_timeout_and_without_a_shell() -> None:
    """pi.exec carries ``{ timeout: BRIEF_TIMEOUT_MS }`` and no shell option."""
    text = source()
    assert "BRIEF_TIMEOUT_MS = 30_000" in text, "the brief timeout is not 30 000 ms"
    for chunk in SPAWN_CALL.findall(text):
        assert re.search(r"\btimeout:\s*BRIEF_TIMEOUT_MS\b", chunk), f"no timeout: {chunk}"
        assert "shell" not in chunk, f"the spawn options mention a shell: {chunk}"


def test_the_fetcher_catches_every_failure() -> None:
    """``try``/``catch`` around the whole body, so no throw escapes to pi.
    ``existsSync`` and ``pi.exec`` both throw, and a throw out of a handler is a
    broken session where the ticket's arm is one short line naming the reason.
    """
    body = function_body(source(), "fetchBrief")
    assert "try {" in body, "the fetcher has no try block"
    assert "catch {" in body, "the fetcher has no catch block"
    assert "failureLine(" in body, "the catch does not produce a failure line"


def test_the_failure_arms_name_a_reason() -> None:
    """A kill says "timed out", empty stdout says "printed nothing", else stderr.
    An exit 0 with no output still has to say something, or the model gets an empty
    message and no idea the census run failed.
    """
    body = function_body(source(), "failureReason")
    assert 'if (r.killed) return "timed out";' in body, (
        "a killed run is not reported as a timeout")
    assert '"printed nothing"' in body, "an empty stdout has no reason of its own"
    assert "r.stderr.trim()" in body, "stderr is not the reason for a plain exit"
    assert "exit code" in body, "no reason for an exit code alone"
    # The success arm is the fetched stdout itself, taken before any reason is read.
    fetch = function_body(source(), "fetchBrief")
    assert "pendingBrief = stdout || failureLine(failureReason(result));" in fetch, (
        "a run that printed the brief does not hand over its stdout")


def test_the_failure_line_is_capped_and_leaks_no_path() -> None:
    """One short failure line, with every path token replaced by "state root".
    ``brief.py`` prints ``--repo <path> is not a directory`` on stderr, so that line
    can carry the state root's absolute path. Both halves are load-bearing: the
    template's length, and the ``.replace`` output rather than raw stderr.
    """
    text = source()
    match = FAILURE_LINE.search(text)
    assert match, "the failure line is missing from the hook"
    assert len(match.group(1)) - 2 <= LINE_LIMIT, (
        f"the failure line template is {len(match.group(1)) - 2} characters")
    assert re.search(r"first\.replace\(PATH_TOKEN, \"state root\"\)", text), (
        "the reason reaches the failure line unredacted")
    assert re.search(r"\.slice\(0, LINE_LIMIT", text), "the cap is not applied"


def test_the_reminder_is_a_deduplicated_prompt_guideline() -> None:
    """A ``promptGuidelines`` push, never a returned or forced ``systemPrompt``: pi
    diffs the structured options and patches only the changed section, where a
    forced prompt is a provider cache miss on every turn that changed. Without the
    guard the same bullet is handed over once per turn.
    """
    text = source()
    body = handler_body(text, "before_agent_start")
    assert "promptGuidelines" in body, "no prompt guideline is added per turn"
    assert "guidelines.push(REMINDER)" in body, "nothing adds the reminder"
    assert re.search(r"if \(!guidelines\.includes\(REMINDER\)\)", body), (
        "the reminder is pushed unconditionally, so it can be added twice")
    assert "ctx.hasUI" not in body, (
        "the reminder must apply in every mode, including a headless one")
    for forbidden in ("systemPrompt:", "forceSystemPrompt", "sendMessage"):
        assert forbidden not in text, f"{forbidden} would miss the prompt cache"


def test_the_reminder_is_within_the_character_bound() -> None:
    """The 300-character bound is a gate, not prose. The lower bound stops a reader
    that found no text at all from passing an upper bound vacuously.
    """
    reminder = string_literal(source(), "REMINDER")
    assert len(reminder) <= LINE_LIMIT, f"reminder is {len(reminder)} characters"
    assert len(reminder) >= 120, f"no reminder text was read: {reminder!r}"
    assert reminder.startswith("noni "), f"the reminder leads elsewhere: {reminder!r}"
    assert reminder.endswith("command."), f"the reminder is cut short: {reminder!r}"
    for word in ("order", "decisions", "invent", "noni decide"):
        assert word in reminder, f"the reminder dropped {word!r}"


def test_the_state_root_resolution_order_is_the_ruled_one() -> None:
    """NONI_STATE_ROOT, then <cwd>/.noni-state holding noni/, then <cwd>, read
    from the code: a resolver that consulted the working directory first would
    still hold every name below.
    """
    body = source()[: source().index("export default")]
    resolver = body[body.index("function stateRoot"):]
    loop = "for (const candidate of"
    candidates = resolver[resolver.index(loop):]
    assert 'if (fromEnv) return fromEnv;' in resolver, (
        "the env var is not taken whole, so a bad value cannot reach the failure arm")
    assert 'join(cwd, ".noni-state")' in candidates, "the pilot layout is not consulted"
    assert candidates.index(".noni-state") < candidates.index("), cwd]"), (
        "the bare working directory is tried before the pilot's state directory")
    assert 'join(candidate, "noni")' in resolver, "a root is taken without its noni/"
    assert "return undefined" in resolver, "with no state root the hook has no arm"
    assert resolver.index('env["NONI_STATE_ROOT"]') < resolver.index(loop), (
        "the env var is not the first source")


def test_the_extension_file_stays_within_its_line_budget() -> None:
    """80 lines, asserted here because ``_limit_for`` in
    tests/test_file_size_limit.py measures .py, .sh, .jq, workflow YAML, SKILL.md
    and anything with a shebang first line, so a plain .ts is invisible to it.
    """
    lines = source().splitlines()
    assert len(lines) <= FILE_LINE_LIMIT, f"noni.ts is {len(lines)} lines"


def test_no_em_dash_in_the_hook_or_its_page() -> None:
    """The repo's plain-prose convention, gated for integrations/pi/ itself."""
    for path in HOOK_FILES:
        assert path.is_file(), f"{path} is missing"
        assert EM_DASH not in path.read_text(encoding="utf-8"), f"{path.name} has a dash"


def test_the_page_names_the_trust_step_the_state_root_and_the_path_rule() -> None:
    """What a reader needs from the page, and nothing the hook does not do."""
    text = HOOK_README.read_text(encoding="utf-8")
    assert "NONI_STATE_ROOT" in text, "the page does not name the state root source"
    assert ".pi/extensions" in text, "the page does not name the install target"
    assert "trusted" in text, "the page does not name the trust step"
    assert "silently" in text, "the page does not say an untrusted project is skipped"
    assert "first on PATH" in text, "the page does not say which `noni` the hook runs"
    assert "session_compact" in text, "the page does not say when the brief is fetched"
    assert "docs/QUICKSTART.md#install-noni" in text, (
        "the page does not link the quickstart's Install section for the PATH step")
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
    The list comes from ``git ls-files``, not a filesystem walk, so an untracked
    scratch file adds no offender and a renamed core page cannot drop out silently.
    """
    tracked = _git(REPO, "ls-files", *CORE_GLOBS).stdout.split()
    assert tracked, "expected to run inside a git checkout"
    found = harness_lines(tracked)
    assert not found, f"the harness is named outside integrations/: {found}"
