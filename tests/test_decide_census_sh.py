"""The census shell wrapper as decide.py's tests exercise it.

Extracted from the decide writer suite: the wrapper script's contract, driven
through the same fixture the writer's tests use."""

import shutil

from decide_fixtures import (
    BASELINE_ID,
)
from decide_hardening_fixtures import (
    _census_sh_case,
    _census_sh_from,
    _census_sh_snapshot,
)


def test_census_sh_censuses_the_ledger_it_was_given_from_a_foreign_cwd(tmp_path):
    """The shim reports the state root's record while the cwd holds a decoy
    ledger with a record of its own beside it.

    Both ledgers are clean, so the assertion is on identity rather than code:
    the rows that come out are the state root's, and the decoy's never appear.
    """
    root, _decoy, cwd = _census_sh_case(tmp_path)
    proc = _census_sh_from(cwd, str(root / "noni" / "decisions"))
    assert proc.returncode == 0, f"{proc.returncode}\n{proc.stderr}"
    assert BASELINE_ID in proc.stdout, proc.stdout


def test_census_sh_reports_the_state_roots_own_violation_not_the_decoys(tmp_path):
    """The half that makes the test above mean something: the state root's ledger
    is broken and the decoy beside the cwd is clean, so only a run that read
    the path it was given can report 10.

    A shim still driven by the cwd would have found the decoy's valid record
    and exited 0, calling a broken ledger clean.
    """
    root, _decoy, cwd = _census_sh_case(tmp_path)
    broken = root / "noni" / "decisions" / "2026-10-02-broken.json"
    broken.write_text("{ not json\n", encoding="utf-8")
    proc = _census_sh_from(cwd, str(root / "noni" / "decisions"))
    assert proc.returncode == 10, f"{proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert "10:unparseable" in proc.stderr, proc.stderr


def test_census_sh_refuses_a_missing_ledger_dir_with_its_own_code(tmp_path):
    """--repo-style fail closed, in the shim's own exit-code shape: a ledger
    directory that does not exist is exit 10 (10:missing-dir) naming the path,
    with no report rows, from a cwd beside a decoy ledger.

    The unified census has its own codes for the same state; this is the shim's
    contract (references/census.md), which the legacy table documents and no
    other entry point shares.
    """
    _root, decoy, cwd = _census_sh_case(tmp_path)
    before = _census_sh_snapshot(decoy)
    missing = tmp_path / "no-such-state-root" / "noni" / "decisions"
    proc = _census_sh_from(cwd, str(missing))
    assert proc.returncode == 10, f"{proc.returncode}\n{proc.stderr}"
    assert "10:missing-dir" in proc.stderr, proc.stderr
    assert "no-such-state-root" in proc.stderr, (
        f"the refusal must name the state root it was given: {proc.stderr}"
    )
    assert proc.stdout.strip() == "", (
        f"a census that could not read its ledger printed a report: {proc.stdout}"
    )
    assert _census_sh_snapshot(decoy) == before, (
        "a refused run read the decoy ledger beside its cwd"
    )


def test_census_sh_refuses_a_ledger_path_that_is_not_a_directory(tmp_path):
    """The second state of the pair: the path exists and is not a directory.

    A plain file passes a bare existence test, so a shim that checked only for
    a path would go on to enumerate it and report an empty ledger. It refuses
    with the same code and names the path instead.
    """
    _root, decoy, cwd = _census_sh_case(tmp_path)
    before = _census_sh_snapshot(decoy)
    not_a_dir = tmp_path / "state-root-is-a-file"
    not_a_dir.write_text("i am a file, not a state root\n", encoding="utf-8")
    proc = _census_sh_from(cwd, str(not_a_dir))
    assert proc.returncode == 10, f"{proc.returncode}\n{proc.stderr}"
    assert "10:missing-dir" in proc.stderr, proc.stderr
    assert "state-root-is-a-file" in proc.stderr, proc.stderr
    assert proc.stdout.strip() == "", proc.stdout
    assert _census_sh_snapshot(decoy) == before


def test_census_sh_refuses_a_ledger_dir_it_cannot_read(tmp_path):
    """A ledger directory that cannot be enumerated is 10:empty-ledger, not a
    silent clean.

    This is the state the enumeration guard already owned and this pins: the
    directory exists (``-d`` answers yes — read permission is not what the
    test removes) but ``find`` cannot list it, and the script has to tell that
    apart from a genuinely empty ledger. An empty directory and a blind census
    share the code; only the message separates them, and the message is what
    says "the ledger is unusable here" rather than "nothing to report".
    """
    _root, _decoy, cwd = _census_sh_case(tmp_path)
    unreadable = tmp_path / "unreadable-ledger"
    unreadable.mkdir()
    (unreadable / "2026-10-01-hidden.json").write_text("{}\n", encoding="utf-8")
    unreadable.chmod(0o000)
    try:
        proc = _census_sh_from(cwd, str(unreadable))
    finally:
        unreadable.chmod(0o755)
    assert proc.returncode == 10, f"{proc.returncode}\n{proc.stderr}"
    assert "find failed to enumerate" in proc.stderr, proc.stderr
    assert "unreadable-ledger" in proc.stderr, proc.stderr
    # The code is asserted as the printed label, not as a substring of it: the
    # sibling branch below prints `42:ledger-empty` and a check that matched
    # "empty-ledger" alone was satisfied by either, so it could not tell a blind
    # census from a recordless one (the pair the agreement test in
    # tests/test_census_ledger_empty.py asserts the same way).
    assert "(10:empty-ledger)" in proc.stderr, proc.stderr
    assert "42:ledger-empty" not in proc.stderr, proc.stderr
    # The header row still goes to stdout (that print is the shim's long-standing
    # shape for every path through the report, and this test is about the
    # ledger's state, not about it). What matters is that no record rows follow:
    # a census that could not list the directory has no records to name.
    assert proc.stdout.strip() == "id\tdate\tby\tstatus\tlive\tsupersedes", proc.stdout


