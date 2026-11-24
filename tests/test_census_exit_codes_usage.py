"""The usage errors of the unified census: the paths that exit 2.

Moved out of ``tests/test_census_exit_codes.py`` so each file stays at or under
the size ratchet; the tests are main's, verbatim. The ``--stale-after`` refusals
joined them: a threshold the run cannot build a timedelta from is bad usage, and
the run owes the caller the tool's own sentence rather than a traceback.
"""

from __future__ import annotations

import census


def test_exit_2_bad_now():
    import io
    from contextlib import redirect_stderr
    err = io.StringIO()
    with redirect_stderr(err):
        rc = census.main(["--now", "invalid"])
    assert rc == 2


def test_exit_2_unknown_check():
    import io
    from contextlib import redirect_stderr
    err = io.StringIO()
    with redirect_stderr(err):
        rc = census.main(["--only", "bogus"])
    assert rc == 2


# Past the largest day count a timedelta can hold (999999999 days) the run must
# refuse; a digit from another script must never reach ``int()`` at all. The first
# two used to die in ``timedelta(days=...)`` with an uncaught OverflowError, the
# two Unicode forms used to pass the shape and convert.
BEYOND_THE_RANGE = ("1000000001", "1" * 22)
# Non-ASCII digit forms: a digit to ``\d``, to ``str.isdigit`` or to neither.
UNICODE_STALE_AFTER = ("\u0661\u0660", "\u00b2")


def test_stale_after_beyond_the_range_exits_two():
    """AC2: a threshold no timedelta can hold is refused, not raised.

    The refusal is the one the shape and the zero already print, on stderr, and it
    is the run's last word: no ``Traceback``, no ``OverflowError`` and no report on
    either stream, because a census that died halfway answers nothing and reads as
    a run that found nothing.
    """
    import io
    from contextlib import redirect_stderr, redirect_stdout
    for value in BEYOND_THE_RANGE + UNICODE_STALE_AFTER:
        err, out = io.StringIO(), io.StringIO()
        with redirect_stderr(err), redirect_stdout(out):
            rc = census.main(["--repo", ".", "--stale-after", value])
        combined = out.getvalue() + err.getvalue()
        assert rc == 2, f"{value!r}: exit {rc}, {combined[:200]}"
        assert err.getvalue().startswith(
            f"error: --stale-after {value!r} must be positive whole days")
        assert combined.count("must be positive whole days") == 1, combined[:400]
        assert "Traceback" not in combined and "OverflowError" not in combined, (
            combined[:400])
        assert out.getvalue() == "", f"{value!r}: a report followed the refusal"


def test_the_stale_after_shape_is_ascii_digits_stated_once():
    """The threshold shape is pinned by its literal text, in the module that owns it.

    A bare ``\\d`` matched a Unicode decimal digit and ``int()`` then converted it, so
    ``--stale-after ١٠`` silently ran the ordering class at ten days. The class is
    asserted on the live constant and on the shipped source, the way the ``--date``
    shape is, so a second copy of the rule cannot start disagreeing with the flag.
    """
    from _harness import REPO

    from noni import census_render

    shape = census_render.STALE_AFTER_RE
    assert shape.pattern == r"^[0-9]+d?$", shape.pattern
    for value in UNICODE_STALE_AFTER:
        assert not shape.fullmatch(value), f"the shape matches {value!r}"
    for value in BEYOND_THE_RANGE:
        assert shape.fullmatch(value), f"{value!r} is refused by the shape, not the range"
    assert shape.fullmatch("30d") and shape.fullmatch("7"), (
        "the shape must still accept the default and a plain day count")

    render = (REPO / "src" / "noni" / "census_render.py").read_text(encoding="utf-8")
    assert render.count('r"^[0-9]+d?$"') == 1, (
        "the threshold shape is spelled more than once in the module that owns it")
    assert 'r"^\\d+d?$"' not in render, (
        "the threshold shape still matches Unicode digits")
