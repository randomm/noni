"""The order writer's last two steps: land the artifact, then commit exactly it.

``order.py`` owns the verbs, the codes, the plan and the guard; this module owns what
happens once a plan has been rendered and the lost-update probe has said this run may
write. Two steps, in that order, and the order between them is the contract: the file
lands on disk first, and only then does git see it, so a run refused by git leaves the
operator something to commit by hand rather than a plan that never existed outside this
process.

Both steps answer in the caller's currency -- an exit code out of the table
``order.py`` publishes, and a (headline, hint) pair out of the wording the writer prints
-- so the one voice that refuses stays the writer's and the one table of codes stays in
the file whose docstring publishes it. Nothing here prints or exits.

Why the write is not folded into the commit: ``git commit --only -- <path>`` takes the
path's bytes from the index, and the index is filled from the working copy by the
``git add`` a moment before. A step that committed straight from a plan would report
committed bytes the file never held, and the census reads the file.
"""

from __future__ import annotations

from pathlib import Path

from . import labels, orderschema
from . import order_gitwrite as gitwrite


def parent_refusal(repo: Path) -> tuple[str, str] | None:
    """Why ``noni/direction`` cannot hold the artifact, or None once it can.

    The one shape about the artifact's parent that the pre-read walk does NOT own: an
    ordinary FILE at ``noni/direction``, under a real ``noni/``, which the walk admits
    because nothing above it is a link. A symlink at that position never reaches here (it
    is refused with the rest of the tree at exit 2, before the artifact is read); a plain
    file is an environment fault, and ``mkdir`` would have failed anyway with a worse
    message -- it would have said "not a directory" about a path the operator cannot see
    from the command they ran.
    """
    parent = repo / orderschema.ORDER_DIR
    if parent.exists() and not parent.is_dir():
        return (f"{orderschema.ORDER_DIR} is not a directory",
                f"remove {orderschema.ORDER_DIR} or move it aside, then re-run "
                "order.py")
    return None


def write(repo: Path, rendered: bytes) -> tuple[str, str] | None:
    """Create the artifact's directory and land ``rendered``, or the (headline, hint) fault.

    ``write_atomic`` is the order writer's own: a same-directory temp file and
    ``os.replace``, with the mode taken from the file being replaced, so a run either
    leaves the whole document or leaves the one that was there. The directory is created
    here rather than at the top of the run because a writer that creates state before it
    knows it may write is a writer that leaves empty directories behind.
    """
    order_path = repo / orderschema.ORDER_REL
    try:
        order_path.parent.mkdir(parents=True, exist_ok=True)
        gitwrite.write_atomic(order_path, rendered)
    except OSError as exc:
        return (gitwrite.written(exc, f"{orderschema.ORDER_REL} could not be "
                                 "written"),
                f"check that {orderschema.ORDER_DIR} is writable, then re-run order.py")
    return None


def commit(repo: Path, verb: str, digest: str) -> tuple[str, str] | None:
    """Stage and commit the artifact's one path, or the (headline, hint) git refused with.

    ``git add -- <path>`` then ``git commit --only -- <path>``, so the commit carries
    exactly what this run wrote and never a file somebody else had staged. Each of the
    four ways git can answer badly -- a hung add, a failed add, a hung commit, a failed
    commit -- names what the run had already achieved, because the truth the operator
    needs is where the file stands: written but unstaged, or written and staged but not
    committed, each with the command that finishes the job by hand. A timeout is its own
    arm because a call that gave no answer may or may not have run, so the remedy is to
    ask git rather than to repeat it.
    """
    rel = orderschema.ORDER_REL
    added = gitwrite.git(repo, "add", "--", rel)
    refused = _git_refusal("add", rel, added,
                           "check 'git status --porcelain' once git answers, then stage "
                           "and commit the path by hand or re-run order.py",
                           "the file is written, its staged state unknown",
                           f"run 'git status --porcelain -- {rel}' and stage the path by "
                           "hand, or re-run order.py",
                           "unstaged")
    if refused is not None:
        return refused
    committed = gitwrite.git(repo, "commit", "-q", "-m", f"direction: {verb} [{digest}]",
                             "--only", "--", rel)
    return _git_refusal("commit", rel, committed,
                        "check 'git log -1 --oneline' once git answers, then commit the "
                        "path by hand or re-run order.py",
                        "the file is written and staged, not committed",
                        f"commit {rel} by hand, or re-run order.py once git answers",
                        "staged, not committed")


def git_layer() -> object:
    """The git module this writer's steps call through, for the tests that drive git.

    Exposed rather than imported into the writer's own namespace: ``order.py`` names no
    git call of its own any more, and a test seam has to be the module object the calls
    are actually made on -- replacing a copy would let a hung git stay hung.
    """
    return gitwrite


def report(order_path: Path, verb: str, no_commit: bool) -> None:
    """The run's last two lines: what was written, and whether git has it.

    One function for both routes because the path it prints must be the same token
    whichever ran -- ``--repo`` plus the artifact's path under it, the caller-cwd form
    issue #77 asks for -- and two call sites printing it is two chances to drift. The
    uncommitted line names the path as something the caller still owes, because the
    census reads the working tree and a file the census cannot see as committed is not
    committed.
    """
    if no_commit:
        print(f"{labels.ORDER}: wrote {order_path}; left uncommitted: "
              "commit this path before running the census")
        return
    print(f"{labels.ORDER}: committed {order_path} ({verb})")


def _git_refusal(verb: str, rel: str, result, hung_hint: str, hung_state: str,
                 failed_hint: str, failed_state: str) -> tuple[str, str] | None:
    """The (headline, hint) pair for one git step's bad answer, or None when it passed.

    The two answers a step can give that are not success are spelled here rather than at
    the call sites because they are the same two questions twice: did the call run out of
    time (no answer, so the state is unknown and the remedy is to ask git), or did it
    answer "no" (which is a reason, quoted verbatim, with the state it left behind named
    exactly). The reason text is git's own and is never invented here; when git gave
    none, the line says so rather than printing an empty parenthesis.
    """
    if result.returncode == gitwrite.GIT_TIMEOUT_RC:
        return (f"git {verb} timed out for {rel} after {gitwrite.GIT_TIMEOUT}s "
                f"({hung_state})", hung_hint)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no reason given"
        return (f"git {verb} failed for {rel} (the file is written, "
                f"{failed_state}): {detail}", failed_hint)
    return None
