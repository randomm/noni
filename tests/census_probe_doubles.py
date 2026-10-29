"""Doubles for the seams the census reads.

``_UnreadableGit`` stands in for a Git object whose history read failed, which is how
a test reaches the cannot-tell paths without a fixture repo that is broken in some
other way. Copied verbatim from ``tests/test_census_unified.py``.
"""

from __future__ import annotations


class _UnreadableGit:
    """A stand-in for a Git object whose history read failed.

    The real object leaves ``available`` False when ``rev-parse``/``log`` or
    ``git log`` cannot answer, so the test drives the shape git actually
    presents rather than one no real run reaches."""

    top = None
    available = False
