"""How the hook builds the one line it prints when ``noni brief`` cannot be read.

The cap is the load-bearing half of that line: ``brief.py`` writes ``--repo <path> is
not a directory`` to stderr, so the line can carry the state root's absolute path, and
the bound is what keeps a 1000-character stderr head off the model. Neither half can be
read off the template, which is 46 characters whatever the cap declares, so the line is
rebuilt here the way the hook builds it, from the hook's own text: the template literal,
the cap's name, the value it declares, the expression it shortens by, the marker it
appends. No literal the hook already owns is copied here as a second truth.

The scrub takes its pattern from its caller. That is deliberate: a check that asked this
module for the pattern and then asserted the path had gone would be measuring the hook's
own regex against itself, and three broken patterns (slashes only, a literal word,
nothing at all) pass such a suite. The caller hands over the pattern text it means to
test, which is what lets a check run the same assertions over a weakened copy of the hook.

A helper module: never named ``test_*``. The checks that use it are in
``test_pi_extension_failure_line.py``.
"""

from __future__ import annotations

import re

from pi_extension_source import (
    CLIP,
    ELLIPSIS,
    LINE_LIMIT,
    function_body,
    path_token,
    template_parts,
)

# How the hook spells the character that marks a clipped line: its own name and its own
# escape, so a cap that appends any other text or none fails the read rather than the
# comparison. Built from pieces so this file carries no backslash to misread.
ELLIPSIS_SOURCE = chr(34) + chr(92) + "u2026" + chr(34)

# The three arms of the reason, in the order a run reaches them: a kill, an exit 0 that
# printed nothing, then a plain exit. Each entry is the arm's own text and the reason it
# hands on. An arm that changed its wording fails the read rather than being tested as a
# sentence the hook no longer prints.
FAILURE_ARMS = (
    ('if (r.killed) return "timed out";', "timed out"),
    ('if (r.code === 0) return "printed nothing";', "printed nothing"),
    ('return r.stderr.trim() || `exit code ${r.code}`;', "usage: noni brief"),
)

# The hole the reason drops into, as the hook writes it.
HOLE = chr(36) + "{scrubbed}"


def scrub(reason: str, pattern: str) -> str:
    """The reason as the hook hands it to the template: head line, trimmed, paths gone.

    ``pattern`` is the pattern text, applied the way the hook applies it. The caller reads
    it out of the hook with ``path_token`` when it wants the shipped behaviour, and hands
    over something else when it wants to know what a weaker pattern would have leaked.
    """
    return re.sub(pattern, "state root", reason.split("\n")[0].strip())


def clip_parts(text: str) -> tuple[str, str, str]:
    """The cap's name, its shortening expression and its marker, from the clip itself.

    The expression is read rather than its effect searched for: ``.slice(0, LINE_LIMIT``
    appeared in the file whether or not the bound was applied to the returned line, and
    it said nothing about what the bound was.
    """
    clip = CLIP.search(function_body(text, "failureLine"))
    assert clip, "the failure line has no cap expression"
    cap, compared, shortened, by, marker = clip.groups()
    assert compared == shortened == "line", "the cap does not compare the line it returns"
    assert by == f"{cap} - 1", f"the cap shortens by {by!r}, not {cap} minus one"
    assert marker == ELLIPSIS_SOURCE, f"the cap appends {marker!r}"
    return cap, by, marker


def bound(text: str) -> int:
    """The number the cap's own constant declares, pinned to the suite's expectation.

    Read from the declaration, so raising the bound in the hook fails the checks rather
    than being measured against a bound copied into the test.
    """
    cap, _by, _marker = clip_parts(text)
    declared = re.search(r"const " + re.escape(cap) + r" = (\d+);", text)
    assert declared, f"the cap names no constant: {cap}"
    limit = int(declared.group(1))
    assert limit == LINE_LIMIT, f"{cap} is {limit}, not {LINE_LIMIT}"
    return limit


def rebuild(text: str, reason: str, pattern: str | None = None) -> str:
    """The failure line the hook would build for ``reason``, read from the hook.

    Raising the bound, dropping the marker, or appending anything else fails here,
    because the returned line is assembled from the parts the source declares. The
    pattern is read out of ``text`` when the caller names none, so a check over the
    shipped hook needs no third argument and a check over a mutated copy supplies the
    pattern it believes that copy declares.
    """
    head, tail = template_parts(text)
    line = head + scrub(reason, path_token(text) if pattern is None else pattern) + tail
    limit = bound(text)
    return line if len(line) <= limit else line[: limit - 1] + ELLIPSIS
