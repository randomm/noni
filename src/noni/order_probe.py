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

import os
import stat
from pathlib import Path
from typing import NamedTuple

from . import _path_kind, labels, orderstate
from . import order_gitwrite as gitwrite

# The line a refused run prints. The caller acts on this wording, so it is pinned in
# one place: tests/test_order_writer_race.py and tests/test_order_writer_docs.py both
# name it, and skills/direction/SKILL.md spells it for the operator.
CHANGED = "the order changed since it was read; re-run"

# The three causes of a refusal, told apart because each has its own remedy and only
# one of them is fixed by a bare re-run. HEAD moving is a concurrent writer and the
# same command re-plans correctly; the file no longer holding what this run read is a
# local change (or a deletion) no re-run can settle, and telling the operator that
# "the order that was committed while it ran still stands" would be a claim this run
# never observed. The index holding bytes that are neither HEAD's nor this run's plan
# is the third, and no re-run settles that either: the next run reads those bytes and
# stages its own, and the operator has to say which of the two orders is wanted.
FILE_CHANGED = "the file changed since it was read; restore it or discard the change"

INDEX_CHANGED = ("the staged copy of the file holds an order this run did not read; "
                 "unstage it or commit it first")

# Which of the three reads moved, named in the hint so a reader of the log can tell
# the three refusals apart even from the line above.
_HEAD_MOVED = "committed order"
_FILE_MOVED = "working file"
_INDEX_MOVED = "staged copy"

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

    The shape question is asked of the package's fail-closed classifier
    (:func:`noni._path_kind.kind_of`) and not of this module's own reader, for two
    reasons. ``orderstate.file_kind`` calls a declined ``lstat`` "absent", which is
    right for the FIRST read (a writer about to create a file may accept that answer)
    and wrong here, where the run has already read bytes once: an ``EACCES`` from a
    parent the operator cannot read is not evidence that nothing sits at the path. And
    ``os.lstat`` raises ``ValueError`` -- not ``OSError``, and it carries no
    ``strerror`` -- for a name carrying a NUL, which :func:`kind_of` catches beside its
    sibling, so this guard owes the operator a refusal instead of a traceback in the
    middle of a commit.

    :func:`kind_of` answers three states and this read must not confuse them: nothing
    of mine is here (ENOENT, ENOTDIR) is the absence the first read may also have seen;
    a link, a directory, a device or a socket is a shape this writer never reads
    through; anything else is the filesystem declining to say. The middle arm of the
    ``if`` below is the one a guard written against ``OSError`` alone gets wrong.
    """
    kind, declined = _path_kind.kind_of(path)
    if kind is None and declined is None:
        # Either nothing of the writer's is at the path (ENOENT, ENOTDIR) or a plain
        # file sits there. Only ``lstat``'s mode tells those apart, and the guard has
        # to: the first is the absence ``read_order`` reported as ``before`` of ``None``
        # and the second is the read this comparison is about.
        if _is_regular(path):
            try:
                return _read(path.read_bytes())
            except (OSError, ValueError) as exc:
                # The shape was fine a moment ago and the read still failed: that is
                # the environment's fault, and reading it as absence would compare
                # ``None`` against the bytes this run planned against and blame a rival
                # writer that never ran.
                return _unreadable(_declined(exc))
        return ABSENT_FILE
    if kind is None:
        return _unreadable(_path_kind._declined(declined))
    return _unreadable(f"the path {kind}")


def _is_regular(path: Path) -> bool:
    """Whether ``path`` itself (not a link it points at) is a plain file.

    The one question :func:`noni._path_kind.kind_of` does not answer: it reports why a
    path is NOT a plain file and says nothing about the path that is one, so a caller
    that treated its silence as "regular" would read a directory or a device as a file.
    ``lstat`` again, never ``stat``: a link is a refusal on this path, not a file.
    """
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except (OSError, ValueError):
        return False


def _declined(exc: BaseException) -> str:
    """The 'this file could not be read' sentence for an exception with no ``strerror``.

    ``ValueError`` -- what every syscall raises for a path carrying a NUL, and the one
    an ``lstat`` guard that catches only ``OSError`` would let escape as a traceback --
    has no ``strerror``, so the reason is taken from the message the filesystem itself
    wrote there.
    """
    reason = getattr(exc, "strerror", None) or str(exc)
    return (f"the file could not be read ({exc.__class__.__name__}: "
            f"{reason or 'no reason given'})")


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
    carried -- and everything below is compared against it. Three reads, in the order
    their remedies differ, each naming the file derived from the ``order_path`` the
    caller was handed so no read can answer about one path while another answers
    about a different one (see :func:`_artifact_rel`):

      HEAD   -- asked first, because ``git commit --only -- <path>`` replaces
         whatever HEAD holds: if HEAD no longer holds the bytes this run read, the
         commit drops an entry it never saw, and this is the one refusal a re-run
         actually settles.
      the index -- asked second, because it is what that same commit takes: git
         commits the bytes the index holds at the path, not the bytes on disk, so an
         entry staged by another hand lands in HEAD holding content this run neither
         read nor planned. Refused when it agrees with neither HEAD nor this plan.
      the file -- asked last, because ``write_atomic`` replaces whatever the path
         holds: a plan built from bytes the file no longer has is not a plan anybody
         approved, even when HEAD never moved.

    ``code_io`` and ``code_refusal`` are the writer's own codes for an environment
    fault and a refusal of the order, passed in rather than repeated here: one table
    of exit codes, in the file that publishes them.
    """
    rel, refusal = _artifact_rel(repo, order_path)
    if refusal is not None:
        return orderstate._fail(code_io, refusal[0], refusal[1],
                                label=f"{labels.ORDER}:")
    committed = gitwrite.committed_bytes(repo, rel)
    if committed.code is not None:
        return _fault(committed, verb, repo_arg, code_io, rel)
    head_exists, head_fault = gitwrite.tree_blob_id(repo, "HEAD")
    if head_fault:
        return _head_fault(rel, repo_arg, verb, code_io, head_fault)
    on_disk = file_bytes(order_path)
    if on_disk.code != NO_FAULT:
        return orderstate._fail(
            code_io, f"{rel}: {on_disk.why}, so this writer cannot "
            "tell whether the file still holds what it read",
            f"fix that path, then re-run 'order.py {verb}' (a file this writer "
            "cannot read is never read as an unchanged order)",
            label=f"{labels.ORDER}:")
    if head_exists is None:
        # No commit at all, so the commit this run is about to make is the repository's
        # first. That is the one state in which the guard has nothing to guard: there
        # is no order in HEAD for a rival to have moved, and the path-restricted
        # ``git commit --only -- <path>`` the writer uses cannot record a first commit
        # for a path the index does not already hold -- so a guard that compared the
        # index here would refuse the very state the quickstart tells the operator to
        # create, and no re-run of it would ever be accepted. Absence of HEAD is read
        # as "no committed order to lose", which is the same answer the two comparisons
        # below would give, and is asked as a return code for the same reason.
        return None
    staged, fault = gitwrite.index_blob_id(repo, rel)
    if fault:
        return _index_fault(rel, repo_arg, verb, code_io, fault)
    head_blob, fault = gitwrite.blob_id(repo, committed.data)
    if fault:
        return _hash_fault(rel, repo_arg, verb, code_io, fault)
    plan_blob, fault = gitwrite.blob_id(repo, before)
    if fault:
        return _hash_fault(rel, repo_arg, verb, code_io, fault)
    # The index is asked only when it holds the path, because that is the one shape
    # the commit obeys: ``git commit --only -- <path>`` takes the path from the index,
    # so those bytes and not the ones on disk are what HEAD will hold. An index that
    # does not hold the path at all is NOT a third state to refuse -- the ``git add --
    # <path>`` the writer makes a moment before the commit fills it from the working
    # copy, and the working copy is the file read below, checked against this run's own
    # plan. Refusing an unstaged path would refuse every ordinary run, and a staged
    # DELETION of the path is that same state by git's own spelling (the row is removed
    # from the index), not a claim the writer is about to delete the artifact.
    if staged is not None and staged != head_blob and staged != plan_blob:
        return _refused(
            code_refusal, INDEX_CHANGED,
            f"unstage {rel} ('git -C {repo_arg} restore --staged -- {rel}') or commit "
            f"what is staged, then re-run 'order.py {verb}': HEAD and the file still "
            f"hold what this run read, so the {_INDEX_MOVED} is the one it cannot "
            "account for", rel)
    if committed.data != before:
        return _refused(code_refusal, CHANGED,
                        f"re-run 'order.py {verb}': this run wrote nothing, so the "
                        f"order that was committed while it ran still stands (the "
                        f"{_HEAD_MOVED} moved)", rel)
    if on_disk.data != before:
        return _refused(
            code_refusal, FILE_CHANGED,
            f"bring {rel} back to what HEAD holds ('git -C "
            f"{repo_arg} checkout HEAD -- {rel}') and re-run "
            f"'order.py {verb}': the committed order did not move, so this run has "
            f"no rival to report -- the {_FILE_MOVED} is the one it no longer "
            "recognises", rel)
    return None


