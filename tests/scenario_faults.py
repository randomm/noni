"""The planted faults of the E5 scenario eval.

Moved out of ``scenario_eval.py`` for the file-size ratchet (issue #52).
A helper module: never named ``test_*``. It sits one layer above
``scenario_core`` (which owns the timeline, the handle and the fixture-side
git/writer helpers) and below ``scenario_build``, so the scenario layering
stays one-way: ``scenario_core`` <- ``scenario_faults`` <- ``scenario_build``
<- ``scenario_report``.

"""

from __future__ import annotations

import json
from pathlib import Path

from scenario_core import Scenario, _commit, _push, _record, _ts

# The artifact every ordering fault is committed to, spelled once for the planters.
ORDER_REL = "noni/direction/order.json"


def _plant_faults(scenario: Scenario, t_c: str) -> None:
    """The planted faults, each in its own disjoint artifact (54, 20
    committed to origin; 12 is planted in the fresh clone at test time).

    54  a committed order that still carries the removed item store's shape: the
        file states the retired schema version and its entry still carries the
        retired key, so the ordering arbiter reports the migration refusal;
    20  a separate decision chain with a dangling supersedes, disjoint from
        the healthy chain, committed to origin.

    Every commit here carries the pinned fault clock or the record's own date,
    so no commit is one a healthy build would not also have made.
    """

    # 20: a separate decision chain with a dangling supersedes, disjoint from
    # the healthy chain.
    t_d3 = _ts(0, 7)
    dangling = _record("2026-10-03-d3", t_d3, "decided",
                       "2026-10-99-nonexistent", "release ordering",
                       "Order task #3 against task #4?")
    _commit(scenario.clone_a, "noni/decisions/2026-10-03-d3.json",
            dangling, "plant: dangling supersedes chain", t_d3)
    _push(scenario.clone_a, t_d3)
    scenario.faults.append("20")

    # 54: an order left behind by the removal of the item store. The item store
    # and its ``noni.order/2`` marker were removed from the product, so a file
    # that still states them is no order any verb reads: the reader refuses it
    # and the arbiter reports it. The state only exists as a committed artifact,
    # since no writer can produce it, so it is committed by hand in the bytes the
    # removed writer wrote -- the retired marker on the document and the retired
    # key on one entry, beside the healthy entries the real writer committed.
    order = json.loads((scenario.clone_a / ORDER_REL).read_text(encoding="utf-8"))
    order["schema"] = "noni.order/2"
    order["entries"].append({"item": "held-idea",
                             "decision": "2026-10-02-d2",
                             "confirmed": _ts(0, 4)})
    _commit(scenario.clone_a, ORDER_REL,
            json.dumps(order, indent=2) + "\n",
            "plant: order still carries the removed item store", t_c)
    _push(scenario.clone_a, t_c)
    scenario.faults.append("54")


def _plant_fault_12(fresh: Path) -> None:
    """12: edit the committed decision record d1 in the fresh clone's working
    tree after cloning (never committed) — the ledger-edited finding."""
    path = fresh / "noni" / "decisions" / "2026-10-01-d1.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["date"] = _ts(0, 12)  # any committed-vs-disk byte change triggers 12
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
