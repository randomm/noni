"""Environment isolation for the census: a hostile HOME, GIT_DIR, or deny-list is not read.

The census runs scripts/public_safety.py's tracked-file scan in-process, and
that scan reads its deny-list from two places a developer's machine can fill:
the NONI_SCRUB_DENYLIST variable and the install-root default file. A suite
that read either would mean something different on the operator's machine than
in CI — the same bug the rest of this file exists to close.

The decoy is a deny-list entry plus a tracked note whose content line is that
entry. If the decoy reaches the census the note is flagged, so the note is the
detector (public_safety reports "path:line: label", never the matched text, so
the entry string never has to appear in output).

Each isolation claim has a pairing control that undoes the fixture's work for
one test and asserts the hostile input IS read: without it the suite's isolation
claims would be self-certifying.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from _harness import _git
from env_isolation_support import (
    CONFTEST,
    DECOY_DENYLIST_ENTRY,
    _capture_census,
    _decoy_ledger,
    _hygiene_repo,
)


def _ledger_rows(out: str) -> set[str]:
    """Every record id the census named in a finding row, plus its own report text.

    The unified census prints rows for findings only, so "the census read this
    ledger" cannot be asserted by looking for a clean record's id in the report --
    a clean record is not a finding and earns no row. These three tests ask the
    census for its machine rows and for its exit code instead, and pair them with
    a planted fault: the fault is what proves which tree was read.
    """
    ids = set()
    for line in out.splitlines():
        if line.strip().startswith("{"):
            row = json.loads(line)
            ids.add(str(row.get("subject")))
            ids.add(str(row.get("message")))
    return ids | {out}


def _broken_ledger_copy(ledger: Path, marker: str) -> None:
    """Add one unparseable record to ``ledger``, named for ``marker``.

    The fault is what makes an isolation claim testable: a census that read the
    wrong tree reports the other tree's fault, and the ids distinguish them.
    """
    (ledger / f"2026-10-09-{marker}-broken.json").write_text(
        "{ not json\n", encoding="utf-8")


def test_census_does_not_read_decoy_ledger_from_hostile_home(tmp_path, monkeypatch, run_census):
    """A hostile HOME with a decoy ledger must not be read by the census when
    the census is pointed at a different (clean) ledger dir.

    The conftest fixture redirects HOME to a sandbox. This test sets up a
    hostile HOME with a decoy ledger whose one record is broken, and points the
    census at a clean ledger dir. The clean tree's verdict -- exit 0, no rows --
    is the answer that can only come from reading the right directory: the
    decoy's broken record would have answered 10 and named itself.
    """
    # Build a hostile HOME with a decoy ledger (the decoy is the leak source).
    hostile_home = tmp_path / "hostile-home"
    hostile_home.mkdir()
    decoy_ledger = _decoy_ledger(hostile_home, "leaked")
    _broken_ledger_copy(decoy_ledger, "leaked")

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
    assert code == 0, (
        f"a clean ledger must census clean; the decoy's broken record was read: "
        f"{code}\n{out}\n{err}")
    assert "leaked" not in "\n".join(_ledger_rows(out)), (
        f"the decoy ledger leaked into the census: {out}")


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
    _broken_ledger_copy(hostile_repo / "noni" / "decisions", "gitdir-leak")

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

    # The census reads the clean tree: exit 0, and the hostile tree's fault is
    # nowhere in its rows.
    code, out, err = run_census(clean_ledger)
    assert code == 0, (
        f"a clean ledger must census clean; the GIT_DIR decoy's broken record was "
        f"read: {code}\n{out}\n{err}")
    assert "gitdir-leak" not in "\n".join(_ledger_rows(out)), (
        f"the decoy ledger leaked via GIT_DIR: {out}")


def test_without_the_fixture_the_hostile_env_is_visible(tmp_path, monkeypatch, run_census):
    """The opposite assertion, and the reason the tests above mean something.

    Undoes the fixture's work for this one test (setting HOME to a hostile dir
    with a decoy ledger, and pointing the census at that decoy) and checks the
    decoy IS read. If a future change made the census immune to the environment
    by accident, this test fails and the suite's isolation claims stop being
    self-certifying.

    "read" here means an answer that can only come from that tree: the decoy's
    one record is broken, so pointing the census at it must exit 10 and name it.
    A census that could not reach the hostile HOME would exit 0 with no rows, and
    the two runs above would be proving nothing.
    """
    # Build a hostile HOME with a decoy ledger whose record will not parse.
    hostile_home = tmp_path / "hostile-home"
    hostile_home.mkdir()
    decoy_ledger = _decoy_ledger(hostile_home, "control")
    _broken_ledger_copy(decoy_ledger, "control")

    # Point the census at the decoy ledger directly (simulating what happens
    # when the fixture is absent and the census's default LEDGER_DIR resolves
    # to the hostile home's ledger)
    monkeypatch.setenv("HOME", str(hostile_home))

    # Run the census on the decoy ledger — it SHOULD read it (this is the
    # negative control: the hostile env IS visible when the fixture is undone)
    code, out, err = run_census(decoy_ledger)
    assert code == 10 and "control" in "\n".join(_ledger_rows(out)), (
        "the decoy ledger is not readable when pointed at directly — either the "
        f"census changed or the negative control stopped working: rc={code}\n"
        f"{out}\n{err}"
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
    monkeypatch.setattr(public_safety, "_default_denylist_file", lambda repo: tmp_path / "absent.txt")
    audited = _hygiene_repo(tmp_path, decoy_in_tree=True)
    # Precondition: with the deny-list routes closed the decoy is inert — the
    # file exists and holds the entry, but nothing points at it.
    assert public_safety.load_denylist(audited).status == "absent"

    repo = audited
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
    monkeypatch.setattr(public_safety, "_default_denylist_file", lambda repo: tmp_path / "absent.txt")
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
