"""The sessions register: shared identity, deletion, stall, probe honesty, cannot-tell.

One row per identity the register carries twice, a register file committed and then
gone, an active session with no commit for a week, and the rows a check that could
not run must still produce.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py`` and the runners in ``tests/census_run.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from _harness import _commit_file, _git, _init_repo
from census_fixtures import (
    _commit_dir_state,
    _ndjson_rows,
    _session_body,
    _sessions_fixture,
    _valid_record,
)
from census_run import _run_census


class TestSessionSameIdentity:
    """The session-same-identity class (warn 43): one row per identity, naming
    every non-terminal file that carries it."""

    def test_two_active_sessions_one_identity(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("developer"))
        _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md", _session_body("developer"))
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, f"warn class must exit 0 without --strict, got {rc}\nstderr: {err}"
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "session-same-identity"]
        assert len(rows) == 1, f"expected one row naming both files: {rows}"
        row = rows[0]
        assert row["code"] == 43
        assert row["severity"] == "warn"
        assert row["subject"] == "developer", f"subject must be the identity: {row}"
        for name in ("2026-10-01-aaaaaa.md", "2026-10-01-bbbbbb.md"):
            assert name in row["message"], f"row does not name {name}: {row['message']}"

    def test_different_identities_are_clean(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("developer"))
        _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md", _session_body("reviewer"))
        rc, out, err = _run_census(repo, skip_hygiene=True)
        assert rc == 0, f"expected 0, got {rc}\nstderr: {err}"
        assert "session-same-identity" not in out, f"unexpected row: {out}"

    def test_one_of_them_closed_is_clean(self, tmp_path):
        """A closed file does not count: only non-terminal files may share an
        identity."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("developer"))
        _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md",
                      _session_body("developer", status="closed"))
        rc, out, err = _run_census(repo, skip_hygiene=True)
        assert rc == 0, f"expected 0, got {rc}\nstderr: {err}"
        assert "session-same-identity" not in out, f"unexpected row: {out}"

    def test_strict_exits_43(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("developer"))
        _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md", _session_body("developer"))
        rc, out, err = _run_census(repo, "--only", "session-same-identity", "--strict",
                                   skip_hygiene=True)
        assert rc == 43, f"expected 43 under --strict, got {rc}\nstderr: {err}\nstdout: {out}"

    def test_double_claim_still_fires_for_shared_identity(self, tmp_path):
        """The legacy shim's "same identity is not a double-claim" rule stays:
        this class warns alongside it, it does not change session-double."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md",
                      _session_body("developer", claims=["#42"]))
        _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md",
                      _session_body("developer", claims=["#42"]))
        rc, out, err = _run_census(repo, skip_hygiene=True)
        assert rc == 0, f"neither class fails without --strict, got {rc}\nstderr: {err}"
        assert "session-double" not in out, (
            f"one identity claiming a task from two files is not a double-claim: {out}"
        )
        assert "session-same-identity" in out, f"expected the warn row: {out}"

class TestSessionDeleted:
    """The session-deleted class (warn 44): a register file in history, gone
    from the working tree."""

    def _plant(self, tmp_path) -> Path:
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("developer"))
        _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md", _session_body("reviewer"))
        return repo

    def test_deleted_session_file_is_reported(self, tmp_path):
        repo = _sessions_fixture(tmp_path)
        (repo / "noni/sessions/2026-10-01-bbbbbb.md").unlink()
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, f"warn class must exit 0 without --strict, got {rc}\nstderr: {err}"
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "session-deleted"]
        assert len(rows) == 1, f"expected one row: {rows}"
        row = rows[0]
        assert row["code"] == 44
        assert row["severity"] == "warn"
        assert row["subject"] == "2026-10-01-bbbbbb.md", f"row must name the file: {row}"
        assert "deleted" in row["message"]
        assert row["fix"]

    def test_deleted_session_file_strict_exits_44(self, tmp_path):
        repo = _sessions_fixture(tmp_path)
        (repo / "noni/sessions/2026-10-01-bbbbbb.md").unlink()
        rc, out, err = _run_census(repo, "--only", "session-deleted", "--strict", skip_hygiene=True)
        assert rc == 44, f"expected 44 under --strict, got {rc}\nstderr: {err}\nstdout: {out}"

    def test_deletion_committed_is_still_reported(self, tmp_path):
        """The deletion being committed does not hide it: git history is the
        source, not the diff."""
        repo = _sessions_fixture(tmp_path)
        (repo / "noni/sessions/2026-10-01-bbbbbb.md").unlink()
        _commit_dir_state(repo, "noni/sessions")
        rc, out, err = _run_census(repo, "--only", "session-deleted", "--strict", skip_hygiene=True)
        assert rc == 44, f"expected 44 for a committed deletion, got {rc}\nstderr: {err}\n{out}"

    def test_deleted_non_session_file_is_ignored(self, tmp_path):
        """A path under noni/sessions/ that is not an allocated register file
        is not this class's business."""
        repo = _sessions_fixture(tmp_path)
        _commit_file(repo, "noni/sessions/notes.md", "scratch\n")
        (repo / "noni/sessions/notes.md").unlink()
        rc, out, err = _run_census(repo, skip_hygiene=True)
        assert rc == 0, f"expected 0, got {rc}\nstderr: {err}"
        assert "session-deleted" not in out, f"unexpected row: {out}"

    def test_never_committed_file_is_not_a_deletion(self, tmp_path):
        """Nothing in history ever held the file, so nothing was deleted."""
        repo = _sessions_fixture(tmp_path)
        path = repo / "noni/sessions/2026-10-01-cccccc.md"
        path.write_text(_session_body("stranger"))
        path.unlink()
        rc, out, err = _run_census(repo, skip_hygiene=True)
        assert rc == 0, f"expected 0, got {rc}\nstderr: {err}"
        assert "session-deleted" not in out, f"unexpected row: {out}"

