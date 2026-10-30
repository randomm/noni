"""The hygiene class's four states are machine-distinguishable: subject, not prose.

A caller can tell which half of the scan a row is about without reading a
sentence, and a public_safety that is not the one the census loaded is refused.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py``, the runners in ``tests/census_run.py`` and the
deny-list planting in ``tests/census_denylist.py``.
"""

from __future__ import annotations

import json
import sys

from _harness import _commit_file, _home_path_violation, _init_repo, _secret_violation
from census_denylist import _clear_denylist, _with_denylist
from census_fixtures import _ndjson_rows, _valid_record
from census_hygiene_target import _hygiene_target
from census_run import _run_census

_SECRET = _secret_violation()

class TestHygieneRowContract:
    """The hygiene class's four states are machine-distinguishable: subject, not
    prose, tells a caller which half of the scan a row is about."""

    def test_subjects_are_the_discriminator(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "note.md", "token " + _SECRET + "\n")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            _rc, out, _err = _run_census(repo, json_out=True)
        finally:
            _clear_denylist()
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
        assert [r["subject"] for r in rows] == ["note.md:1"], (
            f"a violation row's subject is path:line: {rows}"
        )

    def test_not_run_and_denylist_rows_use_their_own_subjects(self, tmp_path):
        """`hygiene scan` and `deny-list` are the documented subject values for
        the two probe-failure states, so a caller can ask "did the scan run?"
        without matching English."""
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "note.txt").write_text("hello\n", encoding="utf-8")
        _rc, out, _err = _run_census(plain, json_out=True)
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
        assert [r["subject"] for r in rows] == ["hygiene scan"], f"rows: {rows}"

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _rc, out, _err = _run_census(repo, json_out=True)
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
        assert [r["subject"] for r in rows] == ["deny-list"], f"rows: {rows}"

    def test_exception_from_the_scan_reports_not_run_and_never_crashes(self, tmp_path, monkeypatch):
        """Any exception type from the scan — not only the ones the class used
        to name — becomes the not-run row. The class promises never to take the
        census down, and a stray ValueError used to discard every finding this
        run had already collected."""
        public_safety = _hygiene_target()

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/.gitkeep", "")
        monkeypatch.setattr(public_safety, "load_denylist",
                            lambda: (_ for _ in ()).throw(ValueError("deny-list store unreachable")))
        rc, out, err = _run_census(repo, json_out=True)
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
        # A scan that cannot run must not lift the exit: this tree's only
        # finding is the recordless ledger's warn, so the run stays at 0 and
        # the failure of the scan is contained in the hygiene class alone.
        assert rc == 0, f"a scan that cannot run must not lift the exit, got {rc}\n{err}"
        assert any(r["subject"] == "hygiene scan" and "did not run" in r["message"] for r in rows), (
            f"expected the not-run row: {rows}"
        )
        # Findings from the other classes are still in the run: an
        # un-caught exception would have taken the whole census down instead,
        # and the summary's own counts are the proof that they were collected.
        # The ledger here is a decisions/ directory with no record: its row is
        # the ledger-empty warn.
        summary = [r for r in _ndjson_rows(out) if r.get("kind") == "summary"][0]
        assert summary["counts"].get("hygiene") == 1, f"summary: {summary}"
        assert summary["counts"].get("ledger-empty"), (
            f"the run collected no ledger row, so the failure was not contained "
            f"inside the hygiene class: {out}"
        )

    def test_not_run_row_never_prints_an_absolute_path(self, tmp_path, monkeypatch):
        """The exception text is bounded and stripped of host paths: the census
        promises never to print a machine-local absolute path, and public_safety's
        denial messages carry them."""
        public_safety = _hygiene_target()

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        leaked = _home_path_violation()
        monkeypatch.setattr(
            public_safety, "load_denylist",
            lambda: (_ for _ in ()).throw(OSError(f"git ls-files failed: {leaked}")))
        _rc, out, _err = _run_census(repo, json_out=True)
        rows = [r for r in _ndjson_rows(out)
                if r.get("check") == "hygiene" and r["subject"] == "hygiene scan"]
        assert len(rows) == 1, f"rows: {rows}"
        assert leaked not in rows[0]["message"], (
            f"the row leaked a machine-local absolute path: {rows[0]['message']}"
        )
        assert len(rows[0]["message"]) < 400, f"message unbounded: {rows[0]['message']}"


    def test_checker_is_loaded_into_a_census_owned_slot(self, tmp_path):
        """The census loads its checker under its own sys.modules key and never
        writes the shared "public_safety" name.

        The census is a read-only arbiter: replacing a host application's module
        (or a second census instance's) while it runs its scan is a side effect
        it must not have. The unqualified key was also the substitution route —
        a module registered there from a sibling sys.path entry was trusted on
        the strength of the key alone.
        """
        import census

        # A fresh load: the census's own slot may already hold the checker from an
        # earlier test, and this one is about what the *loader* registers.
        sys.modules.pop(census.CENSUS_PS_MODULE_KEY, None)
        module = census._load_public_safety()
        assert module is not None, "the package's public_safety must be loadable"
        assert census.CENSUS_PS_MODULE_KEY == "noni_census_public_safety"
        assert sys.modules.get(census.CENSUS_PS_MODULE_KEY) is module
        # The census's own loader never registers under the shared name; it hands
        # back the package module, which carries the package-qualified name.
        assert module.__name__ == "noni.public_safety"

    def test_module_from_another_tree_is_not_trusted(self, tmp_path, monkeypatch):
        """A public_safety whose __file__ is not SCRIPTS_DIR/public_safety.py is
        refused, not executed: the census re-verifies the resolved path on every
        call rather than trusting the registry entry."""
        import census

        class _Foreign:
            __file__ = str(tmp_path / "public_safety.py")

            @staticmethod
            def scrub_tracked_files(repo):
                raise AssertionError("the foreign checker must never be executed")

            @staticmethod
            def _denylist_active(denylist):
                return True

            @staticmethod
            def load_denylist():
                return None

        monkeypatch.setitem(sys.modules, census.CENSUS_PS_MODULE_KEY, _Foreign())
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        # The foreign entry is rejected and the real file loaded in its place:
        # the run reports the deny-list half (the real checker, no deny-list),
        # never an all-clear from the impostor's active=True.
        _rc, out, err = _run_census(repo, json_out=True)
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
        assert [r["subject"] for r in rows] == ["deny-list"], f"rows: {rows}"
        # The impostor's _denylist_active() -> True would have silenced this row
        # entirely, i.e. reported a hygiene-clean guarantee on a scan that never
        # ran; the real checker's absent deny-list is what the row must name.
        assert "absent" in rows[0]["message"], f"row: {rows[0]}"

    def test_object_under_the_bare_public_safety_alias_is_not_trusted(self, monkeypatch):
        """The bare "public_safety" sys.modules entry is not a trust anchor.

        The bare alias is a convenience the test harness registers for tests that
        were written against the old flat scripts/ layout; a foreign object
        registered under that same name is a substitution route, so the checker
        the census trusts is the package module captured once — identified by
        its own ``__name__`` — and nothing reached through the bare alias.
        """
        import types

        import census

        import noni.public_safety as package_public_safety

        impostor = types.ModuleType("public_safety")
        impostor.scrub_tracked_files = lambda repo: []
        impostor._denylist_active = lambda denylist: True
        impostor.load_denylist = lambda: None
        monkeypatch.setitem(sys.modules, "public_safety", impostor)
        sys.modules.pop(census.CENSUS_PS_MODULE_KEY, None)
        module = census._load_public_safety()
        assert module is not impostor, (
            "the census trusted an object registered under the bare alias"
        )
        assert module is package_public_safety

    def test_non_module_object_with_the_right_attributes_is_not_trusted(self, monkeypatch):
        """Carrying the three members is not enough: the object must be a module
        whose ``__name__`` is the package's own."""
        import census

        import noni.public_safety as package_public_safety

        class _LooksLikeTheChecker:
            __name__ = "noni.public_safety"

            @staticmethod
            def scrub_tracked_files(repo):
                raise AssertionError("the lookalike must never be executed")

            @staticmethod
            def _denylist_active(denylist):
                return True

            @staticmethod
            def load_denylist():
                return None

        lookalike = _LooksLikeTheChecker()
        monkeypatch.setitem(sys.modules, census.CENSUS_PS_MODULE_KEY, lookalike)
        assert census._trusted_public_safety(lookalike) is False
        assert census._load_public_safety() is package_public_safety

        # A module object that is not the package's checker: right type, wrong
        # __name__, and registered nowhere the census consults.
        import types

        wrong_name = types.ModuleType("noni.public_safety")
        wrong_name.scrub_tracked_files = lambda repo: []
        wrong_name._denylist_active = lambda denylist: True
        wrong_name.load_denylist = lambda: None
        monkeypatch.setitem(sys.modules, census.CENSUS_PS_MODULE_KEY, wrong_name)
        assert census._trusted_public_safety(wrong_name) is False
        assert census._load_public_safety() is package_public_safety

    def test_the_package_checker_is_trusted(self):
        """The positive case of the same predicate, so the two tests above cannot
        be satisfied by a predicate that simply refuses everything."""
        import census

        import noni.public_safety as package_public_safety

        assert census._trusted_public_safety(package_public_safety) is True
