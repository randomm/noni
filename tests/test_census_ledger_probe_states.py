"""``LedgerProbe``: the states it answers, the fault text it carries, the path it does not.

Split out of ``tests/test_census_ledger_probe.py``; the builders are in
``tests/census_ledger_fixtures.py``.
"""

from __future__ import annotations

from pathlib import Path

import census_ledger
from _harness import _init_repo
from census_ledger_fixtures import (
    _fault_iterdir,
    _kind_absent,
    _kind_dir_ok,
    _kind_parent_nonregular,
    _kind_symlink,
)

# --- the probe ------------------------------------------------------------------


def test_probe_records_listing_fault_text_on_the_probe(tmp_path, monkeypatch):
    """The probe catches the helper's OSError and carries its text verbatim.

    ``listing_fault`` is the one field allowed to hold a fault that is not a
    state of the tree, so the text must survive the probe intact for the row to
    quote it."""
    ledger = tmp_path / "decisions"
    ledger.mkdir()
    (ledger / "2026-10-01-a.json").write_text("{}")
    _fault_iterdir(monkeypatch, ledger, "readdir denied")

    probe = census_ledger.probe_ledger(ledger, _kind_dir_ok)
    # The fault's words with its class in front of them: the text a row renders,
    # built by ``census_text.fault_text`` from the structured fields so the
    # filename is never in it (see ``test_fault_text_never_carries_the_filename``
    # in tests/test_census_text_scrub.py for the rule itself).
    assert probe.listing_fault == "OSError: readdir denied", probe
    assert probe.state == "empty", probe


def test_probe_reports_a_fault_whose_oserror_carries_a_path(tmp_path, monkeypatch):
    """The probe never raises over a fault that carries a path, and never carries it.

    ``OSError`` appends the path it failed on to ``str(e)`` and keeps it in
    ``e.filename``, so the probe's field is the place to take it out: the row is
    built from the exception's class and its ``strerror``, which are the half that
    says what failed. Dropping the whole fault would cost the operator the only
    thing that identifies it, and raising would turn the row about an unreadable
    ledger into a traceback. Nothing downstream has to scrub what was never
    carried here (the scrubber stays a net for other foreign text).
    """
    ledger = tmp_path / "decisions"
    ledger.mkdir()
    (ledger / "2026-10-01-a.json").write_text("{}")
    host = tmp_path / "host-dir" / "decisions"

    real_iterdir = Path.iterdir

    def boom(self):
        if self == ledger:
            raise OSError(5, "Input/output error", str(host))
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", boom)
    probe = census_ledger.probe_ledger(ledger, _kind_dir_ok)
    assert probe.listing_fault is not None, probe
    assert "Input/output error" in probe.listing_fault, probe
    # The whole path, and no part of it: the row names the ledger itself, so the
    # filename the read failed on is a host location and nothing else.
    assert str(host) not in probe.listing_fault, probe.listing_fault
    assert "host-dir" not in probe.listing_fault, probe.listing_fault


def test_probe_answers_ok_for_a_ledger_with_a_record(tmp_path):
    """A real directory holding one ``*.json`` record is "ok", no fault, no
    problem: the only state under which the record pass reports anything."""
    ledger = tmp_path / "decisions"
    ledger.mkdir()
    (ledger / "2026-10-01-a.json").write_text("{}")
    probe = census_ledger.probe_ledger(ledger, _kind_dir_ok)
    assert (probe.state, probe.problem, probe.listing_fault) == ("ok", None, None), probe


def test_probe_answers_empty_for_a_recordless_directory(tmp_path):
    """A directory that lists fine and holds no record is the "empty" warn, with
    no fault text attached -- the read answered, and what it answered was
    "nothing here"."""
    ledger = tmp_path / "decisions"
    ledger.mkdir()
    (ledger / "notes.md").write_text("not a record")
    probe = census_ledger.probe_ledger(ledger, _kind_dir_ok)
    assert (probe.state, probe.problem, probe.listing_fault) == ("empty", None, None), probe


def test_probe_answers_absent_when_there_is_no_noni(tmp_path):
    """No parent at all is "absent", a state of the tree rather than a fault."""
    ledger = tmp_path / "noni" / "decisions"
    probe = census_ledger.probe_ledger(ledger, _kind_absent)
    assert (probe.state, probe.problem, probe.listing_fault) == ("absent", None, None), probe


def test_probe_reports_symlink_and_never_follows_it(tmp_path, monkeypatch):
    """A symlinked ledger is "symlink" with no listing attempted.

    A link whose target holds a record must still answer "symlink": if the
    probe followed the link it would find a record, answer "ok" and the census
    would report nothing about a path it read through."""
    real = tmp_path / "elsewhere"
    real.mkdir()
    (real / "2026-10-01-a.json").write_text("{}")
    ledger = tmp_path / "noni" / "decisions"
    ledger.parent.mkdir(parents=True)
    ledger.symlink_to(real)
    probe = census_ledger.probe_ledger(ledger, _kind_symlink)
    assert probe.state == "symlink", probe
    assert probe.listing_fault is None, probe


def test_probe_keeps_the_parent_problem_for_a_nonregular_noni(tmp_path):
    """``noni/`` not being a directory is reported with the OSError text that
    said so, under the closest documented state word."""
    ledger = tmp_path / "noni" / "decisions"
    probe = census_ledger.probe_ledger(ledger, _kind_parent_nonregular)
    assert probe.state == "not a directory", probe
    assert probe.problem == "path is not a directory", probe


def test_probe_reads_the_ledger_through_the_helper_not_glob(tmp_path, monkeypatch):
    """The probe's one read is the helper's ``iterdir``.

    Patching ``Path.glob`` to raise must not produce a fault: if the probe were
    still listing with ``glob`` it would report the ledger as unreadable here
    while its own seam answered fine, and the reverse patch (``iterdir``
    raising) is what the fault tests above use. Together they pin which call the
    probe actually makes."""
    ledger = tmp_path / "decisions"
    ledger.mkdir()
    (ledger / "2026-10-01-a.json").write_text("{}")

    def boom_glob(self, pattern):
        raise AssertionError("the probe must not list the ledger with glob")

    monkeypatch.setattr(Path, "glob", boom_glob)
    probe = census_ledger.probe_ledger(ledger, _kind_dir_ok)
    assert probe.state == "ok", probe
    assert probe.listing_fault is None, probe


def test_probe_fault_on_a_real_repository_ledger(tmp_path, monkeypatch):
    """The fault arm against a tree built by the harness's own git fixture.

    The repository is real (so the path shapes are the ones a census run sees)
    and only the ledger's readdir faults, which is the state no file permission
    can plant for a root-equivalent runner."""
    repo = _init_repo(tmp_path / "repo")
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    (ledger / "2026-10-01-a.json").write_text("{}")
    _fault_iterdir(monkeypatch, ledger)
    probe = census_ledger.probe_ledger(ledger, _kind_dir_ok)
    assert probe.listing_fault == "OSError: readdir denied", probe
    assert probe.state == "empty", (
        "an unlistable ledger keeps the state word so the git-backed deletion "
        "question is still put when git can answer it"
    )
