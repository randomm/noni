"""The one line the hook prints when ``noni brief`` cannot be read, checked as text.

``failureReason`` chooses the reason and ``failureLine`` wraps, scrubs and caps it. The
cap is the load-bearing half: ``brief.py`` prints ``--repo <path> is not a directory`` on
stderr, so that line can carry the state root's absolute path, and the bound is what
keeps a long stderr head off the model. A check over the template alone passed with a
cap of 100 000 and with the ellipsis dropped, because the template is 46 characters
whatever the cap declares. These checks rebuild the line from the hook's own parts, in
``pi_extension_failure_line.py``.

The scrub is the other half, and it is checked against the hook rather than with the
hook's help. The payloads below are the suite's own literals and the pattern each cell
tests is named by the row it sits in, so a pattern that redacts nothing can pass only by
being handed to itself. The broken patterns are applied by rewriting the hook's declaration
in an in-memory copy, which is what makes a weakened scrub a red check rather than a green
one.

Split out of ``test_pi_extension.py``, which carries the rest of the hook's shape.
"""

from __future__ import annotations

import re

import pytest
from pi_extension_failure_line import FAILURE_ARMS, rebuild
from pi_extension_source import (
    ELLIPSIS,
    LINE_LIMIT,
    PATH_TOKEN,
    function_body,
    path_token,
    path_token_flags,
    path_token_is_portable,
    source,
    template_parts,
)

# Characters that are awkward to read in a row of backslashes or to write without ending a
# string, so every path payload and pattern below is assembled from these.
BS = chr(92)
APOS = chr(39)
BACKTICK = chr(96)
DQUOTE = chr(34)
# What a path component is made of: no whitespace and none of the four characters that end
# a token, so the scrub cannot swallow the punctuation that closes a path. Separators are
# excluded here and admitted only between components.
COMPONENT_BODY = chr(94) + BS + "s" + DQUOTE + APOS + BACKTICK
COMPONENT = "[" + COMPONENT_BODY + "]+"
# The separator the shipped pattern must name: one class holding both separator characters,
# so a forward slash and a backslash split a token alike. A class and not an alternation of
# the two, because an alternation is how the backslash case sat untested: the doubled escape
# means one thing to the engine that runs the hook and another to the one that tests it.
SEPARATOR_CLASS = "[" + BS * 2 + "/" + "]"
# The shipped scrub as the suite expects the hook to declare it: one or more components each
# followed by a separator, then the final component. A doubled backslash is two characters
# of the component class, so what ``safe_path`` prints -- every backslash the caller wrote,
# doubled -- is one token here, which is the whole point of the class carrying both.
SHIPPED_PATTERN = "(?:" + COMPONENT + SEPARATOR_CLASS + ")+[" + COMPONENT_BODY + "]+"

# The tail that forces the clip: the two-character sequence of a space and an apostrophe
# then ``x``, repeated. The pattern stops a token at a space or a quote, so nothing past the
# path is scrubbed and the length that reaches the cap is the reason's own.
TAIL = (" " + APOS + "x") * 400
# Each payload is the first stderr line of a refusal that named the path, with the segment
# of it that must not survive. The Windows and UNC forms are the live shapes: ``safe_path``
# doubles every backslash the caller's ``--repo`` carried before the refusal prints it, so a
# doubled backslash is what the scrub actually receives.
POSIX_PATH = "/srv/data/noni/decisions/"
WIN_PATH = "C:" + BS * 4 + "work" + BS * 4 + "noni" + BS * 4 + "state"
UNC_PATH = BS * 8 + "fileserver" + BS * 4 + "share" + BS * 4 + "noni"
LEAK_PAYLOADS = (
    ("posix-path", "--repo " + POSIX_PATH + TAIL, POSIX_PATH),
    ("windows-path", "--repo " + WIN_PATH + " is not a directory" + TAIL, WIN_PATH),
    ("unc-path", "--repo " + UNC_PATH + " is not a directory" + TAIL, UNC_PATH),
)

