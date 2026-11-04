"""What a session-path refusal prints when the path itself is the attack surface.

The wording of the refusal -- that it names the kind the ``lstat`` found, and that the
same sentence appears on all five pages that owe it -- is the subject of
``test_session_symlink_docs.py``. What the refusal does with the bytes the path is
made of is this file, because the two fail in different ways: a wording change makes a
refusal say the wrong thing, and a rendering change makes it say a name that is not
the name it inspected.

Both tests plant a symlink rather than an absent file. ``lstat`` on a name no writer
can reach answers ``ENOENT``, which the guard reads as "nothing there" and returns
``None`` for -- so an absent file produces no refusal to inspect at all, and a test
that asserted on it would pass by asserting nothing. A symlink is refused whatever its
name carries, which is what makes the name the thing under test.

The expectations are built from :func:`chr`, never quoted literals, and the one
property that cannot be borrowed from the renderer is stated as codes. A test about
escaping whose expected string is a quoted literal is a test whose expected string an
edit can rewrite without anyone counting the backslashes; and an expectation produced
by calling the renderer under test agrees with a mutated renderer, which is how the
first draft of the escape test passed a guard that escaped every path twice.
"""

from __future__ import annotations

from pathlib import Path


def test_a_refused_path_cannot_add_lines_to_the_refusal(tmp_path):
    """A path is operator-supplied text printed to a two-line refusal, so the two
    lines are all the reader gets: newline and carriage return are escaped rather
    than emitted, and no crafted name injects a third line.
    """
    from noni import _session_paths

    crafted = tmp_path / "evil\nrelease.py: fix: all good"
    crafted.symlink_to("nowhere")
    headline, hint = _session_paths.file_refusal(crafted)
    assert headline and hint, "a symlink is refused whatever its name carries"
    assert "\n" not in headline and "\n" not in hint, (
        f"a path injected a line: {headline!r} / {hint!r}")
    assert "\\n" in headline, f"the newline must be shown as an escape: {headline!r}"
    refused = _session_paths.write_refusal(Path("/tmp/root"), "../outside.md")
    assert refused is not None and "\n" not in refused[0], refused


def test_a_refusal_escapes_the_path_once(tmp_path):
    """The other half of rendering a caller's path: it is escaped ONCE, and the
    sentence around it is composed rather than re-rendered.

    Two orders are available wherever a refusal interpolates caller-supplied bytes:
    render the value and interpolate that, or interpolate the raw bytes and render the
    finished sentence. The second escapes the backslash of every escape the first pass
    wrote, so the name in the refusal is no longer the name the guard inspected -- and
    a path an operator copies out of a refusal is then a path nobody created.

    The rendering must also be one-to-one, which is the same property seen from the
    other side. A printed name is a name somebody types back, and two names that print
    the same are two files one refusal speaks for. The pair that makes this worth
    asserting is the one the unescaped form cannot distinguish: a name whose bytes are
    a backslash and an ``n``, and a name whose bytes are a newline. Both are legal
    POSIX filenames.

    Every expectation below is a sequence of :func:`chr` calls, and every planted name
    is spelled the same way, so no backslash here survives an edit uncounted.
    """
    from noni import _safe_text, _session_git, _session_paths

    bs = chr(92)
    nl = chr(10)
    cr = chr(13)
    lower_n = chr(110)
    lower_r = chr(114)

    # The renderer itself, one-to-one where the raw bytes are not: a newline prints as
    # a backslash and an 'n' (two codes), a name whose bytes ARE a backslash and an
    # 'n' prints as two backslashes and an 'n' (three). Without the backslash pass --
    # or with it applied after the quoting instead of before -- both names collapse
    # onto one rendering, and the guard cannot tell an operator which file it refused.
    assert _safe_text.safe_path(nl) == bs + lower_n
    assert _safe_text.safe_path(bs + lower_n) == bs + bs + lower_n
    assert _safe_text.safe_path(cr) == bs + lower_r
    assert _safe_text.safe_path(bs + lower_r) == bs + bs + lower_r
    assert _safe_text.safe_path(bs + lower_n) != _safe_text.safe_path(nl), (
        "a backslash-plus-n and a newline printed the same path")
    assert _safe_text.safe_path(bs + lower_r) != _safe_text.safe_path(cr), (
        "a backslash-plus-r and a carriage return printed the same path")
    # One pass, so the escape it writes is not itself escaped again.
    assert _safe_text.safe_path(_safe_text.safe_path(bs + lower_n)) != (
        _safe_text.safe_path(bs + lower_n)), (
        "the renderer is not idempotent, so a second pass would be visible")

    # The name refusal, which is the half that interpolates caller bytes into a
    # template. Its callers hand it a value they have already quoted --
    # ``f"--session-id {args.session_id!r}"`` -- so the ONE render of these bytes is
    # ``safe_text`` over the value, and the sentence is composed around it. Re-rendering
    # the finished sentence would escape the backslash of the repr's own escapes: the
    # ``\t`` an operator typed would come back at them as four characters, and a name
    # whose bytes are a backslash and an 'n' as four, which is no longer the name that
    # was refused.
    quoted_value = repr("x" + bs + lower_n + "y")
    headline, hint = _session_git.name_refusal("--session-id " + quoted_value)
    assert _safe_text.safe_text("--session-id " + quoted_value) in headline, (
        f"the value must appear rendered once: {headline!r}")
    assert bs * 4 + lower_n not in headline, (
        f"the escape was escaped: {headline!r}")
    _none, arg_hint = _session_git.name_refusal("x", arg="--session" + bs + "id")
    assert _safe_text.safe_text("--session" + bs + "id") in arg_hint, (
        f"the argument name, rendered once: {arg_hint!r}")

    # The guard's two sentences each hold the path rendered once, and the pair is what
    # the module's own templates say it must be: composed, never re-rendered.
    planted = tmp_path / "noni" / "sessions"
    planted.mkdir(parents=True)
    crafted = planted / ("a" + bs + lower_n + "b.md")
    crafted.symlink_to("nowhere")
    rendered = _safe_text.safe_path(str(crafted))
    assert _session_paths.file_refusal(crafted) == (
        _session_paths.FILE_REFUSAL.format(path=rendered, kind="is a symlink"),
        _session_paths.FILE_REFUSAL_HINT.format(
            path=rendered, directory=_session_paths._sessions_rel()))

    directory = planted / ("d" + nl + "ir")
    directory.symlink_to("nowhere")
    rendered_dir = _safe_text.safe_path(str(directory))
    assert _session_paths.directory_refusal(directory) == (
        _session_paths.DIR_REFUSAL.format(path=rendered_dir, kind="is a symlink"),
        _session_paths.DIR_REFUSAL_HINT_NO_CREATE.format(
            path=rendered_dir, directory=_session_paths._sessions_rel()))

    # A name carrying a line break still yields exactly the two lines a refusal has.
    for text in (_session_paths.file_refusal(crafted)
                 + _session_paths.directory_refusal(directory)):
        assert nl not in text and cr not in text, f"a path broke the line: {text!r}"
    # A name that carries a line break, in the shape its callers use: quoted before
    # it reaches the helper, so the break arrives as two characters and cannot become
    # a third line of stderr however the sentence is composed.
    for text in _session_git.name_refusal("--session-id " + repr("a" + nl + "b")):
        assert nl not in text, f"a name broke the refusal into lines: {text!r}"
