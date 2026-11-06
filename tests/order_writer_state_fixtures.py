"""The order writer's own fixtures for the state-root guard modules.

The companions of ``tests/test_order_writer_state.py``: the helpers that ask the
guard's questions with the guard's own functions, and the fixtures that plant the
states the freshness arms exist for. Split out of that module so each stays under
the line limit in AGENTS.md; no behaviour here changed.
"""

from __future__ import annotations

from _harness import _git
from order_fixtures import (
    BASELINE_ID,
    ORDER_REL,
    _canonical,
    _committed_order,
    _entry,
    _order_module,
    _order_path,
    git_input,
)
from order_race_fixtures import RIVAL_STAMP, _rival_raced

__all__ = ["_path_kind_file_bytes", "_restore_head", "_staged_conflict"]


def _path_kind_file_bytes(path):
    """The probe module's own file read, reached through the guard that uses it.

    The fixture asks the guard's three questions and must ask them with the guard's own
    helpers, so a read this step does not name cannot be quietly different from the one
    the run makes. The file read lives on the probe module rather than the git helper
    module, because it reads a path and not a repository.
    """
    return _order_module().order_probe.file_bytes(path)


def _rival_behind_a_staged_copy(repo):
    """Move HEAD to a rival's order while the index keeps a foreign copy.

    Three reads must disagree here -- HEAD (the rival's), the file (what this run will
    read) and the index (a third order) -- so that the ORDER of the guard's arms is what
    decides which refusal the run gets, rather than one arm happening to be clean.
    """
    _rival_raced(repo, (55, BASELINE_ID))
    # The rival's fixture restores the working copy; re-stage the foreign bytes the
    # scenario needs, so all three reads disagree and the order of arms is what decides.
    target = _order_path(repo)
    target.write_text(_canonical([_entry(99, BASELINE_ID, RIVAL_STAMP)]),
                      encoding="utf-8")
    _git(repo, "add", ORDER_REL)


def _restore_head(repo):
    """Restore the file from HEAD so HEAD and the file agree, and hand back HEAD's bytes.

    The scenario has already moved HEAD (a rival commit), and the writer's contract is
    that a refused run never moves it -- so a fixture must not rewind history to undo
    that, and the next run must plan from what HEAD holds now. The documented remedy
    does exactly that and nothing more: ``git checkout HEAD -- <path>`` (the sync the
    skill tells the operator to do after a refusal) restores the working copy AND the
    index from HEAD, so HEAD is unmoved and all three reads agree before the caller
    moves the file.

    The result is read back and asserted rather than trusted: a "restored" that left
    HEAD's order elsewhere would put the next refusal in the wrong arm, and the test
    would be pinning the wrong comparison.
    """
    _git(repo, "checkout", "HEAD", "--", ORDER_REL)
    head_bytes = _committed_order(repo)
    assert head_bytes == _order_path(repo).read_bytes(), (
        "the file does not hold HEAD's order, so the next refusal is the wrong arm")
    return head_bytes


def _staged_conflict(repo, base: str) -> None:
    """Put the artifact's path in the index at stages 1/2/3 and no stage 0.

    A conflict cannot be planted with ``git merge`` in every scenario (a merge needs a
    commit to merge into), and it cannot be planted with ``update-index --cacheinfo``
    either: git reads that option's third field as a PATH and re-hashes the worktree
    bytes for it, so for a path the worktree holds it quietly restages the file at stage
    0 and the index answers a single id -- the read that is supposed to be ambiguous
    would never have happened. ``update-index --index-info`` writes rows as DATA, in the
    exact form ``ls-files -s`` prints them, and is the call git's own merge machinery
    uses; it must be git's last argument and reads its rows on stdin.

    ``base`` is the id of the merge base, passed in because only the caller knows
    whether the path is in HEAD at all. The other two blobs are stored orders, and the
    file is left holding "ours" on disk: git will not accept a staged row for a path
    whose worktree copy it cannot account for, and a conflicted checkout is what this
    state looks like on disk.
    """
    ours_text = _canonical([_entry(99, BASELINE_ID, RIVAL_STAMP)])
    ours_blob = git_input(repo, "hash-object", "-w", "--stdin", text=ours_text)
    theirs_blob = git_input(repo, "hash-object", "-w", "--stdin",
                            text=_canonical([_entry(55, BASELINE_ID, RIVAL_STAMP)]))
    _order_path(repo).write_text(ours_text, encoding="utf-8")
    rows = [f"100644 {blob} {stage}\t{ORDER_REL}"
            for stage, blob in ((1, base), (2, ours_blob), (3, theirs_blob))]
    git_input(repo, "update-index", "--index-info", text="\n".join(rows) + "\n")