# The quoted payload stands apart from those three, in the live check alone. Its secret is the
# empty string because absence carries no claim here: the refusal that ``safe_path`` writes
# adds no quotes, so a quoted path never reaches the scrubber from a live run and the only
# thing left for this payload to pin is what the scrub does at a quote, which the exact line
# below settles. It is also why the matrix excludes it: a quoted path is refused the same way
# by slashes-only and by the shipped pattern, so it refutes no mutation row, and the three
# payloads above are the closed set that refutes all four.
QUOTED_PATH = APOS + "/srv data/noni decisions" + APOS
QUOTED_PAYLOAD = ("quoted-path", "--repo " + QUOTED_PATH + " is not a directory", "")

# The quoted payload's whole line, quotes and all: the exact-output half of what that row is
# for. The component class refuses the quote characters, so the scrub takes the path and
# leaves the quotes standing where they were. A scrub that ate them would destroy the sentence
# written around the path, and one that swallowed the text after the closing quote would put
# the tail of a real refusal on the model; neither mistake shows in an absence check.
QUOTED_LINE = "noni: could not read the brief (--repo '/srv state root decisions' is not a directory)"

# The four patterns that break the scrub, each written as the text its mutated declaration
# carries. Every row is refuted by at least one payload above: the POSIX and quoted payloads
# refute backslashes-only, literal-word and never-matching, and the two doubled-backslash
# payloads refute slashes-only, literal-word and never-matching. Backslashes-only is
# output-equivalent to the shipped pattern on the two backslash payloads -- both print
# "state root" -- and differs from it by the forward slash in its separator class, so that
# row rests on the POSIX cell of the matrix and on the quoted payload's exact line in the
# live check. Each row also names the text its mutated declaration must read back as, so a
# mutation that silently failed to apply cannot report the shipped pattern's own success.
BROKEN_PATTERNS = (
    ("slashes-only", "(?:[" + COMPONENT_BODY + "]+\\/)+[" + COMPONENT_BODY + "]+"),
    ("backslashes-only", "(?:[" + COMPONENT_BODY + "]+[" + BS * 2 + "])+["
     + COMPONENT_BODY + "]+"),
    # A token that matches a word instead of a path: it redacts something, so the presence
    # half of a leak check stays green while the path stands. It is not a word any failure arm
    # prints, which is what keeps the arm check beside the matrix a buddy rather than a second
    # casualty of the same mutation.
    ("literal-word", "unredacted"),
    # A pattern that matches nothing yet still reads back whole: an empty declaration is
    # outside the closed list because the reader cannot read it, so the broken copy has to
    # carry a pattern rather than the absence of one.
    ("never-matching", "(?!x)x"),
)

# Two paths in one stderr head, each with a secret of its own: the shape ``noni brief``
# reaches when the refusal names both the directory it was given and the root it resolved.
# The forward-slash path sits at the head so the leading slash can end the first token and
# the run can reach the doubled-backslash path behind it; the same pair the other way round
# is one token from the first character and matches in a single sweep whatever the flags. The
# claim this row carries is the ``g`` on the scrub's declaration: without it the first match
# is replaced and the second path stands, and every single-path payload above stays green.
# It is not added to the closed list: four patterns are refuted by the three single-path
# payloads, and a row that only the shipped pattern passes would dilute that matrix.
TWO_PATHS_POSIX = "/srv/data/noni/decisions/"
TWO_PATHS_WIN = "C:" + BS * 4 + "work" + BS * 4 + "noni" + BS * 4 + "state"
TWO_PATH_PAYLOAD = ("two-paths", "--repo " + TWO_PATHS_POSIX + " under " + TWO_PATHS_WIN,
                    (TWO_PATHS_POSIX, TWO_PATHS_WIN))


