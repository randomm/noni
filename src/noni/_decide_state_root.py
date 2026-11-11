"""The state-root question of one ``decide`` run, and the exception that admits it.

Split from ``decide.py``, which holds the run. A ``--repo`` that is a directory but
holds no ``noni/`` is the second shape of the wrong path docs/PRODUCT.md 7 describes,
and it is the one a caller actually arrives at: a committed code repository passed
where the state clone was meant is a valid git work tree, so the work-tree probe
admits it and only the question here refuses it.

Two decisions live here and nowhere else:

* whether the run is a **creator** and so admitted -- today one answer: the tree holds
  a ``noni/``, or the caller said ``--init``, and
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
things that are ``decide``'s own -- its answer to the creator question and the one
``--init`` sentence its fix line carries -- and hands each refusal the caller's own
printer and the codes the run's module passes in rather than importing them:
:data:`noni.decide.EXIT_GIT` for a wrong path (the code docs/PRODUCT.md 7 gives this
tool) and the two codes the level check returns. :func:`refuse_run` is the one seam
the run calls: it holds both questions and their order, so a later caller cannot ask
them out of turn.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path

from . import _decide_flags, _path_kind, _writer, ledger_level


def admits_creation(root: Path, init: bool) -> bool:
    """Whether this run may treat its ``--repo`` as a state root.

    One question, answered one way: the tree holds a ``noni`` directory, or the caller
    said ``--init``. A tree that holds ``noni`` is a state root whatever that directory
    holds, which is the census's own account of a ``noni/`` it can see (``empty``,
    ``not a directory``, ``symlink``, each its own state word) and no writer here
    contradicts it. A tree that holds none is a wrong ``--repo``: a committed code
    repository passed where the state clone was meant is a valid git work tree, so the
    work-tree probe admits it and this is the only question that refuses it. ``--init``
    is the caller's word that the tree is a state root they mean to start, and the only
    thing that lets such a run through.

    One question, answered one way: the tree holds a ``noni`` directory, or the caller
    said ``--init``. A tree that holds ``noni`` is a state root whatever that directory
    holds, which is the census's own account of a ``noni/`` it can see (``empty``,
    ``not a directory``, ``symlink``, each its own state word) and no writer here
    contradicts it. A tree that holds none is a wrong ``--repo``: a committed code
    repository passed where the state clone was meant is a valid git work tree, so the
    work-tree probe admits it and this is the only question that refuses it. ``--init``
    is the caller's word that the tree is a state root they mean to start, and the only
    thing that lets such a run through.

    Two answers this one deliberately does not carry. It is not asked of the ledger leaf
    alone: a question about ``noni/decisions`` by itself would be answered yes by a
    committed code repository, which has no ledger either and no state of anyone's. And
    ``--no-commit`` no longer answers it: it used to, which let a run write a record into
    a tree holding no state of anyone's as long as it left the commit to somebody else,
    and the route that needed it is gone.

    A ``noni`` or a ledger that is a link is not admitted here either, though not by this
    predicate: ``_writer.ledger_is_first`` is :func:`noni._path_kind.has_no_noni`, whose
    ``lstat`` reports a link at ``noni`` as neither absent nor a directory, so the flag
    cannot open a tree whose state root is a link. A link deeper down, at
    ``noni/decisions``, is refused by the obstruction guard that every component of the
    guarded list is asked of ahead of this, in the sentence that names the fault.
    """
    return init or not _writer.ledger_is_first(root)


def _refuse_state_root(printer: _decide_flags.Printer, code: int,
                      repo: Path, admits: Callable[[], bool]) -> int | None:
    """The exit-3 refusal for a ``--repo`` that is no noni state root, or None.

    :param printer: ``decide``'s own failure printer, so the prefix stays ``decide.py``.
    :param code: :data:`noni.decide.EXIT_GIT`, pinned by the caller rather than imported,
        so this module stays a leaf the run's module can own the number of.

    :func:`noni._decide_flags.refuse_state_root` words the two lines and holds the
    ordering; this only binds the tool's printer, the tool's code, the tool's answer to
    the creator question, and the ``--init`` sentence this tool alone hands the shared
    renderer. The obstruction question is *not* asked here --
    :func:`noni._decide_flags.refuse_linked_state` asks it
    of the same ``lstat`` ahead of this, so a linked ``noni/`` keeps the sentence that
    names it. The readers reach
    :func:`noni._path_kind.state_root_refusal` through
    :func:`noni._path_kind.refuse_state_root` with no sentence of their own, so no
    command prints a fix line naming a flag it answers with argparse's exit 2.
    """
    return _decide_flags.refuse_state_root(
        printer, code, repo, admits, hint=_path_kind.STATE_ROOT_INIT_HINT)


def refuse_run(fail: _decide_flags.Printer, exit_git: int, exit_usage: int,
               exit_collision: int, repo: Path, init: bool) -> int | None:
    """Both questions this module asks of ``--repo``, in the order they must be asked.

    The state root first, then the census level, because both are asked ahead of the
    allocation and a refusal must never leave a ``noni/`` behind in a tree this run may
    not write to. The caller hands in its printer and its three codes so this stays a
    leaf whose numbers the run's module owns.

    The state-root question is asked through :func:`_refuse_state_root`, this module's
    own seam, with this tool's printer, this tool's code, and this tool's answer to the
    creator question (:func:`admits_creation`), handed over as a thunk so it follows the
    tree as the caller left it rather than the ledger this run is about to allocate. The
    obstruction question is not asked here: :func:`noni._decide_flags.refuse_linked_state`
    asks it of the same ``lstat`` ahead of this, so a linked ``noni/`` keeps the sentence
    that names it.
    """
    refused = _refuse_state_root(
        fail, exit_git, repo, partial(admits_creation, root=repo, init=init))
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
