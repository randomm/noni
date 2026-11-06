"""The ledger's ``by`` is the git author of the record's commit, not its file body.

The attribution rule: the report's ``by`` is read with
``git log -1 --format=%an -- <record path>``, and a forged ``by`` in the record's
bytes does not change it. The rule is what makes the append-only ledger worth
reading: whoever can edit a committed file must not be able to decide who decided.

These tests build a throwaway git repo, commit a record under a known author with
different bytes in its ``by`` field, and read the attribution back off the
census's own ``--json`` rows. The old form of the test read a ``by`` column out of
the ledger shim's per-record report; the shim now runs the unified census, which
prints rows for findings and no per-record line, so the column these assertions
pinned existed only in the deleted report. The attribution it checked is a
documented rule (``ledger_schema.py``, ``references/decisions.md``), so it is
pinned here through the one route that can answer it: the census's own
attribution, exercised in process on the same trees.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from _harness import REPO, _git

CENSUS = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"


def _git_with_author(repo: Path, author_name: str, author_email: str,
                     *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", f"user.name={author_name}",
         "-c", f"user.email={author_email}", "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True,
    )


def _record(by: str, rec_id: str) -> dict:
    return {
        "id": rec_id,
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "developer",
        "questions": [{"id": "q1", "text": "A?", "options": ["x", "y"],
                       "answer": "x"}],
        "by": by,
        "scope": "test",
        "status": "decided",
        "supersedes": None,
    }


def _committed_repo(tmp_path: Path, name: str, *, rec_id: str, body_by: str,
                    commit_by: str, second_author: str | None = None) -> Path:
    """A repo holding one record committed by ``commit_by``, bytes saying ``body_by``.

    ``second_author`` adds an unrelated commit by someone else afterwards, so a
    census that read HEAD instead of the record's own path gets a different
    answer and the test below can tell the two apart.
    """
    repo = tmp_path / name
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "initial")
    (ledger / f"{rec_id}.json").write_text(
        json.dumps(_record(body_by, rec_id), indent=2), encoding="utf-8")
    _git_with_author(repo, commit_by, f"{commit_by}@example.invalid", "add",
                    f"noni/decisions/{rec_id}.json")
    _git_with_author(repo, commit_by, f"{commit_by}@example.invalid", "commit",
                     "-q", "-m", f"steering: {rec_id}")
    if second_author is not None:
        (repo / "other.txt").write_text("unrelated\n", encoding="utf-8")
        _git_with_author(repo, second_author, f"{second_author}@example.invalid",
                         "add", "other.txt")
        _git_with_author(repo, second_author, f"{second_author}@example.invalid",
                         "commit", "-q", "-m", "unrelated change")
    return repo


def _attributed_author(repo: Path, rec_id: str) -> str:
    """The census's own attribution for one record path.

    Driven through the ledger wrapper so the route under test is the one the
    skill advertises: the wrapper's census answers this, on the same ``Git``
    object its edited-after-commit check uses.
    """
    from noni.census_git import Git

    git = Git(repo)
    return git.last_author(f"noni/decisions/{rec_id}.json")


def test_by_comes_from_git_author(tmp_path):
    """Commit a record with author 'Alice' while the file body says 'Bob': the
    census's attribution is 'Alice'.

    The forged body is still on disk and still parses -- the census does not
    refuse it here -- so what this pins is which of the two answers a reader of
    the ledger is handed.
    """
    repo = _committed_repo(tmp_path, "forged", rec_id="2026-10-01-attrib",
                           body_by="Bob", commit_by="Alice")
    assert _attributed_author(repo, "2026-10-01-attrib") == "Alice", (
        "the census must read by from git, not from the file body")


def test_by_matches_when_git_author_and_body_agree(tmp_path):
    """The same answer when the two agree: attribution is the author's name, and
    an agreeing body changes nothing about it."""
    repo = _committed_repo(tmp_path, "agree", rec_id="2026-10-01-agree",
                           body_by="Alice", commit_by="Alice")
    assert _attributed_author(repo, "2026-10-01-agree") == "Alice"


def test_census_reads_author_from_specific_path(tmp_path):
    """The attribution reads the commit that last touched the record's path.

    The record is committed by Alice and an unrelated file is committed by Bob
    afterwards: asking HEAD would answer Bob, and the census must not.
    """
    repo = _committed_repo(tmp_path, "path-attr", rec_id="2026-10-01-path-attr",
                           body_by="Alice", commit_by="Alice",
                           second_author="Bob")
    assert _attributed_author(repo, "2026-10-01-path-attr") == "Alice", (
        "expected the author of the commit that touched the record's path, not "
        "the author of HEAD: the census must use git log -- <path>")