def _with_pattern(text: str, pattern: str) -> str:
    """A copy of the hook whose scrub declares ``pattern``, the file otherwise intact.

    The declaration is replaced through the same reader the checks use, so the copy cannot
    end up holding two of them, and the copy is read back to prove it carries the text that
    was asked for. Nothing is written to disk: the shipped hook is never the mutant.
    """
    mutated = re.sub(PATH_TOKEN.pattern,
                     lambda _match: "const PATH_TOKEN = /" + pattern + "/g;",
                     text, count=1)
    assert mutated != text, "the declaration was not there to mutate"
    assert path_token(mutated) == pattern, (
        f"the mutated copy declares {path_token(mutated)!r}, not {pattern!r}")
    return mutated


def test_the_failure_line_is_capped_and_leaks_no_path() -> None:
    """One short failure line, with every path token replaced by "state root".

    Both halves are load-bearing: the cap, and the ``.replace`` output rather than raw
    stderr. The line is rebuilt from the source rather than measured off the template,
    so a cap of 100 000, a dropped marker, a shortening expression that is not the bound
    minus one, and a marker that is any other character all fail here where the template
    check passed. The payload is the existing POSIX payload: a path, then the
    space-and-apostrophe-plus-``x`` repeat that forces the clip.
    """
    text = source()
    assert "first.replace(PATH_TOKEN, " + DQUOTE + "state root" + DQUOTE + ")" in text, (
        "the reason reaches the failure line unredacted")
    reason = LEAK_PAYLOADS[0][1]
    head, tail = template_parts(text)
    line = rebuild(text, reason)
    assert len(line) <= LINE_LIMIT, f"the line is {len(line)} characters"
    assert line.endswith(ELLIPSIS), "a long reason is not clipped"
    assert line.startswith(head), f"the clipped line lost the template: {line[:40]!r}"
    assert "/home/runner" not in line and "state root" in line, (
        "the state root's path reached the failure line")
    short = rebuild(text, "y" * 150)
    assert ELLIPSIS not in short, "a short line was clipped"
    assert len(short) == 150 + len(head) + len(tail), f"the short line is {len(short)}"


def _without_global_flag(text: str) -> str:
    """A copy of the hook whose scrub loses the ``g`` on its declaration, file else intact.

    The declaration is rewritten through the reader's own pattern, so the copy carries one
    literal that differs from the shipped one by the flag alone. Nothing is written to disk:
    the shipped hook is never the mutant.
    """
    mutated = re.sub(PATH_TOKEN.pattern,
                     lambda _match: "const PATH_TOKEN = /" + SHIPPED_PATTERN + "/;",
                     text, count=1)
    assert mutated != text, "the declaration was not there to mutate"
    assert not PATH_TOKEN.search(mutated), "the copy still declares the scrub as global"
    # The body is still the shipped one and still reaches the same replace call, so the only
    # thing this copy differs by is the flag. The declaration reader requires ``/g;``, so it
    # cannot read this copy -- which is the mutation's own red check -- and the line below is
    # the direct read of what the copy declares instead.
    assert "const PATH_TOKEN = /" + SHIPPED_PATTERN + "/;" in mutated, (
        "the copy does not declare the shipped pattern with no flag")
    assert "first.replace(PATH_TOKEN, " + DQUOTE + "state root" + DQUOTE + ")" in mutated, (
        "the copy no longer scrubs through the replace call")
    return mutated


@pytest.mark.parametrize("label,reason,secret", LEAK_PAYLOADS + (QUOTED_PAYLOAD,),
                         ids=[row[0] for row in LEAK_PAYLOADS] + [QUOTED_PAYLOAD[0]])
def test_no_payload_reaches_the_model_when_the_hook_scrubs(label: str, reason: str,
                                                           secret: str) -> None:
    """Each payload through the hook's own pattern: its secret segment gone, ``state root``
    in its place.

    The payload is the suite's literal and the pattern is the one read out of the hook, so
    this is the live behaviour: the line a run whose ``noni brief`` was refused prints. The
    quoted row is held to its whole line instead, because it has no secret to lose -- see its
    own note above -- and the exact line is what tells a scrub that ate the quotes from one
    that took only the path.
    """
    text = source()
    line = rebuild(text, reason)
    if label == "quoted-path":
        # The exact line is this row's whole claim, and absence and presence cannot carry it:
        # a scrub that ate the quotes, and one that swallowed the text after the closing
        # quote, each leave some pair of those two claims true for a payload of their own.
        assert line == QUOTED_LINE, f"the quoted path became {line!r}"
    else:
        assert secret not in line, f"{label}: the secret segment reached the failure line"
        assert "state root" in line, f"{label}: nothing was scrubbed"


