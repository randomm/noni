"""The state-root question of one ``decide`` run, and the exception that admits it.

Split from ``decide.py``, which holds the run. A ``--repo`` that is a directory but
holds no ``noni/`` is the second shape of the wrong path docs/PRODUCT.md 7 describes,
and it is the one a caller actually arrives at: a committed code repository passed
where the state clone was meant is a valid git work tree, so the work-tree probe
admits it and only the question here refuses it.

Two decisions live here and nowhere else:

* whether the run is a **creator** and so admitted, and
* where in the run that question is asked -- which is not free. The writer's own
  :func:`noni._writer.allocate_ledger` runs ``mkdir(parents=True)``, so a question
  about ``noni/`` deferred past the allocation finds the directory this very run
  made and calls it a state root. The exception is therefore handed to
  :func:`noni._decide_flags.refuse_state_root` as a thunk and asked before any
  allocation, over the tree as the caller left it.

The state of the tree the run writes into is asked here too, in the same place and
for the same reason: :func:`refuse_schema_level_skew` asks which ledger schema level
the project's census runs before a byte is written, so a writer that has outrun the
pinned census refuses rather than committing a record its own arbiter then reports.
Like the state-root question, it is asked ahead of the allocation, so a refused run
never leaves a ``noni/`` behind in a tree it may not write to.

The wording, the ordering and the declined-``lstat`` rule all belong to
:mod:`noni._path_kind` and :mod:`noni._decide_flags`; this module only decides the
things that are ``decide``'s own, and hands each refusal the caller's own printer and
the codes the run's module passes in rather than importing them: :data:`noni.decide.EXIT_GIT`
for a wrong path (the code docs/PRODUCT.md 7 gives this tool) and the two codes the
level check returns. :func:`refuse_run` is the one seam the run calls: it holds both
questions and their order, so a later caller cannot ask them out of turn.
"""

from __future__ import annotations

import os
from functools import partial
from pathlib import Path

from . import _decide_flags, _path_kind, _writer, ledger_level


def _holds_nothing(root: Path) -> bool:
    """Whether ``<root>/noni`` is a real directory with nothing in it.

    The census's own ``empty`` state for a ``noni/`` that is there, recomputed from one
    ``listdir`` rather than imported: the census module reaches this side of the package
    through the writers, and a dependency the other way would be a cycle. Absence answers
    False -- that is :func:`noni._path_kind.has_no_noni`'s finding, which the run asked
    first -- and so does a listing the filesystem declined to give: a directory this run
    could not read is not evidence of an empty one, and an empty one is the weaker of the
    two admits, so a fault admits nothing.
    """
    try:
        return not os.listdir(Path(os.path.normpath(str(root)))
                              / _path_kind.STATE_ROOT_DIR)
    except OSError:
        return False


def admits_creation(root: Path, init: bool) -> bool:
    """Whether this run is the sanctioned first record of a brand-new state root.

    One answer and no more: the tree holds no ``noni`` at all and the caller said
    ``--init``. That is the one tree whose record this run can genuinely be the first of,
    and the only one a writer may bring ``noni/`` into being inside. Without the flag a
    recordless tree is a wrong ``--repo``: a committed code repository passed where the
    state clone was meant is a valid git work tree, so the work-tree probe admits it and
    this is the only question that refuses it.

    Anything else about the tree is not this question's to answer. A ``noni`` that
    exists, empty or holding a stray file, is not admitted here: it is state of somebody's,
    and the ledger question that follows refuses the run rather than letting it mkdir a
    ledger under a directory the census already describes. A ``noni`` or ledger that is a
    link, a plain file or a device is refused by the obstruction guard, which the same run
    asks of every component ahead of this. ``--no-commit`` no longer answers here: it used
    to, which let a run write a record into a tree holding no state of anyone's as long as
    it left the commit to somebody else, and the route that needed it is gone.

    Asked of the tree and never of the ledger leaf alone: a question about
    ``noni/decisions`` by itself would be answered yes by a committed code repository,
    which has no ledger either and no state of anyone's.
    """
    return init and _writer.ledger_is_first(root)


