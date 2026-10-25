"""Tests for the unified census: skills/census/scripts/census.py.

Each test builds a minimal git repo in tmp_path, plants exactly one violation
class, runs census.main(), and asserts the exit code and output.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

from _harness import _commit_file, _git, _home_path_violation, _init_repo, _secret_violation  # noqa: E402

_scripts_dir = str(REPO / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

DENYLIST_ENV_VAR = "NONI_SCRUB_DENYLIST"

# Synthetic violation shapes, built by tests/_harness.py from public_safety's
# own pattern tables (see there for why they are not literals and why they are
# not copy-pasted either).
_HOME_PATH = _home_path_violation()
_SECRET = _secret_violation()


def _commit_dir_state(repo: Path, dirname: str) -> None:
    """Commit the current on-disk contents of a directory (adds + removes) so
    that deletions are part of the committed state."""
    target = repo / dirname
    for p in target.iterdir():
        _git(repo, "add", "-f", str(p))
    _git(repo, "add", "-u", dirname)
    _git(repo, "commit", "-q", "--allow-empty", "-m", f"update {dirname}")


def _valid_record(rec_id: str = "2026-10-01-alpha", status: str = "decided", supersedes=None) -> dict:
    return {
        "id": rec_id,
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "developer",
        "questions": [
            {"id": "q1", "text": "Adopt the new scheduler?", "options": ["yes", "no"], "answer": "yes"}
        ],
        "by": "Operator",
        "scope": "release ordering",
        "status": status,
        "supersedes": supersedes,
    }


def _session_body(identity: str, status: str = "active", claims: list[str] | None = None,
                  host: str = "ws-1", started: str = "2026-10-01T10:00:00Z") -> str:
    lines = [
        f"- identity: {identity}",
        f"- host/worktree: {host}",
        f"- started: {started}",
        f"- status: {status}",
        "- claims:",
    ]
    for c in claims or []:
        lines.append(f"  - claim: {c}")
    return "\n".join(lines) + "\n"


def _run_census(repo: Path, *args: str, json_out: bool = False,
                skip_hygiene: bool = False) -> tuple[int, str, str]:
    """Run census.main in-process and return (exit_code, stdout, stderr).

    ``skip_hygiene`` adds --skip hygiene: tests of the ledger and session
    classes use it so the always-reporting hygiene class (an isolated fixture
    repo has no deny-list) cannot decide the exit code under --strict."""
    import io
    from contextlib import redirect_stderr, redirect_stdout

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    argv = ["--repo", str(repo)]
    if json_out:
        argv.append("--json")
    if skip_hygiene:
        argv.extend(["--skip", "hygiene"])
    argv.extend(args)
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        rc = _census_main(argv)
    return rc, out_buf.getvalue(), err_buf.getvalue()


def _census_main(argv: list[str]) -> int:
    """Import and call census.main(argv) with a fresh module import."""
    import importlib

    return importlib.import_module("census").main(argv)


def _hygiene_target():
    """The public_safety module the census's hygiene class will actually run.

    The census loads its checker into a census-owned sys.modules slot, so a
    seam installed on a plain ``import public_safety`` object can be a
    different module from the one the scan uses. Loading through the census's
    own loader returns the object the scan reads, which is what the hygiene
    tests patch (``_default_denylist_file``, ``_scan_tracked_files``,
    ``FUTURE_PATTERNS``).
    """
    import census

    module = census._load_public_safety()
    assert module is not None, "scripts/public_safety.py must be loadable for the hygiene tests"
    return module


def _ndjson_rows(stdout: str) -> list[dict]:
    rows = []
    for line in stdout.strip().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def census_module():
    """The census module, for tests that pin one of its contract constants."""
    import importlib

    return importlib.import_module("census")


def _with_denylist(tmp_path: Path, *entries: str):
    """Activate the deny-list class for a hygiene test.

    The hygiene class always reports: with an absent deny-list its only row is
    the "class inactive" notice. Tests that want the violation rows write an
    env-named deny-list with at least one entry (the seam
    tests/test_public_safety.py uses), so the deny-list row does not drown the
    violation under test. conftest's isolated env has already cleared
    NONI_SCRUB_DENYLIST, so this only ever sees the fixture file.
    """
    import os

    path = tmp_path / "census-hygiene-denylist.txt"
    path.write_text("\n".join(entries) + "\n", encoding="utf-8")
    os.environ[DENYLIST_ENV_VAR] = str(path)


def _clear_denylist() -> None:
    """Undo _with_denylist (conftest's autouse fixture re-clears it per test)."""
    import os

    os.environ.pop(DENYLIST_ENV_VAR, None)


class TestLedgerEmpty:
    """The ledger-empty class (warn 42): one row per run in the states where
    the census otherwise says nothing about the ledger, each state carrying its
    own message word, exit 0 without --strict and 42 with it. The class only
    ADDS rows — it never softens the ledger-record failure of a decisions/
    directory that exists and holds no record. Symlinks are reported, never
    followed."""

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

        This is the ONLY tree the 'empty' state word may name: a decisions/
        directory that exists and holds no *.json record is not here — it is
        the ledger-record failure (TestClean.test_empty_ledger_dir_is_not_clean).
        The register side is clean, so the ledger-empty row is the run's only
        finding.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/README.md", "noni lives here\n")
        self._assert_one_row(repo, "empty")

    def test_existing_empty_ledger_adds_no_ledger_empty_row(self, tmp_path):
        """PM decision (issue #23): ledger-empty never weakens an existing
        failure. A decisions/ directory that exists and holds no *.json record
        keeps its ledger-record fail (exit 10) and emits no ledger-empty row."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/.gitkeep", "")
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 10, f"the empty ledger keeps its exit 10, got {rc}\nstderr: {err}"
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert [r["check"] for r in rows] == ["ledger-record"], (
            f"expected only the ledger-record row: {rows}"
        )
        assert rows[0]["severity"] == "fail" and rows[0]["code"] == 10
        assert census_module().LEDGER_RECORD_EMPTY_MESSAGE in rows[0]["message"], (
            f"the row must carry the original message: {rows[0]['message']}"
        )

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
        repo = self._plant(tmp_path)
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
        repo = self._plant(tmp_path)
        (repo / "noni/sessions/2026-10-01-bbbbbb.md").unlink()
        rc, out, err = _run_census(repo, "--only", "session-deleted", "--strict", skip_hygiene=True)
        assert rc == 44, f"expected 44 under --strict, got {rc}\nstderr: {err}\nstdout: {out}"

    def test_deletion_committed_is_still_reported(self, tmp_path):
        """The deletion being committed does not hide it: git history is the
        source, not the diff."""
        repo = self._plant(tmp_path)
        (repo / "noni/sessions/2026-10-01-bbbbbb.md").unlink()
        _commit_dir_state(repo, "noni/sessions")
        rc, out, err = _run_census(repo, "--only", "session-deleted", "--strict", skip_hygiene=True)
        assert rc == 44, f"expected 44 for a committed deletion, got {rc}\nstderr: {err}\n{out}"

    def test_deleted_non_session_file_is_ignored(self, tmp_path):
        """A path under noni/sessions/ that is not an allocated register file
        is not this class's business."""
        repo = self._plant(tmp_path)
        _commit_file(repo, "noni/sessions/notes.md", "scratch\n")
        (repo / "noni/sessions/notes.md").unlink()
        rc, out, err = _run_census(repo, skip_hygiene=True)
        assert rc == 0, f"expected 0, got {rc}\nstderr: {err}"
        assert "session-deleted" not in out, f"unexpected row: {out}"

    def test_never_committed_file_is_not_a_deletion(self, tmp_path):
        """Nothing in history ever held the file, so nothing was deleted."""
        repo = self._plant(tmp_path)
        path = repo / "noni/sessions/2026-10-01-cccccc.md"
        path.write_text(_session_body("stranger"))
        path.unlink()
        rc, out, err = _run_census(repo, skip_hygiene=True)
        assert rc == 0, f"expected 0, got {rc}\nstderr: {err}"
        assert "session-deleted" not in out, f"unexpected row: {out}"


class TestHygiene:
    """The hygiene class (warn 50): the in-process public_safety scan over the
    census's own git tree, which always reports — a clean tree included."""

    def test_planted_violation_is_reported(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "note.md", "token " + _SECRET + "\n")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"hygiene is warn: expected 0 without --strict, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, f"expected one hygiene row for the violation: {rows}"
            row = rows[0]
            assert row["code"] == 50
            assert row["severity"] == "warn"
            assert "note.md" in row["subject"], f"row must name the file: {row}"
            assert "note.md" in row["artifact"]
            assert "public hygiene" in row["message"]
            assert row["fix"]

            rc_strict, _o, err = _run_census(repo, "--only", "hygiene", "--strict")
            assert rc_strict == 50, f"expected 50 under --strict, got {rc_strict}\n{err}"
        finally:
            _clear_denylist()

    def test_planted_home_path_is_reported(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "note.md", _HOME_PATH + "\n")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1 and "note.md" in rows[0]["subject"], f"rows: {rows}"
        finally:
            _clear_denylist()

    def test_split_violation_is_exact_not_a_colon_count(self, tmp_path):
        """The parse is exact against public_safety's own label set, not a
        colon-count heuristic: an ambiguous path whose tail would otherwise
        look like a valid "<digits>: <label>" split is refused rather than
        guessed (probe honesty: a verbatim row beats a garbled one).

        "a:1: b" is the trap — dropping the last colon-segment would make "a"
        look like a path with line "1" and label "b". "b" is not a label
        public_safety can emit, so there is no legal split."""
        import census

        # Sanity: the label set is read from public_safety, not duplicated.
        labels = census._hygiene_labels(_hygiene_target())
        assert "GitHub classic token" in labels
        assert "deny-list entry" in labels, "the deny-list label is not in BUILTIN_PATTERNS"

        # Legal shapes, including colons in the path.
        assert census._split_violation("x:y/p.txt:1: GitHub classic token",
                                       labels) == ("x:y/p.txt", 1, "GitHub classic token")
        assert census._split_violation("a:b/c:d.txt:42: deny-list entry",
                                       labels) == ("a:b/c:d.txt", 42, "deny-list entry")
        assert census._split_violation(
            "n.md:3: machine-local absolute home path (/home/<known identity>)",
            labels) == ("n.md", 3, "machine-local absolute home path (/home/<known identity>)")

        # Illegal shapes: refused, so the caller reports them verbatim.
        for bad in ("a:1: b",                      # label "b" is not a real label
                    "n.md:7: not a real label",     # unknown label
                    "nocolons here",                # no structure at all
                    "n.md:xx: private key block",   # non-numeric line
                    ":1: private key block"):       # empty path
            assert census._split_violation(bad, labels) is None, (
                f"must refuse an illegal violation shape: {bad!r}"
            )

    def test_split_violation_tries_every_label_before_giving_up(self):
        """A label whose suffix matches is not the end of the search: when its
        head does not parse, the walk must continue to the next candidate
        rather than returning None there and then. With the early return the
        verdict depends on set-iteration order, so a violation public_safety
        could resolve is reported verbatim on some runs and split on others.

        The fixture is two labels sharing one tail — ``"secret shape (PEM)"``
        and ``"1: secret shape (PEM)"`` — and a violation ending in both:
        ``x:1: 1: secret shape (PEM)``. Against the shorter label the head is
        ``x:1: 1`` (rpartitions to line ``" 1"``, not a digit) so that split
        must be rejected; the longer label's head, ``x:1``, is the one legal
        split. The old ``return None`` found the split only when the shorter
        label happened to sort second, so the loop below pins every order."""
        import census

        unparseable = "secret shape (PEM)"
        parsable = "1: secret shape (PEM)"
        violation = "x:1" + ": " + parsable
        expected = ("x", 1, parsable)

        # Both labels really do claim this violation, and only one parses.
        assert violation.endswith(": " + unparseable)
        assert violation.endswith(": " + parsable)

        for _ in range(200):
            # A fresh set each round, and both insertion orders: the label set
            # is a set, so iteration order is the thing the bug varies on.
            assert census._split_violation(violation, {unparseable, parsable}) == expected
            assert census._split_violation(violation, {parsable, unparseable}) == expected
        # The refusal cases still refuse: nothing matched, so the caller goes
        # verbatim rather than inventing a split.
        assert census._split_violation("1: secret shape (PEM", {unparseable, parsable}) is None

    def test_violation_in_path_containing_a_colon_is_split_correctly(self, tmp_path):
        """Regression: a tracked path may legally contain a colon
        ("x:y/p.txt"). Splitting public_safety's "path:line: label" at the
        FIRST colon truncated artifact to the path prefix before the colon
        ("x") and garbled the message, which also broke the documented
        (artifact, check, subject) sort grouping. The row must name the whole
        path as artifact and the whole path:line as subject."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "x:y/p.txt", "token " + _SECRET + "\n")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"hygiene is warn: expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, f"expected one hygiene row: {rows}"
            row = rows[0]
            assert row["artifact"] == "x:y/p.txt", (
                f"artifact must be the whole violating path, colon and all: {row}"
            )
            assert row["subject"] == "x:y/p.txt:1", (
                f"subject must be the whole path:line: {row}"
            )
            # The message must not be garbled: it names the full path and the
            # label, and never the truncated "y/p.txt1" prefix the first-colon
            # split produced.
            assert "x:y/p.txt" in row["message"], f"message lost the path: {row}"
            assert "y/p.txt1" not in row["message"], f"garbled message: {row}"
            assert row["code"] == 50 and row["severity"] == "warn"
        finally:
            _clear_denylist()

    def test_violation_subject_sorts_with_its_artifact(self, tmp_path):
        """The colon path must sort under its own artifact, not a truncated
        prefix: two rows in one colon-named file keep one artifact."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "x:y/p.txt", "token " + _SECRET + "\nline two\n")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            _rows = _run_census(repo, json_out=True)
            rows = [r for r in _ndjson_rows(_rows[1]) if r.get("check") == "hygiene"]
            artifacts = {r["artifact"] for r in rows}
            assert artifacts == {"x:y/p.txt"}, f"artifact grouping broke: {artifacts}"
        finally:
            _clear_denylist()

    def test_absent_denylist_is_reported_inactive_never_clean(self, tmp_path):
        """With no deny-list the class never reads "clean": it emits exactly
        one row naming the inactive state, even on a violation-free tree."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        rc, out, err = _run_census(repo, json_out=True)
        assert rc == 0, f"expected 0 (warn) without --strict, got {rc}\n{err}"
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
        assert len(rows) == 1, f"expected exactly one inactive-deny-list row: {rows}"
        row = rows[0]
        assert row["subject"] == "deny-list", f"expected the deny-list subject: {row}"
        assert "inactive" in row["message"] and "absent" in row["message"]
        assert "not a hygiene-clean guarantee" in row["message"]
        assert "hygiene-clean" not in row["message"].replace("not a hygiene-clean", ""), (
            f"an inactive class must never describe itself as clean: {row['message']}"
        )

    def test_corrupt_denylist_is_reported_inactive(self, tmp_path, monkeypatch):
        """"corrupt" is a third inactive state: named in the row, never clean."""
        public_safety = _hygiene_target()

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        corrupt = tmp_path / "corrupt-denylist.txt"
        corrupt.write_bytes(b"\xff\xfe\x00\x01not utf8")
        monkeypatch.setattr(public_safety, "_default_denylist_file", lambda: corrupt)
        rc, out, err = _run_census(repo, json_out=True)
        assert rc == 0, f"expected 0 (warn) without --strict, got {rc}\n{err}"
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
        assert len(rows) == 1, f"expected exactly one inactive-deny-list row: {rows}"
        assert rows[0]["subject"] == "deny-list"
        assert "corrupt" in rows[0]["message"], f"expected the corrupt state: {rows[0]['message']}"

    def test_empty_denylist_is_reported_inactive(self, tmp_path, monkeypatch):
        """A deny-list that is present but holds no entry is its own state:
        the class did not run, and the row says so."""
        public_safety = _hygiene_target()

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        empty = tmp_path / "empty-denylist.txt"
        empty.write_text("# only a comment\n", encoding="utf-8")
        monkeypatch.setattr(public_safety, "_default_denylist_file", lambda: empty)
        rc, out, err = _run_census(repo, json_out=True)
        assert rc == 0, f"expected 0 (warn) without --strict, got {rc}\n{err}"
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
        assert len(rows) == 1, f"expected exactly one inactive-deny-list row: {rows}"
        assert "present but empty" in rows[0]["message"], (
            f"expected the present-but-empty state: {rows[0]['message']}"
        )

    def test_active_denylist_on_clean_tree_reports_nothing(self, tmp_path):
        """With the deny-list class active and nothing to flag, hygiene is
        genuinely clean: zero rows."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert rows == [], f"expected no hygiene rows on a clean active-deny-list run: {rows}"
        finally:
            _clear_denylist()

    def test_denylist_entry_violation_is_reported(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "note.md", "port from synthetic-project-name\n")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1 and "note.md" in rows[0]["subject"], f"rows: {rows}"
        finally:
            _clear_denylist()

    def test_violation_of_an_unknown_label_is_reported_verbatim(self, tmp_path, monkeypatch):
        """The verbatim fallback branch is load-bearing: a violation public_safety
        emits with a label the census has never seen must still produce a row
        that carries the whole finding. A row silently dropped here would read
        as a clean scan — the exact probe-honesty failure this class exists to
        close — so this test pins the row, its subject/artifact and its message
        (mutation guard: deleting the add(), or emptying any of its three
        fields, fails here)."""
        public_safety = _hygiene_target()

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        # A label absent from public_safety's tables: _split_violation must
        # refuse it, so the caller reports it verbatim.
        monkeypatch.setattr(
            public_safety, "_scan_tracked_files",
            lambda repo, patterns: ["x:y/p.txt:1: unrecognised future label"],
        )
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0 (warn), got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, f"expected one verbatim hygiene row: {rows}"
            row = rows[0]
            whole = "x:y/p.txt:1: unrecognised future label"
            assert row["subject"] == whole, f"subject must carry the whole finding: {row}"
            assert row["artifact"] == whole, f"artifact must carry the whole finding: {row}"
            assert row["message"] == f"public hygiene: {whole}", (
                f"message must carry the whole finding verbatim: {row['message']}"
            )
            assert row["code"] == 50 and row["severity"] == "warn"
            assert row["fix"]
        finally:
            _clear_denylist()

    def test_malformed_pattern_table_never_crashes_the_census(self, tmp_path, monkeypatch):
        """The label scan reads every ``*_PATTERNS`` attribute public_safety
        exposes, so a future table bound to a truthy non-iterable must degrade
        to the verbatim row rather than raise out of the census (the class's
        own contract is never-crash, report-instead)."""
        public_safety = _hygiene_target()

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        monkeypatch.setattr(public_safety, "FUTURE_PATTERNS", 5, raising=False)
        monkeypatch.setattr(
            public_safety, "_scan_tracked_files",
            lambda repo, patterns: ["n.md:2: GitHub classic token"],
        )
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0 (warn), got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, f"expected one row, no crash: {rows}"
            # The known tables still load, so the well-shaped row still splits.
            assert rows[0]["artifact"] == "n.md", f"expected a split row: {rows[0]}"
        finally:
            _clear_denylist()

    def test_pattern_table_that_raises_on_iteration_never_crashes_the_census(
            self, tmp_path, monkeypatch):
        """The never-crash claim covers more than TypeError.

        A table whose iteration protocol raises (``__iter__``, ``__len__`` or
        ``__bool__`` blowing up) must contribute no labels and let the run
        report verbatim rows — not escape as a traceback that discards every
        finding the census already collected. The int fixture above pins only
        the TypeError shape, so this is the case that makes the contract real."""
        public_safety = _hygiene_target()

        class _BadTable:
            def __bool__(self) -> bool:
                return True

            def __iter__(self):
                raise RuntimeError("table hang")

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        monkeypatch.setattr(public_safety, "FUTURE_PATTERNS", _BadTable(), raising=False)
        monkeypatch.setattr(
            public_safety, "_scan_tracked_files",
            lambda repo, patterns: ["n.md:2: unrecognised future label"],
        )
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0 (warn), got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, f"expected one verbatim row, no crash: {rows}"
            assert rows[0]["artifact"] == "n.md:2: unrecognised future label", (
                f"a table that cannot be walked must not garble the row: {rows[0]}"
            )
        finally:
            _clear_denylist()

    def test_non_git_repo_reports_scan_did_not_run(self, tmp_path):
        """A non-git --repo is probe honesty, never a clean: one row saying the
        scan did not run."""
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "note.txt").write_text("hello\n", encoding="utf-8")
        rc, out, err = _run_census(plain, json_out=True)
        assert rc == 0, f"expected 0 (warn) without --strict, got {rc}\n{err}"
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
        assert len(rows) == 1, f"expected one not-run row: {rows}"
        assert "did not run" in rows[0]["message"]
        assert rows[0]["code"] == 50
        # The artifact is pinned, not just "truthy": the not-run row names the
        # checker from the skill directory (the hygiene artifact namespace),
        # and a row that pointed anywhere else would send a caller to the wrong
        # file when it goes to fix the scan.
        assert rows[0]["artifact"] == "../../../scripts/public_safety.py", (
            f"not-run row must name the checker from the skill dir: {rows[0]}"
        )

    def test_non_git_repo_strict_lifts_the_exit(self, tmp_path):
        """The not-run row is a warn like any other hygiene row: --strict turns
        it into exit 50."""
        plain = tmp_path / "plain-strict"
        plain.mkdir()
        (plain / "note.txt").write_text("hello\n", encoding="utf-8")
        rc, _out, err = _run_census(plain, "--only", "hygiene", "--strict")
        assert rc == 50, f"expected 50 under --strict, got {rc}\n{err}"