def test_a_line_with_two_paths_has_both_scrubbed() -> None:
    """Two paths in one stderr head, each with its own secret: both gone, ``state root`` twice.

    A single-path payload cannot tell a global scrub from one that stops after the first
    match, so this row carries the ``g``. The claim is proven both ways: the shipped hook
    passes, and an in-memory copy of the hook whose declaration lost the flag fails, checked
    through the same rebuild the shipped line is measured with, and the flag is asserted on
    the declaration of both copies. Python replaces every match whatever the flag says, so
    the rebuild cannot see a missing ``g`` and the non-global copy is refuted structurally.
    A scratch run of the shipped pattern under node says what the flag is worth: the line
    with one path standing and one replaced. The mutant is not added to the closed
    four-pattern list -- it is a flag mutation, not a pattern mutation, and the matrix over
    that list is refuted by the single-path payloads alone.
    """
    _label, reason, secrets = TWO_PATH_PAYLOAD
    line = rebuild(source(), reason)
    for secret in secrets:
        assert secret not in line, f"the secret segment reached the failure line: {secret!r}"
    assert line.count("state root") == 2, f"{line.count('state root')} tokens scrubbed: {line!r}"
    # The flag itself, asserted on both copies. Python's ``re.sub`` replaces every match
    # whatever the flag says, so the rebuild above cannot see a missing ``g``: the shipped
    # copy is read as global, and the copy without the flag is the one that fails the read.
    assert path_token_flags(source()) == "g", "the shipped scrub is not global"
    with pytest.raises(AssertionError):
        path_token_flags(_without_global_flag(source()))


@pytest.mark.parametrize("label,reason,secret", LEAK_PAYLOADS,
                         ids=[row[0] for row in LEAK_PAYLOADS])
@pytest.mark.parametrize("broken,broken_pattern", BROKEN_PATTERNS,
                         ids=[row[0] for row in BROKEN_PATTERNS])
def test_a_weakened_scrub_fails_the_leak_check(label: str, reason: str, secret: str,
                                               broken: str,
                                               broken_pattern: str) -> None:
    """Every payload x every broken pattern: the absence check must go red.

    The pattern is read out of a copy of the hook whose declaration was rewritten in
    memory, and the read-back must equal the text this table declares for the row. That
    equality is what stops a mutation that never applied from reporting the shipped
    pattern's own success, which is what keeps the one row the backslash payloads cannot
    refute a row that can still fail.
    """
    text = source()
    mutated = _with_pattern(text, broken_pattern)
    assert path_token(mutated, broken_pattern) == broken_pattern, (
        f"{broken}: the mutated copy declares something else")
    line = rebuild(mutated, reason, broken_pattern)
    assert secret not in line or "state root" not in line, (
        f"{broken} passed the leak check for {label}: {line[:80]!r}")


def test_the_scrub_pattern_is_one_both_engines_read_alike() -> None:
    """The shipped declaration is one literal, and its syntax is the shared subset.

    JavaScript runs the hook's pattern and Python re runs the same text here, so a class or
    an escape that means one thing to each lets the suite stay green while the hook leaks.
    The whitelist names what may appear rather than a few things that may not, so an atomic
    group, a POSIX bracket class or an inline-flag group -- all of which Python compiles and
    JavaScript reads differently or not at all -- are refused here rather than trusted not to
    have been written.
    """
    text = source()
    body = path_token(text, SHIPPED_PATTERN)
    assert text.count("const PATH_TOKEN = ") == 1, "the hook declares the scrub twice"
    assert "(?:" + COMPONENT + SEPARATOR_CLASS + ")+[" + COMPONENT_BODY + "]+" == body, (
        f"the scrub is not components joined by one class over both separators: {body!r}")
    path_token_is_portable(body)


