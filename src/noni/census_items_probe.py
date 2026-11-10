"""The item store's one readdir, as the census's own seam.

The six item classes live in ``census_items.py`` beside the census and their reads in
``census_items_readers.py``; this module owns only the store's listing, re-exported as
a name of the census so the group's tests patch a name of the module they already
import and the run reaches one definition of the readdir.

Nothing here decides anything about a repository: the probe classifies and collects
names, and every verdict a read produces belongs to the group.
"""

from __future__ import annotations

from pathlib import Path

from . import census_items_readers as _items_probe

# Re-exported as the one object, not a copy, for the same reason as ``LedgerProbe``:
# a caller (and the census's own tests) still names the type
# through the module it already imports.
ItemsProbe = _items_probe.ItemsProbe


def _items_listing(items: Path) -> ItemsProbe:
    """The store's one listing, taken by the census exactly once per run.

    The ``_ledger_probe`` twin: the body is the sibling's,
    this is the seam the census's tests patch and the one place the body asks for the
    store. An explicit ``Path.iterdir`` and never ``Path.glob``, because a store the
    run could not list must not answer as the empty store of a project that filed no
    idea (see ``census_items_readers.items_listing``).
    """
    return _items_probe.items_listing(items)
