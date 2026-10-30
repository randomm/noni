"""The public_safety module the census's hygiene class will actually run.

The census loads its checker into a census-owned ``sys.modules`` slot, so the hygiene
tests must patch the object the census's own loader returns, not whatever a plain
``import public_safety`` hands back. Copied verbatim from
``tests/test_census_unified.py``, whose hygiene class now lives in
``tests/test_census_hygiene.py`` and ``tests/test_census_hygiene_row_contract.py``.
"""

from __future__ import annotations


def _hygiene_target():
    """The public_safety module the census's hygiene class will actually run.

    The census loads its checker into a census-owned sys.modules slot, so a
    seam installed on a plain ``import public_safety`` object can be a
    different module from the one the scan uses. Loading through the census's
    own loader returns the object the scan reads, which is what the hygiene
    tests patch (``_default_denylist_file``, ``_scan_tracked_files``,
    ``FUTURE_PATTERNS``).
    """
    import census

    module = census._load_public_safety()
    assert module is not None, "scripts/public_safety.py must be loadable for the hygiene tests"
    return module