# Shapes the whitelist must refuse, each added by one of the tightenings. Each row breaks
# only its own rule, so a loosening reddens the row that names it rather than a neighbour:
# ``[^a\\u0041]`` compiles and is well formed, so only the escape token can refuse it, and the
# old token accepted any non-alphanumeric; ``a[]b`` compiles and is well formed, so only the
# class token's minimum can refuse it, and the old class token matched an empty body; a
# non-compiling body would die in the compile step for the same reason whatever the whitelist
# said, and that is why neither of those two is written as a bare ``[]`` or ``\u0041``.
# Each row is refused by one tightening and by no earlier step, so a loosening reddens the row
# that names it: ``abc\\d`` carries an escape the old token accepted for any non-alphanumeric,
# and Python reads ``\d`` as a digit class while JavaScript reads it as a literal ``d``, which
# is the divergence the escape whitelist exists to stop; ``[]`` has no member for the class
# token to name (verified: the token walk finds no token for it), where the old class token
# matched an empty body; ``a{2,5}`` is a counted repetition whose braces the old
# plain-character class let through as ordinary text; the unbalanced group is the shape that
# never reaches the token walk at all, and so proves the fourth tightening -- a body Python
# cannot compile is reported as an ``AssertionError`` naming the compile error, not as a bare
# ``re.error``. Two refusals need no row of their own because the engines settle them: ``[]``
# above is rejected by Python's compiler a step before the walk, and ``[^]`` is a class of the
# two literals ``^`` and ``]`` in JavaScript, so refusing it would be wrong in either engine.
REFUSED_PATTERNS = (
    ("non-whitelisted-escape", "abc" + BS + "d", "outside the shared subset"),
    ("empty-class", "[" + "]", "the pattern"),
    ("counted-repetition", "a{2,5}", "outside the shared subset"),
    ("unbalanced-group", "(?:a", "does not compile"),
)


@pytest.mark.parametrize("label,pattern,expected", REFUSED_PATTERNS,
                         ids=[row[0] for row in REFUSED_PATTERNS])
def test_the_whitelist_refuses_syntax_outside_the_subset(label: str, pattern: str,
                                                         expected: str) -> None:
    """Each refused shape stops with an ``AssertionError`` that says which rule it broke.

    The whitelist is the only thing that keeps a pattern Python compiles from meaning
    something else in JavaScript, so a loosening has to fail here rather than quietly widen
    what the portable check accepts. A compile failure is asserted as an ``AssertionError``
    carrying the compiler's own words: a bare ``re.error`` escaping the reader would read as
    a broken suite, not as a hook that may not declare the pattern.
    """
    with pytest.raises(AssertionError) as caught:
        path_token_is_portable(pattern)
    assert expected in str(caught.value), f"{label}: {caught.value}"


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


def test_the_mutated_copy_keeps_the_file_readable() -> None:
    """The buddy to the matrix above, stated for the one thing it can certify.

    All three arms carry no path, so the scrub hands each one back unchanged whatever the
    pattern declares and this check stays green under every mutation. That is its whole
    claim: the mutated file still reads as the hook, with its arms, its cap and its
    template where they were, so a red matrix cell means a rule broke and not the file.
    This is no check on the scrub, and detection of a weakened scrub rests on the
    payload-absence check alone.
    """
    text = source()
    for _broken, broken_pattern in BROKEN_PATTERNS:
        mutated = _with_pattern(text, broken_pattern)
        for arm, reason in FAILURE_ARMS:
            assert arm in function_body(mutated, "failureReason"), f"{arm} lost"
            head, tail = template_parts(mutated)
            line = rebuild(mutated, reason, broken_pattern)
            assert line == head + reason + tail, f"the arm prints {line!r}"
            assert len(line) == len(head) + len(reason) + len(tail)
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