def _artifact_rel(repo: Path, order_path: Path) -> tuple[str, tuple[str, str] | None]:
    """The ``(rel, refusal)`` git uses for ``order_path`` inside ``repo``.

    Derived, never assumed. The writer composes ``order_path`` as ``repo`` plus the
    artifact's path, and for that state the two answers are identical; deriving it is
    what makes the equality a fact of this run rather than of a constant. A probe
    that spelled the path from :data:`noni.orderschema.ORDER_REL` would ask HEAD and
    the index about one file and re-read the disk at another, and the two halves of
    one guard would then be comparing two different artifacts -- a refusal that
    names the wrong file, or a pass for an artifact nobody checked.

    A path that is not under the repository asked for is refused as an environment
    fault: the writer cannot name a git path for it, and git's own answer for such a
    revspec is a fatal it would have to be read out of a sentence.
    """
    try:
        rel = order_path.relative_to(repo).as_posix()
    except ValueError:
        return ("", ("the order path is not a path inside the repository this run "
                     "was given, so this writer cannot name it to git",
                     "point --repo at the tree that holds the order, then re-run "
                     "order.py"))
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return ("", ("the order path could not be named as a path inside the "
                     "repository",
                     "point --repo at the tree that holds the order, then re-run "
                     "order.py"))
    return rel, None


