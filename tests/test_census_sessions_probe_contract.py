"""The sessions probe's own contract, asserted where it is written.

A probe that listed nothing earns no row, a probe that listed files answers for
those files, and a probe that faulted earns one row and no question.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py`` and the runners in ``tests/census_run.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from census_fixtures import _sessions_fixture, census_module
from census_probe_doubles import _UnreadableGit


class TestSessionsProbeContract:
    """The probe's own contract, asserted where it is written: at construction and
    at the reporter boundary.

    :class:`TestSessionsListingFault` covers what a faulted register earns
    through ``census.main``; these are the probe as a type. One test is what an
    illegal probe does (it raises, so no caller can build one that means two
    things), and the rest are what ``_check_sessions`` answers to each probe it
    is handed -- the only place the field meanings ("listed and empty" versus
    "did not read") can be pinned, since every end-to-end test reaches the
    reporter through a fault the listing function produced. The ledger side pins
    its probe the same way in ``test_census_ledger_probe``.
    """

    def test_the_probe_admits_only_listed_or_faulted(self):
        """The probe's type is the invariant, not a comment about it.

        ``names=()`` means "listed, and nothing was there" and ``fault`` means
        "the listing raised"; the two must not be able to mean each other, or a
        register this run never opened reports the same clean as one it read and
        found empty -- which is the shape this ticket exists to separate. The
        illegal shapes raise at construction, so the gate in ``main`` and the
        branch in ``_check_sessions`` cannot drift apart by construction either.
        """
        import census

        listed = census.SessionsProbe(names=())
        assert (listed.names, listed.fault) == ((), None), listed
        faulted = census.SessionsProbe(fault="readdir denied")
        assert (faulted.names, faulted.fault) == (None, "readdir denied"), faulted
        for illegal in ({}, {"names": (), "fault": "readdir denied"}):
            with pytest.raises(ValueError):
                census.SessionsProbe(**illegal)
        # The field types are the other half of the boundary: an ill-typed probe
        # has to fail where it is built, not three frames later inside the
        # reporter's file loop (a str element has no .name) or inside the row's
        # scrubber (a bytes fault has no .split).
        for wrong in ({"names": ["2026-10-01-aaaaaa.md"]}, {"names": "x.md"},
                      {"fault": b"readdir denied"}, {"fault": 5}, {"fault": ()}):
            with pytest.raises(TypeError):
                census.SessionsProbe(**wrong)

    def _rows_of(self, repo: Path, probe_value) -> list[dict]:
        """What ``_check_sessions`` appends for one probe, with no git to ask.

        The reporter's boundary, asserted with the census's own ``_check_sessions``
        and a git that answers nothing, so the only thing a row can be reacting to
        is the probe it was handed.
        """
        import census

        found: list[dict] = []
        census._check_sessions(repo / "noni" / "sessions", _UnreadableGit(), repo,
                               self.NOW, self.WEEK, False, found, probe_value)
        return found

    NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)
    WEEK = timedelta(days=7)

    def test_a_probe_that_listed_nothing_earns_no_row(self, tmp_path):
        """``names=()`` means "listed, and nothing was there": no row, no verdict.

        The shape the ticket turned from a silent clean into a distinguishable
        answer, so it is pinned at the reporter itself: an empty listing is not a
        fault row, and it is not a deletion answer either -- with no git here the
        question has no answer to fake.
        """
        import census

        repo = _sessions_fixture(tmp_path)
        assert self._rows_of(repo, census.SessionsProbe(names=())) == []

    def test_a_probe_that_listed_files_answers_for_those_files(self, tmp_path):
        """The names the probe carries are the files the group classifies.

        Two committed active sessions census clean, and the same repo with one
        file removed earns exactly the deletion row that removal deserves: the
        reporter reads the listing it was handed and asks git about those paths,
        in the order the probe carries them.
        """
        import census

        repo = _sessions_fixture(tmp_path)
        register = repo / "noni" / "sessions"
        real_git = census.Git(repo)
        assert real_git.available, "the fixture repo must be a git tree for this pin"

        listed = census_module()._sessions_listing(register)
        found: list[dict] = []
        census._check_sessions(register, real_git, repo, self.NOW, self.WEEK,
                               False, found, listed)
        assert found == [], f"two committed active sessions census clean: {found}"

        (register / "2026-10-01-bbbbbb.md").unlink()
        found: list[dict] = []
        census._check_sessions(register, census.Git(repo), repo, self.NOW, self.WEEK,
                               False, found, census_module()._sessions_listing(register))
        assert [r["check"] for r in found] == ["session-deleted"], found
        assert found[0]["subject"] == "2026-10-01-bbbbbb.md", found[0]

    def test_a_probe_that_faulted_earns_one_row_and_no_question(self, tmp_path):
        """A faulted listing is one whole-artifact row: no file rows, no deletion ask.

        The deletion question is the one a faulted read cannot answer, so the row
        is the group's only output -- and it is the row's own shape that is
        asserted here (warn, its code, the register in both identifier fields, the
        whole-artifact marker), since a filtered run depends on that marker.
        """
        import census

        repo = _sessions_fixture(tmp_path)
        found = self._rows_of(repo, census.SessionsProbe(fault="readdir denied"))
        assert [r["check"] for r in found] == ["session-deleted"], found
        row = found[0]
        assert row["severity"] == "warn" and row["code"] == 44, row
        assert row["subject"] == row["artifact"] == "noni/sessions", row
        assert "readdir denied" in row["message"], row
        assert row[census.WHOLE_ARTIFACT_KEY] is True, row
