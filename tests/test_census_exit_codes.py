"""One test per exit code the unified census can return, plus lowest-code-wins.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py`` and the runners in ``tests/census_run.py``. The probe's
own reads are pinned in ``tests/test_census_ledger_probe_states.py``, the whole-run
version of the same fault in ``tests/test_census_ordering_faults.py``.
"""

from __future__ import annotations

import json

from _harness import _commit_file, _git, _init_repo
from census_fixtures import (
    _commit_dir_state,
    _ndjson_rows,
    _valid_record,
)
from census_run import _run_census


class TestExitCodes:
    def test_usage_error_exits_two(self):
        import io
        from contextlib import redirect_stderr
        err = io.StringIO()
        with redirect_stderr(err):
            import importlib
            census_mod = importlib.import_module("census")
            rc = census_mod.main(["--now", "not-a-timestamp"])
        assert rc == 2, f"expected exit 2 for invalid --now, got {rc}"

    def test_unknown_check_exits_two(self):
        import io
        from contextlib import redirect_stderr
        err = io.StringIO()
        with redirect_stderr(err):
            import importlib
            census_mod = importlib.import_module("census")
            rc = census_mod.main(["--only", "nonexistent-check"])
        assert rc == 2, f"expected exit 2 for unknown check, got {rc}"

    def test_exit_10_schema_violation(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        bad = _valid_record()
        del bad["id"]  # missing required field
        _commit_file(repo, "noni/decisions/2026-10-01-bad.json", json.dumps(bad, indent=2))
        rc, out, err = _run_census(repo)
        assert rc == 10, f"expected exit 10, got {rc}\nstderr: {err}\nstdout: {out}"

    def test_exit_10_bad_filename(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/bad name.json", json.dumps(_valid_record(), indent=2))
        rc, out, err = _run_census(repo)
        assert rc == 10, f"expected exit 10 for bad filename, got {rc}\nstderr: {err}\nstdout: {out}"

    def test_exit_10_not_valid_json(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-bad.json", "{not valid json")
        rc, out, err = _run_census(repo)
        assert rc == 10, f"expected exit 10, got {rc}\nstderr: {err}\nstdout: {out}"

    def test_exit_12_edited_after_commit(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        # Edit the record after commit (change status)
        rec = _valid_record(status="open")
        (repo / "noni/decisions/2026-10-01-alpha.json").write_text(json.dumps(rec, indent=2))
        rc, out, err = _run_census(repo)
        assert rc == 12, f"expected exit 12, got {rc}\nstderr: {err}\nstdout: {out}"

    def test_exit_12_deleted_uncommitted(self, tmp_path):
        """A committed record deleted from the working tree (deletion not
        yet committed) is reported under the ledger-edited class with the
        deleted reason. The ledger still holds a second, valid record, so
        the ledger-record check stays quiet and 12 is the only fired class."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "noni/decisions/2026-10-02-beta.json",
                      json.dumps(_valid_record("2026-10-02-beta"), indent=2))
        (repo / "noni/decisions/2026-10-01-alpha.json").unlink()
        rc, out, err = _run_census(repo)
        assert rc == 12, f"expected exit 12, got {rc}\nstderr: {err}\nstdout: {out}"
        assert "deleted" in out, f"expected 'deleted' reason in output:\n{out}"

    def test_exit_12_deleted_committed(self, tmp_path):
        """A committed record whose deletion is itself committed is also
        reported (exit 12): the git-history enumeration catches it even
        though the working tree and HEAD agree the file is gone."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "noni/decisions/2026-10-02-beta.json",
                      json.dumps(_valid_record("2026-10-02-beta"), indent=2))
        (repo / "noni/decisions/2026-10-01-alpha.json").unlink()
        _commit_dir_state(repo, "noni/decisions")
        rc, out, err = _run_census(repo)
        assert rc == 12, f"expected exit 12, got {rc}\nstderr: {err}\nstdout: {out}"
        assert "deleted" in out, f"expected 'deleted' reason in output:\n{out}"

    def test_exit_12_renamed_committed(self, tmp_path):
        """A committed record that is renamed (committed on a new path, old
        path gone) is reported under the ledger-edited class with the deleted
        reason: the committed record path is missing from the working tree
        because it was deleted or renamed."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "noni/decisions/2026-10-02-beta.json",
                      json.dumps(_valid_record("2026-10-02-beta"), indent=2))
        (repo / "noni/decisions/2026-10-01-alpha.json").rename(
            repo / "noni/decisions/2026-10-03-alpha-renamed.json"
        )
        _commit_dir_state(repo, "noni/decisions")
        rc, out, err = _run_census(repo)
        assert rc == 12, f"expected exit 12, got {rc}\nstderr: {err}\nstdout: {out}"
        assert "deleted" in out, f"expected 'deleted' reason in output:\n{out}"
        assert "renamed" in out, f"expected 'renamed' in message:\n{out}"

    def test_exit_12_deleted_sole_record_still_reports_deleted(self, tmp_path):
        """Regression: deleting the ONLY committed record must still report
        the ledger-edited deletion, not fall silent because the ledger now
        holds no record.

        The ledger-empty probe must not gate the git-backed integrity checks.
        Emptying the ledger by deleting its last record is exactly the case
        where the deletion needs reporting: the now-recordless directory is a
        ledger-empty warn (issue #33), so the deletion is the run's only fail
        class and the ledger-edited row is still there."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        (repo / "noni/decisions/2026-10-01-alpha.json").unlink()
        rc, out, err = _run_census(repo)
        assert rc == 12, (
            "a deleted sole record still fails the census: the recordless "
            "decisions/ directory is a ledger-empty warn, so the ledger-edited "
            f"deletion is the only fail class: expected exit 12, got {rc}\nstderr: {err}\n{out}"
        )
        assert "deleted" in out, f"expected 'deleted' reason:\n{out}"
        assert "ledger-edited" in out, f"expected a ledger-edited row:\n{out}"

    def test_exit_12_deleted_sole_record_reports_both_rows(self, tmp_path):
        """Same tree: both classes report. The recordless ledger is the
        ledger-empty warn row AND the deletion is the ledger-edited fail
        row — neither silences the other, and the warn row does not hide the
        deletion."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        (repo / "noni/decisions/2026-10-01-alpha.json").unlink()
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 12, (
            f"the only fail class is the deletion (42 is a warn here): got {rc}\nstderr: {err}"
        )
        checks = [r["check"] for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert "ledger-empty" in checks, (
            f"a recordless decisions/ directory is the ledger-empty warn: {checks}"
        )
        assert "ledger-edited" in checks, f"missing ledger-edited row: {checks}"
        assert "ledger-record" not in checks, (
            f"no record is malformed, so the record pass adds no row: {checks}"
        )
        empty = [r for r in _ndjson_rows(out) if r.get("check") == "ledger-empty"][0]
        assert empty["severity"] == "warn" and empty["code"] == 42
        edited = [r for r in _ndjson_rows(out) if r.get("check") == "ledger-edited"]
        assert edited[0]["severity"] == "fail"
        assert edited[0]["code"] == 12
        assert "deleted" in edited[0]["message"]

    def test_exit_12_deleted_sole_record_committed_still_reports(self, tmp_path):
        """The deletion being committed does not hide it even when the ledger
        is left empty: git history, not the working tree, is the source."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        (repo / "noni/decisions/2026-10-01-alpha.json").unlink()
        _commit_dir_state(repo, "noni/decisions")
        rc, out, err = _run_census(repo)
        # The recordless directory is a warn, so the deletion (12) is the code
        # this run reports; the ledger-empty row is present alongside it.
        assert rc == 12, f"expected exit 12 (the deletion), got {rc}\nstderr: {err}\n{out}"
        assert "deleted" in out, f"expected 'deleted' reason:\n{out}"

    def test_unreachable_blob_is_warn_not_fail_without_strict(self, tmp_path, monkeypatch):
        """Regression vs origin/main: a committed record whose committed bytes
        are unreachable (shallow or pruned history, or a timed-out
        ``git cat-file``) is a probe-honesty cannot-verify, NOT a protocol
        violation. The row must carry warn severity and leave the process at
        exit 0 without --strict; only --strict may escalate it.

        ``blob_content_sha1`` is monkeypatched to return None so the case is
        reached deterministically on a tree that does hold the object (a real
        shallow clone would not be reproducible here)."""
        import census

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        monkeypatch.setattr(census.Git, "blob_content_sha1",
                            lambda self, commit, relpath: None)
        rc, out, err = _run_census(repo, json_out=True)
        assert rc == 0, (
            f"an unreachable committed blob must not fail the census: got {rc}"
            f"\nstderr: {err}\nstdout: {out}"
        )
        rows = [r for r in _ndjson_rows(out)
                if r.get("check") == "ledger-edited"
                and r["message"].startswith("cannot verify")]
        assert len(rows) == 1, f"expected one cannot-verify row: {rows}"
        row = rows[0]
        assert row["severity"] == "warn", f"must be warn, not fail: {row}"
        assert row["code"] == 12, f"stays in the ledger-edited class: {row}"
        assert row["subject"] == "2026-10-01-alpha", f"names the record: {row}"
        assert "unreachable" in row["message"], f"message text is kept: {row}"

    def test_unreachable_blob_fails_under_strict(self, tmp_path, monkeypatch):
        """The same row escalates under --strict: a census that cannot read its
        own committed input is not allowed to report clean there."""
        import census

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        monkeypatch.setattr(census.Git, "blob_content_sha1",
                            lambda self, commit, relpath: None)
        rc, out, err = _run_census(repo, "--strict", json_out=True, skip_hygiene=True)
        assert rc == 12, (
            f"expected exit 12 under --strict, got {rc}\nstderr: {err}\nstdout: {out}"
        )
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "ledger-edited"]
        assert len(rows) == 1 and rows[0]["severity"] == "fail", f"row: {rows}"

    def test_genuine_edit_still_fails_without_strict(self, tmp_path):
        """Companion to the cannot-verify pair: the severity fix must not leak
        into the real edit row. Working-tree bytes that differ from the
        committed bytes stay a failure with no --strict."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        (repo / "noni/decisions/2026-10-01-alpha.json").write_text(
            json.dumps(_valid_record(status="open"), indent=2))
        rc, out, err = _run_census(repo, json_out=True)
        assert rc == 12, f"expected exit 12, got {rc}\nstderr: {err}\nstdout: {out}"
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "ledger-edited"]
        assert len(rows) == 1 and rows[0]["severity"] == "fail", f"row: {rows}"

    def test_deleted_on_unmerged_branch_is_not_reported(self, tmp_path):
        """A record added and committed on an unmerged feature branch, never
        merged into the current branch (main), must NOT be reported as deleted
        when the census runs on main: it is not part of HEAD's history."""
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "branch", "-M", "main")
        # Second, committed record on main keeps the ledger non-empty so no
        # other finding fires.
        _commit_file(repo, "noni/decisions/2026-10-02-beta.json",
                      json.dumps(_valid_record("2026-10-02-beta"), indent=2))
        # Record added on an unmerged branch.
        _git(repo, "checkout", "-q", "-b", "feat")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _git(repo, "checkout", "-q", "main")
        rc, out, err = _run_census(repo)
        assert rc == 0, f"expected exit 0 on main, got {rc}\nstderr: {err}\nstdout: {out}"
        assert "deleted" not in out, f"must not report a deletion for an unmerged-branch record:\n{out}"

    def test_never_committed_deleted_is_not_a_finding(self, tmp_path):
        """A record that was never committed and is then deleted is not a
        deletion: there is nothing in history to have been removed. A second,
        committed record keeps the ledger non-empty, so no finding fires at
        all (exit 0) — in particular no deleted finding (exit 12)."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-02-beta.json",
                      json.dumps(_valid_record("2026-10-02-beta"), indent=2))
        path = repo / "noni/decisions/2026-10-01-alpha.json"
        path.write_text(json.dumps(_valid_record(), indent=2))
        path.unlink()
        rc, out, err = _run_census(repo)
        assert rc == 0, f"expected exit 0, got {rc}\nstderr: {err}\nstdout: {out}"
        assert "deleted" not in out, f"must not report a deletion for a never-committed file:\n{out}"

    def test_deleted_record_json_keys(self, tmp_path):
        """In --json mode the deleted-record finding carries the documented
        keys: schema, kind, check, code, severity, subject, artifact,
        message, fix."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "noni/decisions/2026-10-02-beta.json",
                      json.dumps(_valid_record("2026-10-02-beta"), indent=2))
        (repo / "noni/decisions/2026-10-01-alpha.json").unlink()
        rc, out, err = _run_census(repo, "--json", "--skip", "hygiene")
        assert rc == 12, f"expected exit 12, got {rc}\nstderr: {err}"
        rows = _ndjson_rows(out)
        finding = [r for r in rows if r["kind"] == "finding"][0]
        expected = {"schema", "kind", "check", "code", "severity", "subject",
                    "artifact", "message", "fix"}
        assert expected <= set(finding), f"missing keys: {expected - set(finding)}"
        assert finding["check"] == "ledger-edited"
        assert finding["code"] == 12
        assert finding["severity"] == "fail"
        assert "deleted" in finding["message"]
        assert "git checkout" in finding["fix"] or "supersede" in finding["fix"]

    def test_exit_20_dangling_supersedes(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record("2026-10-01-alpha"), indent=2))
        dangling = _valid_record("2026-10-22-dangling", "decided", "2026-10-99-nonexistent")
        _commit_file(repo, "noni/decisions/2026-10-22-dangling.json", json.dumps(dangling, indent=2))
        rc, out, err = _run_census(repo)
        assert rc == 20, f"expected exit 20, got {rc}\nstderr: {err}\nstdout: {out}"

    def test_exit_20_duplicate_supersedes(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-root.json",
                      json.dumps(_valid_record("2026-10-01-root"), indent=2))
        _commit_file(repo, "noni/decisions/2026-10-10-a.json",
                      json.dumps(_valid_record("2026-10-10-a", "decided", "2026-10-01-root"), indent=2))
        _commit_file(repo, "noni/decisions/2026-10-20-b.json",
                      json.dumps(_valid_record("2026-10-20-b", "decided", "2026-10-01-root"), indent=2))
        rc, out, err = _run_census(repo)
        assert rc == 20, f"expected exit 20 for duplicate supersede, got {rc}\nstderr: {err}\nstdout: {out}"
