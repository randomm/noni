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

The wording, the ordering and the declined-``lstat`` rule all belong to
:mod:`noni._path_kind` and :mod:`noni._decide_flags`; this module only decides the
one thing that is ``decide``'s own, and pins the exit code to
:data:`noni.decide.EXIT_GIT` -- the code docs/PRODUCT.md 7 gives this tool for a
wrong path.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from . import _decide_flags, _writer


def admits_creation(root: Path, no_commit: bool) -> bool:
    """Whether this run brings ``noni/`` into being, and so holds the creator exception.

    Two answers and no more, and the tree is asked first because it is the stricter of
    the two: :func:`noni._writer.ledger_is_first` admits a run only where ``--repo``
    holds no ``noni/`` at all, which is the one tree whose record this run can genuinely
    be the first of. A ``--no-commit`` run then adds its own case -- it commits nothing
    until its caller commits it, which is how the shim route and the session writers
    mint a record (docs/QUICKSTART.md) -- and a run into a tree that already has a
    ``noni/`` is a state root by the census's own account and reaches its normal reads.

    Asked of the tree and never of the ledger leaf: the directory the writer is about to
    create is the thing under test, and a question about ``noni/decisions`` alone would
    be answered yes by a committed code repository, which has no ledger either and no
    state of anyone's.
    """
    return _writer.ledger_is_first(root) or no_commit


def refuse_state_root(fail, exit_git: int, repo: Path, no_commit: bool) -> int | None:
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
        fail, exit_git, repo, partial(admits_creation, repo, no_commit))
