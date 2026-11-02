"""The two name judgements every session writer rests on, read as tables.

``_session_git.writer_name`` and ``_session_git.relative_name`` decide where a
writer's bytes land and which path git is pointed at, so the interesting thing
about them is a shape: is this id a name, is this name inside the root. Neither
question needs git, a repo, or a filesystem, and both are legible as a list of
accepted shapes and a list of refused ones. That is what this file is: the
primitive's own tests (``test_session_git.py``) drive real commits, and a table
of strings does not belong beside them.

Two layers, and the pair is the point. ``writer_name`` validates a *session id*
before a writer has written anything; ``relative_name`` judges a *name* at the
moment git is about to be handed it. A name built any other way -- by hand, or
from a working-copy marker -- meets the second guard, and the refusal tests below
pin the shape both guards agree on.

Two of these tests are load-bearing in a way the others are not, because each is
the only thing standing between a caller and a write outside the state root: the
id that walks out via ``..`` (see the traversal test in
``test_claim_validation_guards.py``) and the name carrying a NUL, which would
otherwise reach ``subprocess`` and raise. Both are marked where they are asserted.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from noni import _session_git

# One id in the shape the allocator produces, so the accepted half of each table
# reads as the ordinary case rather than as a fixture.
GOOD = "2026-10-01-aaaaaa"


# --- writer_name: is this id a session file name? ---------------------------


def test_writer_name_is_the_one_validated_derivation_the_writers_share():
    """One derivation for the four writers, and it is the guard as well.

    The name they write, stage, print and probe is this function's answer and
    nothing else -- and an id that could make that name mean somewhere else
    answers ``""`` instead, so a writer cannot print a name it would not defend.
    The refusals are the shapes that matter: a separator (a path out of the
    directory), whitespace (a broken commit subject and a file name no shell
    quotes back), an empty id, and a leading dot (a hidden file the census's
    ``*.md`` listing would not report).
    """
    name = _session_git.writer_name(GOOD)
    assert name == "noni/sessions/2026-10-01-aaaaaa.md"
    assert name == f"{_session_git.SESSIONS_REL}/{GOOD}{_session_git.SESSION_SUFFIX}"
    assert _session_git.relative_name(name) == name
    for bad in ("", " ", "a b", "sub/../../../victim", "../victim", "a\\b",
                "a\nb", ".hidden", "..", "2026-10-01-aaaaaa ", "\tsecret"):
        assert _session_git.writer_name(bad) == "", repr(bad)


def test_writer_name_refuses_the_id_that_walks_out_of_the_sessions_directory():
    """The traversal half of the guard, said as its own claim.

    ``sub/../../../victim`` is one token of a commit message and carries no
    separator, so a token check alone admits it -- and the name built from it
    normalises to ``victim.md`` at the state root, a committed file the writer
    was never pointed at. The behaviour is pinned end to end in
    ``test_claim_validation_guards``; this pins the judgement that makes it
    impossible, so a guard narrowed to "contains no slash" fails here first.
    """
    for traversal in ("sub/../../../victim", "../victim", "a/../../b",
                      "noni/sessions/../../../victim"):
        assert _session_git.writer_name(traversal) == "", traversal
    # A leading dot is the other shape that leaves the ordinary listing: the
    # census's probe reports ``*.md`` files, so a '.victim' session file is one
    # no census run counts.
    for hidden in (".hidden", ".victim", ".."):
        assert _session_git.writer_name(hidden) == "", hidden


# --- relative_name: is this name one file the primitive may commit? ---------


def test_relative_name_normalises_the_spellings_of_one_file():
    """The accepted shapes: the same file written several ways is one name.

    ``./`` and ``//`` normalise rather than being refused because the caller
    meant the same file, and a normalised name is the one string a writer prints,
    stages and probes. ``..`` that lands back inside the root is just the file it
    names, which is what makes the refusals below a judgement about the root
    rather than about two characters.
    """
    for spelling, expected in (
        ("noni/sessions/x.md", "noni/sessions/x.md"),
        (PurePosixPath("noni/sessions/x.md"), "noni/sessions/x.md"),
        ("./noni/sessions/x.md", "noni/sessions/x.md"),
        ("noni//sessions/x.md", "noni/sessions/x.md"),
        ("noni/sessions/./x.md", "noni/sessions/x.md"),
        # ``..`` that lands back inside the root is just the file it names: the
        # root rule is about where the name ends up, not about the characters.
        ("noni/sessions/x/../other.md", "noni/sessions/other.md"),
        # On POSIX a backslash is a character of a file name, not a separator.
        # A writer's own id can never carry one (valid_token refuses it), and
        # folding it into '/' would let one name quietly become a path into a
        # subdirectory, so it stays the literal file name it is.
        ("noni/sessions/a\\b.md", "noni/sessions/a\\b.md"),
    ):
        assert _session_git.relative_name(spelling) == expected, repr(spelling)


def test_relative_name_refuses_every_shape_that_is_not_a_session_file():
    """The refused shapes, each named for what it would otherwise do.

    Absolute is refused because ``git add`` accepts an absolute pathspec from
    outside the ``-C`` tree, returns 0 and stages nothing -- the silent
    nothing-landed the primitive must not be able to produce. A name that leaves
    the root is git reading another tree. Not being under ``noni/sessions/``, or
    not being a ``.md`` file, is refused because every caller stages one session
    file: the writers all build their name with ``writer_name``, and the one
    caller that takes a name from a command line (``register --file``) matches it
    against one of exactly those two names, so the shape check costs no caller
    anything.
    """
    for bad in ("/tmp/x.md", "/noni/sessions/x.md", "//server/share/x.md",
                "../x.md", "noni/../../x.md", "..", ".", "",
                "noni/other.md", "notes/x.md", "x.md", "README.md",
                "noni/sessions/x", "noni/sessions", "noni/sessions/",
                "noni/sessions/../../victim.md",
                "noni/sessions/../../../victim.md",
                "noni/sessions/./../../victim.md"):
        assert _session_git.relative_name(bad) == "", repr(bad)


def test_relative_name_refuses_a_name_carrying_a_control_character():
    """The never-raises half, stated where the judgement is made.

    An argv element carrying a NUL makes ``subprocess.run`` raise ``ValueError``,
    so a name like this reaching git would end a writer in a traceback over the
    message the operator was meant to read. Refusing it here is what lets
    ``stage_and_commit`` keep returning ``(False, why)``; the behaviour is pinned
    by ``test_session_git.test_stage_and_commit_returns_a_nul_name_instead_of_raising``.
    """
    for bad in ("noni/sessions/a\x00b.md", "noni/sessions/a\x01b.md",
                "noni/sessions/a\x1fb.md", "noni/sessions/a\nb.md",
                "noni/sessions/a\tb.md", "noni/sessions/a\x7fb.md"):
        assert _session_git.relative_name(bad) == "", repr(bad)


def test_the_name_refusal_wording_is_one_pair_the_writers_share():
    """One sentence and one hint, so five callers cannot say five things.

    The primitive's backstop and the four writers all report a refused name, and
    the drift this prevents is wording: a writer that composed its own sentence
    would tell the operator something the primitive does not mean. The pair names
    the state root rule, and the hint names the argument the operator typed, so
    the fix is about the value that was wrong rather than about --repo.
    """
    headline, hint = _session_git.name_refusal("noni/sessions/a\x00b.md")
    assert headline == _session_git.NAME_REFUSAL.format(
        name="noni/sessions/a\x00b.md", directory=_session_git.SESSIONS_REL)
    assert headline.startswith("cannot commit noni/sessions/a\x00b.md:")
    assert "inside the state root" in headline
    assert "control character" in headline
    assert "--session-id" in hint, hint
    assert _session_git.SESSIONS_REL in hint, hint
    # A caller that owns a different argument says so, and the pair follows.
    other_head, other_hint = _session_git.name_refusal("x", arg="--identity")
    assert "--identity" in other_hint and "--session-id" not in other_hint
