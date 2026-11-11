"""The state-root question of one ``decide`` run, and the ``--init`` flag that admits it.

Split from ``decide.py``, which holds the run. A ``--repo`` that is a directory but
holds no ``noni/`` is the second shape of the wrong path docs/PRODUCT.md 7 describes,
and it is the one a caller actually arrives at: a committed code repository passed
where the state clone was meant is a valid git work tree, so the work-tree probe
admits it and only the question here refuses it.

Two decisions live here and nowhere else:

* whether the run may bring ``noni/`` into being -- only when the caller declares
  the tree new with ``--init`` -- and
* where in the run that question is asked -- which is not free. The writer's own
  :func:`noni._writer.allocate_ledger` runs ``mkdir(parents=True)``, so a question
  about ``noni/`` deferred past the allocation finds the directory this very run
  made and calls it a state root. The question is therefore handed to
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
things that are ``decide``'s own, and pins each exit code from the caller rather
than importing it -- :data:`noni.decide.EXIT_GIT` for a wrong path (the code
docs/PRODUCT.md 7 gives this tool) and the two codes the level check returns.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from . import _decide_flags, ledger_level

# ``decide`` is the writer a wrong ``--repo`` reaches first, so its hint names the one
# flag that turns the refusal into a first run. The headline stays the shared one.
STATE_ROOT_INIT_HINT = (
    "if this is a new state root, run again with --init; if you meant an existing "
    "state clone, pass that clone as --repo")


def admits_creation(init: bool) -> bool:
    """Whether the caller declared this tree new with ``--init``.

    One admission and no more: a ``--repo`` that holds no ``noni/`` is a wrong tree by
    default, and only ``--init`` says the caller means to bring ``noni/`` into being.
    The flag creates nothing of its own -- the writer's normal allocation and commit
    still do that -- it only admits the run past the state-root refusal, with or
    without ``--no-commit``.
    """
    return init


def refuse_state_root(fail, exit_git: int, repo: Path, init: bool) -> int | None:
    """The exit-3 refusal for a ``--repo`` that is no noni state root, or None.

    :param fail: ``decide``'s own failure printer, so the prefix stays ``decide.py``.
    :param exit_git: :data:`noni.decide.EXIT_GIT`, pinned by the caller rather than
        imported, so this module stays a leaf the run's module can own the number of.
    :param init: the caller's ``--init`` flag, the only admission for a no-``noni``
        tree.

    :func:`noni._decide_flags.refuse_state_root` words the two lines and holds the
    ordering; this only binds the tool's printer, the tool's code, and the tool's
    answer to the creator question. The obstruction question is *not* asked here --
    :func:`noni._decide_flags.refuse_linked_state` asks it of the same ``lstat`` ahead
    of this, so a linked ``noni/`` keeps the sentence that names it.
    """
    return _decide_flags.refuse_state_root(
        fail, exit_git, repo, partial(admits_creation, init),
        hint=STATE_ROOT_INIT_HINT)


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
