"""The ledger-empty class: the states where no decision record can be read.

One row per run in each state (absent, empty, not a directory, symlink, ok), the
state words as a closed vocabulary owned by one table, and a whole committed
``decisions/`` directory that no longer exists.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py`` and the runners in ``tests/census_run.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from _harness import _commit_file, _init_repo
from census_fixtures import _ndjson_rows, _session_body, _valid_record
from census_probe_doubles import _UnreadableGit
from census_run import _run_census


class TestLedgerEmpty:
    """The ledger-empty class (warn 42): one row per run in the states where
    no decision record can be read, each state carrying its own message word,
    exit 0 without --strict and 42 with it. The class only ADDS rows — it never
    softens a malformed-record ledger-record failure. Symlinks are reported,
    never followed."""

    def _assert_one_row(self, repo: Path, state_word: str) -> None:
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, f"ledger-empty is warn: expected exit 0, got {rc}\nstderr: {err}"
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert len(rows) == 1, f"expected exactly one row for state {state_word}: {rows}"
        row = rows[0]
        assert row["check"] == "ledger-empty", f"expected ledger-empty: {row}"
        assert row["code"] == 42
        assert row["severity"] == "warn"
        assert state_word in row["message"], (
            f"expected the state word {state_word!r} in: {row['message']}"
        )
        assert row["fix"], "the fix hint must be present in --json rows too"

        rc_strict, _out, err = _run_census(repo, "--only", "ledger-empty", "--strict",
                                            skip_hygiene=True)
        assert rc_strict == 42, f"expected 42 under --strict, got {rc_strict}\nstderr: {err}"

    def test_no_noni_dir_reports_absent(self, tmp_path):
        """No noni/ at all: exactly one ledger-empty row saying 'absent'."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "README.md", "# repo\n")
        self._assert_one_row(repo, "absent")

    def test_noni_present_without_decisions_reports_empty(self, tmp_path):
        """noni/ committed with no decisions/ directory: the row says 'empty'.

        'empty' names a tree with no record to arbitrate, so this tree and the
        recordless decisions/ directory of
        TestClean.test_recordless_ledger_dir_is_a_ledger_empty_warn carry the
        same state word. The register side is clean, so the ledger-empty row is
        the run's only finding.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/README.md", "noni lives here\n")
        self._assert_one_row(repo, "empty")

    def test_recordless_ledger_dir_reports_ledger_empty(self, tmp_path):
        """Operator decision (issue #33): a decisions/ directory that exists and
        holds no *.json record is the ledger-empty 'empty' warn, not a
        ledger-record failure — a freshly attached project must census clean.

        The row is the run's only finding, carries the root-relative ledger
        path (never an absolute path) and the wording of the 'empty' state, and
        no ledger-record row is produced."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/.gitkeep", "")
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, f"a recordless ledger is a warn: expected 0, got {rc}\nstderr: {err}"
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert [r["check"] for r in rows] == ["ledger-empty"], (
            f"expected only the ledger-empty row: {rows}"
        )
        row = rows[0]
        assert row["code"] == 42 and row["severity"] == "warn", f"row: {row}"
        assert "(empty)" in row["message"], f"expected the state word: {row['message']}"
        assert "no *.json record" in row["message"], (
            f"the row must name the missing record: {row['message']}"
        )
        assert row["subject"] == row["artifact"] == "noni/decisions", (
            f"the row names the ledger path relative to the repo root: {row}"
        )
        assert not row["subject"].startswith("/"), f"absolute path in row: {row}"

        rc_strict, _out, err = _run_census(repo, "--only", "ledger-empty", "--strict",
                                            skip_hygiene=True)
        assert rc_strict == 42, f"expected 42 under --strict, got {rc_strict}\nstderr: {err}"

    def test_recordless_ledger_without_git_answers_says_the_deletion_check_could_not_run(
        self, tmp_path, monkeypatch
    ):
        """Probe honesty (issue #33 review): a recordless decisions/ directory
        whose git history the census could not read must not read as a plain
        "empty" warn.

        With this PR the deletion check is the ONLY signal that committed
        records were deleted, so when it cannot run the run must say so: the
        ledger-empty row plus a ledger-edited cannot-tell row, warn by default
        (exit 0) and promoted to exit 12 under --strict, like every other
        cannot-tell row."""
        import census

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/.gitkeep", "")
        monkeypatch.setattr(census, "Git", lambda top: _UnreadableGit())
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, (
            f"the cannot-tell row is a warn: expected exit 0, got {rc}\nstderr: {err}\n{out}"
        )
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert [r["check"] for r in rows] == ["ledger-edited", "ledger-empty"], (
            f"expected the ledger-empty row plus the cannot-tell row: {rows}"
        )
        empty = [r for r in rows if r["check"] == "ledger-empty"][0]
        assert empty["severity"] == "warn" and empty["code"] == 42
        assert "(empty)" in empty["message"], f"state word kept: {empty['message']}"
        row = [r for r in rows if r["check"] == "ledger-edited"][0]
        assert row["subject"] == "cannot-tell", f"row: {row}"
        assert row["code"] == 12, f"stays in the ledger-edited class: {row}"
        assert row["severity"] == "warn", f"cannot-tell is a warn: {row}"
        assert "could not run" in row["message"], (
            f"the row must say the deletion check could not run: {row['message']}"
        )

        rc_strict, out_strict, err = _run_census(repo, "--strict", skip_hygiene=True)
        assert rc_strict == 12, (
            f"--strict escalates the cannot-tell to ledger-edited's code, got {rc_strict}"
            f"\nstderr: {err}\n{out_strict}"
        )

    def test_recordless_ledger_in_a_plain_directory_reports_the_cannot_tell_too(
        self, tmp_path
    ):
        """The same finding in a genuinely non-git directory: there is no
        history anywhere, so the deletion question is just as unanswered and
        the row must still appear (the other no-git trees of this class carry
        states the probe itself answers, not 'empty' with a directory present)."""
        plain = tmp_path / "plain"
        (plain / "noni" / "decisions").mkdir(parents=True)
        rc, out, err = _run_census(plain, json_out=True, skip_hygiene=True)
        assert rc == 0, f"expected exit 0, got {rc}\nstderr: {err}\n{out}"
        checks = [r["check"] for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert sorted(checks) == ["ledger-edited", "ledger-empty"], f"rows: {checks}"

    def test_recordless_ledger_in_a_git_repo_with_no_record_history_is_just_the_warn(
        self, tmp_path
    ):
        """The counterpart: where git did answer, a recordless decisions/
        directory that history never held a record for is exactly the
        ledger-empty warn — no cannot-tell row, since the deletion question was
        answered (nothing was ever added, so nothing was deleted)."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "README.md", "# repo\n")
        _commit_file(repo, "noni/decisions/.gitkeep", "")
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, f"expected exit 0, got {rc}\nstderr: {err}\n{out}"
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert [r["check"] for r in rows] == ["ledger-empty"], (
            f"expected only the ledger-empty row: {rows}"
        )
        assert "(empty)" in rows[0]["message"], f"state word: {rows[0]['message']}"

    def test_noni_not_a_directory_reports_not_a_directory(self, tmp_path):
        """noni/ committed as a plain file: the ledger path is 'not a directory'."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "README.md", "# repo\n")
        _commit_file(repo, "noni", "i am a file, not a directory\n")
        self._assert_one_row(repo, "not a directory")
    def test_noni_symlink_is_reported_never_followed(self, tmp_path):
        """noni/ as a symlink is its own state: reported as 'symlink' and never
        read through (the probe-honesty rule)."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "README.md", "# repo\n")
        real = repo / "elsewhere"
        real.mkdir()
        # Seed the target with a record: if the census followed the link it
        # would find one and report no ledger-empty row at all.
        (real / "decisions").mkdir()
        (real / "decisions" / "2026-10-01-alpha.json").write_text(
            json.dumps(_valid_record(), indent=2), encoding="utf-8"
        )
        (repo / "noni").symlink_to(real)
        self._assert_one_row(repo, "symlink")

    def test_sessions_present_without_ledger_is_still_ledger_empty(self, tmp_path):
        """The two layers stay independent: sessions/ present and decisions/
        absent is one ledger-empty row and no ledger-record failure."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("developer"))
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, f"expected 0, got {rc}\nstderr: {err}"
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert [r["check"] for r in rows] == ["ledger-empty"], f"unexpected rows: {rows}"

    def test_ledger_with_a_record_is_silent(self, tmp_path):
        """A ledger that holds a valid record emits no ledger-empty row."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, f"expected 0, got {rc}\nstderr: {err}"
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert rows == [], f"expected no findings: {rows}"
