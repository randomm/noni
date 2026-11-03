"""The name judgements the four session writers rest on, read as tables.

``_session_git.writer_name`` and ``_session_git.relative_name`` decide where a
writer's bytes land and which path git is pointed at, so the interesting thing
about them is a shape: is this id a name, is this name inside the root. Neither
question needs git, a repo, or a filesystem, and both are legible as a list of
accepted shapes and a list of refused ones. That is what this file is: the
primitive's own tests (``test_session_git.py``) drive real commits, and a table
of strings does not belong beside them.

Three layers, and the pair between them is the point. ``writer_name`` validates
a *session id* before a writer has written anything; ``relative_name`` judges a
*name* at the moment git is about to be handed it; and a name built any other
way -- by hand, or from a working-copy marker -- meets the second guard. The
refusal tests below pin the shape both guards agree on, and the superset test
pins that they cannot disagree: an id whose built name the name guard refuses is
refused at the id step too, where a writer can still report it on its own usage
code instead of faulting at a commit.

Two of these tests are load-bearing in a way the others are not, because each is
the only thing standing between a caller and a write outside the state root: the
id that walks out via ``..`` (see the traversal test in
``test_claim_validation_guards.py``) and the name carrying a NUL, which would
otherwise reach ``subprocess`` and raise. Both are marked where they are asserted.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from noni import _safe_text, _session_git

# One id in the shape the allocator produces, so the accepted half of each table
# reads as the ordinary case rather than as a fixture.
GOOD = "2026-10-01-aaaaaa"

# A name whose bytes no codec can carry. A lone surrogate is neither a control
# character nor an absolute path nor outside the root, so it passes every path
# rule the guard applies, yet it cannot be an argument or a written path.
LONE_SURROGATE = "\ud800"


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
                "a\nb", ".hidden", "..", "2026-10-01-aaaaaa ", "\tsecret",
                # A token is not the whole guard: ``\x01`` is neither whitespace
                # nor a separator, so TOKEN_RE admits it and the name guard run
                # on the built name is what refuses the id.
                "a\x01b", "2026-10-01-\x01aaaaaa", "2026-10-01-aaaa\x7fb"):
        assert _session_git.writer_name(bad) == "", repr(bad)


def test_writer_name_is_a_strict_superset_of_the_name_guard():
    """An id whose built name the name guard refuses answers ``""`` here.

    The two guards judge different objects -- a bare id versus a name -- and the
    token rule is the looser of the two: ``TOKEN_RE`` refuses whitespace and a
    separator, so an id may still carry a control byte or text no codec carries.
    Built into a name and handed to the commit primitive, such an id is a name
    git cannot be given. Running the built name back through ``relative_name``
    is what closes that gap at the step where the writer can still answer on its
    own usage code, and this test pins it structurally rather than by example:
    for every id in the table, the two guards give the same verdict.
    """
    ids = (GOOD, "a\x01b", "a\x00b", "a\tb", "a\nb", LONE_SURROGATE,
           f"2026-10-01-{LONE_SURROGATE}", "plain\u00e9", "2026-10-01-\u00e9")
    for sid in ids:
        built = f"{_session_git.SESSIONS_REL}/{sid}{_session_git.SESSION_SUFFIX}"
        assert _session_git.writer_name(sid) == (_session_git.relative_name(built)
                                                 or ""), repr(sid)
    # The one id the token rule alone would have let through, named explicitly so
    # a future relaxation of TOKEN_RE is caught here and not at a git call.
    assert _session_git.valid_token("a\x01b") is True
    assert _session_git.writer_name("a\x01b") == ""


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

    The set is every Unicode category-C code point, which is what ``safe_text``
    strips, so a name and a printed line are judged the same way: C0 and DEL, the
    C1 range (``\x85`` NEL), the format characters (``\u202e`` RIGHT-TO-LEFT
    OVERRIDE, zero-width joiners) and the surrogates. A C1 or format character is
    the interesting case -- it is not an ASCII control byte, it survives
    ``str.strip()``, and a bidi override is exactly what makes a printed path read
    as something other than what it is.
    """
    for bad in ("noni/sessions/a\x00b.md", "noni/sessions/a\x01b.md",
                "noni/sessions/a\x1fb.md", "noni/sessions/a\nb.md",
                "noni/sessions/a\tb.md", "noni/sessions/a\x7fb.md",
                "noni/sessions/a\x85b.md", "noni/sessions/a\u0085b.md",
                "noni/sessions/a\u202eb.md", "noni/sessions/a\u200bb.md",
                "noni/sessions/a\ufeffb.md", "noni/sessions/a\U000e0001b.md"):
        assert _session_git.relative_name(bad) == "", repr(bad)
        assert _session_git.writer_name(bad.split("/")[2][:-3]) == "", repr(bad)
    # A printable non-ASCII name is still admitted, so the refusals above are
    # category C and not merely "not ASCII".
    assert _session_git.relative_name("noni/sessions/a\u00e9b.md") == \
        "noni/sessions/a\u00e9b.md"


