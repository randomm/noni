"""Every shipped sessions-census route names its state root and refuses to invent one.

No cwd-relative state default in any entry point, no write under the cwd, no read of
a decoy beside it, and no second positional.

Split out of ``tests/test_sessions_census.py``; the builders are in
``tests/sessions_census_fixtures.py``.
"""

from __future__ import annotations

from pathlib import Path

from sessions_census_fixtures import (
    _routes,
    _run_argv,
    _sessions_census_case,
)

REPO = Path(__file__).resolve().parent.parent

# --- Every entry point names the state root; none resolves it from the cwd -----
#
# The module, the .sh wrapper and the steering-ledger --sessions dispatch are
# three routes to one arbiter. A cwd-relative default on any of them would
# census (and report clean for) a register the caller never pointed at, so the
# rule is pinned per route: the run reads the directory it was given, and with
# no directory it fails closed with exit 2 rather than inventing one.

# The three routes the product documents. The package module itself is not one
# of them: it imports ``from . import labels``, so running it by path fails on
# the import rather than censusing anything, and the in-place entry point the
# skills sell is the thin wrapper beside it.
CENSUS_SH = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"
SHIM = REPO / "skills" / "sessions-claims" / "scripts" / "census-sessions.sh"
WRAPPER = REPO / "skills" / "sessions-claims" / "scripts" / "census-sessions.py"


def test_no_shipped_entry_point_carries_a_cwd_relative_state_default():
    """The census's cwd-relative defaults are gone from every entry point, and
    a new one cannot quietly reintroduce one.

    Three sites used to resolve state from wherever the run sat: the package
    module defaulted to ``Path("noni/sessions")``, the sessions shim to the
    same relative path, and the steering-ledger shim to ``"."``. A default of
    that shape is not a convenience here -- it is a verdict on a tree the
    caller never named, reported in the same bytes as a verdict on the state
    root. This pins the absence of the shape itself, on top of the behavioural
    tests above that pin the refusal.
    """
    sites = {
        "src/noni/census_sessions.py": ['Path("noni/sessions")',
                                        "Path('noni/sessions')"],
        "skills/sessions-claims/scripts/census-sessions.sh":
            ['SESSIONS_DIR="noni/sessions"', 'SESSIONS_DIR="."',
             'SESSIONS_DIR="$PWD'],
        "skills/steering-ledger/scripts/census.sh": ['LEDGER_DIR="."',
                                                     'LEDGER_DIR="./"',
                                                     'LEDGER_DIR="$PWD"'],
    }
    for rel, banned in sites.items():
        source = (REPO / rel).read_text(encoding="utf-8")
        for needle in banned:
            assert needle not in source, f"{rel} still defaults state to {needle!r}"


def test_no_route_writes_anything_under_the_cwd(tmp_path):
    """All three routes, pointed at the state root from a foreign cwd, leave it
    empty: the census is read-only, and a cwd it cannot read from is the one
    place it must not end up having touched.

    The one file a launched interpreter is allowed to leave behind is its own
    coverage data file (the gate measures subprocesses, and the launched
    interpreter writes its data where it starts). Those are named, not swept:
    the assertion is about ``noni/``, and it still fails on anything else.
    """
    root, _decoy, cwd = _sessions_census_case(tmp_path)
    for argv in _routes(cwd, root):
        proc = _run_argv(cwd, argv)
        assert proc.returncode == 0, f"{argv[:3]}: {proc.returncode}\n{proc.stderr}"
        strays = [p.name for p in cwd.iterdir() if not p.name.startswith(".coverage")]
        assert strays == [], f"{argv[:3]} wrote under the cwd: {strays}"
        assert not (cwd / "noni").exists(), f"{argv[:3]} created noni/ under the cwd"


def test_no_route_reads_a_decoy_beside_the_cwd(tmp_path):
    """All three routes read the state root and not the decoy beside the cwd.

    The decoy carries a double-claim, so exit 0 is the only answer that can
    come from the right directory: a route still driven by the cwd would have
    reported 30 for the register sitting next to it.
    """
    root, _decoy, cwd = _sessions_census_case(tmp_path)
    for argv in _routes(cwd, root):
        proc = _run_argv(cwd, argv)
        assert proc.returncode == 0, f"{argv[:3]}: {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
        assert "#999" not in proc.stdout, f"{argv[:3]} read the decoy register"


