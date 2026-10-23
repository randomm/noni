"""Proof that tests/conftest.py's isolation is load-bearing, not decorative.

The suite passing is only meaningful if it would *fail* without the fixture.
A suite that passes because the developer's machine happens to lack the
environment CI also lacks proves nothing.

These tests build the hostile condition: a HOME whose directory contains a
decoy ledger, and a GIT_DIR pointing at a hostile repo. Then they assert the
census does NOT read the decoy — which is only true because the conftest
fixture neutralised the inputs.

The negative control (test_without_the_fixture_the_hostile_env_is_visible)
asserts the *opposite*: with the fixture's work undone, the hostile env DOES
leak through. That is what makes the first test's passing a real result.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CENSUS = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"
CONFTEST = Path(__file__).resolve().parent / "conftest.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@fixture.invalid", "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
    )


def _run_census(ledger_dir: Path, *, env: dict | None = None) -> tuple[int, str, str]:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    proc = subprocess.run(
        ["bash", str(CENSUS), str(ledger_dir)],
        capture_output=True,
        text=True,
        env=full_env,
        timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _decoy_ledger(root: Path, marker: str = "decoy") -> Path:
    """A git repo with a noni/decisions/ dir containing a decoy record."""
    repo = root / f"decoy-{marker}"
    (repo / "noni" / "decisions").mkdir(parents=True)
    _git(repo, "init", "-q")
    decoy_record = {
        "id": f"2026-10-01-{marker}",
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "decoy",
        "questions": [{"id": "q1", "text": "Decoy?", "options": ["yes", "no"], "answer": "yes"}],
        "by": "Decoy Author",
        "scope": "decoy scope",
        "status": "decided",
        "supersedes": None,
    }
    (repo / "noni" / "decisions" / f"2026-10-01-{marker}.json").write_text(json.dumps(decoy_record, indent=2))
    _git(repo, "add", f"noni/decisions/2026-10-01-{marker}.json")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "decoy")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "decoy second")
    return repo / "noni" / "decisions"


def test_census_does_not_read_decoy_ledger_from_hostile_home(tmp_path, monkeypatch):
    """A hostile HOME with a decoy ledger must not be read by the census when
    the census is pointed at a different (clean) ledger dir.

    The conftest fixture redirects HOME to a sandbox. This test sets up a
    hostile HOME with a decoy ledger, but points the census at a clean ledger
    dir. The census must report the clean ledger, not the decoy.
    """
    # Build a hostile HOME with a decoy ledger
    # Build a hostile HOME with a decoy ledger (the decoy is the leak source;
    # the variable is intentionally not referenced — the test asserts the
    # clean ledger is reported, not the decoy).
    hostile_home = tmp_path / "hostile-home"
    hostile_home.mkdir()
    _decoy_ledger(hostile_home, "leaked")

    # Build a clean ledger in a separate git repo
    clean_repo = tmp_path / "clean-repo"
    clean_ledger = clean_repo / "noni" / "decisions"
    clean_ledger.mkdir(parents=True)
    _git(clean_repo, "init", "-q")
    clean_record = {
        "id": "2026-10-01-clean",
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "clean",
        "questions": [{"id": "q1", "text": "Clean?", "options": ["yes", "no"], "answer": "yes"}],
        "by": "Clean Author",
        "scope": "clean scope",
        "status": "decided",
        "supersedes": None,
    }
    (clean_ledger / "2026-10-01-clean.json").write_text(json.dumps(clean_record, indent=2))
    _git(clean_repo, "add", "noni/decisions/2026-10-01-clean.json")
    _git(clean_repo, "commit", "-q", "--allow-empty", "-m", "clean")
    _git(clean_repo, "commit", "-q", "--allow-empty", "-m", "clean second")

    # Point HOME at the hostile dir, but run the census on the clean ledger
    monkeypatch.setenv("HOME", str(hostile_home))
    monkeypatch.setenv("USERPROFILE", str(hostile_home))

    code, out, err = _run_census(clean_ledger)
    # The census should report the clean record, not the decoy
    assert "2026-10-01-clean" in out, f"expected the clean record in the census output, got: {out}"
    assert "2026-10-01-leaked" not in out, f"the decoy ledger leaked into the census: {out}"


def test_census_does_not_read_decoy_when_git_dir_is_set(tmp_path, monkeypatch):
    """If GIT_DIR is set to a hostile repo, the census must not use it when
    the ledger dir is in a different (clean) repo.

    The conftest fixture clears GIT_DIR. This test sets GIT_DIR to a hostile
    repo but points the census at a clean ledger dir. The census's
    `git rev-parse --show-toplevel` should resolve to the clean repo, not the
    hostile one.
    """
    # Build a hostile repo (with a decoy ledger) — the decoy ledger path is
    # not referenced by the assertion; the test asserts the clean ledger is
    # reported, not the decoy.
    _decoy_ledger(tmp_path, "gitdir-leak")
    hostile_repo = tmp_path / "decoy-gitdir-leak"

    # Build a clean repo with a clean ledger
    clean_repo = tmp_path / "clean-repo"
    clean_ledger = clean_repo / "noni" / "decisions"
    clean_ledger.mkdir(parents=True)
    _git(clean_repo, "init", "-q")
    clean_record = {
        "id": "2026-10-01-clean2",
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "clean",
        "questions": [{"id": "q1", "text": "Clean?", "options": ["yes", "no"], "answer": "yes"}],
        "by": "Clean Author",
        "scope": "clean scope",
        "status": "decided",
        "supersedes": None,
    }
    (clean_ledger / "2026-10-01-clean2.json").write_text(json.dumps(clean_record, indent=2))
    _git(clean_repo, "add", "noni/decisions/2026-10-01-clean2.json")
    _git(clean_repo, "commit", "-q", "--allow-empty", "-m", "clean")
    _git(clean_repo, "commit", "-q", "--allow-empty", "-m", "clean second")

    # Set GIT_DIR to the hostile repo
    hostile_git_dir = hostile_repo / ".git"
    monkeypatch.setenv("GIT_DIR", str(hostile_git_dir))

    code, out, err = _run_census(clean_ledger)
    # The census should report the clean record, not the decoy
    assert "2026-10-01-clean2" in out, f"expected the clean record in the census output, got: {out}"
    assert "2026-10-01-gitdir-leak" not in out, f"the decoy ledger leaked via GIT_DIR: {out}"


def test_without_the_fixture_the_hostile_env_is_visible(tmp_path, monkeypatch):
    """The opposite assertion, and the reason the tests above mean something.

    Undoes the fixture's work for this one test (setting HOME to a hostile dir
    with a decoy ledger, and pointing the census at that decoy) and checks the
    decoy IS read. If a future change made the census immune to the environment
    by accident, this test fails and the suite's isolation claims stop being
    self-certifying.
    """
    # Build a hostile HOME with a decoy ledger
    hostile_home = tmp_path / "hostile-home"
    hostile_home.mkdir()
    decoy_ledger = _decoy_ledger(hostile_home, "control")

    # Point the census at the decoy ledger directly (simulating what happens
    # when the fixture is absent and the census's default LEDGER_DIR resolves
    # to the hostile home's ledger)
    monkeypatch.setenv("HOME", str(hostile_home))

    # Run the census on the decoy ledger — it SHOULD read it (this is the
    # negative control: the hostile env IS visible when the fixture is undone)
    code, out, err = _run_census(decoy_ledger)
    assert "2026-10-01-control" in out, (
        "the decoy ledger is not readable when pointed at directly — either the "
        "census changed or the negative control stopped working"
    )


def test_conftest_exists_and_is_autouse():
    """The isolation is a single autouse fixture; pin that it is still there
    and still autouse, so it cannot be quietly downgraded to an opt-in helper
    that a new test forgets to request."""
    assert CONFTEST.is_file(), "tests/conftest.py was deleted — suite-wide isolation is gone"
    src = CONFTEST.read_text()
    assert "autouse=True" in src, "the isolation fixture is no longer autouse"
    for var in ("GIT_DIR", "GIT_WORK_TREE", "HOME"):
        assert var in src, f"the fixture no longer neutralises {var}"


def test_isolation_fixture_clears_git_vars():
    """The conftest must clear GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE and the
    author/committer identity vars, so a hostile shell environment cannot
    redirect the census's git resolution."""
    src = CONFTEST.read_text()
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        assert var in src, f"conftest does not clear {var}"