def test_census_sh_refuses_a_broken_symlink_ledger_dir(tmp_path):
    """A ledger path that is a symlink to nothing is the same refusal.

    ``-d`` answers no for it and ``-e`` answers no as well, so a shim with one
    existence test cannot tell this from a plain missing path; both are
    refused, and the message names the path the caller passed.
    """
    _root, _decoy, cwd = _census_sh_case(tmp_path)
    dangling = tmp_path / "dangling-ledger"
    dangling.symlink_to(tmp_path / "nowhere" / "noni" / "decisions")
    proc = _census_sh_from(cwd, str(dangling))
    assert proc.returncode == 10, f"{proc.returncode}\n{proc.stderr}"
    assert "10:missing-dir" in proc.stderr, proc.stderr
    assert "dangling-ledger" in proc.stderr, proc.stderr


def test_census_sh_takes_no_ledger_from_the_cwd_when_given_none(tmp_path):
    """No argument, from a cwd holding a complete decoy ledger: exit 2, no rows.

    The regression this pins is the shim's old ``LEDGER_DIR="."`` default: with
    it, a bare ``census.sh`` audited the caller's cwd, so a script that forgot
    the argument got a report about whatever directory it happened to run in
    and an exit code that looked like a verdict on its own state root. The run
    refuses instead, and the decoy stays unread.
    """
    _root, decoy, cwd = _census_sh_case(tmp_path)
    shutil.copytree(decoy / "noni" / "decisions", cwd / "noni" / "decisions")
    before = _census_sh_snapshot(decoy)
    proc = _census_sh_from(cwd)
    assert proc.returncode == 2, f"{proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert proc.stdout.strip() == "", f"the shim censused its cwd: {proc.stdout}"
    assert "noni/decisions" in proc.stderr, (
        f"the refusal must name the argument it needs: {proc.stderr}"
    )
    assert _census_sh_snapshot(decoy) == before


def test_census_sh_help_advertises_the_state_root_it_requires(tmp_path):
    """The help text names the state directory as an argument, not as an
    optional one: a reader who runs the shim with no argument reads the help
    first, and the help must be the rule the script enforces.
    """
    proc = _census_sh_from(tmp_path, "--help")
    assert proc.returncode == 0, proc.stderr
    assert "census.sh <state-root>/noni/decisions" in proc.stdout, proc.stdout


def test_census_sh_refuses_an_unknown_option_before_any_probe(tmp_path):
    """A flag the shim does not implement is a usage error (2), not an ignored word.

    The loop used to swallow every ``-*`` argument, so ``census.sh --json <dir>``
    printed the human report and exited 0: the caller believed it had machine
    output and a clean ledger. The refusal fires before jq or git is consulted,
    so a typo is answered by the same exit code a missing argument gets and the
    decoy ledger beside the cwd is never opened.
    """
    _root, decoy, cwd = _census_sh_case(tmp_path)
    before = _census_sh_snapshot(decoy)
    proc = _census_sh_from(cwd, "--json", str(decoy / "noni" / "decisions"))
    assert proc.returncode == 2, f"{proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert proc.stdout.strip() == "", f"a refused run printed a report: {proc.stdout}"
    assert "--json" in proc.stderr, f"the refusal must name the word it refused: {proc.stderr}"
    assert "usage:" in proc.stderr, f"the refusal must give the correct shape: {proc.stderr}"
    assert _census_sh_snapshot(decoy) == before, (
        "a refused run read the ledger it was handed after refusing the option"
    )


def test_census_sh_refuses_two_ledger_arguments(tmp_path):
    """Two positionals are a usage error (2), not a census of whichever came last.

    The loop kept the final positional, so ``census.sh A B`` reported on B and
    exited 0: a caller whose command line was built by hand, or by a script that
    appended the path twice, got a clean verdict about one tree and silence
    about the other. Naming both is refused instead, and neither is read.
    """
    root, decoy, cwd = _census_sh_case(tmp_path)
    before = (_census_sh_snapshot(decoy), _census_sh_snapshot(root))
    proc = _census_sh_from(cwd, str(root / "noni" / "decisions"),
                           str(decoy / "noni" / "decisions"))
    assert proc.returncode == 2, f"{proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert proc.stdout.strip() == "", f"a refused run printed a report: {proc.stdout}"
    assert "usage:" in proc.stderr, f"the refusal must give the correct shape: {proc.stderr}"
    assert (_census_sh_snapshot(decoy), _census_sh_snapshot(root)) == before