def test_every_route_refuses_a_missing_sessions_dir(tmp_path):
    """The state root's sessions directory removed: every route fails closed.

    A census that cannot find its register has no findings to report, and a
    run that printed nothing and exited 0 would be read as a clean census by
    whoever scripted it. The refusal names the path it was given and exits 2.
    """
    root, _decoy, cwd = _sessions_census_case(tmp_path)
    for name in root.iterdir():
        name.unlink()
    root.rmdir()
    for argv in _routes(cwd, root):
        proc = _run_argv(cwd, argv)
        assert proc.returncode == 2, f"{argv[:3]}: {proc.returncode}\n{proc.stderr}"
        assert "noni" in proc.stderr, f"{argv[:3]} must name the path: {proc.stderr}"
        assert str(root) in proc.stderr, f"{argv[:3]} must name the path it failed on: {proc.stderr}"
        assert proc.stdout.strip() == "", f"{argv[:3]} printed rows for a tree it could not read"


def test_every_route_refuses_a_sessions_dir_that_is_not_a_directory(tmp_path):
    """The same refusal for a sessions path that exists but is not a directory.

    The two states are the pair the contract pins: a missing path and a path
    that answers to something else (here a plain file) are both usage errors,
    not a census over an empty register.
    """
    root, _decoy, cwd = _sessions_census_case(tmp_path)
    for name in root.iterdir():
        name.unlink()
    root.rmdir()
    root.write_text("i am a file, not a sessions directory\n", encoding="utf-8")
    for argv in _routes(cwd, root):
        proc = _run_argv(cwd, argv)
        assert proc.returncode == 2, f"{argv[:3]}: {proc.returncode}\n{proc.stderr}"
        assert str(root) in proc.stderr, f"{argv[:3]} must name the path: {proc.stderr}"
        assert proc.stdout.strip() == "", f"{argv[:3]} printed rows for a non-directory"


def test_no_route_invents_a_state_root_when_given_no_argument(tmp_path):
    """No argument, from a cwd holding a complete decoy register: exit 2 on every
    route, and no NDJSON row.

    This is the regression the cwd-relative defaults used to allow. With a
    default of ``noni/sessions`` the run would have found the decoy and
    reported 30 for a register nobody pointed it at; with a default of ``.``
    (the steering-ledger shim's old one) it would have audited the cwd as a
    ledger. Either way the exit code would have described a tree other than
    the caller's.
    """
    _root, decoy, cwd = _sessions_census_case(tmp_path)
    assert decoy.is_dir(), "the decoy is the whole point: it must be there to be refused"
    for argv in _routes(cwd, None):
        proc = _run_argv(cwd, argv)
        assert proc.returncode == 2, f"{argv[:3]}: {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
        assert proc.stdout.strip() == "", f"{argv[:3]} censused the decoy: {proc.stdout}"


def test_every_route_refuses_a_second_positional(tmp_path):
    """Two directories named is a usage error (2) on every route, with no row.

    One run censuses one register. The decisions census already refuses a second
    positional (`census.sh`: "one ledger directory at most"), and a sessions
    route that took two silently censused only the first: the caller who typed
    two paths got a verdict on one of them and no signal that the other was
    never read. The refusal is one line on stderr naming both paths given, and
    the second path is the one the caller mistyped, so naming it is what makes
    the refusal actionable.
    """
    root, decoy, cwd = _sessions_census_case(tmp_path)
    for argv in _routes(cwd, root):
        proc = _run_argv(cwd, argv + [str(decoy)])
        assert proc.returncode == 2, f"{argv[:3]}: {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
        assert proc.stdout.strip() == "", f"{argv[:3]} censused one of two: {proc.stdout}"
        assert "at most" in proc.stderr, f"{argv[:3]}: {proc.stderr}"
        assert str(decoy) in proc.stderr, f"{argv[:3]} must name the extra path: {proc.stderr}"