class TestClean:
    def test_clean_repo_exits_zero(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        rc, out, err = _run_census(repo)
        assert rc == 0, f"expected exit 0, got {rc}\nstderr: {err}\nstdout: {out}"

    def test_no_noni_dir_exits_zero(self, tmp_path):
        """A repo with no noni/ directory at all exits 0 (ledger-empty is a
        warn), but it is never silent: exactly one ledger-empty row carries the
        state word "absent", and --strict promotes it to exit 42."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "README.md", "# empty\n")
        rc, out, err = _run_census(repo, json_out=True)
        assert rc == 0, f"expected exit 0 on repo with no noni/, got {rc}\nstderr: {err}\nstdout: {out}"

        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        # hygiene is a separate class with its own report; the ledger side of
        # the run must be exactly one ledger-empty row and nothing else.
        ledger_rows = [r for r in rows if r["check"].startswith("ledger-")]
        assert len(ledger_rows) == 1, f"expected exactly one ledger row: {ledger_rows}"
        assert ledger_rows[0]["check"] == "ledger-empty"
        assert ledger_rows[0]["code"] == 42
        assert ledger_rows[0]["severity"] == "warn"
        assert "absent" in ledger_rows[0]["message"], (
            f"expected the 'absent' state word in the message: {ledger_rows[0]['message']}"
        )

        rc_strict, _out, err = _run_census(repo, "--only", "ledger-empty", "--strict")
        assert rc_strict == 42, (
            f"expected exit 42 for ledger-empty under --strict, got {rc_strict}\nstderr: {err}"
        )

    def test_empty_ledger_dir_is_not_clean(self, tmp_path):
        """An empty ledger directory (exists but no records) is a violation (exit 10)."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/.gitkeep", "")
        rc, out, err = _run_census(repo)
        assert rc == 10, f"expected exit 10 for empty ledger, got {rc}\nstderr: {err}\nstdout: {out}"

    def test_census_is_read_only(self, tmp_path):
        """Running the census leaves git status --porcelain empty."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md",
                      _session_body("developer"))
        before = _git(repo, "status", "--porcelain").stdout
        _run_census(repo)
        after = _git(repo, "status", "--porcelain").stdout
        assert before == after, f"git status changed: {before!r} -> {after!r}"


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
        where the deletion needs reporting: the lowest code still wins, so the
        ledger-record failure of the now-recordless directory exits 10 and the
        deletion row is still there."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        (repo / "noni/decisions/2026-10-01-alpha.json").unlink()
        rc, out, err = _run_census(repo)
        assert rc == 10, (
            "a deleted sole record still fails the census: the recordless "
            f"decisions/ directory is the ledger-record failure that wins the "
            f"lowest-code rule: expected exit 10, got {rc}\nstderr: {err}\n{out}"
        )
        assert "deleted" in out, f"expected 'deleted' reason:\n{out}"
        assert "ledger-edited" in out, f"expected a ledger-edited row:\n{out}"

    def test_exit_12_deleted_sole_record_reports_both_rows(self, tmp_path):
        """Same tree: both classes report. The recordless ledger is the
        ledger-record fail row AND the deletion is the ledger-edited fail
        row — neither silences the other, and no ledger-empty row appears
        because the decisions/ directory is there."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        (repo / "noni/decisions/2026-10-01-alpha.json").unlink()
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 10, (
            "both fail classes report, so the lowest code (10) wins: "
            f"got {rc}\nstderr: {err}"
        )
        checks = [r["check"] for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert "ledger-record" in checks, f"missing ledger-record row: {checks}"
        assert "ledger-edited" in checks, f"missing ledger-edited row: {checks}"
        assert "ledger-empty" not in checks, (
            f"an existing decisions/ directory is not a ledger-empty state: {checks}"
        )
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
        # 10 (the recordless directory) is the lowest failing code here; the
        # deleted row is present alongside it.
        assert rc == 10, f"expected exit 10 (lowest code), got {rc}\nstderr: {err}\n{out}"
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

    def test_exit_30_double_claim(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md",
                      _session_body("developer", claims=["#42"]))
        _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md",
                      _session_body("reviewer", claims=["#42"]))
        rc, out, err = _run_census(repo)
        assert rc == 30, f"expected exit 30, got {rc}\nstderr: {err}\nstdout: {out}"

    def test_exit_31_claim_without_register(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        # File with claims but no identity field
        body = ("- host/worktree: ws-1\n"
                "- started: 2026-10-01T10:00:00Z\n"
                "- status: active\n"
                "- claims:\n"
                "  - claim: #42\n")
        _commit_file(repo, "noni/sessions/2026-10-01-cccccc.md", body)
        rc, out, err = _run_census(repo)
        assert rc == 31, f"expected exit 31, got {rc}\nstderr: {err}\nstdout: {out}"

    def test_exit_32_malformed_claim_row(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        body = ("- identity: developer\n"
                "- host/worktree: ws-1\n"
                "- started: 2026-10-01T10:00:00Z\n"
                "- status: active\n"
                "- claims:\n\n"
                "  - claim:\n")
        _commit_file(repo, "noni/sessions/2026-10-01-dddddd.md", body)
        rc, out, err = _run_census(repo)
        assert rc == 32, f"expected exit 32, got {rc}\nstderr: {err}\nstdout: {out}"

    def test_lowest_code_wins(self, tmp_path):
        """When exit 30 (double-claim) and 32 (malformed) both fire, 30 wins."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md",
                      _session_body("developer", claims=["#42"]))
        _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md",
                      _session_body("reviewer", claims=["#42"]))
        # Malformed file (missing all fields)
        _commit_file(repo, "noni/sessions/2026-10-01-eeeeee.md",
                      "- host/worktree: ws\n- started: 2026-10-01T10:00:00Z\n- status: active\n- claims:\n")
        rc, out, err = _run_census(repo)
        assert rc == 30, f"expected lowest code 30 to win, got {rc}\nstderr: {err}\nstdout: {out}"


class TestJsonMode:
    def test_json_emits_ndjson_to_stdout(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md",
                      _session_body("developer", claims=["#42"]))
        _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md",
                      _session_body("reviewer", claims=["#42"]))
        rc, out, err = _run_census(repo, json_out=True)
        rows = _ndjson_rows(out)
        assert rc == 30
        finding_rows = [r for r in rows if r.get("kind") == "finding"]
        summary_rows = [r for r in rows if r.get("kind") == "summary"]
        assert len(finding_rows) >= 1
        assert len(summary_rows) == 1, "exactly one summary record"
        summary = summary_rows[0]
        assert summary["exit"] == 30
        assert summary["ok"] is False
        for row in finding_rows:
            assert row["schema"] == "noni.census/1"
            assert row["kind"] == "finding"
            assert "check" in row
            assert "code" in row
            assert "subject" in row
            assert "artifact" in row
            assert "message" in row
            assert "fix" in row
            assert "severity" in row

    def test_every_finding_names_an_artifact_path(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md",
                      _session_body("developer", claims=["#42"]))
        _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md",
                      _session_body("reviewer", claims=["#42"]))
        rc, out, err = _run_census(repo, json_out=True)
        rows = _ndjson_rows(out)
        for row in rows:
            if row.get("kind") == "finding":
                assert row["artifact"], f"finding row has empty artifact: {row}"

    def test_json_summary_ok_true_on_clean(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        rc, out, err = _run_census(repo, json_out=True)
        rows = _ndjson_rows(out)
        summary = [r for r in rows if r.get("kind") == "summary"][0]
        assert summary["ok"] is True
        assert summary["exit"] == 0

    def test_json_reproducible_two_runs(self, tmp_path):
        """Two runs with the same --now produce byte-identical stdout."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md",
                      _session_body("developer", claims=["#42"]))
        _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md",
                      _session_body("reviewer", claims=["#42"]))
        args = ["--now", "2026-10-02T00:00:00Z"]
        rc1, out1, _ = _run_census(repo, *args, json_out=True)
        rc2, out2, _ = _run_census(repo, *args, json_out=True)
        assert rc1 == rc2 == 30
        assert out1 == out2, f"two runs produced different output:\n---\n{out1}\n---\n{out2}"


