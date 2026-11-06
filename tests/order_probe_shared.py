"""The shared pieces of the freshness-guard suite: one fixture, one wording.

Held apart rather than duplicated so the two files cannot build the same state two
ways, or pin the guard's third refusal to two slightly different sentences.
"""

from __future__ import annotations

from pathlib import Path

from _harness import _git
from order_fixtures import BASELINE_ID, _record_json

# The guard's third refusal, pinned once to the product's own wording so a test
# cannot drift from the line the operator reads.
STAGED = ("the staged copy of the file holds an order this run did not read; "
        "unstage it or commit it first")


def _no_commit_repo(tmp_path: Path, subdir: str) -> Path:
    """A ``git init`` with no commit at all, plus the decision record on disk.

    The state the fixture's :func:`_bare_repo` cannot model, because that one makes
    one empty commit so a later commit has a parent. Here nothing has ever been
    committed: there is no parent for anything, ``HEAD`` names no object, and git's
    own answer for ``show HEAD:<path>`` under it is "invalid object name 'HEAD'."
    (or, with a file of that name sitting in the working tree, "exists on disk, but
    not in 'HEAD'"). The record ``add --decision`` cites is written to disk and left
    uncommitted, which is what the writer reads: it looks the id up by filename.
    """
    repo = tmp_path / subdir
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Replay")
    _git(repo, "config", "user.email", "replay@fixture.invalid")
    record = repo / "noni" / "decisions" / f"{BASELINE_ID}.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(_record_json(BASELINE_ID, "decided", None), encoding="utf-8")
    return repo


