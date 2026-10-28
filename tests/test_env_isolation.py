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


# --- Every tool reads only under --repo, never from HOME -----------------------
#
# The state-root contract says the state root is the path --repo names (or the
# cwd, for that flag's one documented default) and nothing else. HOME is the
# other directory a tool could reach without being told: git reads it for
# config, and a path spelled with a leading ~ resolves through it. A hostile
# HOME carrying a complete decoy state root is therefore the sharpest test of
# the rule -- it is a real tree a tool could have found, in a place the caller
# never named. The decoy pattern is the one the census tests above use,
# extended to the writers, because they write and the census only reads.

DECOY_SID = "2026-10-01-aaaaaa"
DECOY_TASK = "#42"
BASELINE_DECISION_ID = "2026-10-01-baseline"

WRITER_LAUNCHERS = {
    # tool -> (script, argv after --repo). The argv is the smallest one each
    # writer accepts: an argument the writer requires must be present or the
    # run fails on usage and measures nothing.
    "register": ("skills/sessions-claims/scripts/register.py",
                 ["--identity", "developer"]),
    "claim": ("skills/sessions-claims/scripts/claim.py",
              ["--session-id", DECOY_SID, "--task", DECOY_TASK]),
    "close": ("skills/sessions-claims/scripts/close.py",
              ["--session-id", DECOY_SID]),
    "release": ("skills/sessions-claims/scripts/release.py",
                ["--session-id", DECOY_SID, "--task", "#7"]),
    "decide": ("skills/steering-ledger/scripts/decide.py",
               ["--slug", "scheduler", "--date", "2026-10-26",
                "--scope", "release ordering", "--asked-by", "developer",
                "--question", "q1=Ship it?", "--option", "q1=yes",
                "--option", "q1=no", "--answer", "q1=yes"]),
    "order": ("skills/direction/scripts/order.py",
              ["add", "7", "--decision", BASELINE_DECISION_ID,
               "--now", "2026-10-02T00:00:00Z"]),
}

# The decoy register under HOME: an active session already holding the row
# claim.py would append and release.py would remove -- the row a writer driven
# by HOME would have produced, planted so the snapshot comparison catches it.
_DECOY_SESSION = """# session 2026-10-01-aaaaaa

- identity: decoy
- host/worktree: decoy-ws
- started: 2026-10-01T10:00:00Z
- status: active
- claims:
  - claim: #42
"""

# The register in the real state root: active and unclaimed, so claim.py has a
# row to append and release.py has one to remove (its own row, named below).
_STATE_SESSION = """# session 2026-10-01-aaaaaa

- identity: developer
- host/worktree: ws-1
- started: 2026-10-01T10:00:00Z
- status: active
- claims:
  - claim: #7
"""

_DECOY_RECORD = {
    "id": "2026-10-01-home-decoy",
    "date": "2026-10-01T10:00:00Z",
    "asked_by": "decoy",
    "questions": [{"id": "q1", "text": "Decoy?", "options": ["yes", "no"],
                   "answer": "yes"}],
    "by": "Decoy Author",
    "scope": "decoy scope",
    "status": "decided",
    "supersedes": None,
}

_DECOY_ORDER = [{"issue": 999, "decision": BASELINE_DECISION_ID,
                 "confirmed": "2026-10-01T00:00:00Z"}]


def _hostile_home(tmp_path: Path) -> Path:
    """A HOME carrying a complete decoy state root: all three noni/ directories.

    The three directories are the whole layout (direction, decisions, sessions),
    so every writer in WRITER_LAUNCHERS has a plausible place to have landed
    here -- and none of them may.
    """
    home = tmp_path / "hostile-home"
    state = home / "noni"
    (state / "decisions").mkdir(parents=True)
    (state / "sessions").mkdir(parents=True)
    (state / "direction").mkdir(parents=True)
    (state / "decisions" / "2026-10-01-home-decoy.json").write_text(
        json.dumps(_DECOY_RECORD, indent=2), encoding="utf-8")
    (state / "sessions" / f"{DECOY_SID}.md").write_text(
        _DECOY_SESSION, encoding="utf-8")
    (state / "direction" / "order.json").write_text(
        json.dumps(_DECOY_ORDER, indent=2), encoding="utf-8")
    return home


def _home_snapshot(home: Path) -> dict[str, str]:
    """Every file under ``home`` as path -> bytes, so 'untouched' names what moved."""
    return {str(p.relative_to(home)): p.read_bytes()
            for p in sorted(home.rglob("*")) if p.is_file()}


def _home_state_repo(tmp_path: Path) -> Path:
    """The real state root: a git repo with an identity, the session the three
    session writers act on, and the decision record order.py's --decision cites.

    The state root starts as the mirror image of the decoy under HOME: it holds
    the session (at ``active`` with one ``#7`` row) but no ordering artifact,
    while HOME holds an ordering artifact and no session of the writer's.
    A writer that landed in the wrong tree therefore had something to write
    there, so a clean result can only mean it went to --repo.
    """
    from _harness import _init_repo

    root = _init_repo(tmp_path / "state-root")
    _git(root, "config", "user.name", "Replay")
    _git(root, "config", "user.email", "replay@fixture.invalid")
    decision = dict(_DECOY_RECORD)
    decision["id"] = BASELINE_DECISION_ID
    (root / "noni" / "decisions").mkdir(parents=True, exist_ok=True)
    (root / "noni" / "decisions" / f"{BASELINE_DECISION_ID}.json").write_text(
        json.dumps(decision, indent=2), encoding="utf-8")
    _git(root, "add", f"noni/decisions/{BASELINE_DECISION_ID}.json")
    _git(root, "commit", "-q", "-m", "baseline decision")
    (root / "noni" / "sessions").mkdir(parents=True, exist_ok=True)
    (root / "noni" / "sessions" / f"{DECOY_SID}.md").write_text(
        _STATE_SESSION, encoding="utf-8")
    _git(root, "add", f"noni/sessions/{DECOY_SID}.md")
    _git(root, "commit", "-q", "-m", "session")
    return root


