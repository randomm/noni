"""A fault's row carries the fault's words and none of the file's name.

The host-shaped faults whose filename the scrubber keeps losing, and the ledger-empty
probe error beside them.

Split out of ``tests/test_census_ledger_probe.py``; the builders are in
``tests/census_ledger_fixtures.py``.
"""

from __future__ import annotations

import json

import pytest
from _harness import _commit_file, _init_repo
from census_ledger_fixtures import _host_shaped_faults, _rows, _valid_record


@pytest.mark.parametrize("case", range(2))
def test_the_listing_fault_row_carries_no_part_of_the_filename(tmp_path, monkeypatch, case):
    """The ledger group's row for an unlistable ledger names the fault, never the path.

    Two faults, both of which the scrubber has historically lost: a filename with
    a non-ASCII component and a space in it, and the bare home of a service
    account. Neither may reach any field of the row, and the row still has to say
    what failed and which ledger it could not read -- so the assertions pull in
    both directions and a rule that dropped the fault's words to keep its
    silence would fail here too.

    The fault is planted in the interpreter, at the probe's own listing.
    """
    import census

    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    ledger = repo / "noni" / "decisions"
    fault, parts = _host_shaped_faults()[case]

    real_iterdir = census.Path.iterdir

    def boom(self):
        if self == ledger:
            raise fault
        return real_iterdir(self)

    monkeypatch.setattr(census.Path, "iterdir", boom)
    rows = _rows(repo, "--skip", "hygiene")
    assert [r["check"] for r in rows] == ["ledger-edited"], rows
    row = rows[0]
    for field in ("subject", "artifact", "message"):
        for part in parts:
            assert part not in row[field], f"{part!r} leaked into {field}: {row[field]!r}"
        assert "/home/someone" not in row[field], row[field]
    # What the row is for: the fault's own words, and the ledger it could not read.
    assert "Permission denied" in row["message"], row["message"]
    assert "PermissionError" in row["message"], row["message"]
    assert row["subject"] == row["artifact"] == "noni/decisions", row


@pytest.mark.parametrize("case", range(2))
def test_the_ledger_empty_probe_error_carries_no_part_of_the_filename(
        tmp_path, monkeypatch, case):
    """The other row that quotes an ``OSError``: ``probe.problem`` in ``ledger-empty``.

    The fault here comes from a stat rather than a readdir, which is a different
    producer (``_file_kind``) and a different row (``ledger-empty``, composed with
    a state word and the census's own path). Same rule: the row is built from the
    exception's class and its ``strerror``, so no part of the filename reaches it
    and nothing downstream has to recognise the path to remove it.
    """
    import census

    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/README.md", "noni lives here\n")
    ledger = repo / "noni" / "decisions"
    ledger.mkdir()
    fault, parts = _host_shaped_faults()[case]

    real_is_dir = census.Path.is_dir

    def boom_is_dir(self):
        if self == ledger:
            raise fault
        return real_is_dir(self)

    monkeypatch.setattr(census.Path, "is_dir", boom_is_dir)
    empty = [r for r in _rows(repo, "--skip", "hygiene") if r["check"] == "ledger-empty"]
    assert len(empty) == 1, empty
    row = empty[0]
    for field in ("subject", "artifact", "message"):
        for part in parts:
            assert part not in row[field], f"{part!r} leaked into {field}: {row[field]!r}"
    assert "probe error" in row["message"], row["message"]
    assert "Permission denied" in row["message"], row["message"]
    assert "not a directory" in row["message"], row["message"]
