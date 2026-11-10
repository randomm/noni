"""How the census reports: the state root, a clean tree, ``--json`` and the filters.

``--repo`` is the state root and the cwd is never consulted; a clean tree exits 0;
``--json`` emits one NDJSON row per finding; ``--only`` and ``--skip`` filter classes
and nothing else.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py`` and the runners in ``tests/census_run.py``.
"""

from __future__ import annotations

import json

from _harness import _commit_file, _git, _init_repo
from census_fixtures import _ndjson_rows, _valid_record
from census_run import _run_census, _run_census_from


class TestStateRoot:
    """--repo is the state root: every noni path resolves from it, and the cwd
    of the run decides nothing except the default nobody uses here.

    The three trees of each case: a separate state repository holding the
    ``noni/`` layout, a decoy ``noni/`` planted under the cwd carrying findings
    the census must never report, and an empty cwd a stray write would show up
    in. A census that resolved any group from the cwd would report the decoy's
    double-claim or grow a ``noni/`` directory, and both are asserted against."""

    def test_census_reads_only_the_state_root_named_by_repo(self, tmp_path):
        """A clean state root censuses clean while a schema violation sits in a
        decoy ledger beside the cwd."""
        root = _init_repo(tmp_path / "state-root")
        _commit_file(root, "noni/decisions/2026-10-01-alpha.json",
                     json.dumps(_valid_record(), indent=2))
        cwd = tmp_path / "elsewhere"
        cwd.mkdir()
        decoy = cwd / "noni" / "decisions"
        decoy.mkdir(parents=True)
        # A record missing a required key: exit 10 whenever the ledger group
        # reads this directory.
        bad = _valid_record()
        del bad["status"]
        (decoy / "2026-10-01-bbbbb.json").write_text(
            json.dumps(bad, indent=2), encoding="utf-8")

        rc, out, err = _run_census_from(cwd, root, "--json", "--skip", "hygiene",
                                        "--now", "2026-10-02T00:00:00Z")
        assert rc == 0, f"the state root is clean, got {rc}\n{out}\n{err}"
        rows = _ndjson_rows(out)
        assert not [r for r in rows if r.get("kind") == "finding"
                    and r.get("check") == "ledger-record"], (
            f"the census reported the decoy's schema violation, so the ledger "
            f"group resolved from the cwd and not --repo: {rows}"
        )
        assert not [r for r in rows if r.get("kind") == "finding"
                    and "bbbbb" in json.dumps(r)], (
            f"a row named a file that exists only in the decoy: {rows}"
        )
        assert not (cwd / "noni" / "direction" / "order.json").exists(), (
            "the census is read-only: it wrote an ordering artifact under the cwd"
        )

    def test_census_reports_the_state_roots_own_findings_from_a_foreign_cwd(
        self, tmp_path,
    ):
        """The other half of the same pair: the state root's own violation is
        reported even though the cwd holds nothing but a decoy.

        Without this, a first test that asserts the decoy is silent could be
        satisfied by a census that read nothing at all."""
        root = _init_repo(tmp_path / "state-root")
        bad = _valid_record()
        del bad["status"]
        _commit_file(root, "noni/decisions/2026-10-01-bad.json",
                     json.dumps(bad, indent=2))
        cwd = tmp_path / "elsewhere"
        cwd.mkdir()

        rc, out, err = _run_census_from(cwd, root, "--json", "--skip", "hygiene",
                                        "--now", "2026-10-02T00:00:00Z")
        assert rc == 10, f"the state root's schema violation must fire, got {rc}\n{out}\n{err}"
        rows = _ndjson_rows(out)
        # The row's subject is the record's own ``id`` (what a malformed record
        # still carries) and its artifact is the file path, so the pair names the
        # file the operator has to open.
        assert any(r.get("check") == "ledger-record"
                   and r.get("subject") == "2026-10-01-alpha"
                   and "2026-10-01-bad.json" in r.get("artifact", "")
                   for r in rows), rows

    def test_census_refuses_a_repo_that_is_not_a_directory(self, tmp_path):
        """A --repo naming no directory is a usage error (exit 2) naming the
        path, whatever the cwd holds."""
        cwd = tmp_path / "elsewhere"
        cwd.mkdir()
        rc, _out, err = _run_census_from(cwd, tmp_path / "no-such-state-root",
                                         "--skip", "hygiene")
        assert rc == 2, f"expected 2, got {rc}: {err}"
        assert "repo path does not exist" in err, err

    def test_census_reads_nothing_under_home_when_the_caller_names_no_home_path(
        self, tmp_path,
    ):
        """HOME holds a decoy ledger with a schema violation; a census of an empty
        state root reports nothing from it.

        HOME is the one directory a tool reaches without being told (git reads
        it for config, and a leading ~ resolves through it), so it is the
        sharpest test of "every path resolves from --repo": the caller named
        none of it. The state root is deliberately empty, because a census of
        an empty tree is the run most easily satisfied by reading the wrong
        directory and still exiting clean.
        """
        root = _init_repo(tmp_path / "state-root")
        _commit_file(root, "README.md", "# state\n")
        import os

        home = tmp_path / "hostile-home"
        decoy = home / "noni" / "decisions"
        decoy.mkdir(parents=True)
        bad = _valid_record()
        del bad["status"]
        (decoy / "2026-10-01-aaaaaa.json").write_text(
            json.dumps(bad, indent=2), encoding="utf-8")
        cwd = tmp_path / "elsewhere"
        cwd.mkdir()

        previous_home = os.environ.get("HOME")
        previous_userprofile = os.environ.get("USERPROFILE")
        os.environ["HOME"] = str(home)
        os.environ["USERPROFILE"] = str(home)
        try:
            rc, out, err = _run_census_from(cwd, root, "--json", "--skip", "hygiene",
                                            "--now", "2026-10-02T00:00:00Z")
        finally:
            _restore = {"HOME": previous_home, "USERPROFILE": previous_userprofile}
            for name, value in _restore.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        rows = _ndjson_rows(out)
        assert rc == 0, f"an empty state root is clean, got {rc}\n{err}"
        assert not [r for r in rows if r.get("check") == "ledger-record"], (
            f"the census reported a violation that exists only under HOME: {rows}"
        )
        assert "aaaaaa" not in json.dumps(rows), rows
        assert not (home / "noni" / "direction").exists(), (
            "the census is read-only and never writes under HOME either"
        )

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
        state word "absent", and --strict promotes it to exit 42.

        The tree is a code repository (README and source, no noni/), which is how the
        state ends up missing in practice: --repo aimed at the project instead of the
        state clone. So the run must also say the one plain thing -- no noni/
        directory was found under --repo -- because two warn rows about absent
        artifacts read as a project that has not steered yet rather than as a caller
        who named the wrong tree.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "README.md", "# empty\n")
        _commit_file(repo, "src/app.py", "def main() -> int:\n    return 0\n")
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

        # The machine-readable half of the same fact: --json prints no "note:" line,
        # so the sentence has to be on the one summary row or a CI consumer of this
        # stream would never learn the tree holds no state at all.
        summary = [r for r in _ndjson_rows(out) if r.get("kind") == "summary"]
        assert len(summary) == 1, _ndjson_rows(out)
        carried = summary[0].get("not_evaluated")
        assert isinstance(carried, list) and carried, (
            f"--json must carry the no-noni/ note: {summary[0]}")
        assert any("no noni/ directory was found under --repo" in str(line)
                   for line in carried), carried

        rc_strict, _out, err = _run_census(repo, "--only", "ledger-empty", "--strict")
        assert rc_strict == 42, (
            f"expected exit 42 for ledger-empty under --strict, got {rc_strict}\nstderr: {err}"
        )

    def test_no_noni_note_prints_ahead_of_the_rows(self, tmp_path):
        """The no-noni/ note is the first line, and the verdict line stays the last.

        Ordering is the whole point of the note: findings are sorted by
        (artifact, check, subject), so a note appended after them would sit below the
        very rows a wrong --repo makes meaningless, and an operator scanning the top
        of the report would see ledger-empty and deny-list warnings and conclude the
        project was merely unconfigured. The verdict line's position is the other half
        -- a CI step parses lines[-1] -- so both ends are pinned on the same run.
        """
        repo = _init_repo(tmp_path / "note-order")
        _commit_file(repo, "README.md", "# empty\n")
        _commit_file(repo, "src/app.py", "def main() -> int:\n    return 0\n")
        rc, out, err = _run_census(repo)
        lines = out.splitlines()
        assert rc == 0, f"{rc}\n{out}\n{err}"
        assert lines[0].startswith("note: "), (
            f"the no-noni/ note must open the report, above the headline and every "
            f"row: {lines[:4]!r}")
        assert "no noni/ directory was found under --repo" in lines[0], lines[0]
        assert str(repo) in lines[0], f"the note must name --repo as it was passed: {lines[0]}"
        assert lines[-1].startswith("summary: "), lines[-1]
        assert lines[-1].endswith("verdict ok"), lines[-1]
        # Said once, not twice: the leading note is excluded from the trailing block.
        assert sum(1 for line in lines if line.startswith("note: ")) == 2, lines

    def test_no_noni_note_is_silent_under_a_path_override(self, tmp_path):
        """No note when a path override names the state, because --repo need not hold it.

        --ledger, --ordering and --intent replace the path under the state
        root rather than selecting it, so a caller who keeps the ledger beside an
        unrelated --repo has done the sanctioned thing and must not be told their
        --repo holds no noni/. The state words of ledger-empty keep reporting the
        override's own tree either way.
        """
        repo = _init_repo(tmp_path / "override")
        _commit_file(repo, "README.md", "# empty\n")
        outside = tmp_path / "state" / "noni" / "decisions"
        outside.mkdir(parents=True)
        _commit_file(_init_repo(outside.parent), "README.md", "# state\n")
        _rc, out, _err = _run_census(repo, "--ledger", str(outside))
        assert "no noni/ directory was found under --repo" not in out, out

    def test_recordless_ledger_dir_is_a_ledger_empty_warn(self, tmp_path):
        """A decisions/ directory that exists but holds no record is a warn, not
        a violation: the census exits 0 (issue #33 — a freshly attached project
        with no decisions yet must not sit permanently red)."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/.gitkeep", "")
        rc, out, err = _run_census(repo)
        assert rc == 0, f"expected exit 0 for a recordless ledger, got {rc}\nstderr: {err}\nstdout: {out}"

    def test_census_is_read_only(self, tmp_path):
        """Running the census leaves git status --porcelain empty."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        before = _git(repo, "status", "--porcelain").stdout
        _run_census(repo)
        after = _git(repo, "status", "--porcelain").stdout
        assert before == after, f"git status changed: {before!r} -> {after!r}"

