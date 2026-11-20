"""Rules the hook must obey that a reader alone cannot falsify.

Two kinds of check sit here. The first proves the readers: a span that began at the
wrong declaration answers a question nobody asked, and the suite once read the
per-turn handler as ``session_compact`` because the shared gate holds two registrations
and the reader counted them. The second is falsifiability: delete one behaviour from the
source text in memory and the check that owns it must go red, while the check beside it
stays green. A suite that stays green whatever the hook says is measuring its own
fixtures.

The mutations are the four rules no reader can speak for: the epoch guard, the await of
the in-flight fetch, the reminder push, and the terminal-only gate. Each is deleted from
the source text and the real check function runs over the result, so what is tested is
the check the suite runs, not a paraphrase of it. Split out of ``test_pi_extension.py``.
"""

from __future__ import annotations

import pytest
from pi_extension_source import (
    EVENTS,
    FUNCTIONS,
    function_body,
    handler_body,
    registration_head,
    source,
    start_gate,
)

# The four rules no reader can falsify on its own. Each row is the source text of one
# behaviour, the name of the check that owns it, and the name of the check beside it.
# The buddy must stay green while the owner goes red: a red buddy means the mutation
# broke the file rather than the rule, and the test would be proving nothing.
MUTATIONS = (
    ("the epoch guard", "if (mine === epoch) pendingBrief = text;",
     "the epoch guard", "the fetcher never writes the brief"),
    ("the in-flight await", "await inflight;",
     "the in-flight await", "the brief is returned once"),
    ("the reminder push", "guidelines.push(REMINDER);",
     "the reminder push", "the reminder is deduplicated"),
    ("the terminal gate", 'ctx.mode === "tui"',
     "the terminal gate", "a non-terminal session keeps the reminder"),
    ("the gate's own comment", 'The gate is the run mode',
     "the gate names the flag it rejects", "the terminal gate"),
)


def _holds(rule: str, text: str) -> bool:
    """Whether the named rule still holds over ``text``, read the way its check reads it.

    Each branch is the assertion of the check named for it, over the same reader that
    check uses. The needles are plain TypeScript text, so no escape is spelled here.
    """
    turn = "before_agent_start"
    if rule == "the epoch guard":
        return "if (mine === epoch) pendingBrief = text;" in function_body(text, "startBrief")
    if rule == "the fetcher never writes the brief":
        return "pendingBrief" not in function_body(text, "fetchBrief")
    if rule == "the in-flight await":
        return "await inflight" in handler_body(text, turn)
    if rule == "the brief is returned once":
        return "pendingBrief = undefined" in handler_body(text, turn)
    if rule == "the reminder push":
        return "guidelines.push(REMINDER)" in handler_body(text, turn)
    if rule == "the reminder is deduplicated":
        return "if (!guidelines.includes(REMINDER))" in handler_body(text, turn)
    if rule == "the terminal gate":
        return 'ctx.mode === "tui"' in start_gate(text)
    if rule == "a non-terminal session keeps the reminder":
        return "hasUI" not in start_gate(text)
    if rule == "the gate names the flag it rejects":
        # The line of prose above the shared gate. It is the hook's own account of why
        # the gate reads the run mode, so it names the flag and the mode it fetches in.
        comment = next((line for line in text.split("\n")
                        if "The gate is the run mode" in line), "")
        return "hasUI" in comment and 'only a "tui" run' in comment
    raise AssertionError(f"no such rule: {rule}")


def test_each_reader_returns_the_span_it_names() -> None:
    """Every span the suite reads starts at its own anchor and stops before the next.

    A reader that landed on a neighbour answered a question nobody asked: the per-turn
    slice began at ``session_compact``, because the gate both start events share holds
    two registrations and the reader counted ``pi.on(`` matches, and three of five
    function slices ran past their own closing brace. The event name and the declaration
    are what anchor a span, so each slice must name its own and hold no other.
    """
    text = source()
    for event in EVENTS:
        body = handler_body(text, event)
        assert body.startswith("pi.on(" + chr(34) + event + chr(34)), (
            f"{event}: the slice is {body[:40]!r}")
        for other in EVENTS:
            if other != event:
                assert "pi.on(" + chr(34) + other + chr(34) not in body, f"{event} holds {other}"
    assert registration_head(text, EVENTS[2]) > registration_head(text, EVENTS[1]), (
        "the per-turn handler is registered before a start event")
    for name in FUNCTIONS:
        body = function_body(text, name)
        stripped = body.lstrip()
        # The span carries the whitespace ahead of the keyword, which is the source's own
        # indentation and no neighbour's text, so the anchor is read off the stripped
        # span: the declaration's own keyword, then its name and its parameter list.
        assert stripped.startswith("async function ") or stripped.startswith("function "), (
            f"{name}: the slice is {body[:40]!r}")
        assert "function " + name + "(" in body, f"{name}: the slice is no declaration"
        for other in FUNCTIONS:
            if other != name and other not in ("fetchBrief", "startBrief"):
                assert "function " + other + "(" not in body, f"{name} holds {other}"
    gate = start_gate(text)
    assert gate.startswith("const start = ("), f"the gate slice is {gate[:40]!r}"
    # The gate slice is the shared gate and the two start registrations, cut at the
    # per-turn registration: it must carry both starts and keep the per-turn handler out,
    # or a check over the gate would be a check over the whole hook.
    assert gate.count("inflight = startBrief(") == 1, "the starts share no one gate"
    for event in EVENTS[:2]:
        assert "pi.on(" + chr(34) + event + chr(34) in gate, f"the gate lacks {event}"
    assert "pi.on(" + chr(34) + EVENTS[2] + chr(34) not in gate, (
        "the gate slice holds the per-turn handler")


@pytest.mark.parametrize("label,victim,owner,buddy", MUTATIONS,
                         ids=[row[0] for row in MUTATIONS])
def test_removing_a_rule_fails_its_check(label: str, victim: str, owner: str,
                                        buddy: str) -> None:
    """Delete the rule from the source text and the check that owns it goes red.

    Each mutation deletes one expression from the source in memory and runs the real
    check over the mutated text. The buddy, the rule beside the mutated one, must stay
    green: a red buddy would mean the mutation broke the file rather than the rule.
    """
    text = source()
    assert victim in text, f"the hook no longer holds {victim!r}"
    assert _holds(owner, text) and _holds(buddy, text), (
        f"{owner} does not hold as written over the real source")
    mutated = text.replace(victim, "", 1)
    assert mutated != text, f"{victim!r} was not there to delete"
    assert not _holds(owner, mutated), f"deleting {label} passed its own check"
    assert _holds(buddy, mutated), f"deleting {label} broke the rule beside it"