def _refused(code_refusal: int, headline: str, hint: str, rel: str) -> int:
    """One refusal of the order, in the writer's own label and shape.

    The path it names is the one every read of this guard asked about, so the line
    the operator reads and the three comparisons behind it cannot disagree.
    """
    return orderstate._fail(code_refusal, f"{rel}: {headline}",
                            hint, label=f"{labels.ORDER}:")


def _head_fault(rel: str, repo_arg: str, verb: str, code_io: int, fault: str) -> int:
    """The refusal for a HEAD this run could not resolve, in the writer's voice.

    Distinct from :func:`_fault` below: that one reports a blob read that failed, this
    one reports that the guard could not even settle whether the repository has a
    commit. Both are environment faults and neither is ever read as "nothing moved".
    """
    return orderstate._fail(
        code_io, f"git could not tell whether this repository has a commit "
        f"({fault}), so this writer cannot tell what the committed order at "
        f"{rel} holds",
        f"find out why 'git -C {repo_arg} rev-parse --verify --quiet HEAD' cannot "
        f"answer, then re-run 'order.py {verb}'", label=f"{labels.ORDER}:")


def _index_fault(rel: str, repo_arg: str, verb: str, code_io: int, fault: str) -> int:
    """The refusal for an index this run could not look in, in the writer's voice.

    Same rule as the HEAD read: a call that answered nothing is never read as "the
    index agrees with HEAD", which is how a staged order somebody else wrote would
    reach HEAD unchecked. Named as the index and not as the ``git show`` below it, so
    the operator goes looking at the right thing.
    """
    return orderstate._fail(
        code_io, f"git ls-files failed for {rel}, so this writer cannot tell "
        f"what the index holds at that path ({fault})",
        f"find out why 'git -C {repo_arg} ls-files -s -- {rel}' cannot answer, "
        f"then re-run 'order.py {verb}'", label=f"{labels.ORDER}:")


def _hash_fault(rel: str, repo_arg: str, verb: str, code_io: int, fault: str) -> int:
    """The refusal for an id this run could not get, in the writer's voice.

    The index comparison is made between object ids, so a run that cannot name the id
    of the bytes it read cannot make it. Reading that as "the index agrees with me"
    would be the guard passing on a question it never got an answer to.
    """
    return orderstate._fail(
        code_io, f"git hash-object could not name the bytes this run read at "
        f"{rel} ({fault}), so this writer cannot compare the index against them",
        f"find out why 'git -C {repo_arg} hash-object --stdin' cannot answer, "
        f"then re-run 'order.py {verb}'", label=f"{labels.ORDER}:")


def _fault(answer: gitwrite.Committed, verb: str, repo_arg: str,
           code_io: int, rel: str) -> int:
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
            code_io, f"git show timed out for {rel} after "
            f"{gitwrite.GIT_TIMEOUT}s, so this writer cannot tell whether "
            "the committed order still holds what it read",
            f"once git answers again, re-run 'order.py {verb}' (a git that "
            "cannot answer is never read as an unchanged order)",
            label=f"{labels.ORDER}:")
    return orderstate._fail(
        code_io, f"git show failed for {rel} "
        f"(exit {answer.code}), so this writer cannot tell whether the "
        "committed order still holds what it read",
        f"find out why 'git -C {repo_arg} show "
        f"HEAD:{rel}' cannot answer, then re-run "
        f"'order.py {verb}'", label=f"{labels.ORDER}:")