def test_relative_name_refuses_a_name_that_cannot_be_encoded_as_utf8():
    """The other half of never-raises: text no codec can carry.

    A lone surrogate passes every path rule -- it is not a control character, not
    absolute, and sits under the root with the right suffix -- yet it cannot be
    encoded as UTF-8, so it is no argv element and no path to write. The name
    guard answers ``""`` for it, which is what keeps ``stage_and_commit``'s
    promise of ``(False, why)`` where a bare ``text.encode()`` would have raised.
    """
    # Lone surrogates, high and low: the shape a mangled argv element or marker
    # byte actually produces, and the one UTF-8 refuses.
    for bad in (f"noni/sessions/{LONE_SURROGATE}.md",
                "noni/sessions/a\udc00b.md",
                "noni/sessions/2026-10-01-\ud83d.md"):
        assert _session_git.relative_name(bad) == "", repr(bad)
    # A non-ASCII name that does encode is accepted, so the refusals above are
    # about encodability and not about the characters being unusual.
    assert _session_git.relative_name("noni/sessions/\u00e9.md") == "noni/sessions/\u00e9.md"
    # An id the allocator could not produce is refused at the id step too.
    assert _session_git.writer_name(LONE_SURROGATE) == ""


def test_the_name_refusal_wording_is_one_pair_the_writers_share():
    """One sentence and one hint, so five callers cannot say five things.

    The primitive's backstop and the four writers all report a refused name, and
    the drift this prevents is wording: a writer that composed its own sentence
    would tell the operator something the primitive does not mean. The pair names
    the state root rule, and the hint names the argument the operator typed, so
    the fix is about the value that was wrong rather than about --repo.

    The offender is interpolated before the render, so the one assertion that
    pins sanitisation is not this one: see
    :func:`test_the_name_refusal_never_prints_caller_control_bytes`.
    """
    headline, hint = _session_git.name_refusal("noni/sessions/a-unsafe-b.md")
    assert headline == _session_git.NAME_REFUSAL.format(
        name="noni/sessions/a-unsafe-b.md", directory=_session_git.SESSIONS_REL)
    assert headline.startswith("cannot commit noni/sessions/a-unsafe-b.md:")
    assert "inside the state root" in headline
    assert "control character" in headline
    assert "--session-id" in hint, hint
    assert _session_git.SESSIONS_REL in hint, hint
    # A caller that owns a different argument says so, and the pair follows.
    other_head, other_hint = _session_git.name_refusal("x", arg="--identity")
    assert "--identity" in other_hint and "--session-id" not in other_hint


def test_the_name_refusal_never_prints_caller_control_bytes():
    """The refusal's own safety: caller-supplied text cannot put an escape on stderr.

    A refused name is refused because its bytes are not fit for a terminal or an
    argv element, and the sentence about it is printed to stderr with the name
    interpolated into it. Rendered raw, an escape sequence in the name would be
    acted on by the terminal reading the refusal -- so the whole line, after the
    interpolation, goes through ``safe_text``. A name carrying ``\x1b`` and an
    argument name carrying one are the two caller-supplied fields of the pair.
    """
    for offender in ("noni/sessions/a\x1b[31mred.md",
                     "noni/sessions/a\x07b.md",
                     "noni/sessions/a\x00b.md",
                     "noni/sessions/a\x01b.md",
                     "--session-id a\x1b[0mq"):
        for headline, hint in (_session_git.name_refusal(offender),
                               _session_git.name_refusal("x", arg=offender)):
            for text in (headline, hint):
                for ch in _safe_text.CONTROL_CHARS:
                    assert ch not in text, repr((offender, text))
    # The wording still names the offender, minus its control bytes.
    headline, _ = _session_git.name_refusal("noni/sessions/a\x1b[31mred.md")
    assert headline.startswith("cannot commit noni/sessions/a[31mred.md:"), headline
