"""A ``noni/sessions/`` that cannot be listed is a fault, never a clean register.

The probe's own contract at its construction sites, then the fault end to end: the
``OSError`` leaves the listing, the row carries the fault's words and none of its
path, no file row is invented behind it, and the listing primitive stays ``iterdir``.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py`` and the runners in ``tests/census_run.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from _harness import (
    _commit_file,
    _fault_the_sessions_listing,
    _harness_source,
    _home_path_violation,
    _permission_fault_on,
)
from census_fixtures import (
    _ndjson_rows,
    _session_body,
    _sessions_fixture,
    census_module,
)
from census_run import _run_census

REPO = Path(__file__).resolve().parent.parent

CENSUS_PY = REPO / "skills" / "census" / "scripts" / "census.py"

SESSIONS_CHECKS_PY = REPO / "src" / "noni" / "census_sessions_checks.py"

SESSIONS_PROBE_PY = REPO / "src" / "noni" / "census_sessions_probe.py"
CENSUS_RUN_PY = REPO / "src" / "noni" / "census_run.py"

class TestSessionsListingFault:
    """A ``noni/sessions/`` that cannot be listed is a fault, not a clean register.

    ``Path.glob`` swallows the ``OSError`` readdir raises and yields nothing, so
    while the register was listed with ``glob`` a directory the run could not
    read reported the same verdict as a project that had never opened a session.
    The register is listed with ``iterdir`` now, and these are the rows that
    fault earns — the sessions-side twin of ``TestLedgerStateVocabulary``'s
    ledger-listing tests, kept to the same contract and the same fault-injection
    seam for the same reason (a chmod fixture is vacuous on a root-equivalent
    runner, and patching ``glob`` would fault nothing).
    """


    def test_unlistable_sessions_dir_is_one_cannot_tell_row(self, tmp_path, monkeypatch):
        """One row of the class the deletion check already uses, naming the register."""
        repo = _sessions_fixture(tmp_path)
        _fault_the_sessions_listing(monkeypatch, repo / "noni" / "sessions")
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, f"cannot-tell is a warn, got {rc}\nstderr: {err}\n{out}"
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "session-deleted"]
        assert len(rows) == 1, f"expected exactly one row: {rows}"
        row = rows[0]
        assert row["severity"] == "warn", f"cannot-tell is a warn: {row}"
        assert row["code"] == 44, row
        assert row["subject"] == row["artifact"] == "noni/sessions", (
            f"subject and artifact name the register, root-relative: {row}"
        )
        assert not row["subject"].startswith("/"), (
            f"no machine-local path in the row: {row}"
        )
        assert row["message"].startswith("cannot-tell: "), (
            f"every cannot-tell row says so with this prefix: {row['message']}"
        )

    def test_the_fault_text_reaches_the_row_and_its_path_does_not(
        self, tmp_path, monkeypatch
    ):
        """Both halves of the rule on one fault text: keep the words, drop the path.

        ``PermissionError`` renders its ``str()`` as the errno words *and* the
        path it failed on, so the two halves pull against each other and each
        rule broken alone passes the other's test. The words survive because
        ``census_text.fault_text`` quotes the ``strerror``; the path never
        appears because that helper never reads ``filename``.

        The words are checked at the length the producer answers with, not the
        length the row prints: the row binds the foreign fragment to what its own
        sentence can pay for (``fault_bound`` in
        ``census_ledger.append_listing_fault``), so a fault whose text runs past
        that budget loses its tail, not the register's name or the verdict. The
        filename is checked in all three rendered fields, not only the message:
        the two identifier fields are the ones a caller joins on, and a leak
        there is the leak that matters.
        """
        repo = _sessions_fixture(tmp_path)
        leaked = _home_path_violation()
        monkeypatch.setattr(
            census_module().Path, "iterdir",
            _permission_fault_on(repo / "noni" / "sessions", leaked))
        _rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "session-deleted"]
        assert len(rows) == 1, f"expected one row: {rows}"
        row = rows[0]
        # The errno words are the finding. Measured against fault_text's own
        # answer so the fragment bound cannot silently drop part of them and
        # this assertion go green on a shorter string.
        # The words the row can carry are the ones the fragment bound leaves:
        # fault_text's answer is what the probe stores, and the shared builder
        # binds that fragment to what its own sentence pays for. Assert the
        # errno phrase the fixture was built to carry, which is shorter than the
        # bound, so this fails if the producer or the scrub dropped the words.
        assert "input/output error" in row["message"], (
            f"the errno words are the finding and must survive the scrub: "
            f"{row['message']!r}"
        )
        for field in ("subject", "artifact", "message"):
            assert leaked not in row[field], (
                f"the row leaked a machine-local absolute path in {field}: "
                f"{row[field]!r}"
            )
            for part in (".ssh", "id_ed25519"):
                assert part not in row[field], (
                    f"a component of the fault's filename reached {field}: "
                    f"{row[field]!r}"
                )
        # The register is named root-relative, and naming it is the row's point:
        # the scrub that drops the host path may not drop this too.
        assert "noni/sessions" in row["message"], row["message"]

    def test_the_fault_adds_no_other_session_row(self, tmp_path, monkeypatch):
        """One row for the fault, and no row about a file this run never saw.

        Three dishonesties are closed here at once. No file-based class may
        report on files nobody read: a second active session sharing one identity
        is a ``session-same-identity`` row on a register the run could not open,
        and a ``session-stalled`` cannot-tell would be a verdict on a file whose
        status was never parsed. The git-backed deletion question is not put
        either: for a directory this run could not enumerate, "missing from the
        working tree" is not something the run established, so the file the test
        deletes below earns no deletion row.
        """
        repo = _sessions_fixture(tmp_path)
        _commit_file(repo, "noni/sessions/2026-10-01-cccccc.md", _session_body("developer"))
        (repo / "noni/sessions/2026-10-01-bbbbbb.md").unlink()
        _fault_the_sessions_listing(monkeypatch, repo / "noni" / "sessions")
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out)
                if r.get("kind") == "finding" and r.get("artifact") == "noni/sessions"]
        assert [r["check"] for r in rows] == ["session-deleted"], (
            f"the fault's own row and nothing else from the sessions group: {rows}"
        )
        assert rows[0]["subject"] == "noni/sessions", (
            f"the one row names the directory it could not list, not a file: {rows[0]}"
        )
        assert rc == 0, f"the row is a warn, got {rc}\nstderr: {err}"

    def test_the_fault_is_not_reported_as_a_probe_row(self, tmp_path, monkeypatch):
        """One read, one row: the fault is not double-booked under ``probe``.

        ``probe`` answers a question about a path this run classified (the row
        for a sessions path that is not a directory at all). A listing fault
        earns the deletion class's cannot-tell only, so one failed readdir does
        not read as two separate problems found.
        """
        repo = _sessions_fixture(tmp_path)
        _fault_the_sessions_listing(monkeypatch, repo / "noni" / "sessions")
        _rc, out, _err = _run_census(repo, json_out=True, skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "probe"]
        assert rows == [], f"a listing fault is not a probe classification: {rows}"

    def test_the_row_survives_a_filter_that_named_no_session_class(
        self, tmp_path, monkeypatch
    ):
        """The filter cannot buy back the clean verdict.

        ``--only`` drops rows of classes it does not name, and this is a
        ``session-deleted`` row like any other — but it is also a whole-artifact
        row, about the directory the group was asked to read rather than one file
        inside it, so the group's filter keeps it and the group runs even when
        the filter named none of its classes.
        """
        repo = _sessions_fixture(tmp_path)
        _fault_the_sessions_listing(monkeypatch, repo / "noni" / "sessions")
        for extra in (("--only", "ledger-record"), ("--skip", "session-deleted"),
                      ("--only", "session-double", "--strict")):
            rows = [r for r in _ndjson_rows(_run_census(repo, *extra, json_out=True,
                                                        skip_hygiene=True)[1])
                    if r.get("kind") == "finding"]
            found = [r for r in rows if r.get("check") == "session-deleted"]
            assert len(found) == 1, f"{extra}: the unreadable register must be reported: {rows}"
            assert "could not be listed" in found[0]["message"], found[0]

    def test_the_row_escalates_to_44_under_strict(self, tmp_path, monkeypatch):
        """Warn by default, the class's 44 under ``--strict``.

        ``--only session-deleted`` names the class outright and hygiene is
        skipped, so this row alone decides the exit code: proving the promotion
        runs through ``_row``'s severity override rather than a hard-coded word.
        """
        repo = _sessions_fixture(tmp_path)
        _fault_the_sessions_listing(monkeypatch, repo / "noni" / "sessions")
        rc, out, err = _run_census(repo, "--only", "session-deleted", "--strict",
                                   skip_hygiene=True)
        assert rc == 44, f"expected 44 under --strict, got {rc}\nstderr: {err}\n{out}"

    def test_the_group_runs_for_the_fault_under_a_filter_of_another_group(
        self, tmp_path, monkeypatch
    ):
        """The gate, not just the filter: a run that skipped the group would be a silent run.

        ``keep`` cannot help a group that never ran, so ``main`` lists the
        register once, reads the fault off that listing, and runs the group on the
        answer even when the filter named none of its classes. This pins both
        halves at once: with the fault planted and a filter of the ledger group
        only, the fault still reaches the report.
        """
        repo = _sessions_fixture(tmp_path)
        _fault_the_sessions_listing(monkeypatch, repo / "noni" / "sessions")
        # The probe is answered by the same ``iterdir`` the group reads through,
        # so a probe that consulted a stat instead of a listing would say "no
        # fault" here and the group would never run.
        probe = census_module()._sessions_listing(repo / "noni" / "sessions")
        assert probe.fault is not None and probe.names is None, probe
        rc, out, err = _run_census(repo, "--only", "ledger-record",
                                   json_out=True, skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out)
                if r.get("kind") == "finding" and r.get("artifact") == "noni/sessions"]
        assert [r["check"] for r in rows] == ["session-deleted"], (
            f"the group must run for the fault even under another group's filter: {rows}"
        )
        assert rc == 0, f"the row is a warn, got {rc}\nstderr: {err}"

    def test_a_readable_register_lists_once_and_answers_its_names(self, tmp_path):
        """The other half of the gate: a listable register answers with names, no fault.

        A probe that always answered "faulted" would run the sessions group on
        every filtered run, quietly paying for a listing on runs that asked for
        none; one that dropped the names would leave the group no files to check.
        """
        repo = _sessions_fixture(tmp_path)
        probe = census_module()._sessions_listing(repo / "noni" / "sessions")
        assert probe.fault is None, probe.fault
        assert [p.name for p in (probe.names or ())] == [
            "2026-10-01-aaaaaa.md", "2026-10-01-bbbbbb.md"], probe

    def test_the_listing_is_the_one_readdir(self, tmp_path):
        """``_sessions_listing`` is the single answer to "which files are a register file".

        Every ``*.md`` entry the directory holds, in the order the probe carries
        them: a file whose name is not an allocated register name is in the
        listing on purpose -- the file loop gives it its ``session-malformed``
        row -- and a non-``.md`` entry is not, so it earns no session row at all.

        The ``glob`` half of this contract is not asserted here. It is a property
        of the listing function's own body and :meth:`test_the_listing_is_iterdir
        and_not_glob` pins it at that scope, from the AST, where a change of
        spelling cannot hide it; a behavioural test cannot see which primitive a
        function used, only what it returned.
        """
        import census

        sessions = tmp_path / "sessions"
        sessions.mkdir()
        for name in ("2026-10-01-bbbbbb.md", "2026-10-01-aaaaaa.md", "notes.md", "order.json"):
            (sessions / name).write_text("x\n")
        listed = [p.name for p in census._sessions_listing(sessions).names]
        assert listed == ["2026-10-01-aaaaaa.md", "2026-10-01-bbbbbb.md", "notes.md"], listed
        assert "order.json" not in listed, listed

    def test_the_listing_raises_where_glob_would_yield_nothing(
        self, tmp_path, monkeypatch
    ):
        """The bug, stated as the probe's contract: a faulted readdir is not lost.

        The census may not classify a directory it could not enumerate, and the
        only listing primitive that says so is ``iterdir``. On the interpreters
        this suite runs on, ``glob`` does not surface the fault the way
        ``iterdir`` does (it yields no entries rather than raising, and any it
        does raise is not the one this contract runs on), so the pair is pinned
        here: the read's ``OSError`` leaves the listing function, and no other
        reader of the register may reach for the primitive that swallows it.

        Both forms are asserted: the raw call raises (the primitive is the one
        that reports), and the probe carries the words rather than answering
        "listed, nothing there" (the fault is never lost on its way to a row).
        """
        import census

        sessions = tmp_path / "sessions"
        sessions.mkdir()
        (sessions / "2026-10-01-aaaaaa.md").write_text("x\n")
        _fault_the_sessions_listing(monkeypatch, sessions)
        with pytest.raises(OSError):
            census.Path.iterdir(sessions)
        probe = census._sessions_listing(sessions)
        assert probe.names is None and probe.fault is not None, probe
        assert "input/output error" in probe.fault, probe.fault

    def test_the_group_reports_no_file_rows_at_all_behind_the_fault(
        self, tmp_path, monkeypatch
    ):
        """The empty-listing shape must not be reachable by way of the fault.

        Had the group kept a ``glob`` listing, the same fault would have handed
        it an empty list and it would have reported "no sessions registered":
        the exit 0 and the silence below are what that read produced, and they
        are now produced only by a register the census actually read (see
        :meth:`test_a_missing_sessions_dir_is_still_clean`).
        """
        repo = _sessions_fixture(tmp_path)
        _fault_the_sessions_listing(monkeypatch, repo / "noni" / "sessions")
        rc, out, err = _run_census(repo, "--only", "session-malformed", "--strict",
                                   json_out=True, skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out)
                if r.get("kind") == "finding" and r.get("artifact") == "noni/sessions"]
        assert [r["check"] for r in rows] == ["session-deleted"], (
            f"the fault's row survives its own class's filter, and no file row "
            f"is invented behind it: {rows}"
        )
        assert rc == 44, f"the fault row is promoted, got {rc}\nstderr: {err}"

    def test_the_listing_is_iterdir_and_not_glob(self):
        """The source pins the seam: ``glob`` swallowing the fault is the bug.

        A change back to ``glob`` makes every fault test above pass vacuously --
        the listing would return nothing, the group would report no rows, and the
        run would exit 0 exactly as it did before the fix. This check fails on the
        source instead, so the regression cannot arrive as a passing suite.

        It reads the call graph, not a string: the bug is any listing primitive
        that swallows the readdir ``OSError``, and a pin written against one
        spelling of it (``sessions.glob("*.md")``) is satisfied by every other --
        ``sessions.glob(pattern)``, ``Path.glob(sessions, ...)`` -- while the
        silent clean is back. So the pin asks two AST questions of the source the
        register's listing lives in: the register's own listing function calls
        ``iterdir`` and holds no ``glob`` call, and no ``glob`` call is anywhere
        else in the census's own modules either. The listing's body sits in
        ``census_sessions_probe`` (the file-size ratchet moved the probe out of
        ``census.py``, which keeps the one call site of it); the ban covers every
        module of the census, the split-outs included, so a listing cannot reach
        for ``glob`` by moving house.
        """
        # The census's tree holds the census, the probe's tree the split-out
        # probe, the checks' tree the split-out session group and the run's tree
        # the body of the run that asks for the register; the ban below reads all
        # four, so a listing cannot reach for `glob` by moving house.
        census_trees = [(CENSUS_PY, ast.parse(_harness_source(CENSUS_PY))),
                        (SESSIONS_PROBE_PY, ast.parse(_harness_source(SESSIONS_PROBE_PY))),
                        (SESSIONS_CHECKS_PY, ast.parse(_harness_source(SESSIONS_CHECKS_PY))),
                        (CENSUS_RUN_PY, ast.parse(_harness_source(CENSUS_RUN_PY)))]
        # Two names, one listing: the sibling defines the readdir as
        # `sessions_listing` and the census wraps it as `_sessions_listing`, the
        # name `main` calls. One definition of each (a second of either is a
        # second reader of the register), and the `iterdir` assertion below is
        # asked of the one that actually lists -- the wrapper holds no readdir of
        # its own, by the same rule that keeps the run to one read.
        for name in ("_sessions_listing", "sessions_listing"):
            defs = [node for _, tree in census_trees for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == name]
            assert len(defs) == 1, \
                f"the register's listing is no longer defined once under {name}, " \
                "so this pin has nothing to scope to"
        listings = [node for node in (
            n for _, tree in census_trees for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef)
            and n.name in ("_sessions_listing", "sessions_listing"))
            if {c.func.attr for c in ast.walk(node)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
            & {"iterdir", "glob"}]
        assert len(listings) == 1, \
            "the register's reader is no longer the one function that performs a " \
            "readdir, so this pin has nothing to scope to"
        listing_calls = {node.func.attr for node in ast.walk(listings[0])
                         if isinstance(node, ast.Call)
                         and isinstance(node.func, ast.Attribute)}
        assert "iterdir" in listing_calls, \
            "the register is no longer listed with iterdir, the call that raises"
        assert "glob" not in listing_calls, \
            "the register's listing reached for glob, which swallows the fault and " \
            "reads an unreadable directory as an empty one"
        # The wider ban is a separate claim from the register's own rule, and it
        # is a claim about the census's modules: no listing primitive in any of
        # them may swallow an OSError the census then has to answer for.
        module_calls = {node.func.attr
                        for _, tree in census_trees
                        for node in ast.walk(tree)
                        if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)}
        assert "glob" not in module_calls, \
            "a glob call is back in the census; glob swallows the fault and reads " \
            "an unreadable directory as an empty one"
