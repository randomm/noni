"""Shared decoy builders for the suite-wide environment-isolation tests.

Isolation is only a real claim when the hostile input is a tree a tool could
actually have used. These builders plant the decoys (a ledger under a hostile
HOME, a git repo whose tracked files are hygiene-clean, a complete decoy state
root under HOME) so the pairing controls — "the decoy IS read when the fixture
is undone" — can assert the same bytes the isolation tests assert the absence of.

Two families of decoy live here: the ledger/hygiene decoys (the census reads
only) and the HOME state-root decoy (the writers would write, so the mirror
image matters: one tree holds the session, the other holds the ordering artifact).
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from _harness import _git

REPO = Path(__file__).resolve().parent.parent
CENSUS = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"
CONFTEST = Path(__file__).resolve().parent / "conftest.py"

# The decoy deny-list entry. It appears only in the decoy deny-list file and in
# one planted note's content line (public_safety matches line content).
DECOY_DENYLIST_ENTRY = "decoy-denylist-probe"

# The identity the decoy session registers carry, and the task a writer run
# would claim or release: the row the snapshot comparison catches.
DECOY_SID = "2026-10-01-aaaaaa"
DECOY_TASK = "#42"
BASELINE_DECISION_ID = "2026-10-01-baseline"


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
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        census_mod.main(["--repo", str(repo), "--now", "2026-10-02T00:00:00Z"])
    return out.getvalue(), err.getvalue()


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