def admits_reopening(root: Path, init: bool) -> bool:
    """Whether ``--init`` opens a ``--repo`` whose ``noni/`` exists but holds nothing.

    The create a caller asks for on a tree that is not brand new: an operator who made the
    state clone and created its empty ``noni/`` by hand has a tree with no ledger to write
    into, and the state-root question alone would leave them no way forward. Two questions
    answer it, the tree first: the caller has to have said ``--init``, and ``noni`` has to
    be a directory holding no entry at all.

    The tree half is what keeps the flag from being a waiver. ``--init`` on a repository
    whose ``noni/`` holds a stray file -- an aborted run's residue, an earlier
    mis-targeted write, anything somebody committed under that name -- admits nothing: the
    entries are state of somebody's, so this run is not the one that root was waiting for,
    and a writer that mkdir'd the ledger beside them would commit direction into that
    repository on the caller's branch. The refusal tells the caller to remove the residue
    in the right tree instead.
    """
    return init and _holds_nothing(root)


def refuse_run(fail: _decide_flags.Printer, exit_git: int, exit_usage: int,
               exit_collision: int, repo: Path, init: bool) -> int | None:
    """Both questions this module asks of ``--repo``, in the order they must be asked.

    The state root first, then the census level, because both are asked ahead of the
    allocation and a refusal must never leave a ``noni/`` behind in a tree this run may
    not write to. The caller hands in its printer and its three codes so this stays a
    leaf whose numbers the run's module owns.

    The state-root question is asked through :func:`noni._decide_flags.refuse_state_root`
    with this tool's printer, this tool's code, and this tool's two answers to the creator
    question (:func:`admits_creation` for a brand-new tree, :func:`admits_reopening` for a
    scaffolded one), handed over as thunks so each follows the tree as the caller left it
    rather than the ledger this run is about to allocate. The obstruction question is not
    asked here: :func:`noni._decide_flags.refuse_linked_state` asks it of the same
    ``lstat`` ahead of this, so a linked ``noni/`` keeps the sentence that names it.
    """
    refused = _decide_flags.refuse_state_root(
        fail, exit_git, repo, partial(admits_creation, root=repo, init=init),
        partial(admits_reopening, root=repo, init=init))
    if refused is not None:
        return refused
    return refuse_schema_level_skew(fail, exit_usage, exit_collision, repo)


def refuse_schema_level_skew(fail: _decide_flags.Printer, exit_usage: int,
                             exit_collision: int, repo: Path) -> int | None:
    """The refusal printed when this writer has outrun the project's census, or None.

    The question a run asks of the tree it is about to write: is
    :data:`noni.ledger_level.LEDGER_SCHEMA_LEVEL` above the level the project's
    ``noni/direction/census-level.json`` declares? If it is, the record this run
    would commit may carry a field the census at that level reports as an unknown
    field, which is the drift the shared schema declares one level for. The run
    returns its collision code -- the ledger it would have written is one its own
    arbiter refuses.

    A declaration the run cannot read is refused too, with the usage code, and is
    never treated as silence: bytes that are not readable JSON, a document that is
    not an object, or a level that is not an integer of at least 1 say nothing
    about the census, and writing into that uncertainty is the silent drift the
    check exists to close. A tree with no declaration file at all answers None and
    writes exactly as it did before the file existed.

    :param fail: ``decide``'s own failure printer, so the prefix stays ``decide.py``.
    :param exit_usage: :data:`noni.decide.EXIT_USAGE`, for a declaration that
        answers nothing; :param exit_collision: :data:`noni.decide.EXIT_COLLISION`,
        for a level this writer has passed. Both are pinned by the caller rather
        than imported, so this module stays a leaf whose codes the run's module owns.
    """
    try:
        declared = ledger_level.read_schema_level(repo)
    except ledger_level.DeclarationError as exc:
        return fail(exit_usage, *ledger_level.declaration_refusal(exc.why))
    if declared is None or ledger_level.LEDGER_SCHEMA_LEVEL <= declared:
        return None
    return fail(exit_collision, *ledger_level.schema_level_skew(
        ledger_level.LEDGER_SCHEMA_LEVEL, declared))