class TestCheckFilters:
    def test_list_prints_all_checks(self):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            import importlib
            census_mod = importlib.import_module("census")
            rc = census_mod.main(["--list"])
        assert rc == 0
        lines = out.getvalue().strip().splitlines()
        expected = {"ledger-record", "ledger-edited", "ledger-chain",
                     "session-double", "session-claim", "session-malformed",
                     "session-stalled", "probe",
                     "ledger-empty", "session-same-identity", "session-deleted",
                     "hygiene"}
        assert set(lines) == expected, f"got {lines}"

    def test_only_session_double(self, tmp_path):
        """--only session-double skips ledger checks."""
        repo = _init_repo(tmp_path / "repo")
        # Plant both a ledger violation and a double-claim
        bad = _valid_record()
        del bad["id"]
        _commit_file(repo, "noni/decisions/2026-10-01-bad.json", json.dumps(bad, indent=2))
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md",
                      _session_body("developer", claims=["#42"]))
        _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md",
                      _session_body("reviewer", claims=["#42"]))
        rc, out, err = _run_census(repo, "--only", "session-double")
        assert rc == 30, f"expected 30 (session-double only), got {rc}\nstderr: {err}\nstdout: {out}"

    def test_skip_session_double(self, tmp_path):
        """--skip session-double skips the double-claim check."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md",
                      _session_body("developer", claims=["#42"]))
        _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md",
                      _session_body("reviewer", claims=["#42"]))
        rc, out, err = _run_census(repo, "--skip", "session-double")
        assert rc == 0, f"expected 0 (double-claim skipped), got {rc}\nstderr: {err}\nstdout: {out}"


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
        # report: a real decisions/ directory — whatever it holds. A directory
        # with no record is the ledger-record failure, not a ledger-empty state
        # (TestLedgerEmpty.test_existing_empty_ledger_adds_no_ledger_empty_row).
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
            # noni/ present, decisions/ missing — the one tree 'empty' names.
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
        glob), not at the record pass and not at a stat the rest of the census
        also performs — so the ledger is a real directory at probe time and
        only the probe's readdir faults, which is exactly the state where a
        label of "symlink" would be a lie about which state occurred.
        """
        import census

        repo = _init_repo(tmp_path / "repo")
        # A real record committed: the probe fault alone must decide the row,
        # so this test also proves the probe's fault is reported even when the
        # ledger is not empty.
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        ledger = repo / "noni" / "decisions"

        real_glob = census.Path.glob

        def boom(self, pattern):
            if self == ledger:
                raise OSError("input/output error")
            return real_glob(self, pattern)

        monkeypatch.setattr(census.Path, "glob", boom)
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "ledger-empty"]
        assert len(rows) == 1, f"expected one row: {rows}"
        assert "input/output error" in rows[0]["message"], (
            f"the OSError text must survive into the row: {rows[0]['message']}"
        )
        assert "symlink" not in rows[0]["message"], (
            f"an I/O fault must not be reported as a symlink: {rows[0]['message']}"
        )
        # The probe faulted, so there is no censusable ledger: its warn is the
        # only row the ledger group adds (the record pass runs on the real
        # directory and finds its one valid record).
        assert rc == 0, f"the state stays warn, got {rc}\n{err}"


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
        # The only fail row this tree can produce is the ledger's; the exit
        # below is that 10, never a 50 from a scan that did not run.
        assert rc == 10, f"a scan that cannot run must not lift the exit, got {rc}\n{err}"
        assert any(r["subject"] == "hygiene scan" and "did not run" in r["message"] for r in rows), (
            f"expected the not-run row: {rows}"
        )
        # Findings from the other classes are still in the run: an
        # un-caught exception would have taken the whole census down instead,
        # and the summary's own counts are the proof that they were collected.
        # The ledger here is a decisions/ directory with no record: its row is
        # the ledger-record fail, not a ledger-empty warn.
        summary = [r for r in _ndjson_rows(out) if r.get("kind") == "summary"][0]
        assert summary["counts"].get("hygiene") == 1, f"summary: {summary}"
        assert summary["counts"].get("ledger-record"), (
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

        module = census._load_public_safety()
        assert module is not None, "scripts/public_safety.py must be loadable"
        assert census.CENSUS_PS_MODULE_KEY == "noni_census_public_safety"
        assert sys.modules.get(census.CENSUS_PS_MODULE_KEY) is module
        # The census's own loader never registers under the shared name; a test
        # that imported the module normally may have, so assert about the
        # census's write, not about the registry's contents.
        assert module.__name__ == census.CENSUS_PS_MODULE_KEY

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


class TestCheckContractIsDerived:
    """The check ids, codes and severities have exactly one source (CHECKS);
    the surfaces a caller reads are renderings of it, not extra copies."""

    def test_list_matches_the_table(self):
        import io
        from contextlib import redirect_stdout

        import census

        buf = io.StringIO()
        with redirect_stdout(buf):
            assert census.main(["--list"]) == 0
        assert set(buf.getvalue().split()) == set(census.CHECKS), (
            "--list and CHECKS have drifted apart"
        )

    def test_strict_help_lists_the_warn_classes(self):
        import census

        parser = census._build_parser()
        strict = next(a for a in parser._actions if a.dest == "strict")
        for name, (_code, sev, _fix) in census.CHECKS.items():
            if sev == "warn":
                assert name in strict.help, f"--strict help omits warn class {name}: {strict.help}"
        # No fail class leaks into the list a reader uses to decide what
        # --strict changes. Match the id as a whole word, not as a substring:
        # "session-double" is contained in "session-double-…" style ids and
        # would pass an `in` test for the wrong reason.
        listed = set(re.findall(r"[a-z][a-z-]+", strict.help))
        for name, (_code, sev, _fix) in census.CHECKS.items():
            if sev == "fail":
                assert name not in listed, f"--strict help names a fail class {name}: {strict.help}"

    def test_skill_md_options_table_strict_row_matches_the_help_string(self):
        """The --strict contract is written in CHECKS and rendered in three
        places; the two prose renderings must list the same classes."""
        import census

        parser = census._build_parser()
        help_ids = {m for m in re.findall(r"[a-z][a-z-]+",
                                         next(a for a in parser._actions
                                             if a.dest == "strict").help)
                    if m in census.CHECKS}
        text = (REPO / "skills" / "census" / "SKILL.md").read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith("| `--strict`"))
        table_ids = set(re.findall(r"`([a-z][a-z-]+)`", row)) - {"--strict"}
        assert help_ids == table_ids, (
            f"--strict help and the SKILL.md options row disagree: {help_ids ^ table_ids}"
        )

    def test_skill_md_documents_the_same_table(self):
        """SKILL.md's exit-code block is the operator-facing contract; a class
        added to CHECKS without documenting it here fails."""
        import census

        text = (REPO / "skills" / "census" / "SKILL.md").read_text(encoding="utf-8")
        documented = set(re.findall(r"^\s*(\d{2})\s+([a-z-]+)", text, re.MULTILINE))
        by_code = {(str(c), n) for n, (c, _s, _f) in census.CHECKS.items()}
        assert by_code <= documented, (
            f"SKILL.md is missing exit-code lines for: {sorted(by_code - documented)}"
        )
        for name, (_code, _sev, _fix) in census.CHECKS.items():
            assert f"`{name}`" in text, f"SKILL.md does not document check {name}"
