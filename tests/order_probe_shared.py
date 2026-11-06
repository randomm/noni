"""The shared pieces of the freshness-guard suite: one fixture, one wording.

Held apart rather than duplicated so the two files cannot build the same state two
ways, or pin the guard's third refusal to two slightly different sentences.
"""

from __future__ import annotations

from pathlib import Path

from _harness import _git
from order_fixtures import (
    BASELINE_ID,
    ORDER_REL,
    RIVAL_DATE,
    _canonical,
    _entry,
    _record_json,
    git_input,
    git_output,
)

__all__ = [
    "CONFLICTED", "STAGED", "UNMERGED", "_conflicted_repo", "_no_commit_repo",
    "staged_conflict",
]

# The guard's third refusal, pinned once to the product's own wording so a test
# cannot drift from the line the operator reads.
STAGED = ("the staged copy of the file holds an order this run did not read; "
        "unstage it or commit it first")

# The guard's fourth refusal: the index holds the path in conflict (unmerged stages),
# which no blob id answers. Pinned from the product's constant by the test that asserts
# the two index arms stay distinguishable -- unstaging is not the fix for a conflict.
CONFLICTED = ("the index holds the file in conflict (unmerged stages), so this writer "
              "cannot tell what its commit would write; resolve or abort the merge")

# A path the index holds in conflict answers one ``ls-files -s`` row per stage, and no
# single id names "what the index holds at that path". The helper's answer for it, kept
# out of the test file so a rename cannot turn the assertion into a tautology.
UNMERGED = "unmerged"


def staged_conflict(repo: Path, base: str) -> None:
    """Put the artifact's path in the index at stages 1/2/3 and no stage 0.

    A conflict cannot be planted with ``git merge`` in every scenario (a merge needs a
    commit to merge into), and it cannot be planted with ``update-index --cacheinfo``
    either: git reads that option's third field as a PATH and re-hashes the worktree
    bytes for it, so for a path the worktree holds it quietly restages the file at stage
    0 and the index answers a single id -- the read that is supposed to be ambiguous
    would never have happened. ``update-index --index-info`` writes rows as DATA, in the
    exact form ``ls-files -s`` prints them, and is the call git's own merge machinery
    uses; it must be git's last argument and reads its rows on stdin.

    Three stages and no stage 0 is what a conflict IS: the index holds no single answer
    for the name, and a stage-0 row beside the three would be a fourth blob under one
    name, which git itself never writes -- so any stage-0 row the path already had is
    dropped in the same call (git's spelling of that is a mode of six zeroes over a null
    sha1, and rows are validated as a set, so removal and addition cannot be split).

    ``base`` is the id of the merge base, passed in because only the caller knows
    whether the path is in HEAD at all; the other two rows are stored orders written
    here. The rows are written EXACTLY as given -- no removal row, and the working copy
    is not touched -- because the guard is being asked about a path that HEAD and the
    file both still hold: adding a removal row or restamping the file would move two of
    the three reads and the refusal the run gets could then come from either of them.
    """
    ours_blob = git_input(repo, "hash-object", "-w", "--stdin",
                          text=_canonical([_entry(99, BASELINE_ID, RIVAL_DATE)]))
    theirs_blob = git_input(repo, "hash-object", "-w", "--stdin",
                            text=_canonical([_entry(55, BASELINE_ID, RIVAL_DATE)]))
    rows = [f"000000 {'0' * 40} 0\t{ORDER_REL}"]
    rows += [f"100644 {blob} {stage}\t{ORDER_REL}"
             for stage, blob in ((1, base), (2, ours_blob), (3, theirs_blob))]
    # Rows must be written as data, so ``--index-info`` is git's last argument and
    # reads them from stdin.
    git_input(repo, "update-index", "--index-info", text="\n".join(rows) + "\n")


def _conflicted_repo(tmp_path: Path, subdir: str) -> Path:
    """A repository whose committed artifact path sits in an unresolved index conflict.

    The state that makes the index read ambiguous: ``git ls-files -s`` answers THREE
    rows for the path (the merge base and both sides) rather than the single stage-0
    row the guard reads an id out of. A reader that took the first row would report one
    side of somebody else's merge as "the bytes the index holds", and the coming
    ``git commit --only -- <path>`` would obey a blob this run never read.

    The conflict is planted while HEAD and the file still hold the seeded order, so the
    two other reads of the guard have nothing to report and the refusal the run gets can
    only have come from the index. That is why the rows are handed to
    :func:`staged_conflict` unchanged and the file is left alone: a fixture that moved
    the file to match one side of the conflict would be testing the file arm instead.
    """
    repo = tmp_path / subdir
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Replay")
    _git(repo, "config", "user.email", "replay@fixture.invalid")
    record = repo / "noni" / "decisions" / f"{BASELINE_ID}.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(_record_json(BASELINE_ID, "decided", None), encoding="utf-8")
    order = repo / ORDER_REL
    order.parent.mkdir(parents=True, exist_ok=True)
    order.write_text(_canonical([_entry(11, BASELINE_ID)]), encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "direction: seed the order")
    seeded = order.read_bytes()
    staged_conflict(repo, git_output(repo, "rev-parse", f"HEAD:{ORDER_REL}"))
    assert (repo / ORDER_REL).read_bytes() == seeded, (
        "the fixture moved the file, so the file arm would answer before the index")
    return repo


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


