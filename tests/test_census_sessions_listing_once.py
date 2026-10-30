"""The register is listed once per run, and the group gates on that one answer.

A listing that faults is reported and never read as an empty register, and a
register outside the tree leaks no absolute path.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py`` and the runners in ``tests/census_run.py``.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from _harness import (
    _HOME_PATH_KNOWN_IDENTITY,
    _commit_file,
    _fault_the_sessions_listing,
    _harness_source,
    _init_repo,
    _permission_fault_on,
)
from census_fixtures import (
    _ndjson_rows,
    _session_body,
    _sessions_fault_row,
    _sessions_fixture,
    _valid_record,
    census_module,
)
from census_run import _run_census

REPO = Path(__file__).resolve().parent.parent

CENSUS_PY = REPO / "skills" / "census" / "scripts" / "census.py"
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

    def test_the_register_is_listed_once_and_the_group_gates_on_that_answer(
        self, tmp_path, monkeypatch
    ):
        """One readdir, and the gate answers from it: pinned at the syscall and the AST.

        Two halves, because the contract has two halves. The behavioural one
        counts the register's readdirs for a whole run and says "one": a gate
        that classified the directory through a second reader, or a group that
        listed again behind the probe, fails here whatever it named itself. The
        source one asks the AST how many times ``main`` calls the register's one
        reader -- a docstring that mentions it does not count, and a second
        reader with another name is already caught by the counter.

        That the gate and the reporter agree on the fault itself is the end-to-end
        job of :meth:`test_the_group_runs_for_the_fault_under_a_filter_of_another_
        group`, which plants a real fault and insists the row reaches a run whose
        filter named no session class. Pinning the two spellings as text instead
        would fail a refactor that kept the invariant and pass one that broke it.
        """
        repo = _sessions_fixture(tmp_path)
        register = repo / "noni" / "sessions"
        _fault_the_sessions_listing(monkeypatch, register)

        import census

        real_iterdir = census.Path.iterdir
        reads: list[str] = []

        def spy(self):
            if self == register:
                reads.append(str(self))
            return real_iterdir(self)

        monkeypatch.setattr(census.Path, "iterdir", spy)
        rc, out, err = _run_census(repo, "--only", "ledger-record",
                                   json_out=True, skip_hygiene=True)
        assert len(reads) == 1, \
            f"the register was listed {len(reads)} times in one run: {reads}"
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "session-deleted"]
        assert len(rows) == 1 and rows[0]["subject"] == "noni/sessions", (
            f"the one listing is also what the group reported from: {rows}"
        )
        assert rc == 0, f"the fault row is a warn, got {rc}\nstderr: {err}"

        # The one call site of the register's reader now lives in the run split
        # (census_run.py, issue #52); the census still defines the seam itself, so
        # both files are read: the definition from the census, the call site from
        # the run that asks for the register.
        census_tree = ast.parse(_harness_source(CENSUS_PY))
        run_tree = ast.parse(_harness_source(CENSUS_RUN_PY))
        defined = {node.name for node in ast.walk(census_tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert "_sessions_listing" in defined, \
            "the register's one reader is gone from the census"
        call_sites = [node for node in ast.walk(run_tree)
                      if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Attribute)
                      and node.func.attr == "_sessions_listing"]
        assert len(call_sites) == 1, (
            f"the register has {len(call_sites)} listing call sites; the gate and "
            "the rows must be the answer of one readdir"
        )

    def test_an_unlistable_register_outside_the_tree_leaks_no_absolute_path(
        self, tmp_path, monkeypatch
    ):
        """An out-of-tree ``--sessions`` whose listing faults must not print a host path.

        The override is the case where ``_rel_to_root`` cannot root the register
        and hands back the machine-local absolute path it was given. The ledger
        twin of this row keeps only the path's last segment
        (``census_ledger.ledger_name``), and this row takes the same identifier
        from the same helper, so the two siblings cannot drift back apart: the
        operator learns which register could not be listed, and the host
        directory that holds it never reaches the report.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                     json.dumps(_valid_record(), indent=2))
        outside = tmp_path / "elsewhere-home" / "sessions"
        outside.mkdir(parents=True)
        (outside / "2026-10-01-aaaaaa.md").write_text(_session_body("developer"),
                                                      encoding="utf-8")
        needle = str(outside)
        monkeypatch.setattr(
            census_module().Path, "iterdir",
            _permission_fault_on(outside, needle))

        rc, out, err = _run_census(repo, "--sessions", str(outside),
                                   json_out=True, skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "session-deleted"]
        assert len(rows) == 1, f"expected the one fault row: {rows}"
        row = rows[0]
        assert row["subject"] == row["artifact"] == "sessions", (
            f"the row names the register by its last segment, as the ledger row does: {row}"
        )
        for field in ("subject", "artifact", "message"):
            assert needle not in row[field], \
                f"machine-local path leaked in {field}: {row[field]!r}"
        assert "could not be listed" in row["message"], row["message"]
        # The fault's words are kept to what the sentence can pay for. This is the
        # long sentence at its shortest useful fault: the fixture's errno pair is
        # ``PermissionError`` with a ``Permission denied - input/output error``
        # strerror, and the budget the raw out-of-tree path leaves over cuts it to
        # the class and the head of the words. What may not survive is the path.
        assert "Permission" in row["message"], row["message"]
        assert rc == 0, f"a fault is a warn, got {rc}\nstderr: {err}"

        # A home-relative form is the shape ``ledger_name``'s last-segment rule
        # cannot reduce to a bare segment. The row's identifier is that rule
        # applied to the *scrubbed* path, which is why the two fields that a
        # caller joins on and the prose clause cannot disagree about one path:
        # the scrub turns the home form into its marker and the reduction has
        # nothing left to keep. Asserted through the shared builder rather than
        # by composing the helpers by hand, so the row cannot drift from the
        # helpers it is documented to use.
        home_form = f"~{_HOME_PATH_KNOWN_IDENTITY}/elsewhere/sessions"
        row = _sessions_fault_row(home_form, "readdir denied")
        for field in ("subject", "artifact", "message"):
            assert _HOME_PATH_KNOWN_IDENTITY not in row[field], (
                f"the unrootable home form reached {field}: {row[field]!r}"
            )
        # The three fields hold one answer about one path: the identifier rule's
        # answer, which the row narrates and joins on alike. They cannot disagree,
        # because they are built from one call to ``ledger_name``.
        assert row["subject"] == row["artifact"] == "sessions", row
        assert "(sessions) exists but could not be listed" in row["message"], row
