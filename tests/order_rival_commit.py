"""The rival-commit fixture of the order writer's suite.

Split out of ``tests/order_fixtures.py`` so each file stays under the line limit in
AGENTS.md. This is the one fixture big enough to be a file of its own: it is the
deterministic half of the two-writer race of issue #116, and its docstring is the
record of why three reads have to move together. No behaviour changed.
"""

from __future__ import annotations

import re
from pathlib import Path

from _harness import _git, _git_e2, git_pin_date
from order_fixtures import (
    ORDER_REL,
    RIVAL_DATE,
    _canonical,
    _order_path,
    git_input,
)

__all__ = ["_rival_commit"]


def _rival_commit(repo: Path, entries: list[dict],
                  message: str = "direction: rival writer commits first") -> None:
    """Commit ``entries`` at the artifact path, then leave the tree as it was found.

    The deterministic half of the two-writer race (issue #116): the real race is a
    window of milliseconds, so racing processes would be flaky by construction, and
    what has to be reproduced is the state the losing run reaches its write phase in
    -- one sentence, HEAD moved after this run read.

    Three things have to be true at once, which is why this is a fixture and not a
    bare commit:

      HEAD  -- moved, so the run's commit would overwrite an order it never read.
      file  -- left exactly as it was found, because "HEAD moved after this run
               read" is the state under test and nothing else: a rival that also
               rewrote the working copy would be caught by the reader's own
               comparison, which is a different case with a different message.
      the run's plan -- still a write, so the run cannot take the no-change
               shortcut and exit 0 having committed nothing.

    So the fixture commits the entries it is handed with the rival's own stamp on
    every entry (bytes that differ from HEAD's, so git makes the commit rather than
    refusing an empty one), and puts the file back byte for byte afterwards. The
    caller seeds the order first: the seeded bytes are then the baseline the losing
    run reads, and the only thing that has moved by the time it writes is HEAD.

    Committing the rival's brand-new entries and leaving them in the tree instead
    would model something else entirely -- a run that read the rival's order and
    wrote it back -- which is a correct run, and refusing it would be a bug.

    The commit goes through :func:`git_pin_date` rather than a bare ``_git``: the
    writer's git calls run under ``gitenv.child_env()``, which strips every ``GIT_*``
    name and sandboxes ``HOME``, so a rival committed with the ambient identity is a
    commit the writer's ``git show`` cannot always resolve -- the probe then reads
    "nothing committed" where HEAD holds the rival's order, and the run this guard
    exists to refuse goes ahead. Pinned identity and date are what both can see.
    """
    target = _order_path(repo)
    parent_existed = target.parent.is_dir()
    # The bytes HEAD is about to lose, captured BEFORE anything is written: the state the
    # fixture restores afterwards is the state THIS run read, not whatever the rival's
    # commit happened to put on disk.
    was = target.read_bytes() if target.is_file() else None
    target.write_text(_canonical([dict(entry) for entry in entries]), encoding="utf-8")
    _git(repo, "add", ORDER_REL)
    git_pin_date(repo, RIVAL_DATE, "commit", "-q", "-m", message)

    # Undo the rival's write, everything but the commit. Three things move together
    # in a `git add` and a commit, and leaving any one of them behind describes a
    # scenario that is not this one:
    #
    #   HEAD   -- left where the rival put it, which is the whole point. This is a
    #            real commit and not a rewound history: `git reset` here would move
    #            HEAD back and erase the very thing the guard is meant to notice.
    #   file   -- back to the exact bytes the losing run reads, or unlinked when it
    #            read no file at all.
    #   index  -- back to the commit this run read, so the tree reports no
    #            staged change the rival's `git add` made and the writer's own
    #            `git add` cannot stage it.
    #
    # The index is put back from HEAD's own parent, named, because this is a commit the
    # fixture made and is now taking back. The path form of ``git reset`` fills the index
    # from the WORKING TREE and only falls back to the commit when the file is gone, so on
    # a tree whose file holds a copy of its own (any scenario with a staged or restamped
    # file, which is most of them) it leaves the rival's order staged -- and an index that
    # quietly holds a foreign copy hands the next run an index refusal it was never built
    # to test, which reads as a wrong-arm bug in the guard.
    # The index is put back to the commit this run read. HEAD is moved first, so this
    # helper never knows which commit the rival's is -- the caller restores HEAD when it
    # wants a particular one, and this line puts the index at the commit under HEAD either
    # way. ``git reset -- <path>`` is the obvious spelling and is wrong here: it fills the
    # index from the WORKING TREE and consults the commit only when the file is missing, so
    # on a tree whose file carries a copy of its own (any scenario with a staged or
    # restamped file, which is most of them) it leaves the rival's order staged -- and an
    # index that quietly holds a foreign copy hands the next run an index refusal it was
    # never built to test, which reads as a wrong-arm bug in the guard. ``--`` is what
    # keeps it path-scoped: without it the same command would move HEAD itself.
    # ``--source=`` and not a positional: ``git restore`` takes its source as an option
    # and refuses a positional that follows ``--`` as a pathspec, so the bare form reads
    # "HEAD~1" as a file to restore and dies.
    # HEAD's parent, asked BEFORE the commit under test is taken back, and pinned to a
    # full object id: a rev walked twice is a rev that can name two things, and this one
    # decides which bytes the index is put back to.
    shown = _git_e2(repo, "rev-parse", "HEAD~1^{commit}")
    assert shown.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", shown.stdout.strip()), (
        shown.stderr, shown.stdout)
    parent = shown.stdout.strip()
    # The row itself is read out of that commit and written back as data. Asking git to
    # "restore the index from a commit" is the obvious shape and does not answer this
    # question: ``git restore --staged --source=<commit>`` copies the row including that
    # commit's stat cache, and git then reports the path as a staged change until it is
    # rehashed -- and a path the source commit never held is left in the index at all,
    # which is a third state nobody asked for. ``--index-info`` writes the entry as data
    # (the same call git's own merge machinery uses), with the mode taken from the tree
    # entry, so the row round-trips exactly. No row in the commit means no row in the
    # index, which is the honest answer.
    listing = _git_e2(repo, "ls-tree", parent, "--", ORDER_REL).stdout.splitlines()
    row = next((line for line in listing if line.strip()), "")
    null = "0" * 40
    if row:
        mode, blob = row.split()[0], row.split()[2]
    else:
        mode, blob = "000000", null
    git_input(repo, "update-index", "--index-info",
              text=f"{mode} {blob} 0\t{ORDER_REL}\n")
    # A row that came from a commit carries that commit's stat cache, and git's index
    # refresh refuses to trust it for a path whose worktree copy it cannot see (which is
    # the case on every run of this helper: the file is restored just below). Asked
    # anyway, it dies with "does not match index". So the row is refreshed AFTER the file
    # is put back, by the line that follows the restore below, and this one only stages
    # what HEAD's parent held.
    if was is None:
        target.unlink()
        # Tolerated rather than checked: when the rival's order was the path's first
        # appearance in HEAD, the reset above already took it out of the index, and
        # `git rm --cached` on a path the index does not know exits 128. The state
        # wanted is "the index does not hold this path", which both answers leave.
        _git(repo, "rm", "--cached", "--ignore-unmatch", "--quiet", "--", ORDER_REL)
        if not parent_existed:
            target.parent.rmdir()
    else:
        target.write_bytes(was)
        # The row above came from a commit, so it carries that commit's stat cache and
        # git calls it a staged change ("M ") until it is rehashed against the worktree.
        # ``git add`` is the call that rehashes it, and it is honest here: the bytes about
        # to be staged are the bytes the run reads, so the index ends up holding exactly
        # the copy the guard is entitled to see as clean. (``update-index
        # --really-refresh`` cannot do this job: it refuses to trust a stat cache it did
        # not write and dies with "does not match index".)
        _git(repo, "add", "--", ORDER_REL)
    # Pinned from git rather than assumed: the whole point of the two calls above is that
    # the tree the fixture hands back has HEAD moved and NOTHING ELSE -- the file and the
    # staged copy both answering the bytes the losing run reads. A fixture that quietly
    # left a foreign copy staged hands the next run the index refusal it never set out to
    # test, and the guard then looks wrong-arm for reasons of its own that it does not
    # have. Asked of git (not of the guard, which is the code under test).
    if was is not None:
        rows = [f.split() for f in _git_e2(
            repo, "ls-files", "-s", "--", ORDER_REL).stdout.splitlines() if f.strip()]
        assert [r[2] for r in rows] in ([], ["0"]), (
            f"the rival's index was not put back: {rows}")
        assert not rows or _git_e2(repo, "rev-parse", rows[0][1]).stdout.strip(), rows
        assert not rows or _git_e2(
            repo, "cat-file", "blob", rows[0][1]).stdout.encode() == was, (
            "the index does not hold the bytes the run reads")
