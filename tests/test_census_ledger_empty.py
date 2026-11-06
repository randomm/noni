"""The empty-state contract both ledger entry points owe an attached project.

The issue (noni #97): a project can be attached with a real ``noni/`` skeleton
and no records yet, or a previous run can have staged a record that was then
lost. ``census.py`` answers both with the lowest code that tells the truth --
``42`` for a recordless ``decisions/`` (a warn, so ``--strict`` is what turns it
red) and ``10`` for a directory that cannot be read at all. What the issue added
is the *agreement*: the ledger shim used to answer these states with its own
codes, read through its ``jq`` program, and the two tools handed back different
verdicts for one tree -- a team's CI chose its verdict by which script it called.

The shim is now a thin wrapper over the unified census (issue #99), so the
agreement is structural rather than two implementations kept in step, and these
tests are the witness for that. ``TestLedgerEmptyWithoutJq`` and
``TestJqMustActuallyRun`` pinned the shim's probes for ``jq``: with the schema
program, and the dependency on ``jq``, deleted, the probe and its exit-3
sub-class are gone with them. What survives is the wrapper's own refusal -- no
importable package is exit 3 and prints nothing -- and the rule that the census
alone refuses for a missing tool.

``census.sh`` is driven directly here: these are its exit codes, asserted
byte-for-byte against the census the skill documents. ``tests/conftest.py``
routes the shared ``run_census`` fixture through the same script so the whole
ledger suite reads through the entry point the skill advertises; the unified
census is driven separately wherever a test needs to compare the two.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from _harness import REPO, _commit_file, _init_repo, subprocess_env
from census_fixtures import _ndjson_rows, _session_body, _valid_record
from census_run import _run_census
from ledger_schema_fixtures import no_package_env

CENSUS_SH = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"


def _empty_ledger(tmp_path: Path) -> Path:
    ledger = tmp_path / "noni" / "decisions"
    ledger.mkdir(parents=True)
    return ledger


def _run_sh(ledger: Path) -> tuple[int, str]:
    """census.sh over ``ledger``; returns (exit code, stdout+stderr).

    The streams are merged because the contract under test is what the caller
    sees, not which fd carried it: a row on stderr and an exit code on the
    process have to agree, and a test that reads only one of them cannot see a
    refusal that says "no schema applied" on one stream while exiting clean on
    the other.
    """
    proc = subprocess.run(["bash", str(CENSUS_SH), str(ledger)],
                          capture_output=True, text=True,
                          env=subprocess_env(), timeout=120)
    return proc.returncode, proc.stdout + proc.stderr


def _run_sh_with_empty_package(tmp_path: Path, ledger: Path,
                               name: str) -> subprocess.CompletedProcess[str]:
    """census.sh over ``ledger`` in an environment that cannot load the census.

    The state the wrapper refuses on its own: the census is not importable, so
    there is nothing to run, and a traceback or an exit 0 would both be a false
    green. The env fixture is shared with
    ``tests/test_ledger_name_and_marker_rules.py`` (``no_package_env``): one
    fixture, one guard that proves the package really is unreachable.
    """
    env = no_package_env(tmp_path, name)
    return subprocess.run(["bash", str(CENSUS_SH), str(ledger)],
                          capture_output=True, text=True, env=env, timeout=120)


class TestWrapperRefusesWithoutItsPackage:
    """A ledger the wrapper cannot read is not a clean ledger (issue #97, #99).

    The wrapper's one refusal of its own. It used to be a probe for ``jq`` and a
    sub-class ``3:schema-program-missing``; the schema program is gone, so the
    only thing that can stop this wrapper from running is its interpreter or its
    package. The rule that did not change is the one this class exists for: a
    census that read no record has no verdict to give, and printing a header row
    beside exit 0 is a false green.
    """

    def test_a_recordless_ledger_without_the_package_exits_3_not_0(self, tmp_path):
        """No records, so no schema question was asked, and an exit 0 here would
        have called a tree the tool could not read clean."""
        ledger = tmp_path / "fresh" / "noni" / "decisions"
        ledger.mkdir(parents=True)
        proc = _run_sh_with_empty_package(tmp_path, ledger, "no-pkg-empty")
        assert proc.returncode == 3, (
            f"a census that cannot read a record has no verdict to give: "
            f"rc={proc.returncode}\nout: {proc.stdout}\nerr: {proc.stderr}")
        assert "not importable" in proc.stderr, proc.stderr
        assert "42:ledger-empty" not in proc.stderr, (
            f"the recordless warn was reached with the census absent: {proc.stderr}")
        assert proc.stdout.strip() == "", (
            f"a census that read nothing printed a report: {proc.stdout}")

    def test_a_ledger_holding_a_record_without_the_package_exits_3(self, tmp_path):
        """The control: both ledgers must answer 3, or the recordless case is a
        special favour rather than one rule."""
        ledger = tmp_path / "held" / "noni" / "decisions"
        ledger.mkdir(parents=True)
        (ledger / "2026-10-01-alpha.json").write_text(
            json.dumps(_valid_record(), indent=2) + "\n", encoding="utf-8")
        proc = _run_sh_with_empty_package(tmp_path, ledger, "no-pkg-held")
        assert proc.returncode == 3, (
            f"expected 3 with a record present too: rc={proc.returncode}\n"
            f"out: {proc.stdout}\nerr: {proc.stderr}")
        assert "not importable" in proc.stderr, proc.stderr

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
            assert _run_sh_with_empty_package(tmp_path, ledger, "ro").returncode == 3
        after = [{p.name: p.read_bytes() for p in ledger.iterdir()}
                 for ledger in ledgers]
        assert after == before, "a refused census wrote to the ledger"


class TestWrapperCarriesNoArbiterOfItsOwn:
    """The census alone owns the ledger verdicts; the wrapper owns none.

    The shim once declared its own exit-code table, its own schema program and
    its own probes for ``jq``, and the two arbiters disagreed (issue #97). The
    schema program is deleted and the table is documented in exactly one place
    (``skills/census/SKILL.md``), so what is left to pin is the *absence*: the
    census's code names appear in the census's own help and reference and nowhere
    in the wrapper, and the wrapper's own 3 says only that it could not load.
    """

    #: The codes and row names the unified census owns. A wrapper that names one
    #: of these in its own text has started carrying an arbiter again.
    CENSUS_CODES = ("10:schema", "42:ledger-empty", "ledger-empty")

    def test_the_shim_names_no_census_code_of_its_own(self):
        """No 10/42 sub-class and no tool-missing marker in the wrapper's text.

        The wrapper's whole surface is its comments plus its usage line: the
        census's codes belong in the census's help and in the reference that
        collects them, and a copy in the wrapper would be the drift these tests
        exist to stop.
        """
        text = CENSUS_SH.read_text(encoding="utf-8")
        for marker in self.CENSUS_CODES:
            assert marker not in text, (
                f"census.sh carries the census's own {marker}; the code table is "
                "documented once, in skills/census/SKILL.md")

    def test_the_wrapper_has_no_schema_program_beside_it(self):
        """The second arbiter's program is gone, so nothing can be read by it.

        This is the guarantee the AC asks for in its plainest form: a file that
        declared the rules in a second language is not on disk, so there is no
        path by which the wrapper could apply rules the census does not.
        """
        scripts = CENSUS_SH.parent
        assert not (scripts / "census-schema.jq").exists(), (
            "census-schema.jq is still beside the wrapper: the second arbiter "
            "was retired, not merely bypassed")
        assert not any(p.suffix == ".jq" for p in scripts.iterdir()), (
            f"a jq program is still in the ledger scripts dir: "
            f"{sorted(p.name for p in scripts.iterdir())}")

    def test_the_wrapper_needs_no_jq(self, tmp_path):
        """A machine with no ``jq`` on PATH runs the wrapper like any other.

        The dependency this issue removes was a hard one: with ``jq`` absent the
        old shim exited 3 and refused to read. The census is Python and stdlib
        json, so ``jq`` is simply not part of the reading machine any more, and a
        PATH that holds none must not change the verdict.
        """
        ledger = tmp_path / "nojq" / "noni" / "decisions"
        ledger.mkdir(parents=True)
        (ledger / "2026-10-01-alpha.json").write_text(
            json.dumps(_valid_record(), indent=2) + "\n", encoding="utf-8")
        # A PATH holding the tools a census run reaches for and no ``jq`` at all:
        # the old shim's own probe list, less the one program whose absence used
        # to decide the verdict. The census is Python and stdlib json, so the
        # dependency is simply not part of the reading machine any more.
        bin_dir = tmp_path / "path-without-jq"
        bin_dir.mkdir()
        for tool in ("bash", "sh", "dirname", "find", "grep", "sort", "awk",
                     "sed", "cat", "head", "cut", "mktemp", "rm", "hostname",
                     "git", "python3"):
            source = shutil.which(tool)
            if source is not None:
                (bin_dir / tool).symlink_to(source)
        assert not (bin_dir / "jq").exists(), "the fixture PATH holds jq"
        env = subprocess_env({"HOME": str(tmp_path), "PATH": str(bin_dir),
                              "NONI_PYTHON": sys.executable})
        proc = subprocess.run(["bash", str(CENSUS_SH), str(ledger)],
                              capture_output=True, text=True, env=env, timeout=120)
        assert proc.returncode == 0, (
            f"the wrapper still depends on jq: rc={proc.returncode}\n"
            f"out: {proc.stdout}\nerr: {proc.stderr}")
        assert "jq" not in proc.stderr, proc.stderr


class TestToolMissingIsTheCensusNotTheWrapper:
    """The census owns the missing-tool refusal; the wrapper owns none.

    A missing or broken tool is exit 3 under the census's own table (its git
    probe, which the census suite pins in ``test_census_probe_honesty.py``). The
    wrapper used to reach 3 by probing ``jq`` itself and printing a sub-class of
    its own; now the only exit-3 it can produce is its own load failure, which is
    a different fact and says so in plain words. Both halves are pinned: the census
    still refuses by naming the tool it wanted, and the wrapper never invents one.
    """

    def test_the_census_still_refuses_a_missing_tool_with_3(self, tmp_path, monkeypatch):
        """The census's own probe, unchanged by this PR: a tool it needs that is
        absent answers 3 and names the tool it wanted, on a ledger that
        would otherwise read clean.

        This is the half that is easy to lose: the wrapper's probe for ``jq`` being
        removed must not take the census's probe for ``git`` with it, or a broken
        reading machine becomes a silent pass on both paths. The seam is the
        ``shutil.which`` of the module that asks the question, the same one
        ``test_census_probe_honesty.py`` uses.
        """
        from census_run import _census_main

        import noni.census_run as census_run

        monkeypatch.setattr(census_run.shutil, "which", lambda name: None)
        ledger = _empty_ledger(tmp_path)
        (ledger / "2026-10-01-alpha.json").write_text(
            json.dumps(_valid_record(), indent=2) + "\n", encoding="utf-8")
        import io
        from contextlib import redirect_stderr, redirect_stdout


        out_buf, err_buf = io.StringIO(), io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = _census_main(["--repo", str(tmp_path), "--ledger", str(ledger)])
        combined = out_buf.getvalue() + err_buf.getvalue()
        assert rc == 3, f"a missing tool must exit 3, got {rc}\n{combined}"
        assert "git" in combined and "not found" in combined, (
            f"the refusal must name the tool it wanted: {combined}")

    def test_the_wrapper_never_invents_a_tool_refusal(self, tmp_path):
        """The wrapper never reports a missing tool it did not need.

        The old wrapper reached 3 by running ``command -v jq`` itself and printing
        a sub-class of its own; that is the conflation this class pins out, and the
        load failure is pinned here too -- an interpreter that cannot resolve is 3
        on a plain line, not a traceback and not a false clean.
        """
        ledger = tmp_path / "wrapper-tool" / "noni" / "decisions"
        ledger.mkdir(parents=True)
        (ledger / "2026-10-01-alpha.json").write_text(
            json.dumps(_valid_record(), indent=2) + "\n", encoding="utf-8")
        rc, out = _run_sh(ledger)
        assert rc == 0, f"expected the census to run and exit 0: {rc}\n{out}"
        assert "not found" not in out, (
            f"the wrapper reported a tool it did not need: {out}")
        missing = tmp_path / "no-such-interpreter"
        proc = subprocess.run(["bash", str(CENSUS_SH), str(ledger)],
                              capture_output=True, text=True,
                              env=subprocess_env({"NONI_PYTHON": str(missing)}),
                              timeout=120)
        assert proc.returncode == 3, (
            f"a wrapper with no interpreter has no verdict to give: "
            f"rc={proc.returncode}\nout: {proc.stdout}\nerr: {proc.stderr}")
        combined = proc.stdout + proc.stderr
        assert "Traceback" not in combined, (
            f"a traceback is not a diagnostic: {combined}")
        assert str(missing) in combined, (
            f"the refusal must name the interpreter it could not resolve: {combined}")


class TestLedgerRowsAreSilentWhenThereIsSomethingToRead:
    """The two states where the empty class owes no row at all (issue #99).

    The class is a reporter of absence, so its contract has a negative half: a
    register that is present and current is not a ledger complaint, and a ledger
    that holds a record is not an empty one. Both were pinned on the census side
    before the wrappers were retargeted at the unified arbiter, and both are
    states a wrapper that grew a verdict of its own would break -- a shim that
    printed a ledger row beside the census's would print this one. The rows, not
    just the exit code, are the claim: exit 0 is also what a run that reported
    nothing at all looks like.
    """

    def test_sessions_present_without_a_ledger_is_exactly_one_ledger_empty_row(
        self, tmp_path
    ):
        """The two layers stay independent: sessions/ present and decisions/
        absent is one ledger-empty row and no ledger-record failure.

        A register is not a ledger. The run must still report the missing ledger
        once -- a census that stayed quiet here could not tell "nothing to
        census" apart from "the ledger went missing" -- and must not turn the
        present register into a record complaint or a second row of its own.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md",
                     _session_body("developer"))
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, f"expected 0, got {rc}\nstderr: {err}"
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert [r["check"] for r in rows] == ["ledger-empty"], f"unexpected rows: {rows}"

    def test_a_ledger_holding_a_record_produces_no_ledger_rows(self, tmp_path):
        """A ledger that holds a valid record emits no ledger-empty row (and no
        other ledger row): the state the class calls "ok" is silent.

        The counterpart of the case above, and the one that makes it mean
        something -- a class that always printed would satisfy nothing else.
        Silence is asserted as the empty row set, not as exit 0: the exit code is
        the same for a run that reported a finding of another class.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                     json.dumps(_valid_record(), indent=2))
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, f"expected 0, got {rc}\nstderr: {err}"
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert rows == [], f"expected no findings: {rows}"