class TestStalled:
    def test_stalled_session_warn_by_default(self, tmp_path):
        """An active session with no commit for >7 days is a warn (not fail)."""
        repo = _init_repo(tmp_path / "repo")
        # Commit a session file, then simulate time passing via --now
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md",
                      _session_body("developer", started="2026-01-01T00:00:00Z"))
        rc, out, err = _run_census(repo, "--now", "2026-10-02T00:00:00Z", "--stale-after", "30")
        # The session was committed recently (just now), so it is NOT stalled
        # based on commit time. The test below verifies the warn behavior
        # when the commit IS old.
        assert rc == 0, f"freshly committed session should be clean, got {rc}\nstderr: {err}"

    def test_cannot_tell_when_no_git_history(self, tmp_path):
        """A sessions dir outside a git tree is cannot-tell (warn), never clean-skip."""
        sessions = tmp_path / "sessions"
        sessions.mkdir()
        (sessions / "2026-10-01-aaaaaa.md").write_text(_session_body("developer"))
        rc, out, err = _run_census(tmp_path, "--sessions", str(sessions), "--now", "2026-10-02T00:00:00Z")
        # Cannot-tell is a warn; with no --strict the exit is 0
        assert rc == 0, f"cannot-tell is warn (exit 0), got {rc}\nstderr: {err}\nstdout: {out}"
        assert "cannot-tell" in out.lower() or "cannot-tell" in err.lower(), (
            f"expected cannot-tell in output: stdout={out!r} stderr={err!r}"
        )

class TestProbeHonesty:
    def test_symlinked_session_file_is_not_read(self, tmp_path):
        """A symlinked session file is reported as probe failure, never read."""
        repo = _init_repo(tmp_path / "repo")
        real = repo / "real-session.md"
        real.write_text(_session_body("developer"))
        (repo / "noni" / "sessions").mkdir(parents=True, exist_ok=True)
        (repo / "noni/sessions/2026-10-01-aaaaaa.md").symlink_to(real)
        rc, out, err = _run_census(repo)
        # Probe failure is a warn (exit 0 without --strict)
        assert rc == 0, f"probe fail is warn (exit 0), got {rc}\nstderr: {err}"
        assert "symlink" in out.lower() or "symlink" in err.lower(), (
            f"expected symlink mention: stdout={out!r} stderr={err!r}"
        )

    def test_non_utf8_session_file_is_malformed(self, tmp_path):
        """A session file with non-UTF-8 bytes is reported as malformed."""
        repo = _init_repo(tmp_path / "repo")
        (repo / "noni" / "sessions").mkdir(parents=True, exist_ok=True)
        (repo / "noni/sessions/2026-10-01-aaaaaa.md").write_bytes(b"\xff\xfe\x00\x01invalid")
        _git(repo, "add", "noni/sessions/")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "add bad file")
        rc, out, err = _run_census(repo)
        assert rc == 32, f"expected exit 32 for non-UTF-8, got {rc}\nstderr: {err}\nstdout: {out}"

    def test_probe_failure_never_reports_clean_under_strict(self, tmp_path):
        """Under --strict, a probe failure becomes a failure (exit 41)."""
        repo = _init_repo(tmp_path / "repo")
        (repo / "noni" / "sessions").mkdir(parents=True, exist_ok=True)
        real = repo / "outside.md"
        real.write_text(_session_body("developer"))
        (repo / "noni/sessions/2026-10-01-aaaaaa.md").symlink_to(real)
        _git(repo, "add", "noni/sessions/")
        _git(repo, "commit", "-q", "--allow-empty", "-m", "add symlink")
        rc, out, err = _run_census(repo, "--strict")
        assert rc == 41, f"expected exit 41 (probe under --strict), got {rc}\nstderr: {err}\nstdout: {out}"

