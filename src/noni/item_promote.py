"""The promote that rewrites two artifacts: the item, and the order that cited it.

``item.py promote`` marks a candidate as the issue it became. When an order entry cites
that item -- the ``item`` field of ``noni.order/2``, the only way a queue can hold an
idea that is not yet an issue -- the entry has to carry the new issue instead, and the
item file's own status changes in the same breath. Committing one and not the other
leaves the queue holding a position for an idea that has become work, which is the
disagreement the item census classes exist to report. So both bytes land in one commit
or neither does.

The module exists because neither writer owns this shape on its own: ``item.py`` cannot
reach into the order writer's commit, and ``order.py`` commits one path and carries no
rollback. What it reuses is what already does the job --
:func:`noni._writer.stage_and_commit` (``git add -- <paths>`` then
``git commit --only -- <paths>``, both paths rolled back through
:func:`noni.gitwrite.rollback` when either step fails), :func:`noni.order_probe.probe`
(the order's lost-update guard: HEAD, the working file and the index, each with its own
remedy) and :func:`noni.order_gitwrite.write_atomic` (a same-directory temp file and
``os.replace``, the mode taken from the file being replaced).

Why the guard is asked at all: this run read the order, built its rewrite from those
entries, and the commit takes each path from the index, so anything a second hand
committed or staged inside that window would be replaced by bytes this run never saw --
and a promote that rewrote two files from one read inherits that race across both of
them. A run that refuses on a check, on the guard or on a rival's commit writes, stages
and commits nothing.

The one case no check can cover is a write that fails halfway: the item lands and the
order does not. :func:`rollback` puts both paths back, and where it cannot (a directory
that will not hold either file) it says so rather than reporting a clean undo -- so the
state an operator can meet is the reported one, a promoted item whose committed order
still cites it, and never a record the run destroyed on the way out.

Nothing here prints or exits. The exit codes arrive as arguments the way
``orderstate`` takes them, so the one table of codes stays in the writer that publishes
them, and the prose of each refusal is the order writer's own: the operator learns one
remedy for a moved order, whichever command happened to be the one running.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from . import _writer, gitwrite, item_write, itemschema, order_probe, orderschema, orderstate
from . import order_gitwrite as orderwrite


class Pair(NamedTuple):
    """The two renderings a citing promote writes, plus the bytes it read them from.

    ``order_before`` is what the order held when this run read it, and ``None`` is the
    honest "there was no file" -- the state a first write into an empty tree matches,
    and the value the guard compares HEAD against.
    """

    item_rel: str
    item_bytes: bytes
    order_rel: str
    order_bytes: bytes
    order_before: bytes | None


class Refused(Exception):
    """The rewritten order cannot be rendered, so there is nothing to commit.

    Carries the (headline, hint) pair the caller prints and the code it returns:
    the render step is the last thing between a checked plan and a written file, and a
    renderer that refuses its own validated output is the writer's bug rather than a
    property of the file -- which is why the pair arrives with a code chosen by the
    caller rather than one invented here.
    """

    def __init__(self, headline: str, hint: str) -> None:
        super().__init__(headline)
        self.headline = headline
        self.hint = hint


def plan(item_body: dict, entries: list, item_rel: str,
         before: bytes | None) -> Pair:
    """The pair a citing promote writes, from the item's body and the rewritten entries.

    The order goes through its own renderer and never through a hand-assembled document:
    ``order.py`` refuses bytes it would render differently, so a promote that composed
    JSON of its own could write an order no verb would open again. The version is the
    version those entries describe -- ``/1`` once the last item entry has been rewritten
    to its issue, ``/2`` while another still cites an idea -- so the artifact keeps the
    version its own contents need and never a version this run guessed.

    :raises Refused: when either rendering is impossible, which is the writer's own bug
    rather than the operator's, since every value of the plan was validated upstream.
    """
    try:
        item_bytes = itemschema.item_bytes(item_body)
        rendered = orderstate.render(orderstate.body_of(
            {"schema": orderschema.schema_for({"entries": entries}),
             "entries": entries}))
    except ValueError:
        raise Refused("the promoted item and its order entry cannot be written as JSON",
                      "re-run item.py; if it repeats, remove the item and re-file "
                      "the idea") from None
    if isinstance(rendered, orderstate.RenderRefused):
        raise Refused(rendered.headline, rendered.hint)
    return Pair(item_rel, item_bytes, orderschema.ORDER_REL, rendered, before)


def guard(repo: Path, pair: Pair, verb: str, repo_arg: str, exit_io: int,
          exit_refusal: int) -> int | None:
    """The exit code the freshness guard forces, or None when this run may commit.

    A pair that read no order has no committed bytes to compare, so the probe is not
    asked of a file this run never saw: the comparison it would make has no baseline, and
    refusing the first order a project ever wrote on the strength of a file that appeared
    beside it is not what the guard means. Everything else is asked of the order writer's
    own probe, in the writer's own words and under the order writer's own label, so a
    promote refused for a rival writer prints the sentence an ``order.py`` run prints.
    The item path is not asked: this run read one file, rewrote it atomically, and the
    commit names the path explicitly, so there is no second entry list for a rival to
    have moved underneath it.
    """
    if pair.order_before is None:
        return None
    return order_probe.probe(repo, repo / pair.order_rel, pair.order_before, verb,
                             repo_arg, exit_io, exit_refusal)


def write(repo: Path, pair: Pair, seen: dict | None = None,
          writer=orderwrite.write_atomic) -> bool:
    """Land both renderings, each through the order writer's own atomic writer.

    Bytes, not text, at both paths: the freshness guard compares this run's bytes
    against git's, and a writer that translated on the way out would make that
    comparison a coin flip. The item is written first so a crash between the two leaves a
    promoted item whose order still cites it -- a state the census reports as the
    disagreement it is -- rather than an order citing an idea the store still calls a
    candidate, which is the same disagreement from the side no verb can repair.

    ``seen``, when the caller hands in a dict, is told whether the item path held a file
    before this run put one there, and told *as it is asked*, before either write and
    before the directory is made. That is the one fact :func:`rollback` needs to undo the
    write without destroying a record, and a caller that read it back from the return
    value would not have it for the very fault the undo exists for: the second write
    raising leaves the first on disk and this function never returns. The making of the
    order directory can itself raise, and a fact recorded after it would be missing for
    exactly that fault.

    :raises OSError: for either path, with the caller's own wording of which directory
    to make writable; the direction directory is created here because a promote is the
    first writer a project with no order has ever run. ``writer`` is the atomic writer
    itself, and a test that wants one path to fail hands in a different one; production
    callers leave it at the order writer's own.
    """
    item_existed = (repo / pair.item_rel).is_file()
    if seen is not None:
        seen["item_existed"] = item_existed
    (repo / orderschema.ORDER_DIR).mkdir(parents=True, exist_ok=True)
    writer(repo / pair.item_rel, pair.item_bytes)
    writer(repo / pair.order_rel, pair.order_bytes)
    return item_existed


def rollback(repo: Path, pair: Pair, item_existed: bool = False) -> str | None:
    """Undo a two-path write that raised partway: None when the tree is clean again.

    ``write`` puts the item down first and lets whichever path failed raise the
    ``OSError``, so the state this leaves is the one no verb can repair on its own -- a
    promoted item whose committed order still cites the idea. This puts both paths back.

    The order half is the undo ``commit`` uses for a git step that failed: both paths
    leave the index and the order is written back to ``pair.order_before``, the bytes this
    run read at the freshness guard, through :func:`noni.gitwrite.write_atomic` -- so a
    directory that refused the first write refuses this one too, and the failure is
    reported rather than papered over. An order this run meant to *create* has no
    committed bytes to restore, so the file it wrote at a path that held none is simply
    taken away.

    The item half is spelled here rather than taken from that undo, because that undo's
    first act is an unconditional ``unlink`` of its record path -- right for decide's
    supersede, whose record is a file that run created, wrong for a promote. ``add`` files
    the candidate and ``promote`` replaces it, so the file at that path belonged to the
    store before this run began, and deleting one the run did not create would destroy a
    record while reporting a clean rollback. ``item_existed`` is what ``write`` saw there:
    the path is unlinked only when this run made the file, and a file it replaced is left
    holding this run's bytes -- the state the census reports as the disagreement it exists
    to name, and the one a re-run of the same command repairs once the fault is gone.

    The caller prints what comes back: the undo's own wording when the undo could not
    finish, so nothing is ever reported as rolled back that was not.
    """
    if not item_existed:
        try:
            (repo / pair.item_rel).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return f"{pair.item_rel} could not be removed"
    reset = gitwrite.run_git(repo, "reset", "-q", "--",
                             pair.item_rel, pair.order_rel)
    if reset.returncode != 0:
        detail = reset.stderr.strip() or reset.stdout.strip() or "no reason given"
        return (f"git reset failed (exit {reset.returncode}): {detail}; "
                f"{pair.item_rel} and {pair.order_rel} may still be staged")
    if pair.order_before is None:
        try:
            (repo / pair.order_rel).unlink()
        except FileNotFoundError:
            return None
        except OSError:
            return f"{pair.order_rel} could not be removed"
        return None
    try:
        gitwrite.write_atomic(repo / pair.order_rel,
                              pair.order_before.decode("utf-8"))
    except OSError:
        return f"{pair.order_rel} could not be written back"
    return None


def unchanged(repo: Path, pair: Pair) -> bool:
    """Whether both paths already hold exactly these bytes, so the run has nothing to do.

    Asked of both files and not one: an item already promoted and an order already
    rewritten is a repeat of a finished promote, and the honest report is that nothing
    changed -- with no commit, since a commit of unchanged bytes would move HEAD for no
    content. A missing order is never "unchanged": this run planned to create it, so
    there is a file to write and a commit to make. A run whose item changed but whose
    order did not is the other case, and it commits: the order's bytes are already what
    this run would write, so the one thing left to record is the item.
    """
    if pair.order_before is None:
        return False
    return (item_write.unchanged(repo / pair.item_rel, pair.item_bytes)
            and item_write.unchanged(repo / pair.order_rel, pair.order_bytes))


def commit(label: str, repo: Path, pair: Pair, subject: str) -> tuple[str, str] | None:
    """Stage and commit both paths in one commit, or hand back a (headline, hint) refusal.

    The caller owns the code and the printing; this only sequences the git steps and
    their rollback. The rollback's two slots are filled by what they hold here: the
    *record* is the item file this run wrote (the undo unlinks it, which is right for a
    path this run created and harmless for one it replaced), and the *target* is the
    order, whose committed bytes this run read at check time and can be restored from.
    """
    return _writer.stage_and_commit(label, repo,
                                    [pair.item_rel, pair.order_rel], subject,
                                    target_rel=pair.order_rel,
                                    record_rel=pair.item_rel,
                                    committed_bytes=pair.order_before)
