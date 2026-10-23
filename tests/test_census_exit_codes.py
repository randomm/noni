"""Test the census exit codes against one committed golden fixture per code.

Each golden fixture under tests/fixtures/census-exit-<code>.json describes the
ledger tree and the environment condition the test must set up. The test reads
the fixture, builds the tree in tmp_path, runs the census, and asserts the
exit code. A fixture that is wrong for its code makes the corresponding test
fail, so the fixtures and the script cannot disagree.

The exit codes are:
  0   clean — every record valid, chain intact
  3   jq not found on the reading machine
  10  a record is missing or malformed (schema violation)
  12  a record was edited after commit (working tree differs from git)
  20  the supersede chain is broken (dangling, duplicate, orphan, or a
      chain resolving to zero or more than one live record)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO = Path(__file__).resolve().parent.parent
CENSUS = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid", "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
    )


def _setup_ledger(
    tmp_path: Path,
    ledger_name: str,
    records: dict[str, dict],
    commit_order: list[str] | None,
    committed_version: dict | None = None,
    working_tree_version: dict | None = None,
    exit_code: int = 0,
) -> Path:
    """Build a ledger tree in tmp_path from a fixture's record dict.

    If commit_order is given, each record is committed in that order (for
    git-based fixtures). If committed_version / working_tree_version are given
    (exit-12), the committed version is committed first and the working-tree
    version is written on top.
    """
    repo = tmp_path / "repo"
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    _git(repo, "init", "-q")

    if commit_order:
        for fname in commit_order:
            if fname in records:
                content = json.dumps(records[fname], indent=2)
                (ledger / fname).write_text(content)
                _git(repo, "add", "noni/decisions/" + fname)
                _git(repo, "commit", "-q", "--allow-empty", "-m", f"add {fname}")
    else:
        for fname, rec in records.items():
            content = json.dumps(rec, indent=2)
            (ledger / fname).write_text(content)

    if committed_version is not None:
        # exit-12: commit the committed_version, then write the working_tree_version
        fname = list(records.keys())[0]
        content = json.dumps(committed_version, indent=2)
        (ledger / fname).write_text(content)
        _git(repo, "add", "noni/decisions/" + fname)
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"add {fname} (committed version)")
        if working_tree_version is not None:
            content = json.dumps(working_tree_version, indent=2)
            (ledger / fname).write_text(content)

    return ledger


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_exit_0_clean(tmp_path, run_census):
    """A clean ledger (valid records, intact chain, no edits, prior commits)
    exits 0."""
    fx = _fixture("census-exit-0.json")
    assert fx["exit_code"] == 0
    ledger = _setup_ledger(
        tmp_path, "repo", fx["records"], fx["setup"].get("commit_order"),
        exit_code=fx["exit_code"],
    )
    code, out, err = run_census(ledger)
    assert code == 0, f"expected exit 0, got {code}\nstderr: {err}\nstdout: {out}"


def test_exit_3_jq_missing(tmp_path, run_census):
    """With jq absent from PATH, the census exits 3 (missing dependency)."""
    fx = _fixture("census-exit-3.json")
    assert fx["exit_code"] == 3
    ledger = _setup_ledger(
        tmp_path, "repo", fx["records"], fx["setup"].get("commit_order"),
        exit_code=fx["exit_code"],
    )
    # Build a PATH that has `bash` (so the census can run) but no `jq`
    # (so the census exits 3). Symlink the real bash into a temp dir.
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    import shutil as _shutil
    real_bash = _shutil.which("bash")
    assert real_bash, "bash not found on this system"
    (fake_bin / "bash").symlink_to(real_bash)
    env = {"PATH": str(fake_bin)}
    code, out, err = run_census(ledger, env=env)
    assert code == 3, f"expected exit 3, got {code}\nstderr: {err}\nstdout: {out}"
    assert "jq" in err.lower() or "jq" in out.lower()


def test_exit_10_schema_violation(tmp_path, run_census):
    """A record with a missing field (or other schema violation) exits 10."""
    fx = _fixture("census-exit-10.json")
    assert fx["exit_code"] == 10
    ledger = _setup_ledger(
        tmp_path, "repo", fx["records"], fx["setup"].get("commit_order"),
        exit_code=fx["exit_code"],
    )
    code, out, err = run_census(ledger)
    assert code == 10, f"expected exit 10, got {code}\nstderr: {err}\nstdout: {out}"


def test_exit_12_edited_after_commit(tmp_path, run_census):
    """A record committed, then edited in the working tree (status changed
    from decided to open), exits 12."""
    fx = _fixture("census-exit-12.json")
    assert fx["exit_code"] == 12
    ledger = _setup_ledger(
        tmp_path, "repo", fx["records"], fx["setup"].get("commit_order"),
        committed_version=fx["setup"].get("committed_version"),
        working_tree_version=fx["setup"].get("working_tree_version"),
        exit_code=fx["exit_code"],
    )
    code, out, err = run_census(ledger)
    assert code == 12, f"expected exit 12, got {code}\nstderr: {err}\nstdout: {out}"


def test_exit_20_broken_chain(tmp_path, run_census):
    """A record with a dangling supersedes (names a non-existent id) exits 20."""
    fx = _fixture("census-exit-20.json")
    assert fx["exit_code"] == 20
    ledger = _setup_ledger(
        tmp_path, "repo", fx["records"], fx["setup"].get("commit_order"),
        exit_code=fx["exit_code"],
    )
    code, out, err = run_census(ledger)
    assert code == 20, f"expected exit 20, got {code}\nstderr: {err}\nstdout: {out}"
    assert "dangling" in err.lower() or "chain" in err.lower()


def test_exit_20_zero_live_chain(tmp_path, run_census):
    """A chain in which every record is superseded (root superseded by the
    successor, successor also marked superseded) resolves to zero live
    records and exits 20."""
    fx = _fixture("census-exit-20-zero-live.json")
    assert fx["exit_code"] == 20
    ledger = _setup_ledger(
        tmp_path, "repo", fx["records"], fx["setup"].get("commit_order"),
        exit_code=fx["exit_code"],
    )
    code, out, err = run_census(ledger)
    assert code == 20, f"expected exit 20 for zero-live chain, got {code}\nstderr: {err}\nstdout: {out}"
    assert "zero-live" in err, f"expected 'zero-live' in stderr, got: {err}"


def test_exit_20_multi_live_chain(tmp_path, run_census):
    """A chain in which the superseded root was never marked superseded
    resolves to more than one live record and exits 20."""
    fx = _fixture("census-exit-20-multi-live.json")
    assert fx["exit_code"] == 20
    ledger = _setup_ledger(
        tmp_path, "repo", fx["records"], fx["setup"].get("commit_order"),
        exit_code=fx["exit_code"],
    )
    code, out, err = run_census(ledger)
    assert code == 20, f"expected exit 20 for multi-live chain, got {code}\nstderr: {err}\nstdout: {out}"
    assert "multi-live" in err, f"expected 'multi-live' in stderr, got: {err}"


def test_every_fixture_has_its_exit_code():
    """The fixture's exit_code field matches the code in the filename, so a
    rename or a wrong fixture cannot slip through unnoticed."""
    for f in sorted(FIXTURES.glob("census-exit-*.json")):
        fx = _fixture(f.name)
        # The name is census-exit-<code> or census-exit-<code>-<suffix>; the
        # code is the first integer segment after the prefix.
        code_in_name = int(f.stem.replace("census-exit-", "").split("-", 1)[0])
        assert fx["exit_code"] == code_in_name, (
            f"{f.name}: exit_code in fixture is {fx['exit_code']} but filename says {code_in_name}"
        )
