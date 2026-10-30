"""The rows a faulted ledger probe produces: bounded, path-free, never silent.

The census's exit codes for those rows are proved by the census's own suites; these
prove the read and the row it feeds.

Split out of ``tests/test_census_ledger_probe.py``; the builders are in
``tests/census_ledger_fixtures.py``.
"""

from __future__ import annotations

import json

from _harness import _commit_file, _init_repo
from census_ledger_fixtures import _code, _rows, _valid_record

# --- the fault rows, end to end -------------------------------------------------
#
# The rows the fault produces, driven through census.main: the machine-local
# path rule, the one-probe rule, and the filter that must not buy back a clean
# verdict. The unit tests above prove the read; these prove what the run says
# about it.

def test_unreadable_ledger_outside_the_repo_leaks_no_absolute_path(tmp_path, monkeypatch):
    """An out-of-tree ``--ledger`` whose listing faults must not print a host path.

    The ledger override is the one case where the ledger lives outside the
    audited tree, so ``_rel_to_root`` cannot root it and hands back the string it
    was given -- the machine-local absolute path, verbatim. The row that reports
    the fault therefore has to scrub and bound that text the way the ordering
    group's equivalent row does (``census_ordering`` composes its listing-fault
    sentence with the fault text passed through ``bounded``), and the OSError
    text itself is foreign content that goes through the same rule.

    The fault message is planted with a host path inside it, so the assertion is
    about the scrubbing and not about which string the fixture happened to use.
    """
    import census

    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "README.md", "# repo\n")
    outside = tmp_path / "ledger-home" / "decisions"
    outside.mkdir(parents=True)
    (outside / "2026-10-01-a.json").write_text(json.dumps(_valid_record(), indent=2),
                                               encoding="utf-8")

    real_iterdir = census.Path.iterdir
    needle = str(outside)

    def boom(self):
        if self == outside:
            raise OSError(f"readdir denied for {needle}")
        return real_iterdir(self)

    monkeypatch.setattr(census.Path, "iterdir", boom)
    found = _rows(repo, "--skip", "hygiene", "--ledger", str(outside))
    assert [r["check"] for r in found] == ["ledger-edited"], found
    row = found[0]
    for field in ("subject", "artifact", "message"):
        assert needle not in row[field], f"absolute path leaked in {field}: {row[field]!r}"
        assert not any(part.startswith(f"{tmp_path}/") for part in row[field].split()), (
            f"machine-local path leaked in {field}: {row[field]!r}"
        )
    # The operator still learns what failed and where: the fault's own words
    # survive the scrub, and the row still names the ledger it could not read.
    assert "readdir" in row["message"] and "denied" in row["message"], row["message"]
    assert "decisions" in row["subject"] and "decisions" in row["artifact"], row
    assert _code(repo, "--skip", "hygiene", "--ledger", str(outside)) == 0
    assert _code(repo, "--skip", "hygiene", "--strict", "--ledger", str(outside)) == 12


def test_an_unreadable_ledger_empty_row_bounds_the_probe_problem(tmp_path, monkeypatch):
    """``probe.problem`` is OSError text and reaches the ledger-empty row through
    the census's bound-and-scrub, not raw.

    The probe's problem text is foreign text from this tree, so a long strerror
    or one carrying a host path would otherwise land in the row unbounded and
    unscrubbed. Unlike the listing-fault row, this one composes its own
    root-relative path, so only the probe's text is scrubbed -- the state word
    the row exists to carry stays intact.
    """
    import census

    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/README.md", "noni lives here\n")
    ledger = repo / "noni" / "decisions"
    ledger.mkdir()
    leak = str(tmp_path / "secret-host-dir")

    real_is_dir = census.Path.is_dir

    def boom_is_dir(self):
        if self == ledger:
            raise OSError("i/o fault " + "u" * 400 + " at " + leak)
        return real_is_dir(self)

    monkeypatch.setattr(census.Path, "is_dir", boom_is_dir)
    empty = [r for r in _rows(repo, "--skip", "hygiene") if r["check"] == "ledger-empty"]
    assert len(empty) == 1, empty
    msg = empty[0]["message"]
    assert "probe error" in msg, msg
    assert leak not in msg, f"machine-local path in the row: {msg}"
    assert "u" * 400 not in msg, f"unbounded fault text in the row: {msg}"
    # The bound is the one ``_bounded`` applies to foreign text (300 chars); the
    # sentence the census composed around it is its own wording and keeps its own
    # path fragments, so only the probe's text is measured here.
    probe_text = msg.split("(probe error: ", 1)[1]
    assert len(probe_text) <= 301, f"foreign text past the bound: {len(probe_text)}"
    assert "not a directory" in msg, f"state word kept: {msg}"


def test_the_listing_fault_row_is_clipped_as_a_whole(tmp_path, monkeypatch):
    """The fault row keeps the bound every other row of the report keeps.

    ``append_listing_fault`` composes its sentence around two pieces of foreign
    text and clipped neither: the finished row was as long as the errno text
    inside it, and a ``strerror`` of a few thousand characters (a kernel that
    names the mount it failed on, a fuse daemon that answers at length) was a
    row of a few thousand characters in a report whose every other row is bound.
    The bound wraps the whole message, so the sentence this run wrote is at most
    the bound whoever wrote the fault's words.

    In-process: the fault is inside the interpreter, where no file permission
    can plant it.
    """
    import census

    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    ledger = repo / "noni" / "decisions"

    real_iterdir = census.Path.iterdir

    def boom(self):
        if self == ledger:
            raise OSError("input/output error: " + "u" * 5000)
        return real_iterdir(self)

    monkeypatch.setattr(census.Path, "iterdir", boom)
    rows = _rows(repo, "--skip", "hygiene")
    assert [r["check"] for r in rows] == ["ledger-edited"], rows
    message = rows[0]["message"]
    assert len(message) <= 300, f"{len(message)} chars: {message[:80]}"
    assert "noni/decisions" in message, message
    assert "input/output error" in message, message
    assert "u" * 5000 not in message, message
