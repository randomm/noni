"""The one line the hook prints when ``noni brief`` cannot be read, checked as text.

``failureReason`` chooses the reason and ``failureLine`` wraps, scrubs and caps it. The
cap is the load-bearing half: ``brief.py`` prints ``--repo <path> is not a directory`` on
stderr, so that line can carry the state root's absolute path, and the bound is what
keeps a long stderr head off the model. A check over the template alone passed with a
cap of 100 000 and with the ellipsis dropped, because the template is 46 characters
whatever the cap declares. These checks rebuild the line from the hook's own parts, in
``pi_extension_failure_line.py``.

Split out of ``test_pi_extension.py``, which carries the rest of the hook's shape.
"""

from __future__ import annotations

import re

import pytest
from pi_extension_failure_line import FAILURE_ARMS, rebuild
from pi_extension_source import (
    ELLIPSIS,
    LINE_LIMIT,
    function_body,
    source,
    template_parts,
)


def test_the_failure_line_is_capped_and_leaks_no_path() -> None:
    """One short failure line, with every path token replaced by "state root".

    Both halves are load-bearing: the cap, and the ``.replace`` output rather than raw
    stderr. The line is rebuilt from the source rather than measured off the template,
    so a cap of 100 000, a dropped marker, a shortening expression that is not the bound
    minus one, and a marker that is any other character all fail here where the template
    check passed. The payload is spaces and apostrophes after the path, because the
    hook's own pattern stops a path token at a space or a quote: the length that reaches
    the cap is then the reason's own, not what the scrubber left behind.
    """
    text = source()
    assert "first.replace(PATH_TOKEN, " + chr(34) + "state root" + chr(34) + ")" in text, (
        "the reason reaches the failure line unredacted")
    reason = "/home/runner/state/noni/decisions/" + " 'x" * 400
    # The path first, then a payload of spaces and apostrophes: the hook's own
    # pattern stops a path token at a space or a quote, so nothing past the path is
    # scrubbed and the length that reaches the cap is the reason's own.
    head, tail = template_parts(text)
    line = rebuild(text, reason)
    assert len(line) <= LINE_LIMIT, f"the line is {len(line)} characters"
    assert line.endswith(ELLIPSIS), "a long reason is not clipped"
    assert line.startswith(head), f"the clipped line lost the template: {line[:40]!r}"
    assert "/home/runner" not in line and "state root" in line, (
        "the state root's path reached the failure line")
    short = rebuild(text, "y" * 150)
    assert ELLIPSIS not in short, "a short reason was clipped"
    assert len(short) == 150 + len(head) + len(tail), f"the short line is {len(short)}"


@pytest.mark.parametrize("arm,reason", FAILURE_ARMS,
                         ids=["killed", "exit-zero", "plain-exit"])
def test_every_failure_arm_prints_one_capped_line(arm: str, reason: str) -> None:
    """Each arm's reason through the cap: a kill says "timed out", an exit 0 with no
    stdout says "printed nothing", a plain exit says what stderr said. An exit 0 with no
    output still has to say something, or the model gets an empty message and no idea the
    census run failed.

    The arm is read from the source before its line is rebuilt, and the length asserted
    is the reason plus the template's own head and close, so no length is claimed that
    the hook did not write.
    """
    text = source()
    assert arm in function_body(text, "failureReason"), f"the hook has no arm: {arm}"
    head, tail = template_parts(text)
    line = rebuild(text, reason)
    assert line == head + reason + tail, f"the arm prints {line!r}"
    assert len(line) == len(head) + len(reason) + len(tail), (
        f"the line is {len(line)} characters for a {len(reason)}-character reason")
    assert ELLIPSIS not in line, f"a short line was clipped: {line!r}"


def test_the_reason_arms_are_the_whole_function() -> None:
    """``failureReason`` holds the three arms and nothing else, so the arm a run reaches
    is one of the three rebuilt above: an arm added outside the table would print a line
    no check has read.
    """
    text = source()
    body = function_body(text, "failureReason")
    returns = re.findall(r"return .*?;", body)
    assert len(returns) == len(FAILURE_ARMS), f"{len(returns)} arms, not {len(FAILURE_ARMS)}"
    for arm, reason in FAILURE_ARMS:
        needle = arm if "$" not in reason else "exit code"
        assert needle in body, f"the arms never say {reason!r}"