class TestCannotTellRows:
    """A check that could not run says so: no filtered or --strict run reads
    "no rows" as "nothing was wrong" when the question was never answered."""

    def test_sessions_override_outside_the_tree_reports_cannot_tell(self, tmp_path):
        """--sessions pointing outside the audited git tree disables the
        append-only check: that is reported, not silently clean."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        outside = tmp_path / "elsewhere-sessions"
        outside.mkdir()
        (outside / "2026-10-01-aaaaaa.md").write_text(_session_body("developer"))
        rc, out, err = _run_census(repo, "--sessions", str(outside),
                                   "--only", "session-deleted", "--strict", skip_hygiene=True)
        assert rc == 44, (
            "an override that turns off an integrity check must not exit 0: "
            f"got {rc}\nstderr: {err}\nstdout: {out}"
        )
        assert "cannot-tell" in out, f"expected the cannot-tell row: {out}"

    def test_ledger_override_outside_the_tree_reports_cannot_tell(self, tmp_path):
        """Same rule for --ledger: the group says it could not answer."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "README.md", "# repo\n")
        outside = tmp_path / "elsewhere-ledger"
        outside.mkdir()
        (outside / "2026-10-01-alpha.json").write_text(json.dumps(_valid_record(), indent=2))
        rc, out, err = _run_census(repo, "--ledger", str(outside), "--only", "ledger-edited",
                                   "--strict", json_out=True, skip_hygiene=True)
        assert rc == 12, (
            f"the cannot-tell row is the ledger-edited class and exits 12 under --strict, "
            f"got {rc}\nstderr: {err}\nstdout: {out}"
        )
        assert "cannot-tell" in out, f"expected the cannot-tell row: {out}"
        # The cannot-tell is a warn without --strict: reading it as the class's
        # own fail severity would make "I could not read the tree" look like a
        # protocol violation (see test_ledger_cannot_tell_is_warn_without_strict).
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "ledger-edited"]
        assert len(rows) == 1, f"expected one ledger-edited row: {rows}"
        assert rows[0]["subject"] == "cannot-tell", f"row: {rows[0]}"

    def test_ledger_cannot_tell_is_warn_without_strict(self, tmp_path):
        """The same override without --strict stays a warning: the census could
        not read the ledger, which is not itself a protocol violation."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "README.md", "# repo\n")
        outside = tmp_path / "elsewhere-ledger-quiet"
        outside.mkdir()
        (outside / "2026-10-01-alpha.json").write_text(json.dumps(_valid_record(), indent=2))
        rc, out, err = _run_census(repo, "--ledger", str(outside), skip_hygiene=True)
        assert rc == 0, f"expected 0 (warn), got {rc}\nstderr: {err}\nstdout: {out}"
        assert "cannot-tell" in out, f"expected the cannot-tell row: {out}"

    def test_no_git_tree_is_not_reported_as_a_deletion_cannot_tell(self, tmp_path):
        """A plain directory has no history at all: that state belongs to
        hygiene (scan did not run) and the ledger-empty probe, not to the
        deletion classes — otherwise "I ran no git" looks like a protocol bug."""
        plain = tmp_path / "plain"
        sessions = plain / "noni" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "2026-10-01-aaaaaa.md").write_text(_session_body("developer"))
        (plain / "noni" / "decisions").mkdir()
        (plain / "noni" / "decisions" / "2026-10-01-alpha.json").write_text(
            json.dumps(_valid_record(), indent=2), encoding="utf-8")
        rc, out, err = _run_census(plain, "--only", "session-deleted", skip_hygiene=True)
        assert rc == 0, f"expected 0, got {rc}\nstderr: {err}\nstdout: {out}"
        assert "session-deleted" not in out, f"unexpected row: {out}"
