"""``ledger_name``: the row's identifier is a name, never a location.

The reduction is total -- no input earns an empty or crashed identifier -- and a
root-relative path keeps its whole name.

Split out of ``tests/test_census_ledger_probe.py``; the builders are in
``tests/census_ledger_fixtures.py``.
"""

from __future__ import annotations

import census_ledger  # noqa: E402
import pytest
from census_ledger_fixtures import _is_census_written_path


@pytest.mark.parametrize("rel,expected", (
    # The ordinary case: a path the census could root keeps its root-relative form.
    ("noni/decisions", "noni/decisions"),
    ("noni/sessions", "noni/sessions"),
    # A tilde that names a directory, not a home directory, is not a host path.
    ("noni/a~b", "noni/a~b"),
    # Every shape that could carry a host location is reduced to its last segment.
    ("~deploy/a/b c", "b c"),
    ("~/x/y", "y"),
    ("../host-dir/decisions", "decisions"),
    ("../../home/someone/decisions", "decisions"),
    ("/abs/host-dir/decisions", "decisions"),
    # A segment no repository directory is ever named with: a fragment the caller
    # walked, not a name the census wrote, so the row keeps its last segment and
    # no run of someone else's characters reaches the fields a caller joins on.
    ("build/home/someone/.aws/" + "a" * 240 + "/sessions", "sessions"),
    # The cap is on the segment, not the path: a shallow tree with ordinary names
    # stays root-relative however many segments it holds.
    ("x/" + "b" * 79, "x/" + "b" * 79),
    ("a/b/c/d/e", "a/b/c/d/e"),
    # A dot segment is a walk, not a name, so it is not root-relative either.
    ("./noni/decisions", "decisions"),
    ("noni/./decisions", "decisions"),
    # Nothing left to name: the generic word, never an empty field.
    ("", "ledger"),
    ("/", "ledger"),
))
def test_ledger_name_keeps_a_root_relative_path_and_shrinks_the_rest(rel, expected):
    """The identifier rule, stated once: root-relative stays, anything else is one segment.

    The row's ``subject``/``artifact`` are joined on, so they cannot go through the
    scrubber, and they are rendered too, so they cannot carry a host path either.
    The reduction is what settles that, and it is stated as a predicate over the
    path (see :func:`_is_census_written_path`) rather than as a list of shapes to
    shrink: a rule that names shapes is a rule that misses one.
    """
    assert _is_census_written_path(rel) == (expected == rel)
    assert census_ledger.ledger_name(rel) == expected


def test_ledger_name_answers_for_every_path_shape_it_may_be_handed():
    """The rule is total: no input earns an empty or crashed identifier.

    ``ledger_name`` runs on whatever ``_rel_to_root`` handed back, including the
    forms no test lists -- a doubled separator, a dot segment, a bare filename --
    and the row's identifier fields are required, so every one of them must come
    back as a name the report can print and a caller can join on.
    """
    for rel in ("~deploy/a/b c", "~/x/y", "../host-dir/decisions",
                "../../home/someone/decisions", "/abs/host-dir/decisions", "/", "",
                "noni/decisions", "noni/a~b", "a//b", "a/./b", "decisions", "//", "~",
                "/home/someone/decisions", "a/./", "./noni/decisions", "noni//"):
        name = census_ledger.ledger_name(rel)
        assert name, f"{rel!r} answered an empty identifier"
        assert "\\" not in name and "\n" not in name, f"{rel!r} -> {name!r}"
        assert len(name) <= max(len(rel), census_ledger._ROOT_SEGMENT_MAX), \
            f"{rel!r} -> {name!r}: an identifier is never longer than its path"
        if name != rel:  # a root-relative path is kept whole, everything else shrunk
            assert not name.startswith("/") and not name.startswith("~"), \
                f"{rel!r} -> {name!r}: an identifier may not be a location"
            assert ".." not in name.split("/") and "." not in name.split("/"), \
                f"{rel!r} -> {name!r} escapes the tree"


def test_ledger_name_never_shrinks_a_root_relative_path():
    """The other direction of the rule: the census's own path keeps its name.

    Shrinking too much is as expensive as shrinking too little -- a row whose
    identifier reads ``decisions`` instead of ``noni/decisions`` tells the
    operator nothing they can act on, and a report that joins on the field joins
    on the root-relative path. These are the paths ``_rel_to_root`` actually hands
    back for an in-tree ledger and register.
    """
    for rel in ("noni/decisions", "noni/sessions", "noni/a~b", "noni/decisions/sub"):
        assert census_ledger.ledger_name(rel) == rel
