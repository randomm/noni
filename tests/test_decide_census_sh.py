"""The census shell wrapper as decide.py's tests exercise it.

Extracted from the decide writer suite: the wrapper script's contract, driven
through the same fixture the writer's tests use.

The wrapper runs the unified census over the ledger group (issue #99), and the
unified census is a *findings* report: a clean record earns no row, so identity
can no longer be asserted by looking for a record id in a report the wrapper does
not print. The tests below ask the wrapper to *fail* on the state root's tree and
assert the finding it reports -- which is the same claim (whose ledger did this
run read?) stated in the currency both entry points share.
"""


from decide_hardening_fixtures import (
    _census_sh_case,
    _census_sh_from,
    _census_sh_snapshot,
)


def test_census_sh_censuses_the_ledger_it_was_given_from_a_foreign_cwd(tmp_path):
    """The shim reports the state root's ledger while the cwd holds a decoy
    ledger with a record of its own beside it.

    The decoy's one committed record is broken here and the state root's is
    valid, so only a run that resolved its ledger from the cwd could exit 0: the
    state root's clean tree is what the exit code reports, and the decoy's id
    never appears.
    """
    root, decoy, cwd = _census_sh_case(tmp_path)
    (decoy / "noni" / "decisions" / "2026-10-01-baseline.json").write_text(
        "{ not json\n", encoding="utf-8")
    proc = _census_sh_from(cwd, str(root / "noni" / "decisions"))
    assert proc.returncode == 0, f"{proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert "2026-10-01-baseline" not in proc.stdout + proc.stderr, (
        f"a run that read the decoy reported its unparseable record: {proc.stdout}")


def test_census_sh_reports_the_state_roots_own_violation_not_the_decoys(tmp_path):
    """The half that makes the test above mean something: the state root's ledger
    is broken and the decoy beside the cwd is clean, so only a run that read
    the path it was given can report 10.

    A wrapper still driven by the cwd would have found the decoy's valid record
    and exited 0, calling a broken ledger clean.
    """
    root, _decoy, cwd = _census_sh_case(tmp_path)
    broken = root / "noni" / "decisions" / "2026-10-02-broken.json"
    broken.write_text("{ not json\n", encoding="utf-8")
    proc = _census_sh_from(cwd, str(root / "noni" / "decisions"))
    assert proc.returncode == 10, f"{proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert "2026-10-02-broken" in proc.stdout, proc.stdout


def test_census_sh_refuses_a_missing_ledger_dir_with_its_own_code(tmp_path):
    """A ledger directory that does not exist is the usage refusal (2) naming the
    path, with no report rows, from a cwd beside a decoy ledger.

    The refusal is the wrapper's own, and it has to be: the unified census takes
    ``--repo`` and audits the tree, so a path the caller named and which is not
    there is invisible to a run over the tree around it -- and a census that read
    nothing must not exit 0, which whoever scripted it would read as a clean
    ledger.
    """
    _root, decoy, cwd = _census_sh_case(tmp_path)
    before = _census_sh_snapshot(decoy)
    missing = tmp_path / "no-such-state-root" / "noni" / "decisions"
    proc = _census_sh_from(cwd, str(missing))
    assert proc.returncode == 2, f"{proc.returncode}\n{proc.stderr}"
    assert str(missing) in proc.stderr, proc.stderr
    assert "summary:" not in proc.stdout, (
        f"a refused run printed a report: {proc.stdout}")
    assert _census_sh_snapshot(decoy) == before, "the refused run touched the decoy"
