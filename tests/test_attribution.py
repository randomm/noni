"""Test that `by` is read from the git commit author of the record's path,
not from the file body.

The attribution rule: `by` is the git author of the record's commit, read with
`git log -1 --format=%an -- <record path>`. A forged `by` in the file body
does not change what the census reports — it reads the author from git.

These tests build a throwaway git repo, commit a record with a known author,
and verify the census report shows the git author, not the file body's `by`
field.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CENSUS = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid", "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
    )


def _git_with_author(repo: Path, author_name: str, author_email: str, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", f"user.name={author_name}", "-c", f"user.email={author_email}", "-c", "commit.gpgsign=false", *args],
        check=True,
        capture_output=True,
    )





def test_by_comes_from_git_author(tmp_path, run_census):
    """Commit a record with author 'Alice' but the file body says 'Bob'. The
    census report shows 'Alice' (the git author), not 'Bob'."""
    repo = tmp_path / "repo"
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "initial")

    record = {
        "id": "2026-10-01-attrib",
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "developer",
        "questions": [
            {"id": "q1", "text": "A?", "options": ["x", "y"], "answer": "x"}
        ],
        "by": "Bob",  # forged in the file body
        "scope": "test",
        "status": "decided",
        "supersedes": None,
    }
    (ledger / "2026-10-01-attrib.json").write_text(json.dumps(record, indent=2))
    _git_with_author(repo, "Alice", "alice@example.invalid", "add", "noni/decisions/2026-10-01-attrib.json")
    _git_with_author(repo, "Alice", "alice@example.invalid", "commit", "-q", "-m", "steering: attributed to Alice")
    _git_with_author(repo, "Alice", "alice@example.invalid", "commit", "-q", "--allow-empty", "-m", "second commit")

    code, out, err = run_census(ledger)
    # The report should show 'Alice' in the by column, not 'Bob'
    lines = out.strip().split("\n")
    assert len(lines) >= 2, f"expected header + at least one record line, got: {out}"
    record_line = lines[1]  # first record line (after header)
    fields = record_line.split("\t")
    assert len(fields) == 6, f"expected 6 tab-separated fields, got: {fields}"
    by_field = fields[2]
    assert by_field == "Alice", f"expected 'Alice' (git author), got '{by_field}' — the census must read by from git, not the file body"


def test_by_matches_when_git_author_and_body_agree(tmp_path, run_census):
    """When the git author and the file body's `by` agree, the report shows
    that author."""
    repo = tmp_path / "repo"
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "initial")

    record = {
        "id": "2026-10-01-agree",
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "developer",
        "questions": [
            {"id": "q1", "text": "A?", "options": ["x", "y"], "answer": "x"}
        ],
        "by": "Alice",  # matches the git author
        "scope": "test",
        "status": "decided",
        "supersedes": None,
    }
    (ledger / "2026-10-01-agree.json").write_text(json.dumps(record, indent=2))
    _git_with_author(repo, "Alice", "alice@example.invalid", "add", "noni/decisions/2026-10-01-agree.json")
    _git_with_author(repo, "Alice", "alice@example.invalid", "commit", "-q", "-m", "steering: agreed attribution")
    _git_with_author(repo, "Alice", "alice@example.invalid", "commit", "-q", "--allow-empty", "-m", "second commit")

    code, out, err = run_census(ledger)
    lines = out.strip().split("\n")
    record_line = lines[1]
    fields = record_line.split("\t")
    assert fields[2] == "Alice", f"expected 'Alice', got '{fields[2]}'"


def test_census_reads_author_from_specific_path(tmp_path, run_census):
    """The census reads the author of the commit that last touched the record's
    path, not the author of HEAD. Commit the record as Alice, then make a
    second commit as Bob (on a different file). The record's author is still
    Alice."""
    repo = tmp_path / "repo"
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "initial")

    record = {
        "id": "2026-10-01-path-attr",
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "developer",
        "questions": [
            {"id": "q1", "text": "A?", "options": ["x", "y"], "answer": "x"}
        ],
        "by": "Alice",
        "scope": "test",
        "status": "decided",
        "supersedes": None,
    }
    (ledger / "2026-10-01-path-attr.json").write_text(json.dumps(record, indent=2))
    _git_with_author(repo, "Alice", "alice@example.invalid", "add", "noni/decisions/2026-10-01-path-attr.json")
    _git_with_author(repo, "Alice", "alice@example.invalid", "commit", "-q", "-m", "steering: Alice commits the record")

    # A second commit by Bob on a different file
    (repo / "other.txt").write_text("unrelated\n")
    _git_with_author(repo, "Bob", "bob@example.invalid", "add", "other.txt")
    _git_with_author(repo, "Bob", "bob@example.invalid", "commit", "-q", "-m", "unrelated change by Bob")

    code, out, err = run_census(ledger)
    lines = out.strip().split("\n")
    record_line = lines[1]
    fields = record_line.split("\t")
    # The record's author is Alice (the commit that last touched the record's
    # path), not Bob (the author of HEAD).
    assert fields[2] == "Alice", (
        f"expected 'Alice' (author of the commit that touched the record's path), "
        f"got '{fields[2]}' — the census must use git log -- <path>, not git log HEAD"
    )
