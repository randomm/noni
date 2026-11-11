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
  :func:`_refuse_state_root` as a thunk and asked before any
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
from collections.abc import Callable
from functools import partial
from pathlib import Path

from . import _decide_flags, _path_kind, _writer, ledger_level
from ._safe_text import safe_path


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


def _refuse_state_root(printer: _decide_flags.Printer, code: int,
                       repo: Path,
                       admits: Callable[[], bool],
                       admits_reopening: Callable[[], bool] | None = None) -> int | None:
    """The exit code for a ``--repo`` that is no noni state root, or None.

    The question a run asks of its ``--repo`` before it writes anything: the tree holds
    state of somebody's or it holds none, and a tree holding none is a wrong ``--repo``
    whatever the verb intends -- a committed code repository passed where the state clone
    was meant passes the git work-tree probe, so this is the seam that refuses it.

    ``admits`` is the run's creator exception, asked HERE, over the tree as it stands:
    the writer below is reached only once the state root has been settled, and its own
    :func:`noni._writer.allocate_ledger` runs ``mkdir parents=True`` -- so a question about
    the tree deferred past that allocation finds the ``noni/`` this very run made and calls
    it a state root, which is how a wrong ``--repo`` used to answer its own question and
    gain a ledger and a committed record of its own. A writer hands the answer over as a
    thunk so the exception follows the tree's contents rather than the verb's say-so, and
    is asked here -- before the guard that can decline to ask anything at all.

    The obstruction question is not asked here: :func:`refuse_linked_state` asks it of the
    same ``lstat`` ahead of this, so a linked ``noni/`` keeps the sentence that names it.
    ``code`` is the caller's own constant and ``printer`` its own, so the prefix is the
    command the operator ran and the number is the one its documents state.

    This is the one seam that asks for the ``--init`` tail (``init=True`` below): it is
    reached only by ``decide``, the writer that owns the flag. The readers reach
    :func:`noni._path_kind.state_root_refusal` through
    :func:`noni._path_kind.refuse_state_root` and keep the two shared sentences, so no
    command prints a fix line naming a flag it answers with argparse's exit 2.

    The seam asks a second question of a run the creator exception did not admit, because
    the shared sentence above can only report a tree with no ``noni/`` at all: a tree whose
    ``noni/`` is there but holds neither of the three artifacts is neither absent nor a
    state root with something in it, and :func:`noni._path_kind.state_root_refusal` answers
    None for it. That is the state an aborted or mis-targeted run leaves in a code
    repository, and a writer that mkdir'd the ledger under it would commit direction into
    that repository on the caller's branch -- the exposure this refusal exists to close. So
    a run that is not a creator is refused for an absent ledger too, in the words below,
    and only a tree that holds a real ledger or a real ``noni/direction`` is admitted to
    write into it. A reader asks neither question: it writes nothing and leaves an absent
    ledger to its own answer about the record it could not read.

    ``admits_reopening`` is the same caller's word for the second create, asked only when
    the ledger question finds nothing: ``--init`` on a tree whose ``noni/`` exists but
    holds no artifact. A caller with no flag to give passes nothing and is refused there,
    which is why the parameter is optional and why the readers never reach it. It is a
    second thunk rather than the first one's answer because the two admits differ by the
    flag alone: a bare tree is admitted with ``--init`` by ``admits``, and a scaffolded one
    by this.
    """
    if admits():
        return None
    reopens = admits_reopening is not None and admits_reopening()
    if not _path_kind.state_root_ledger_is_absent(repo):
        return None
    if reopens:
        return None
    refused = (_path_kind.state_root_refusal(repo, init=True)
               or _no_ledger_refusal(repo, reopens=_path_kind.noni_is_empty(repo)))
    return None if refused is None else printer(code, *refused)


def _no_ledger_refusal(repo: Path, reopens: bool) -> tuple[str, str] | None:
    """The ``(headline, hint)`` pair for a ``--repo`` whose ``noni/`` holds no artifact.

    :func:`noni._path_kind.state_root_ledger_is_absent` asks the question; the wording is
    :mod:`noni._path_kind`'s, as every refusal's is, and the path is the root as the caller
    spelled it, rendered once through :func:`noni._safe_text.safe_path`. ``reopens`` says
    whether ``--init`` would open this very tree (an ``noni`` that exists and holds
    nothing), and picks the hint that names the flag; a tree holding a stray file gets the
    hint that tells the caller to clear the residue instead, because the flag admits
    nothing there and promising it would be a second dead-end fix line. Nothing is printed
    and nothing raises: the caller prints the pair with its own label and code.
    """
    if not _path_kind.state_root_ledger_is_absent(repo):
        return None
    text = safe_path(str(repo))
    hint = _path_kind.STATE_ROOT_NO_LEDGER_HINT + (
        _path_kind.STATE_ROOT_NO_LEDGER_INIT_HINT if reopens else
        "; if a run left this noni/ behind in the wrong repository, remove it there "
        "rather than adding records to it")
    return (_path_kind.STATE_ROOT_NO_LEDGER.format(path=text), hint)

def refuse_run(fail: _decide_flags.Printer, exit_git: int, exit_usage: int,
               exit_collision: int, repo: Path, init: bool) -> int | None:
    """Both questions this module asks of ``--repo``, in the order they must be asked.

    The state root first, then the census level, because both are asked ahead of the
    allocation and a refusal must never leave a ``noni/`` behind in a tree this run may
    not write to. The caller hands in its printer and its three codes so this stays a
    leaf whose numbers the run's module owns.

    The state-root question is asked through :func:`_refuse_state_root`, this module's
    own seam, with this tool's printer, this tool's code, and this tool's two answers to the creator
    question (:func:`admits_creation` for a brand-new tree, :func:`admits_reopening` for a
    scaffolded one), handed over as thunks so each follows the tree as the caller left it
    rather than the ledger this run is about to allocate. The obstruction question is not
    asked here: :func:`noni._decide_flags.refuse_linked_state` asks it of the same
    ``lstat`` ahead of this, so a linked ``noni/`` keeps the sentence that names it.
    """
    refused = _refuse_state_root(
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