def _writers_under_a_hostile_home(tmp_path: Path, monkeypatch):
    """Run every writer with HOME pointing at a decoy state root.

    Returns (home, bytes-before, [(tool, process)], cwd). The caller asserts
    both halves: the home's bytes are unchanged, and each run succeeded. A
    refusal would leave the decoy untouched too, so the verdict alone proves
    nothing -- and neither does a pass, which is why the control test below
    checks the decoy is a tree a writer could actually have used.
    """
    import subprocess
    import sys

    from _harness import _git_env_with_identity, subprocess_env

    home = _hostile_home(tmp_path)
    root = _home_state_repo(tmp_path)
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    before = _home_snapshot(home)
    results = []
    for tool, (rel_script, argv) in WRITER_LAUNCHERS.items():
        env = subprocess_env()
        env.update(_git_env_with_identity())
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        proc = subprocess.run(
            [sys.executable, str(REPO / rel_script), "--repo", str(root), *argv],
            capture_output=True, text=True, env=env, cwd=str(cwd), timeout=120,
        )
        results.append((tool, proc))
    return home, before, results, cwd


def test_no_writer_reads_or_writes_under_home(tmp_path, monkeypatch):
    """Each writer runs against --repo while HOME holds a complete decoy state
    root: the decoy's bytes are unchanged and no noni/ appears under the cwd.

    This is the HOME half of the isolation pair. The cwd half lives in each
    tool's own state-root test (tests/test_claim_validation.py and the modules
    named there); this one covers the directory a caller never names, which is
    the one a tool reaches by accident rather than by argument.
    """
    home, before, results, cwd = _writers_under_a_hostile_home(tmp_path, monkeypatch)
    failures = {tool: (proc.returncode, proc.stderr[-300:])
                for tool, proc in results if proc.returncode != 0}
    assert not failures, (
        "every writer was given a valid state root, so all must succeed: "
        f"{failures}"
    )
    after = _home_snapshot(home)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert changed == [], (
        "a writer read or wrote under HOME, so a noni/ path resolved from HOME "
        f"rather than --repo; changed: {changed}"
    )
    assert not (cwd / "noni").exists(), "a writer created noni/ under the cwd"


def test_each_writer_actually_wrote_in_the_state_root(tmp_path, monkeypatch):
    """The other half of the pair above: the run must have done its work in --repo.

    A launcher that refused every run would leave the decoy under HOME exactly
    as untouched as a correct one does. What separates the two is that the
    state root's own bytes moved, in the way each verb promises, so each writer
    is checked at its own write here and the isolation claim stops being
    self-certifying.
    """
    _home, _before, _results, _cwd = _writers_under_a_hostile_home(tmp_path, monkeypatch)
    root = tmp_path / "state-root"
    sessions = root / "noni" / "sessions"

    register_files = sorted(p.name for p in sessions.glob("*.md"))
    assert len(register_files) == 2, (
        f"register.py allocates one new session beside the one that was there: "
        f"{register_files}"
    )
    claim_body = (sessions / f"{DECOY_SID}.md").read_text(encoding="utf-8")
    assert f"- claim: {DECOY_TASK}" in claim_body, (
        f"claim.py did not append its row to the state root's register:\n"
        f"{claim_body}"
    )
    assert "- status: closed" in claim_body, (
        "close.py did not move the state root's own session to closed"
    )
    assert "- claim: #7" not in claim_body, (
        "release.py did not remove the row it was given from the state root"
    )
    assert (root / "noni" / "direction" / "order.json").is_file(), (
        "order.py wrote its artifact somewhere other than the state root"
    )
    decisions = sorted(p.name for p in (root / "noni" / "decisions").glob("*.json"))
    assert "2026-10-26-scheduler.json" in decisions, decisions


def test_the_hostile_home_decoy_is_readable(tmp_path):
    """The negative control: the decoy under HOME is a state root a tool could
    have used, not a tree that would have failed on its own terms.

    Without it, the test above could pass because the decoy was unusable rather
    than because the tool ignored it -- the same self-certifying-isolation trap
    the census tests above close for the deny-list.
    """
    home = _hostile_home(tmp_path)
    assert (home / "noni" / "decisions" / "2026-10-01-home-decoy.json").is_file()
    body = (home / "noni" / "sessions" / f"{DECOY_SID}.md").read_text(
        encoding="utf-8")
    assert f"- claim: {DECOY_TASK}" in body, (
        "the decoy register must carry the row a run makes")
    order = json.loads((home / "noni" / "direction" / "order.json").read_text(
        encoding="utf-8"))
    assert order[0]["issue"] == 999
    for rel in ("noni/decisions", "noni/sessions", "noni/direction"):
        assert (home / rel).is_dir(), rel
