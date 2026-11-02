"""Did a rebase stop here, or was it never started?

One question, one module, asked of the two directories a stopped rebase can
leave: the merge backend writes ``rebase-merge/`` and the am backend writes
``rebase-apply/``, so a probe that looks at one of them can call a live stopped
rebase absent. The module is split from :mod:`noni._session_git`, whose commit
primitive no rebase probe is part of; its only caller is the push loop,
:mod:`noni._session_push`, which aborts a rebase only when this answers
"stopped".

The word that matters is *evidence*. Existence of a state directory is not
evidence: a leftover from an abandoned run is somebody else's state, and
``git rebase --abort`` on it resets the caller's worktree and index. So the
answer comes from reading two files, and a directory whose files cannot be read
is its own answer rather than either of the other two.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

# What :func:`stopped_state` answers about one probed rebase state directory.
StoppedStateAnswer = Literal["stopped", "absent", "unreadable"]

# The two directories a stopped rebase can leave: the merge backend writes
# rebase-merge/, the am backend writes rebase-apply/, so the classifier probes
# both.
REBASE_STATE_DIRS: tuple[str, ...] = ("rebase-merge", "rebase-apply")


def stopped_state(repo: Path, probed: Path) -> tuple[Path | None, StoppedStateAnswer]:
    """One probed rebase state directory: ``(dir, answer)``, answer in three kinds.

    ``"stopped"`` when the directory carries positive evidence of a live
    stopped rebase -- both ``head-name`` and ``onto`` read back non-empty,
    which is what a stopped rebase always leaves and what a stray directory
    does not; ``"absent"`` when there is nothing stopped here; ``"unreadable"``
    when the question could not be answered because a state file could not be
    read. Existence alone is not evidence: a directory whose files cannot be
    read is somebody else's leftover, and aborting it would reset the caller's
    worktree and index -- which is why unreadable is its own answer and not
    folded into either of the others.

    ``probed`` is what ``git rev-parse --git-path`` printed, which is relative
    to the working tree that call resolved (the clone itself), so a relative
    answer is joined to ``repo`` here rather than by each caller.
    """
    state = probed if probed.is_absolute() else repo / probed
    try:
        head_name = (state / "head-name").read_text(encoding="utf-8", errors="replace")
        onto = (state / "onto").read_text(encoding="utf-8", errors="replace")
    except OSError:
        # Absent is an answer (nothing stopped here); unreadable is not.
        return None, "unreadable" if state.is_dir() else "absent"
    if head_name.strip() and onto.strip():
        return state, "stopped"
    return None, "absent"
