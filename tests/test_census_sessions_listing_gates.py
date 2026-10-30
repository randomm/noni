"""The listing fault's gate is the read, and the readable paths stay as they were.

A register reached through a symlink cannot read clean, a committed listable
register censuses clean as before, and a missing register is still clean.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py`` and the runners in ``tests/census_run.py``.
"""

from __future__ import annotations

import json

from _harness import _commit_file, _fault_the_sessions_listing, _init_repo
from census_fixtures import (
    _ndjson_rows,
    _session_body,
    _sessions_fixture,
    _valid_record,
)
from census_run import _run_census


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

    def test_a_symlinked_override_outside_the_tree_reports_the_fault(
        self, tmp_path, monkeypatch
    ):
        """The gate is the read, so a register reached through a link cannot read clean.

        The path the census classifies and the path it lists are the one the
        caller gave it. Here a register of the audited tree is reached through a
        symlink under ``noni/``, so the classification follows the link to a
        directory and the readdir faults: exactly the pair the fault row exists
        for. A gate that classified the directory first and reached the listing
        only when the classification looked listable would be a second read
        entitled to disagree with the first, and this is the case it would get
        wrong -- a clean run for a register nobody read.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                     json.dumps(_valid_record(), indent=2))
        register = tmp_path / "real-register"
        register.mkdir()
        (register / "2026-10-01-aaaaaa.md").write_text(_session_body("developer"),
                                                       encoding="utf-8")
        (tmp_path / "repo" / "noni" / "linked").symlink_to(register)
        _fault_the_sessions_listing(monkeypatch, register)

        rc, out, err = _run_census(repo, "--sessions", str(register), json_out=True,
                                   skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out)
                if r.get("kind") == "finding" and r.get("check") == "session-deleted"]
        assert len(rows) == 1, (
            f"the symlinked register the run could not list must be reported: {rows}"
        )
        assert "could not be listed" in rows[0]["message"], rows[0]
        assert rc == 0, f"the fault row is a warn, got {rc}\nstderr: {err}"

    def test_a_readable_register_behaves_exactly_as_before(self, tmp_path):
        """The fix must not disturb the paths that already worked.

        A committed, listable register with two active sessions censuses clean
        (the deletion check finds nothing missing), and the same repo with one
        file removed still reports that deletion: the group's normal reads go
        through the same call now and must answer as they did on the base commit.
        """
        repo = _sessions_fixture(tmp_path)
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, f"a readable register censuses clean, got {rc}\nstderr: {err}\n{out}"
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert rows == [], f"a committed ledger and a readable register are clean: {rows}"
        (repo / "noni/sessions/2026-10-01-bbbbbb.md").unlink()
        rc, out, err = _run_census(repo, "--only", "session-deleted",
                                   json_out=True, skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "session-deleted"]
        assert len(rows) == 1 and rows[0]["subject"] == "2026-10-01-bbbbbb.md", rows
        assert rc == 0, f"warn class exits 0, got {rc}\nstderr: {err}"

    def test_a_missing_sessions_dir_is_still_clean(self, tmp_path):
        """No register at all is a state of the tree, not a fault of this read.

        The acceptance criterion names it explicitly: a missing ``noni/sessions/``
        keeps its old behaviour, which is silence. The fault row exists precisely
        to separate "could not look" from "nothing to see", so the second of
        those must stay wordless or the first is worth nothing.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "README.md", "# repo\n")
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, f"no sessions dir is clean, got {rc}\nstderr: {err}\n{out}"
        rows = [r for r in _ndjson_rows(out)
                if r.get("kind") == "finding" and r.get("artifact") == "noni/sessions"]
        assert rows == [], (
            f"a missing register adds no row of its own: {rows}"
        )
