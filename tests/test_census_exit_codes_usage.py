"""The usage errors of the unified census: the two paths that exit 2.

Moved out of ``tests/test_census_exit_codes.py`` so each file stays at or under
the size ratchet; the tests are main's, verbatim.
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
