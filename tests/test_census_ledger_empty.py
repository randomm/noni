"""The ledger-empty class: the states where no decision record can be read.

One row per run in each state (absent, empty, not a directory, symlink, ok), the
state words as a closed vocabulary owned by one table, and a whole committed
``decisions/`` directory that no longer exists.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py`` and the runners in ``tests/census_run.py``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from _harness import REPO, _commit_file, _init_repo, subprocess_env
from census_fixtures import _ndjson_rows, _session_body, _valid_record
from census_probe_doubles import _UnreadableGit
from census_run import _run_census
from ledger_schema_fixtures import _run_py, _run_sh

CENSUS_SH = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"

# Every external command census.sh reaches for on a run that does read records,
# and the interpreter the run itself is started with. No ``jq``: that absence is
# the state under test, and the list is closed so a shim that quietly grew a new
# external dependency fails here rather than inheriting the host's PATH.
CENSUS_SH_TOOLS = ("bash", "sh", "dirname", "find", "grep", "sort", "awk",
                   "sed", "cat", "head", "cut", "sha1sum", "mktemp", "rm",
                   "hostname", "git")


def _path_without_jq(tmp_path: Path) -> Path:
    """A private bin dir holding the census's own tools and no ``jq``.

    Symlinks, not copies: a PATH of links is cheap to build per test and a
    broken link resolves to nothing, which is what an absent tool is. ``jq`` is
    named nowhere in the list, so the directory cannot hold it even on a host
    where every other tool resolves.
    """
    bin_dir = tmp_path / "path-without-jq"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for tool in CENSUS_SH_TOOLS:
        source = shutil.which(tool)
        link = bin_dir / tool
        if source is not None and not link.exists():
            link.symlink_to(source)
    return bin_dir


def _run_sh_without_jq(tmp_path: Path, ledger: Path) -> subprocess.CompletedProcess[str]:
    """census.sh over ``ledger`` with a PATH that holds no ``jq``.

    The env is built from scratch rather than subtracted from the host's: an
    inherited PATH element could still carry a ``jq`` the test did not remove.
    """
    env = subprocess_env({"PATH": str(_path_without_jq(tmp_path)),
                          "HOME": str(tmp_path)})
    return subprocess.run(["bash", str(CENSUS_SH), str(ledger)],
                          capture_output=True, text=True, env=env, timeout=120)


class TestLedgerEmptyWithoutJq:
    """A ledger this machine cannot read is not a clean ledger (issue #97).

    The shim's (42:ledger-empty) branch was reached before its ``jq`` probe, so
    on a machine with no jq a recordless ``decisions/`` directory — and nothing
    else — exited 0, and the report header went to stdout beside it. The census
    had read no record and applied no schema, and called the ledger clean for
    it. The probe answers 3 for a missing jq whatever the ledger holds, so these
    two runs pin that the recordless tree is refused on the same terms as a
    ledger full of records."""

    def test_a_recordless_ledger_without_jq_exits_3_not_0(self, tmp_path):
        """The branch this PR changed: no records, so no schema question was
        asked, and the old order called that a clean tree at exit 0."""
        ledger = tmp_path / "fresh" / "noni" / "decisions"
        ledger.mkdir(parents=True)
        proc = _run_sh_without_jq(tmp_path, ledger)
        assert proc.returncode == 3, (
            f"a census that cannot read a record has no verdict to give: "
            f"rc={proc.returncode}\nout: {proc.stdout}\nerr: {proc.stderr}")
        assert "jq not found" in proc.stderr, proc.stderr
        assert "42:ledger-empty" not in proc.stderr, (
            f"the recordless warn was reached with jq absent: {proc.stderr}")
        assert proc.stdout.strip() == "", (
            f"a census that read nothing printed a report: {proc.stdout}")

    def test_a_ledger_holding_a_record_without_jq_exits_3(self, tmp_path):
        """The control: the state the probe always owned. Both ledgers must
        answer 3, or the recordless case is a special favour rather than one
        rule."""
        ledger = tmp_path / "held" / "noni" / "decisions"
        ledger.mkdir(parents=True)
        (ledger / "2026-10-01-alpha.json").write_text(
            json.dumps(_valid_record(), indent=2) + "\n", encoding="utf-8")
        proc = _run_sh_without_jq(tmp_path, ledger)
        assert proc.returncode == 3, (
            f"expected 3 with a record present too: rc={proc.returncode}\n"
            f"out: {proc.stdout}\nerr: {proc.stderr}")
        assert "jq not found" in proc.stderr, proc.stderr
        assert proc.stdout.strip() == "", (
            f"a census that read nothing printed a report: {proc.stdout}")

    def test_the_ledger_itself_is_left_alone(self, tmp_path):
        """A refused census is read-only: the records it could not read are
        still the bytes the caller had, both ledgers, in one run."""
        ledgers = []
        for name in ("ro-empty", "ro-held"):
            ledger = tmp_path / name / "noni" / "decisions"
            ledger.mkdir(parents=True)
            if name == "ro-held":
                (ledger / "2026-10-01-alpha.json").write_text(
                    json.dumps(_valid_record(), indent=2) + "\n", encoding="utf-8")
            ledgers.append(ledger)
        before = [{p.name: p.read_bytes() for p in ledger.iterdir()}
                  for ledger in ledgers]
        for ledger in ledgers:
            assert _run_sh_without_jq(tmp_path, ledger).returncode == 3
        after = [{p.name: p.read_bytes() for p in ledger.iterdir()}
                 for ledger in ledgers]
        assert after == before, "a refused census wrote to the ledger"


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

    def test_both_censuses_agree_on_a_freshly_attached_tree(self, tmp_path):
        """A freshly attached tree is a committed ``noni/decisions/`` holding no
        record, and the two entry points must hand back one verdict (issue #97).

        Before the fix ``census.sh`` exited 10 there while the unified census
        exited 0 with the ``ledger-empty`` warn, so the same project read as
        permanently red to one tool and clean to the other, and a team's CI chose
        its verdict by which script it happened to call. The shim converged on the
        unified census, not the reverse: the warn stays a warn (42 under
        ``--strict``, which the shim has no flag for), and the states the shim's
        read never reached -- a directory it could not enumerate -- stay 10.

        Both censuses are driven over the one ledger directory, so the only thing
        that differs between the two verdicts is the tool.
        """
        ledger = tmp_path / "fresh" / "noni" / "decisions"
        ledger.mkdir(parents=True)

        sh_code, sh_out = _run_sh(ledger)
        assert sh_code == 0, f"census.sh must exit 0 on a recordless ledger:\n{sh_out}"
        assert "42:ledger-empty" in sh_out, (
            f"the shim must name the state it reported, not fail silently: {sh_out}")
        assert "10:empty-ledger" not in sh_out, (
            f"the shim still calls a recordless ledger an unusable one: {sh_out}")

        py_code, py_out = _run_py(ledger)
        assert py_code == 0, f"the unified census must exit 0 on a recordless ledger:\n{py_out}"
        assert sh_code == py_code, (
            f"the two censuses disagree on a freshly attached tree: sh={sh_code} "
            f"py={py_code}\nsh: {sh_out}\npy: {py_out}")
        # ``_run_py`` merges both streams, so the rows are read from a second run
        # through this file's own runner: the census prints the NDJSON stream on
        # stdout and the exit-code note on stderr, and the verdict under test is
        # the row set.
        rc, out, err = _run_census(ledger.parent.parent, "--ledger", str(ledger),
                                   "--json", "--only", "ledger-empty",
                                   "--only", "ledger-record")
        assert rc == 0 and sh_code == rc, f"sh={sh_code} py={rc}\n{err}"
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert [r["check"] for r in rows] == ["ledger-empty"], out
