"""``listing_helper``: the run's one readdir, and a readdir fault raises.

``Path.glob`` returns nothing when readdir raises, which is how a directory the run
could not read arrives as a project that never steered anything. The helper's
contract is the opposite.

Split out of ``tests/test_census_ledger_probe.py``; the builders are in
``tests/census_ledger_fixtures.py``.
"""

from __future__ import annotations

from pathlib import Path

import census_ledger
from census_ledger_fixtures import _fault_iterdir

# --- the listing helper ---------------------------------------------------------


def test_listing_helper_returns_record_names_from_iterdir(tmp_path, monkeypatch):
    """The helper lists the ledger's ``*.json`` names and only those.

    The record pass of ``census.py`` and the ordering readers both go through
    this one call, so "which files count as ledger records" has one answer:
    ``*.json`` names, non-JSON entries and directories excluded, in a stable
    order. The test asserts the names and not the ``Path`` objects, because the
    callers key their rows on names.
    """
    ledger = tmp_path / "decisions"
    ledger.mkdir()
    for name in ("2026-10-02-b.json", "2026-10-01-a.json", "notes.md", "sub"):
        (ledger / name).mkdir() if name == "sub" else (ledger / name).write_text("{}")
    seen: list[str] = []

    real_iterdir = Path.iterdir

    def spy(self):
        seen.append(str(self))
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", spy)
    names = census_ledger.listing_helper(ledger)
    assert sorted(names) == ["2026-10-01-a.json", "2026-10-02-b.json"], names
    assert ledger in [Path(s) for s in seen], (
        "the helper must reach the directory through iterdir, not glob"
    )


def test_listing_helper_raises_on_a_readdir_fault(tmp_path, monkeypatch):
    """The helper does not swallow the fault: it raises, and the caller decides.

    ``Path.glob`` returns an empty iterator when readdir raises, which is how a
    directory the run could not read comes to look like a project that has
    never steered anything. The helper's contract is the opposite: the OSError
    propagates so the probe can carry its text and the census can report the
    fault instead of an answer."""
    ledger = tmp_path / "decisions"
    ledger.mkdir()
    (ledger / "2026-10-01-a.json").write_text("{}")
    _fault_iterdir(monkeypatch, ledger, "input/output error")

    raised = None
    try:
        census_ledger.listing_helper(ledger)
    except OSError as e:
        raised = e
    assert raised is not None, "a readdir fault must propagate, not yield nothing"
    assert "input/output error" in str(raised)
    # glob is not the seam: had the helper called it, this call would have
    # returned [] and raised nothing.
    assert list(ledger.glob("*.json")) != [], "the fixture itself is listable by glob"
