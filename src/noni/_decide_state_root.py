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
level check returns.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from . import _decide_flags, _writer, ledger_level


def admits_creation(root: Path, init: bool) -> bool:
    """Whether this run is allowed to bring ``noni/`` into being.

    One answer and no more: :data:`noni._writer.ledger_is_first` admits a run only where
    ``--repo`` holds no ``noni/`` at all, which is the one tree whose record this run can
    genuinely be the first of, and the caller has to have said so with ``--init``.
    Without the flag a recordless tree is a wrong ``--repo``: a committed code repository
    passed where the state clone was meant is a valid git work tree, so the work-tree
    probe admits it and this is the only question that refuses it.

    ``--no-commit`` no longer answers here. It used to, which let a run write a record
    into a tree holding no state of anyone's as long as it left the commit to somebody
    else; the route that needed it (minting a record without a commit of its own) is
    gone, and the flag still commits nothing on a tree that holds ``noni/``.

    Asked of the tree and never of the ledger leaf: the directory the writer is about to
    create is the thing under test, and a question about ``noni/decisions`` alone would
    be answered yes by a committed code repository, which has no ledger either and no
    state of anyone's.
    """
    return init and _writer.ledger_is_first(root)


def refuse_state_root(fail, exit_git: int, repo: Path, init: bool) -> int | None:
    """The exit-3 refusal for a ``--repo`` that is no noni state root, or None.

    :param fail: ``decide``'s own failure printer, so the prefix stays ``decide.py``.
    :param exit_git: :data:`noni.decide.EXIT_GIT`, pinned by the caller rather than
        imported, so this module stays a leaf the run's module can own the number of.

    :func:`noni._decide_flags.refuse_state_root` words the two lines and holds the
    ordering; this only binds the tool's printer, the tool's code, and the tool's
    answer to the creator question. The obstruction question is *not* asked here --
    :func:`noni._decide_flags.refuse_linked_state` asks it of the same ``lstat`` ahead
    of this, so a linked ``noni/`` keeps the sentence that names it.
    """
    return _decide_flags.refuse_state_root(
        fail, exit_git, repo, partial(admits_creation, repo, init))


def refuse_run(fail, exit_git: int, exit_usage: int, exit_collision: int,
               repo: Path, init: bool) -> int | None:
    """Both questions this module asks of ``--repo``, in the order they must be asked.

    The state root first, then the census level, because both are asked ahead of the
    allocation and a refusal must never leave a ``noni/`` behind in a tree this run may
    not write to. The caller hands in its printer and its three codes so this stays a
    leaf whose numbers the run's module owns.
    """
    refused = refuse_state_root(fail, exit_git, repo, init)
    if refused is not None:
        return refused
    return refuse_schema_level_skew(fail, exit_usage, exit_collision, repo)


def refuse_schema_level_skew(fail, exit_usage: int, exit_collision: int,
                             repo: Path) -> int | None:
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
