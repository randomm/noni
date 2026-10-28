"""The message scrub's path rule, tested on the strings that decide it.

``census_text._stripped`` has one rule and two ways to break it: scrub too
little and a host path reaches a report that promises never to print one;
scrub too greedily and the errno words the fault row exists to carry are
replaced along with it. Both halves pull against each other, which is why the
rule is pinned here on the tokens themselves rather than only through a census
row -- through a row a passing assertion can be satisfied by whichever half
happened to hold.

The kept tokens are the relative paths a census row derives itself
(``noni/decisions``, ``input/output``, ``a/b``). The scrubbed tokens are the
absolute and home paths a foreign message can carry: from the root, one
component deep, with a leading ``~``, with a username, quoted (the shape
``PermissionError`` builds when it appends the file it failed on, whose only
separator sits behind a quote), and preceded by ``=`` or ``:``.

A literal home path would itself trip the census's hygiene class if it were
written into a tracked file, so the host paths are built from the harness
fixture rather than spelled out here.
"""

from __future__ import annotations

import pytest
from _harness import _home_path_violation

census_text = pytest.importorskip("noni.census_text")

_HOME = _home_path_violation()
# A quoted absolute path with a space in a component: the shape the OSError
# family appends to its text, and the one a two-run floor misses on its own.
_QUOTED_SPACED = "'/home/me/my dir/decisions'"
_QUOTED_SPACED_SCRUBBED = "'<path>'"


def _stripped(message: str) -> str:
    return census_text._stripped(message)


def test_the_scrub_collapses_whitespace_runs():
    """The rule is a scrub, not only a path rule: the row's text stays one line."""
    assert _stripped("the  listing\tfailed\non   readdir") == "the listing failed on readdir"


@pytest.mark.parametrize("kept", [
    "noni/decisions",
    "input/output error",
    "a/b",
    "the ledger at noni/decisions holds no record",
    "an input/output error while reading a/b",
])
def test_a_relative_token_survives_the_scrub(kept: str):
    """What the census named itself is the finding, and must reach the operator.

    A scrub anchored on nothing ate the middle of every ``/`` it saw, so a
    scrubbed ``noni/decisions`` came out as ``noni<path>``: neither the path nor
    a usable stand-in, and the row that names the ledger became the row that
    cannot say which ledger.
    """
    assert _stripped(kept) == " ".join(kept.split())


@pytest.mark.parametrize("message", [
    _HOME,
    "/home/dev/x",
    "/home",
    "/srv",
    "~/x",
    "~user/x",
    "'~/x'",
    "=~/x",
    f": '{_HOME}'",
    "'/abs/with space/d'",
    "[Errno 13] Permission denied: '/home/dev/x'",
    "[Errno 13] Permission denied: '/a/b'",
    f"readdir denied for {_HOME}",
])
def test_a_machine_local_path_is_scrubbed(message: str):
    """Every host path in a foreign message becomes ``<path>``, with nothing of it
    left as a path.

    Each case is a way the previous rule missed one: a single component below
    the root (``/home``, ``/srv``) is shorter than any two-run floor; a quoted
    path opens its first separator behind a quote, so only a delimiter test that
    counts the quote reaches it; ``=`` and ``:`` are the other two characters an
    errno message puts in front of a path. The tail check is what stops a rule
    that replaced the first component and left the rest standing.
    """
    scrubbed = _stripped(message)
    assert "<path>" in scrubbed, scrubbed
    assert "/" not in scrubbed, f"a separator of the scrubbed path remains: {scrubbed!r}"


def test_a_quoted_path_loses_its_path_and_keeps_only_its_quotes():
    """``'/home/me/my dir'`` becomes ``'<path>'``, and no more.

    The parameterised cases above pin which path-shaped texts are scrubbed; the
    quote rule needs the exact output, because both directions of the mistake
    are silent here: a scrub that ate the quotes would destroy the sentence this
    run wrote around the fault, and a scrub that stopped at the first space
    would leave the tail of the host's directory in a report that promises not
    to print it. ``'/home/me/my dir/decisions'`` is the shape
    ``PermissionError`` appends for a file whose name holds a space.
    """
    assert _stripped("'/home/me/my dir'") == "'<path>'"
    assert _stripped(_QUOTED_SPACED) == _QUOTED_SPACED_SCRUBBED
    assert _stripped(f"Permission denied: {_QUOTED_SPACED}") == (
        f"Permission denied: {_QUOTED_SPACED_SCRUBBED}"
    )


def test_the_errno_words_and_the_path_are_separated_in_one_text():
    """One fault, both halves of the rule at once.

    ``str(PermissionError)`` is the errno words and the path it failed on, and
    the row that carries it must keep the first and drop the second. Tested on
    the composed text rather than either half alone because that is the text the
    row renders: the words are only worth keeping if the scrub does not take
    them with the path beside them.
    """
    message = f"[Errno 13] Permission denied - input/output error: '{_HOME}'"
    scrubbed = _stripped(message)
    assert "Permission denied" in scrubbed, scrubbed
    assert "input/output error" in scrubbed, scrubbed
    assert "Errno 13" in scrubbed, scrubbed
    assert _HOME not in scrubbed, scrubbed
    assert "<path>" in scrubbed, scrubbed
