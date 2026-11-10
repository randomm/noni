"""The hygiene class's four states are machine-distinguishable: subject, not prose.

A caller can tell which half of the scan a row is about without reading a
sentence, and a public_safety that is not the one the census loaded is refused.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py``, the runners in ``tests/census_run.py`` and the
deny-list planting in ``tests/census_denylist.py``.

The not-run row has two arms, and they are told apart by what the scan raised
(``src/noni/census_hygiene.py``, ``check_hygiene``): a filesystem fault is
rendered by ``census_text.fault_text``, which reads the exception's class and
its ``strerror`` and never the filename it failed on, and anything else keeps
its class and its own message through the census's scrub-and-clip. The two
arms are tested apart because the text they may carry is different in kind:
one is a location the reporter must not have at all, the other is the reason
the reporter exists to print.
"""

from __future__ import annotations

import json
import sys

from _harness import (
    _commit_file,
    _home_path_violation,
    _init_repo,
    _permission_fault_guard,
    _secret_violation,
)
from census_denylist import _clear_denylist, _with_denylist
from census_fixtures import _ndjson_rows, _valid_record
from census_hygiene_target import _hygiene_target
from census_run import _run_census

_SECRET = _secret_violation()


def _not_run_message(stdout: str) -> str:
    """The single not-run row's message of a --json run.

    Fails loudly rather than returning a default: a run that produced no not-run
    row is the bug, and a caller that compared against ``""`` would read it as a
    message that simply lacked the expected words.
    """
    rows = [r for r in _ndjson_rows(stdout)
            if r.get("check") == "hygiene" and r["subject"] == "hygiene scan"]
    assert len(rows) == 1, f"expected exactly one not-run row: {rows}"
    return rows[0]["message"]

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

    def test_not_run_row_of_an_errno_fault_keeps_the_words_and_loses_the_path(
        self, tmp_path, monkeypatch
    ):
        """An ``OSError`` carrying an errno pair keeps its ``strerror`` and loses
        its filename: the words say what failed, and the path is the location no
        row may print.

        ``str(OSError)`` mixes the two in one string, so the row is built from the
        structured fields instead (``census_text.fault_text``) rather than scrubbed
        after the fact: the shapes a host path takes are not enumerable, and the
        scrubber is a net, not the thing standing between a directory and a
        published report. The filename below is deliberately a shape that net has
        historically lost (a non-ASCII component and one holding a space), built
        at runtime so this file carries no host path of its own.
        """
        public_safety = _hygiene_target()

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/.gitkeep", "")
        host = "/home/someone/\u00fcn\u00ef c\u00f6de/my dir/denylist"
        monkeypatch.setattr(
            public_safety, "scrub_tracked_files",
            lambda _repo: (_ for _ in ()).throw(OSError(13, "Permission denied", host)))
        _rc, out, _err = _run_census(repo, json_out=True)
        rows = [r for r in _ndjson_rows(out)
                if r.get("check") == "hygiene" and r["subject"] == "hygiene scan"]
        assert len(rows) == 1, f"rows: {rows}"
        message = rows[0]["message"]
        for part in ("someone", "\u00fcn\u00ef", "c\u00f6de", "my dir", "denylist"):
            assert part not in message, f"filename part leaked into the row: {part!r} in {message!r}"
        # The words the row exists to print survive: a not-run row that named no
        # reason would read the same as any other scan that did not run.
        assert "Permission denied" in message, message
        assert "PermissionError" in message, message
        assert "hygiene scan did not run" in message, message
        assert len(message) < 400, f"message unbounded: {message}"

    def test_not_run_row_keeps_the_reason_of_a_non_oserror(self, tmp_path, monkeypatch):
        """The other arm: a fault that is not a filesystem fault keeps its own
        message, because the reason it carries IS the finding.

        ``public_safety`` raises ``RuntimeError(f"git ls-files failed: …")`` for a
        scan whose ``git ls-files`` did not come back, and a row reduced to the
        class name would tell the operator only that something failed. The text
        is foreign, so it still goes through the scrub-and-clip net: the reason
        stays and any host path inside it does not.
        """
        public_safety = _hygiene_target()

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/.gitkeep", "")
        monkeypatch.setattr(
            public_safety, "scrub_tracked_files",
            lambda _repo: (_ for _ in ()).throw(
                RuntimeError("git ls-files failed: " + _home_path_violation())))
        _rc, out, _err = _run_census(repo, json_out=True)
        rows = [r for r in _ndjson_rows(out)
                if r.get("check") == "hygiene" and r["subject"] == "hygiene scan"]
        assert len(rows) == 1, f"rows: {rows}"
        message = rows[0]["message"]
        assert "git ls-files failed" in message, (
            f"the non-OSError arm dropped the reason: {message!r}")
        assert _home_path_violation() not in message, f"host path leaked: {message!r}"
        assert "RuntimeError" in message, message
        assert len(message) < 400, f"message unbounded: {message}"

    def test_the_two_not_run_arms_are_not_swapped(self, tmp_path, monkeypatch):
        """The two arms are distinguished by the exception's type, not by which
        message happened to be shorter.

        One planted fault per arm, and each is asserted against the other's
        behaviour: a scan fault that rendered its filename is the leak, and a
        foreign message that was reduced to a class name lost the reason. Either
        half swapped would let the other look correct in isolation.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/.gitkeep", "")
        target = _hygiene_target()
        leaked = "/home/someone/\u00fcn\u00ef c\u00f6de/my dir/denylist"

        monkeypatch.setattr(
            target, "scrub_tracked_files",
            lambda _repo: (_ for _ in ()).throw(OSError(13, "Permission denied", leaked)))
        _rc, out, _err = _run_census(repo, json_out=True)
        os_message = _not_run_message(out)
        assert "Permission denied" in os_message and leaked.split("/")[3] not in os_message, (
            f"the OSError arm printed the wrong half: {os_message!r}")

        monkeypatch.setattr(
            target, "scrub_tracked_files",
            lambda _repo: (_ for _ in ()).throw(ValueError("deny-list store unreachable")))
        _rc, out, _err = _run_census(repo, json_out=True)
        other_message = _not_run_message(out)
        assert "deny-list store unreachable" in other_message, (
            f"the non-OSError arm dropped the reason: {other_message!r}")
        assert "Permission denied" not in other_message, other_message

    def test_not_run_row_naming_is_stable_for_a_bare_errno_and_a_plain_message(
        self, tmp_path, monkeypatch
    ):
        """The two ``OSError`` shapes that carry no words and no path still name
        the fault by its class, and stay inside the row bound.

        ``OSError(5)`` renders itself as ``[Errno 5] None`` and ``OSError()`` as
        the empty string, so a row built from ``str(e)`` said "did not run: 5" or
        "did not run:" and nothing else. Built from the fields, the first is
        named by its class and the second keeps the sentence it was raised with
        (there is no filename in it to lose).
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/.gitkeep", "")
        target = _hygiene_target()

        monkeypatch.setattr(target, "scrub_tracked_files",
                            lambda _repo: (_ for _ in ()).throw(OSError(5)))
        _rc, out, _err = _run_census(repo, json_out=True)
        message = _not_run_message(out)
        assert "OSError" in message, message
        assert "did not run" in message, message
        assert "None" not in message, f"an empty strerror rendered as None: {message!r}"

        monkeypatch.setattr(target, "scrub_tracked_files",
                            lambda _repo: (_ for _ in ()).throw(OSError("input/output error")))
        _rc, out, _err = _run_census(repo, json_out=True)
        message = _not_run_message(out)
        assert "input/output error" in message, message
        assert len(message) < 400, f"message unbounded: {message}"

    def test_not_run_row_holds_its_shape_whatever_the_fault_carries(
        self, tmp_path, monkeypatch
    ):
        """The row's contract is fixed for every fault shape the scan can raise:
        the exact ``hygiene scan did not run`` substring, the checker in the
        hygiene artifact namespace, and warn severity.

        The three rows above pin one shape each; this one sweeps them, because the
        guarantee is about the row and not about any single exception. The guard
        builds each fault inside the raise, so the shape a handler leaves behind
        cannot leak into the next one.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/.gitkeep", "")
        target = _hygiene_target()
        leaked = "/home/someone/\u00fcn\u00ef c\u00f6de/my dir/denylist"

        faults = [_permission_fault_guard(repo, text="readdir denied"),
                  _permission_fault_guard(
                      repo, text="Permission denied - input/output error",
                      filename=leaked)]
        for guard in faults:
            def raise_from_guard(_repo, _guard=guard):
                # Drive the guard's own raise: the fault it builds is the fixture.
                _guard(repo)
                raise AssertionError("the guard did not fault its target")

            monkeypatch.setattr(target, "scrub_tracked_files", raise_from_guard)
            _rc, out, _err = _run_census(repo, json_out=True)
            rows = [r for r in _ndjson_rows(out)
                    if r.get("check") == "hygiene" and r["subject"] == "hygiene scan"]
            assert len(rows) == 1, f"rows: {rows}"
            row = rows[0]
            assert "hygiene scan did not run" in row["message"], row["message"]
            assert row["artifact"] == "noni/public_safety.py", row
            assert row["severity"] == "warn", row
            assert leaked.split("/")[3] not in row["message"], row["message"]
            assert len(row["message"]) < 400, row["message"]


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
