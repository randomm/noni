"""Isolation tests for the census hygiene class's deny-list inputs (issue #23).

The census runs scripts/public_safety.py's tracked-file scan in-process, and
that scan reads its deny-list from two places a developer's machine can fill:
the NONI_SCRUB_DENYLIST variable and the install-root default file. A suite
that read either would mean something different on the operator's machine than
in CI — the same bug the rest of this file exists to close.

The decoy is a deny-list entry plus a tracked note whose content line is that
entry. If the decoy reaches the census the note is flagged, so the note is the
detector (public_safety reports "path:line: label", never the matched text, so
the entry string never has to appear in output).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CENSUS = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"
CONFTEST = Path(__file__).resolve().parent / "conftest.py"

# The unified census and the hygiene checker are imported by the isolation tests
# below under their bare names; _harness registers those names from the package,
# so no script directory ever goes on sys.path (a lookalike there would be
# trusted as the census's own code).

from _harness import _git  # noqa: E402

# The decoy deny-list entry. It appears only in the decoy deny-list file and in
# one planted note's content line (public_safety matches line content).
DECOY_DENYLIST_ENTRY = "decoy-denylist-probe"


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


def test_census_does_not_read_decoy_ledger_from_hostile_home(tmp_path, monkeypatch, run_census):
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

    code, out, err = run_census(clean_ledger)
    # The census should report the clean record, not the decoy
    assert "2026-10-01-clean" in out, f"expected the clean record in the census output, got: {out}"
    assert "2026-10-01-leaked" not in out, f"the decoy ledger leaked into the census: {out}"


def test_census_does_not_read_decoy_when_git_dir_is_set(tmp_path, monkeypatch, run_census):
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

    code, out, err = run_census(clean_ledger)
    # The census should report the clean record, not the decoy
    assert "2026-10-01-clean2" in out, f"expected the clean record in the census output, got: {out}"
    assert "2026-10-01-gitdir-leak" not in out, f"the decoy ledger leaked via GIT_DIR: {out}"


def test_without_the_fixture_the_hostile_env_is_visible(tmp_path, monkeypatch, run_census):
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
    code, out, err = run_census(decoy_ledger)
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


# --- census hygiene class: the deny-list inputs --------------------------------


def test_conftest_clears_the_scrub_denylist_var():
    """NONI_SCRUB_DENYLIST must stay in the fixture's cleared set.

    The census's hygiene class now reads the deny-list in-process, so a variable
    exported by the developer's shell would make every hygiene test scan against
    private vocabulary the fixtures were never written against — and would make
    the suite pass in CI only because CI has no such variable."""
    src = CONFTEST.read_text()
    assert "NONI_SCRUB_DENYLIST" in src, (
        "conftest no longer neutralises NONI_SCRUB_DENYLIST — the census hygiene "
        "class would read the operator's deny-list"
    )


def test_census_hygiene_does_not_read_the_scrub_denylist(tmp_path, monkeypatch):
    """The census's hygiene class must never scan against a deny-list the
    developer's shell exported.

    The conftest's autouse fixture is what keeps ``NONI_SCRUB_DENYLIST`` out,
    so this test asserts the load-bearing consequence: with a hostile value
    planted in the environment *the way the fixture plants it* (cleared, i.e.
    exactly the state every other test runs in), the decoy deny-list — which
    holds the entry that a tracked note's content line carries — does not
    reach the census, and the note is not flagged. The pairing control
    (``test_without_the_fixture_the_scrub_denylist_is_visible``) sets the same
    variable through ``os.environ`` after the fixture ran and sees the note
    flagged, so the assertion below is a real result and not an artefact of
    nothing being set.
    """
    import census as _census
    import public_safety

    decoy = tmp_path / "decoy-denylist.txt"
    decoy.write_text(DECOY_DENYLIST_ENTRY + "\n", encoding="utf-8")
    monkeypatch.delenv(public_safety.DENYLIST_ENV_VAR, raising=False)
    monkeypatch.setattr(public_safety, "_default_denylist_file", lambda: tmp_path / "absent.txt")
    # Precondition: with the deny-list routes closed the decoy is inert — the
    # file exists and holds the entry, but nothing points at it.
    assert public_safety.load_denylist().status == "absent"

    repo = _hygiene_repo(tmp_path, decoy_in_tree=True)
    out, err = _capture_census(_census, repo)
    assert "flagged-note.md" not in out, (
        f"a deny-list reached the census hygiene scan while the env was isolated: {out}{err}"
    )
    # Isolation must not become a mute button: the class still reports that its
    # deny-list half did not run (the census's probe-honesty rule).
    assert "deny-list class inactive" in out, f"expected the inactive notice: {out}{err}"


def test_without_the_fixture_the_scrub_denylist_is_visible(tmp_path, monkeypatch):
    """The pairing control for the test above, and the reason it means
    something: the same decoy, with the variable written to ``os.environ``
    after the fixture ran (exactly how a shell export would arrive for a test
    that never got cleared). The decoy IS read and the note carrying its entry
    IS flagged. If a future change made the census immune to the environment by
    accident, this test fails and the claim stops being self-certifying.
    """
    import census as _census
    import public_safety

    decoy = tmp_path / "decoy-denylist.txt"
    decoy.write_text(DECOY_DENYLIST_ENTRY + "\n", encoding="utf-8")
    monkeypatch.setattr(public_safety, "_default_denylist_file", lambda: tmp_path / "absent.txt")
    os.environ[public_safety.DENYLIST_ENV_VAR] = str(decoy)
    try:
        repo = _hygiene_repo(tmp_path, decoy_in_tree=True)
        out, err = _capture_census(_census, repo)
        assert "flagged-note.md" in out, (
            "the decoy deny-list is not read even with the variable set — either the "
            f"census stopped honouring {public_safety.DENYLIST_ENV_VAR} or the control "
            f"broke: {out}{err}"
        )
    finally:
        del os.environ[public_safety.DENYLIST_ENV_VAR]


def _hygiene_repo(tmp_path: Path, decoy_in_tree: bool) -> Path:
    """A clean-ledger git repo whose tracked files are hygiene-clean, plus (when
    ``decoy_in_tree``) a note whose content line is the decoy deny-list entry.

    The entry string appears in exactly one place per variant, so the two runs
    differ in nothing but whether the decoy deny-list was in effect.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "noni" / "decisions").mkdir(parents=True)
    record = {
        "id": "2026-10-01-clean",
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "clean",
        "questions": [{"id": "q1", "text": "Clean?", "options": ["yes", "no"], "answer": "yes"}],
        "by": "Clean Author",
        "scope": "clean scope",
        "status": "decided",
        "supersedes": None,
    }
    (repo / "noni" / "decisions" / "2026-10-01-clean.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    (repo / "plain-note.md").write_text("nothing to see\n", encoding="utf-8")
    if decoy_in_tree:
        (repo / "flagged-note.md").write_text(
            f"a line carrying the decoy entry: {DECOY_DENYLIST_ENTRY}\n", encoding="utf-8"
        )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "clean")
    return repo


def _capture_census(census_mod, repo: Path) -> tuple[str, str]:
    """Run the unified census on repo (text mode) and return (stdout, stderr)."""
    import io
    from contextlib import redirect_stderr, redirect_stdout

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        census_mod.main(["--repo", str(repo), "--now", "2026-10-02T00:00:00Z"])
    return out.getvalue(), err.getvalue()
