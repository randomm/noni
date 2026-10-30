"""The ledger-empty state words are a closed vocabulary owned by one table.

The states, their wording, and the probe error's text: renamed without updating
the wording and its rows, and a probe error keeps its words and drops its path.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py`` and the runners in ``tests/census_run.py``.
"""

from __future__ import annotations

import json

from _harness import _commit_file, _home_path_violation, _init_repo
from census_fixtures import _ndjson_rows, _valid_record
from census_run import _run_census


class TestLedgerStateVocabulary:
    """The ledger-empty state words are a closed vocabulary owned by one table.

    tests iterate LEDGER_EMPTY_MESSAGES rather than re-listing the words, so a
    state word cannot be renamed or added without the wording table and these
    cases moving together — the invariant AGENTS.md asks a script or a census
    check to hold, expressed as a test over the arbiter's own data."""

    def test_state_table_is_the_whole_vocabulary(self):
        import census

        assert set(census.LEDGER_EMPTY_STATES) == set(census.LEDGER_EMPTY_MESSAGES), (
            "the pinned state words and the message table have drifted apart"
        )
        # Exactly one state is silent, and it is the one the class must not
        # report: a decisions/ directory that holds at least one record. A
        # recordless tree — no decisions/ at all, or one with no *.json — is
        # the 'empty' state (TestLedgerEmpty.test_recordless_ledger_dir_reports_ledger_empty).
        silent = {s for s, detail in census.LEDGER_EMPTY_MESSAGES.items() if detail is None}
        assert silent == {"ok"}, f"expected only 'ok' to be silent, got {silent}"
        for state in census.LEDGER_EMPTY_STATES:
            if state != "ok":
                assert census.LEDGER_EMPTY_MESSAGES[state], (
                    f"state {state!r} has no wording: it would render an empty row"
                )

    def test_every_reported_state_word_appears_in_its_own_row(self, tmp_path):
        """Each non-silent state of the table is reachable and names itself in
        exactly one row — the probe-honesty contract for this class."""
        import census

        cases = {
            "absent": lambda repo: _commit_file(repo, "README.md", "# repo\n"),
            # noni/ present, decisions/ missing — one of the two trees 'empty'
            # names; the other is the recordless decisions/ directory below.
            "empty": lambda repo: _commit_file(repo, "noni/README.md", "noni here\n"),
            "not a directory": lambda repo: _commit_file(repo, "noni", "a file, not a dir\n"),
        }
        for state in census.LEDGER_EMPTY_STATES:
            if state not in cases:
                continue
            repo = _init_repo(tmp_path / f"repo-{state.replace(' ', '-')}")
            cases[state](repo)
            rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "ledger-empty"]
            assert rc == 0 and len(rows) == 1, f"{state}: expected one row, got {rc} {rows}"
            assert f"({state})" in rows[0]["message"], f"{state}: {rows[0]['message']}"
            # The row never carries a machine-local absolute path in subject.
            assert not rows[0]["subject"].startswith("/"), (
                f"subject must be root-relative like artifact, not an absolute path: {rows[0]}"
            )
            assert rows[0]["subject"] == rows[0]["artifact"]

    def test_probe_error_keeps_its_text(self, tmp_path, monkeypatch):
        """An OSError while listing the ledger is not labelled a symlink: the
        row carries the error text so the operator sees what actually failed.

        The fault is injected at the probe's own listing of the ledger (its
        ``iterdir``), not at the record pass and not at a stat the rest of the
        census also performs — so the ledger is a real directory at probe time
        and only the probe's readdir faults, which is exactly the state where a
        label of "symlink" would be a lie about which state occurred.

        The seam is the probe's listing call itself, not ``Path.glob``: glob
        swallows the OSError readdir raises and yields nothing, so a fault
        injected there would reach the probe as a recordless directory rather
        than as a fault. The row that carries the text is the ``ledger-edited``
        cannot-tell of a ledger that could not be listed, not a ``ledger-empty``
        row: an unreadable ledger answers no state word, so no state word is
        rendered for it.
        """
        import census

        repo = _init_repo(tmp_path / "repo")
        # A real record committed: the probe fault alone must decide the row,
        # so this test also proves the probe's fault is reported even when the
        # ledger is not empty.
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        ledger = repo / "noni" / "decisions"

        real_iterdir = census.Path.iterdir

        def boom(self):
            if self == ledger:
                raise OSError("input/output error")
            return real_iterdir(self)

        monkeypatch.setattr(census.Path, "iterdir", boom)
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "ledger-edited"]
        assert len(rows) == 1, f"expected one row: {rows}"
        assert "input/output error" in rows[0]["message"], (
            f"the OSError text must survive into the row: {rows[0]['message']}"
        )
        assert "symlink" not in rows[0]["message"], (
            f"an I/O fault must not be reported as a symlink: {rows[0]['message']}"
        )
        # The probe faulted, so there is no censusable ledger and no state word
        # to render: its warn is the only row the ledger group adds (the record
        # pass runs on the real directory and finds its one valid record).
        empty = [r for r in _ndjson_rows(out) if r.get("check") == "ledger-empty"]
        assert empty == [], f"an unreadable ledger is not an empty one: {empty}"
        assert rc == 0, f"the state stays warn, got {rc}\n{err}"

    def test_an_unreadable_ledger_adds_no_state_word_row(self, tmp_path, monkeypatch):
        """The probe-honesty half of the same fault: the four words of
        LEDGER_EMPTY_MESSAGES name states of the tree, and "exists but could
        not be listed" is not one of them. The run reports the fault under the
        ledger-edited class and renders none of those words for it."""
        import census

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        ledger = repo / "noni" / "decisions"

        real_iterdir = census.Path.iterdir

        def boom(self):
            if self == ledger:
                raise OSError("readdir denied")
            return real_iterdir(self)

        monkeypatch.setattr(census.Path, "iterdir", boom)
        _rc, out, _err = _run_census(repo, json_out=True, skip_hygiene=True)
        rows = _ndjson_rows(out)
        assert [r["check"] for r in rows if r.get("kind") == "finding"] == ["ledger-edited"], rows
        row = [r for r in rows if r.get("check") == "ledger-edited"][0]
        for word in census.LEDGER_EMPTY_STATES:
            assert f"({word})" not in row["message"], (
                f"a state word the probe never established: {row['message']}"
            )
        assert row["subject"] == row["artifact"] == "noni/decisions", (
            f"subject and artifact name the ledger, root-relative: {row}"
        )
        assert not row["subject"].startswith("/"), (
            f"no machine-local path in the row: {row}"
        )

    def test_probe_error_text_keeps_its_words_and_drops_its_path(self, tmp_path, monkeypatch):
        """One OSError text, both halves of the rule, in the row that carries it.

        The fault is the one ``PermissionError`` raises: its ``str()`` is the errno
        words *and* the path it failed on, so a single row must keep the first and
        drop the second. They pull against each other, and each rule broken on its
        own passes the other's test. An unanchored scrub ate the middle of every
        ``/`` it saw, so it took ``input/output`` with it and the row that exists
        to say what failed said nothing; a rule that dropped the fault instead of
        its path would leave the operator with a bare class name.

        The path is gone because the producer never wrote it: the row is built
        from the exception's class and its ``strerror``, so the marker the scrub
        leaves behind has no part to replace. This row no longer prints one, and
        asking it to would ask for the path to have been in the text first. The
        scrub's own marker is pinned in tests/test_census_text_scrub.py.

        The home path is the harness fixture rather than a literal: a tracked file
        carrying one would trip the census's own hygiene class.
        """
        import census

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        ledger = repo / "noni" / "decisions"
        leaked = _home_path_violation()

        real_iterdir = census.Path.iterdir
        # str() of the fault is what the row renders, and OSError builds it from
        # the errno pair: strerror carries the words, filename the path. The
        # errno words are extended so the one text holds both halves of the rule.
        fault = OSError(13, "Permission denied - input/output error", leaked)

        def boom(self):
            if self == ledger:
                raise fault
            return real_iterdir(self)

        monkeypatch.setattr(census.Path, "iterdir", boom)
        _rc, out, _err = _run_census(repo, json_out=True, skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "ledger-edited"]
        assert len(rows) == 1, f"expected one row: {rows}"
        message = rows[0]["message"]
        assert "input/output error" in message, (
            f"the errno words are the finding and must survive the scrub: {message}"
        )
        assert leaked not in message, (
            f"the row leaked a machine-local absolute path: {message}"
        )
        for part in (".ssh", "id_ed25519"):
            assert part not in message, (
                f"a component of the fault's filename reached the row: {message}"
            )
        # The ledger is named root-relative, and naming it is the row's whole
        # point: the scrub that drops the host path may not drop this too.
        assert rows[0]["subject"] == rows[0]["artifact"] == "noni/decisions", rows[0]
        assert "noni/decisions" in message, message
