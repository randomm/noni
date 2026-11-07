"""The path gates a census run consults before it owes a group a read.

``census_run.py`` sequences the run; this module owns the two rules that decide whether
the intent file and the item store are owed their read at all, given the flags the run
was started with. They are split from the body for the reason the body is split from
``census.py``: a file that both sequences the run and words every gate of every group
is larger than one responsibility is worth, and each gate here is a rule about a path,
not a step of the sequence.

Both gates ask the census's own classifier, by a call rather than a binding made at
import, so the seam a test puts on ``census._file_kind`` is the one the gate uses: a
run's gate and a run's rows then answer for one path from one seam. And both answer
"worth a read" rather than "there is something to report", which is why neither may
use ``Path.exists`` -- it follows links, so it reads the symlink whose cannot-tell row
the gate exists to keep as absent, and it propagates the ``OSError`` of a parent it
cannot traverse, which would end a filtered run with a traceback on exactly the input
the class reports as ``cannot-tell``.
"""

from __future__ import annotations

from pathlib import Path


def _census():
    """The census module, imported at the call and never at import time.

    The census re-exports the run of which this gate is a helper, so the three
    modules name each other in a circle and a module-level ``from . import census``
    would bind whichever half was still loading when this one ran. Imported per call,
    the gate always asks the finished module, and a seam a test puts on
    ``census._file_kind`` is the classifier the gate uses.
    """
    from . import census
    return census


def _intent_present(intent: Path) -> bool:
    """Whether a read of ``intent`` is owed, for the group's filter gate.

    Classified through the census's own classifier, the one the class itself uses,
    so the gate and the rows can never disagree about what stands at the path. A
    bare ``Path.exists`` would be both wrong and unsafe here: it follows links, so
    it answers False for the symlink whose cannot-tell row the gate exists to keep
    (dangling, or a chain that loops), and it propagates the ``OSError`` of a
    parent it cannot read -- which would end a filtered run with a traceback on
    exactly the input the class reports as ``cannot-tell``. "Anything the run could
    not classify is worth a read" is the honest rule, and the class owns every
    verdict that read produces, the fault's included.

    The classifier is asked by a call rather than bound at import so the seam a
    test puts on ``census._file_kind`` is the one the gate uses: this run's gate
    and this run's rows then answer for the path from one seam.
    """
    kind, _ = _census()._file_kind(intent)
    return kind != "absent"


def _items_present(items: Path, given: bool) -> bool:
    """Whether the store's one readdir is owed, for the group's filter gate.

    Two answers, and the second is the whole of the ``--items`` ruling: a store the
    caller named with ``--items`` is owed a read whatever stands at it, because a
    path the caller pointed the census at and this run cannot read is a finding
    (``item-unlistable``), while a default path that is simply absent is the state of
    a project that has never filed an idea and is not a finding at all. So the flag
    decides, and an absent default answers False without a classification -- no row
    can come from it either way, and a filtered run of a project with no store pays
    nothing for the read it can be shown to need.

    A ``--items`` path that is a symlink or a plain file is also owed the read: the
    probe classifies it and the group words the row, so the gate asks nothing of its
    own about the shape and never reaches a verdict the group has not stated.
    """
    if given:
        return True
    return _census()._file_kind(items, kind="dir")[0] != "absent"


