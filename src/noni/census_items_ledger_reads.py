"""The ledger records the items group's citation classes may read from a shared map.

``census_run.py`` sequences the run and owns no copy of the ledger's documents; this module
owns the one step that hands the items group what the ledger group has already parsed. It
is a separate file for the reason the run is separate from ``census.py``: the sharing is a
rule about two groups reading one directory, not a step of the sequence, and a reader of
the run should not have to hold it to follow the run.

The rule is stated once here and nowhere else: the citation classes ask two words
(``status`` and ``supersedes``) out of records the ledger group's own validation pass has
already opened and parsed, so the run hands the parsed records down instead of letting each
citing item re-read and re-parse the ledger for itself.
"""

from __future__ import annotations

from pathlib import Path


def shared_map(ledger: Path, ledger_probe) -> dict:
    """The ledger's records as the citation classes read them: parsed once, by the group
    that already parsed them.

    ``check_ledger_records`` is the census's one pass that opens every record and hands
    back each document it validated, and the items group's citation classes ask two words
    out of those same documents. Before the map was threaded through, each item citing a
    record re-read and re-parsed the ledger for itself: quadratic in the store and the
    ledger, for an answer the first pass had already produced. Handing the parsed records
    down is the sharing, and it is honest about its one condition -- the ledger group must
    have run this pass, so the map is taken when its probe read the directory and left
    empty when it did not, in which case the citation classes take their own reads.

    The two inert callbacks are what the pass needs to report rows with. This call wants
    no rows -- the ledger group adds its own later in the run, from its own call and its
    own row factory, and a row added here would be the same finding twice -- so the
    factory returns nothing and the classifier says every file is what it is.
    """
    if ledger_probe.state != "ok" or ledger_probe.names is None:
        # The group reads no records at all in any other state (see the pass's own
        # docstring), so there is nothing to share and the classes must be free to
        # answer for themselves. A filtered run that never entered the ledger group
        # reaches the same arm through the state it left behind, which is why the map
        # is taken as it is and never forced.
        return {}
    from . import census_ledger_checks as _ledger_checks
    from .census import _file_kind

    valid, _unparseable = _ledger_checks.check_ledger_records(
        ledger, Path("/"), [], ledger_probe,
        row=lambda *a, **k: {},
        file_kind=_file_kind,
        rel_to_root=lambda path, _root: str(path),
        ledger_name=lambda name: name)
    return {body["id"]: {"status": body.get("status"),
                        "supersedes": body.get("supersedes"),
                        "read": True}
            for _name, _path, body in valid}
