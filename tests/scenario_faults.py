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

from scenario_core import (NOW, Scenario, _commit, _item_body, _push, _record,
                           _run_item, _ts)


def _plant_faults(scenario: Scenario, t_c: str) -> None:
    """The planted faults, each in its own disjoint artifact (52, 53, 20
    committed to origin; 12 is planted in the fresh clone at test time).

    52  a separate item file that is not the noni.item/1 shape, committed to
        origin (the item census reads it as a store of one);
    53  the order and the store disagree: an ordered item the store has dropped;
    20  a separate decision chain with a dangling supersedes, disjoint from
        the healthy chain, committed to origin.

    Every commit here carries the pinned fault clock or the record's own date,
    so no commit is one a healthy build would not also have made.
    """

    # 52: a store file that is not the item shape (here: an id that is not its
    # own file name, one of the schema's two id rules).
    _commit(scenario.clone_a, "noni/items/malformed-idea.json",
            _item_body("another-name"), "plant: malformed item", t_c)
    _push(scenario.clone_a, t_c)
    scenario.faults.append("52")

    # 20: a separate decision chain with a dangling supersedes, disjoint from
    # the healthy chain. It comes first because 53 cites one of its records.
    t_d3 = _ts(0, 7)
    dangling = _record("2026-10-03-d3", t_d3, "decided",
                       "2026-10-99-nonexistent", "release ordering",
                       "Order task #3 against task #4?")
    _commit(scenario.clone_a, "noni/decisions/2026-10-03-d3.json",
            dangling, "plant: dangling supersedes chain", t_d3)
    _push(scenario.clone_a, t_d3)
    scenario.faults.append("20")

    # 53: an item the order still cites after the store dropped it. The drop is
    # a real ``item.py drop`` (a drop needs a decision the ledger holds, and d3
    # is that record, which 20 already commits). The order half is a hand-
    # committed byte change to the artifact rather than an ``order.py add --item``
    # run: the writer refuses to place an idea the store has already dropped, so
    # the ordered-but-dropped state only exists as a disagreement between two
    # committed artifacts. The entry is a one-line append to the writer-committed
    # file, in the writer's own shape (a ``noni.order/2`` entry citing the item id,
    # as ``order.py add --item`` writes it). Its ``confirmed`` rides on the
    # scenario clock at --now rather than the fault clock, which is the date the
    # writer would have stamped on a placement made when the census is run: at the
    # fault clock the same entry also reads ``ordering-stale``, a second row this
    # build never planted.
    _run_item(scenario.clone_a, "add", "held-idea", "--title", "Held idea")
    order_rel = "noni/direction/order.json"
    order = json.loads((scenario.clone_a / order_rel).read_text(encoding="utf-8"))
    order["schema"] = "noni.order/2"
    order["entries"].append({"item": "held-idea",
                             "decision": "2026-10-02-d2",
                             "confirmed": NOW})
    _commit(scenario.clone_a, order_rel,
            json.dumps(order, indent=2) + "\n",
            "plant: order still cites the dropped item", t_c)
    _run_item(scenario.clone_a, "drop", "held-idea", "--decision",
              "2026-10-03-d3", "--why", "planted: dropped while ordered")
    _push(scenario.clone_a, t_c)
    scenario.faults.append("53")


def _plant_fault_12(fresh: Path) -> None:
    """12: edit the committed decision record d1 in the fresh clone's working
    tree after cloning (never committed) — the ledger-edited finding."""
    path = fresh / "noni" / "decisions" / "2026-10-01-d1.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["date"] = _ts(0, 12)  # any committed-vs-disk byte change triggers 12
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
