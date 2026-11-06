"""The freshness probe of the order writer: the lost-update guard (issue #116).

The writer reads ``noni/direction/order.json`` once, plans from those bytes, then
writes and commits with ``git commit --only -- <path>``. That commit takes the path
from the index, so a second writer that committed inside the window between the read
and the commit had its entry dropped from HEAD with exit 0 -- and an ``add --at 1``
computed against the stale list landed at a position nobody chose.

This module owns the one check that stops it: re-read HEAD and the file just before
the write, and refuse unless both still hold what this run planned against. It is a
separate module because it is the writer's only concurrency concern and has one
question to answer; ``order.py`` decides *when* to ask, and this decides *what the
answer means*.

Absence is a value and not a wildcard. A run that read no file has ``before`` of
``None``, which equals an absent HEAD and refuses a HEAD that answered with bytes --
the two absences matching is what lets the very first ``add`` into a fresh repository
run at all.
"""

from __future__ import annotations

from pathlib import Path

from . import labels, orderschema, orderstate
from . import order_gitwrite as gitwrite

# The writer's own exit codes, repeated here rather than imported from order.py so
# this module stays importable from the writer without a cycle.
EXIT_IO = 3
EXIT_REFUSAL = 4

# The line a refused run prints. The caller acts on this wording, so it is pinned in
# one place: tests/test_order_writer_race.py and tests/test_order_writer_docs.py both
# name it, and skills/direction/SKILL.md spells it for the operator.
CHANGED = "the order changed since it was read; re-run"


def file_bytes(path: Path) -> bytes | None:
    """The bytes at ``path``, or ``None`` when the path holds no file at all.

    The second read of the artifact, in the same currency as the first: ``None``
    means absence, which is what ``read_order`` hands back as ``before`` for a path
    that does not exist, so the two compare honestly. A path that became a directory,
    a symlink or an unreadable file is ``None`` too, and that is a change the guard
    must catch: the run read bytes it can no longer get back. Both answers share the
    value because a run that read bytes never has ``before`` of ``None`` -- the
    reader refuses or faults on those shapes before the guard is reached.
    """
    try:
        return path.read_bytes()
    except OSError:
        return None


def probe(repo: Path, order_path: Path, before: bytes | None, verb: str,
          repo_arg: str) -> int | None:
    """The exit code the probe forces, or ``None`` when this run may write.

    Called after every input, artifact and plan refusal has had its turn and before
    mkdir, the atomic write and any ``git add``, so a refused run neither writes nor
    stages nor moves HEAD. The remedy is a re-run, which re-reads and therefore
    re-plans: ``--at N`` is resolved against the entries of the new run, not the
    stale positions of this one.

    ``before`` is the one thing this run planned from -- the bytes the artifact read
    carried -- and both reads below are compared against it.

      HEAD   -- because ``git commit --only -- <path>`` replaces whatever HEAD
                holds. If HEAD no longer holds the bytes this run read, the commit
                drops an entry it never saw.
      file   -- because ``write_atomic`` replaces whatever the path holds. A plan
                built from bytes the file no longer has is not a plan anybody
                approved, even when HEAD never moved.
    """
    committed = gitwrite.committed_bytes(repo, orderschema.ORDER_REL)
    fault = _fault(committed, verb, repo_arg)
    if fault is not None:
        return fault
    if committed != before or file_bytes(order_path) != before:
        return orderstate._fail(
            EXIT_REFUSAL, f"{orderschema.ORDER_REL}: {CHANGED}",
            f"re-run 'order.py {verb}': this run wrote nothing, so the order that "
            "was committed while it ran still stands", label=f"{labels.ORDER}:")
    return None


def _fault(answer, verb: str, repo_arg: str) -> int | None:
    """The exit code a probe answer that could not answer forces, or ``None``.

    A probe that cannot answer is an environment fault and never a pass: reading a
    hang or a corrupt object store as "committed bytes, unchanged" would commit an
    order nobody checked, which is the same lie as the lost update this guard exists
    to stop. The two refusals differ in what the caller does next -- a timeout waits
    for git and repeats, any other non-zero answer means the repository itself needs
    looking at -- and neither is the exit 4 a concurrent writer gets.
    """
    if answer == gitwrite.GIT_TIMEOUT_RC:
        return orderstate._fail(
            EXIT_IO, f"git show timed out for {orderschema.ORDER_REL} after "
            f"{gitwrite.GIT_TIMEOUT}s, so this writer cannot tell whether "
            "the committed order still holds what it read",
            f"once git answers again, re-run 'order.py {verb}' (a git that "
            "cannot answer is never read as an unchanged order)",
            label=f"{labels.ORDER}:")
    if isinstance(answer, int):
        return orderstate._fail(
            EXIT_IO, f"git show failed for {orderschema.ORDER_REL} "
            f"(exit {answer}), so this writer cannot tell whether the "
            "committed order still holds what it read",
            f"find out why 'git -C {repo_arg} show "
            f"HEAD:{orderschema.ORDER_REL}' cannot answer, then re-run "
            f"'order.py {verb}'", label=f"{labels.ORDER}:")
    return None
