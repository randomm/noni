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
answer means*. It also decides the *code*: the exit codes arrive as parameters, the
way ``orderstate`` receives them, so one table of codes stays in ``order.py`` and no
second copy here can drift from it.

Absence is a value and not a wildcard. A run that read no file has ``before`` of
``None``, which equals an absent HEAD and refuses a HEAD that answered with bytes --
the two absences matching is what lets the very first ``add`` into a fresh repository
run at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from . import labels, orderschema, orderstate
from . import order_gitwrite as gitwrite

# The line a refused run prints. The caller acts on this wording, so it is pinned in
# one place: tests/test_order_writer_race.py and tests/test_order_writer_docs.py both
# name it, and skills/direction/SKILL.md spells it for the operator.
CHANGED = "the order changed since it was read; re-run"

# The two causes of a refusal, told apart because only one of them is fixed by a bare
# re-run. HEAD moving is a concurrent writer and the same command re-plans correctly;
# the file no longer holding what this run read is a local change (or a deletion) no
# re-run can settle, and telling the operator that "the order that was committed
# while it ran still stands" would be a claim this run never observed.
FILE_CHANGED = "the file changed since it was read; restore it or discard the change"

# Which of the two reads moved, named in the hint so a reader of the log can tell
# the two refusals apart even from the line above.
_HEAD_MOVED = "committed order"
_FILE_MOVED = "working file"

# The three answers of a second read of the artifact's own path, shaped like
# ``order_gitwrite``'s answer for HEAD so the two reads of the guard are read the
# same way: ``data`` holds the bytes when the read succeeded; ``code`` is set only
# for a read that FAILED (an absent path is not a failure, it is ``ABSENT_FILE``);
# ``why`` names what this run found at the path, for the fault's own message.
NO_FAULT: int = 0


class Read(NamedTuple):
    """One answer of :func:`file_bytes`: bytes, absence, or a failed read."""

    data: bytes | None
    code: int
    why: str


ABSENT_FILE = Read(data=None, code=NO_FAULT, why="")


def _read(data: bytes) -> Read:
    """The arm for a file this run could read."""
    return Read(data=data, code=NO_FAULT, why="")


def _unreadable(why: str) -> Read:
    """The arm for a path that holds no readable file, naming the shape found."""
    return Read(data=None, code=1, why=why)


def file_bytes(path: Path) -> Read:
    """The bytes at ``path``, or the reason this run cannot get them back.

    The second read of the artifact, in the same currency as the first: absence is
    what ``read_order`` hands back as ``before`` for a path that does not exist, so
    the two compare honestly. A path that is a symlink, a directory, a device or an
    unreadable file is a :class:`Read` with a code and a reason rather than another
    name for absence: a run that read bytes it can no longer read is facing an
    environment fault, and telling the operator to re-run against a concurrent writer
    would send them chasing a rival that was never there.
    """
    kind, why = orderstate.file_kind(path)
    if kind == "absent":
        return ABSENT_FILE
    if kind != "regular":
        return _unreadable(why or "the path is not a regular file")
    try:
        return _read(path.read_bytes())
    except OSError as exc:
        return _unreadable(f"the file could not be read ({exc.__class__.__name__}: "
                           f"{exc.strerror or exc})")


def probe(repo: Path, order_path: Path, before: bytes | None, verb: str,
          repo_arg: str, code_io: int, code_refusal: int) -> int | None:
    """The exit code the probe forces, or ``None`` when this run may write.

    Called after every input, artifact and plan refusal has had its turn and before
    mkdir, the atomic write and any ``git add``, so a refused run neither writes nor
    stages nor moves HEAD. The remedy is a re-run, which re-reads and therefore
    re-plans: ``--at N`` is resolved against the entries of the new run, not the
    stale positions of this one -- and the re-run settles the matter only once the
    working copy agrees with HEAD again, which ``skills/direction/SKILL.md`` says.

    ``before`` is the one thing this run planned from -- the bytes the artifact read
    carried -- and both reads below are compared against it, HEAD first because
    ``git commit --only -- <path>`` replaces whatever HEAD holds: if HEAD no longer
    holds the bytes this run read, the commit drops an entry it never saw. The file
    is compared second, because ``write_atomic`` replaces whatever the path holds: a
    plan built from bytes the file no longer has is not a plan anybody approved, even
    when HEAD never moved. HEAD is asked first so the cause a re-run actually fixes
    is the one a run that has both problems is told about.

    ``code_io`` and ``code_refusal`` are the writer's own codes for an environment
    fault and a refusal of the order, passed in rather than repeated here: one table
    of exit codes, in the file that publishes them.
    """
    committed = gitwrite.committed_bytes(repo, orderschema.ORDER_REL)
    if committed.code is not None:
        return _fault(committed, verb, repo_arg, code_io)
    on_disk = file_bytes(order_path)
    if on_disk.code != NO_FAULT:
        return orderstate._fail(
            code_io, f"{orderschema.ORDER_REL}: {on_disk.why}, so this writer cannot "
            "tell whether the file still holds what it read",
            f"fix that path, then re-run 'order.py {verb}' (a file this writer "
            "cannot read is never read as an unchanged order)",
            label=f"{labels.ORDER}:")
    if committed.data != before:
        return _refused(code_refusal, CHANGED,
                        f"re-run 'order.py {verb}': this run wrote nothing, so the "
                        f"order that was committed while it ran still stands (the "
                        f"{_HEAD_MOVED} moved)")
    if on_disk.data != before:
        return _refused(
            code_refusal, FILE_CHANGED,
            f"bring {orderschema.ORDER_REL} back to what HEAD holds ('git -C "
            f"{repo_arg} checkout HEAD -- {orderschema.ORDER_REL}') and re-run "
            f"'order.py {verb}': the committed order did not move, so this run has "
            f"no rival to report -- the {_FILE_MOVED} is the one it no longer "
            "recognises")
    return None


def _refused(code_refusal: int, headline: str, hint: str) -> int:
    """One refusal of the order, in the writer's own label and shape."""
    return orderstate._fail(code_refusal, f"{orderschema.ORDER_REL}: {headline}",
                            hint, label=f"{labels.ORDER}:")


def _fault(answer: gitwrite.Committed, verb: str, repo_arg: str,
           code_io: int) -> int:
    """The refusal for a probe call that answered nothing, in the writer's voice.

    A probe that cannot answer is an environment fault and never a pass: reading a
    hang or a corrupt object store as "committed bytes, unchanged" would commit an
    order nobody checked, which is the same lie as the lost update this guard exists
    to stop. The two refusals differ in what the caller does next -- a timeout waits
    for git and repeats, any other non-zero answer means the repository itself needs
    looking at -- and neither is the code a concurrent writer gets.
    """
    if answer.code == gitwrite.GIT_TIMEOUT_RC:
        return orderstate._fail(
            code_io, f"git show timed out for {orderschema.ORDER_REL} after "
            f"{gitwrite.GIT_TIMEOUT}s, so this writer cannot tell whether "
            "the committed order still holds what it read",
            f"once git answers again, re-run 'order.py {verb}' (a git that "
            "cannot answer is never read as an unchanged order)",
            label=f"{labels.ORDER}:")
    return orderstate._fail(
        code_io, f"git show failed for {orderschema.ORDER_REL} "
        f"(exit {answer.code}), so this writer cannot tell whether the "
        "committed order still holds what it read",
        f"find out why 'git -C {repo_arg} show "
        f"HEAD:{orderschema.ORDER_REL}' cannot answer, then re-run "
        f"'order.py {verb}'", label=f"{labels.ORDER}:")