class TestJsonMode:
    """``--json`` is a machine contract: stdout is finding rows plus one summary
    row, and stderr carries this run's own usage and tool faults and nothing the
    scan printed (issue #77, AC3). The human mode keeps its banner."""

    def _clean_repo(self, tmp_path):
        """A state root with no findings for the non-hygiene classes.

        Hygiene stays in ``requested``: with no deny-list configured (the
        autouse conftest clears ``NONI_SCRUB_DENYLIST``) that is the one class
        that always reports, and so the only one that ever printed the banner
        this contract removes.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                     json.dumps(_valid_record(), indent=2))
        return repo

    def test_json_writes_nothing_to_stderr_on_a_clean_run(self, tmp_path):
        """The absent-deny-list banner is not repeated on stderr in --json mode.

        The state root is deliberately one whose deny-list is INACTIVE: an
        active deny-list prints nothing, so a test written that way would pass
        whether the banner fired or not. The paired non-vacuity assertion is the
        deny-list row on stdout: the state is still reported, as a documented
        finding row with its fix hint, which is why the banner is redundant.
        """
        repo = self._clean_repo(tmp_path)
        rc, out, err = _run_census(repo, "--now", "2026-10-02T00:00:00Z",
                                   json_out=True)
        assert err == "", f"a clean --json run wrote to stderr: {err!r}"
        assert rc == 0, f"expected 0, got {rc}\n{out}\n{err}"
        rows = _ndjson_rows(out)
        deny_rows = [r for r in rows if r.get("kind") == "finding"
                     and r.get("subject") == "deny-list"]
        assert len(deny_rows) == 1, (
            f"the run must still report the inactive deny-list as a row: {rows}")

    def test_json_writes_nothing_to_stderr_with_a_corrupt_denylist(self, tmp_path):
        """The second stderr writer is silenced too, and it leaked an absolute path.

        ``public_safety.load_denylist`` prints its own ``deny-list <path>
        unreadable`` notice for a candidate it cannot decode, and that path is
        machine-local. A test of the absent case alone would leave it standing.
        """
        repo = self._clean_repo(tmp_path)
        # Not committed: the deny-list is untracked operator config, and a
        # tracked non-UTF-8 file would be a hygiene violation row of its own.
        (repo / ".noni-scrub-denylist").write_bytes(b"\xff\xfe\x00not-utf8")
        rc, out, err = _run_census(repo, "--now", "2026-10-02T00:00:00Z",
                                   json_out=True)
        assert err == "", f"a corrupt deny-list leaked a banner to stderr: {err!r}"
        assert str(repo) not in out, f"an absolute path reached stdout: {out!r}"
        rows = _ndjson_rows(out)
        deny_rows = [r for r in rows if r.get("kind") == "finding"
                     and r.get("subject") == "deny-list"]
        assert len(deny_rows) == 1, f"the corrupt state must still be a row: {rows}"
        assert "corrupt" in deny_rows[0]["message"], deny_rows[0]
        assert rc == 0, f"expected 0, got {rc}\n{out}\n{err}"

    def test_json_stdout_and_the_human_banner_are_unchanged(self, tmp_path):
        """Silencing the banner moved no byte of stdout and none of human mode.

        The contract AC3 removes a stderr line, nothing else: the same run's
        NDJSON is byte-stable across two runs, and the human report still names
        the skipped class (the wording ``scripts/public_safety.py``'s own gate
        and docs/PUBLISHING.md step 1 rely on).
        """
        repo = self._clean_repo(tmp_path)
        args = ["--now", "2026-10-02T00:00:00Z"]
        _rc1, out1, err1 = _run_census(repo, *args, json_out=True)
        _rc2, out2, err2 = _run_census(repo, *args, json_out=True)
        assert out1 == out2, "two identical --json runs differed"
        assert err1 == err2 == ""
        rows = _ndjson_rows(out1)
        assert [r["kind"] for r in rows].count("summary") == 1
        assert all(r["kind"] in ("finding", "summary") for r in rows), rows
        _rc, human, err_human = _run_census(repo, *args)
        assert "deny-list" in human, human
        assert "deny-list class SKIPPED" not in err_human, (
            f"the census's human report must not print the gate's banner: "
            f"{err_human!r}")

    def test_json_emits_ndjson_to_stdout(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        bad = _valid_record()
        del bad["id"]
        _commit_file(repo, "noni/decisions/2026-10-01-bad.json",
                      json.dumps(bad, indent=2))
        rc, out, err = _run_census(repo, json_out=True)
        rows = _ndjson_rows(out)
        assert rc == 10
        finding_rows = [r for r in rows if r.get("kind") == "finding"]
        summary_rows = [r for r in rows if r.get("kind") == "summary"]
        assert len(finding_rows) >= 1
        assert len(summary_rows) == 1, "exactly one summary record"
        summary = summary_rows[0]
        assert summary["exit"] == 10
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
        bad = _valid_record()
        del bad["id"]
        _commit_file(repo, "noni/decisions/2026-10-01-bad.json",
                      json.dumps(bad, indent=2))
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
        bad = _valid_record()
        del bad["id"]
        _commit_file(repo, "noni/decisions/2026-10-01-bad.json",
                      json.dumps(bad, indent=2))
        args = ["--now", "2026-10-02T00:00:00Z"]
        rc1, out1, _ = _run_census(repo, *args, json_out=True)
        rc2, out2, _ = _run_census(repo, *args, json_out=True)
        assert rc1 == rc2 == 10
        assert out1 == out2, f"two runs produced different output:\n---\n{out1}\n---\n{out2}"

class TestCheckFilters:
    def test_list_prints_all_checks(self):
        """``--list`` names every class the table holds, pinned by hand.

        The expected set is written out here and nowhere else on purpose. A version
        that read it from ``census_report.CHECKS`` was a tautology: remove a class from
        the table and the listing still matched it, which is the failure a listing test
        exists to catch. The names below are the contract -- the ledger, ordering,
        intent and hygiene classes the census ships. A class may only join or leave this
        set together with the row that documents it.
        """
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
                     "probe",
                     "ledger-empty",
                     "hygiene", "intent",
                     "ordering-malformed", "ordering-stale", "ordering-closed"}
        assert set(lines) == expected, f"got {lines}"
        assert len(lines) == len(set(lines)), "a class was listed twice"

    def test_only_ignores_classes_it_did_not_name(self, tmp_path):
        """--only ordering-malformed drops the ledger violation planted beside it."""
        repo = _init_repo(tmp_path / "repo")
        bad = _valid_record()
        del bad["id"]
        _commit_file(repo, "noni/decisions/2026-10-01-bad.json",
                     json.dumps(bad, indent=2))
        rc, out, err = _run_census(repo, "--only", "ordering-malformed",
                                   "--skip", "hygiene")
        assert rc == 0, (
            f"expected 0 (ledger class not named), got {rc}\nstderr: {err}\nstdout: {out}")

    def test_skip_drops_the_named_class(self, tmp_path):
        """--skip ledger-record skips the schema violation."""
        repo = _init_repo(tmp_path / "repo")
        bad = _valid_record()
        del bad["id"]
        _commit_file(repo, "noni/decisions/2026-10-01-bad.json",
                     json.dumps(bad, indent=2))
        rc, out, err = _run_census(repo, "--skip", "ledger-record", "--skip", "hygiene")
        assert rc == 0, (
            f"expected 0 (schema class skipped), got {rc}\nstderr: {err}\nstdout: {out}")
