"""The items group's run-side composition: hand the group the run's own mechanics.

``census_run.py`` sequences the run; this module is the one call the items group is
made through. It is split for the reason the body is split from ``census.py``: the
file that sequences every group should not also be the file that words every group's
argument list, and a group that gained its mechanics here would grow the body by a
dozen named arguments each time a rule moved to a new owner.

Nothing here reads a repository. Every mechanic is a name of the census, read at the
call so a seam a test puts on the census is the seam the group uses, and the store and
ledger listings are the run's own, handed in rather than re-taken here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from . import census_items as _items
from . import census_items_readers as _items_readers
from . import census_json as _census_json


def _census():
    """The census module, imported at the call and never at import time.

    The census re-exports the run this helper belongs to, so the modules name each
    other in a circle and a module-level ``from . import census`` would bind whichever
    half was still loading when this one ran. Imported per call, the helper always
    asks the finished module.
    """
    from . import census
    return census


def _check_items(
    items: Path, ledger: Path, order: Path, root: Path, now: datetime,
    item_stale_after: timedelta, strict: bool, findings: list[dict], probe,
    ledger_names: tuple[str, ...] | None,
) -> None:
    """The items group, run by the module beside the census.

    The row factory, the root-relative identifier, the path classifier, the two
    message bounders, the strict JSON reader and the store's own readers module are
    read off the census at the call rather than closed over at import, so the row
    shape, the machine-local-path rule and the bound on a foreign message keep their
    single owner in ``census.py`` and a seam a test puts on any of them is the one
    the moved group uses.

    ``probe`` is the run's one listing of the store (its names and its fault) and
    ``ledger_names`` is the same run's one listing of the ledger: the group reads
    both directories the census already read and never walks either for itself.
    """
    census = _census()
    _items.check_items(items, ledger, order, root, now, item_stale_after, strict,
                       findings,
                       listed=probe.names, fault=probe.fault,
                       ledger_names=ledger_names,
                       row=census._row,
                       rel_to_root=census._rel_to_root,
                       file_kind=census._file_kind,
                       read_record=_item_read_record,
                       bounded=census._bounded,
                       clipped=census._clipped,
                       load_json_strict=_census_json.load_json_strict,
                       readers=_items_readers)


def _item_read_record(path: Path) -> tuple[bytes | None, OSError | None]:
    """One file's bytes, opened the way the census opens a file it did not write.

    The census's single open-time-safe reader (``census_intent_readers.read_record``:
    ``O_NOFOLLOW``, ``O_NONBLOCK`` and an ``fstat`` on the descriptor that was
    opened), handed to the items group so it uses the same open the intent class
    uses rather than a second implementation of the same refusal. Classifying first
    and opening second leaves an interval in which a file can be swapped for a link,
    and it is the flags on the open, not the earlier ``lstat``, that close it.
    """
    from .census_intent_readers import read_record
    return read_record(path)


