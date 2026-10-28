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
component deep, with a leading ``~``, with a username (the bare ``~user`` form
included, which is what the tilde arm used to miss), quoted (the shape
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
    "~deploy",
    "~deploy/",
    "~deploy/x",
    "/home/someone/x",
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


# --- the producer: a fault's row text, built without its filename -----------


def _home_like_fault() -> OSError:
    """The fault ``PermissionError`` raises on a directory the host cannot name.

    Built rather than spelled out where a literal would trip the census's own
    hygiene class: the filename holds a home path, a non-ASCII component, a
    space and a trailing separator -- the shapes that have each beaten the
    scrubber in review, and the reason the row is built without the filename
    instead of scrubbed after it.
    """
    return OSError(13, "Permission denied", "/home/someone/\u00fcn\u00ef c\u00f6de/my dir/")


def test_the_net_has_a_boundary_and_the_boundary_is_on_the_record():
    """``_stripped`` guesses at what a path looks like, and the guesses end somewhere.

    A component written outside the ASCII alphabet is a host path the absolute
    arm cannot read past, because the alphabet that tells a path from a sentence
    stops at the first character it does not recognise. That is why a census row
    never relies on the net for a filesystem fault: ``fault_text`` builds the
    row's fault wording so the path is never in it. This pins the boundary so
    nobody mistakes the net for a guarantee.
    """
    assert "\u00fcn\u00ef" in _stripped("/home/someone/\u00fcn\u00ef c\u00f6de/my dir/")


def test_fault_text_never_carries_the_filename():
    """The row text of a fault is its class and its errno words, and no path.

    The shapes the scrub cases above cannot all catch -- a home path, a non-ASCII
    component, a space and a trailing separator -- are caught here instead,
    because the filename never enters the text at all: ``fault_text`` reads
    ``e.strerror`` and never ``e.filename``. The words are the finding the row
    exists to print (``str(e)`` of this shape buries them under the path), and
    every row that quotes a fault already names the artifact by the census's own
    identifier, so the filename would add a host location and no information.
    """
    e = _home_like_fault()
    text = census_text.fault_text(e)
    assert text == "PermissionError: Permission denied", text
    for part in ("someone", "\u00fcn\u00ef", "c\u00f6de", "my dir", "decisions"):
        assert part not in text, text
    assert "/" not in text, text


def test_fault_text_drops_both_filenames_and_keeps_the_words():
    """A fault carrying filenames keeps its errno words and loses both paths.

    ``OSError`` carries a secondary filename (``rename`` keeps the source there)
    and ``str()`` renders both, so a rule that only avoided ``filename`` would
    still print one host path out of the two -- and a rule that threw the text
    away with the paths would leave the operator with a bare class name and no
    idea which fault the tree answered with.
    """
    e = OSError(13, "Permission denied", "/home/someone/a", "/home/someone/b")
    text = census_text.fault_text(e)
    assert text == "PermissionError: Permission denied", text
    assert "someone" not in text, text


def test_fault_text_keeps_the_text_of_a_plain_message_fault():
    """A fault raised from a message alone has no filename, so its text is kept.

    ``OSError("input/output error")`` -- the shape a test plants and a
    hand-written raise produces -- fills neither ``strerror`` nor ``filename``,
    and the message is the whole finding. Dropping it would leave a row that
    says ``OSError`` and nothing about what failed.
    """
    assert census_text.fault_text(OSError("input/output error")) == "OSError: input/output error"
    assert census_text.fault_text(PermissionError("readdir denied")) == (
        "PermissionError: readdir denied"
    )


def test_fault_text_names_a_fault_with_no_words_of_its_own_by_its_class():
    """A bare errno pair fills neither field worth keeping, so the class is left.

    ``OSError(errno, None)`` has no strerror, and with a filename it has no words
    at all that are safe to print: ``str(e)`` would be ``[Errno 13] None:
    '/...'``, path included. The class name is the most either fault can honestly
    say -- and ``errno`` is what tells that fault apart from a plain-message one,
    whose text the helper keeps because there is no filename in it to drop.
    """
    named = OSError(13, None, "/home/someone/x")
    assert census_text.fault_text(named) == "PermissionError"
    assert "someone" not in census_text.fault_text(named)
    assert census_text.fault_text(OSError(13, None)) == "PermissionError"
