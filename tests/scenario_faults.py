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

from scenario_core import Scenario, _claim, _commit, _push, _record, _register, _ts


def _plant_faults(scenario: Scenario, t_c: str) -> None:
    """The planted faults, each in its own disjoint artifact (30, 31, 20, 40
    committed to origin; 12 is planted in the fresh clone at test time).

    30  session B additionally claims task #1 via the real claim.py --push —
        both claims on #1 sit in origin's linear history;
    31  a separate session file with a claim row but no identity field,
        committed to origin;
    20  a separate decision chain with a dangling supersedes, disjoint from
        the healthy chain, committed to origin;
    40  a third session (identity "agent-c", no claims) whose last commit is
        older than --stale-after relative to --now: register.py commits the file
        itself, and the commit that leaves this session stale is this fixture's
        own commit with the date pinned, which leaves no commit a healthy build
        would not have.
    """

    # 30: the double claim on #1 (real claim.py --push, fetch-rebase-push).
    _claim(scenario.clone_b, scenario.sid_b, "#1")
    scenario.faults.append("30")

    # 31: a separate session file with a claim row but no identity field.
    orphan_body = (
        "- host/worktree: orphan (plant-31)\n"
        f"- started: {t_c}\n"
        "- status: active\n"
        "- claims:\n"
        "  - claim: #7\n"
    )
    _commit(scenario.clone_a, "noni/sessions/2026-10-01-cccccc.md",
            orphan_body, "plant: claim without identity", t_c)
    _push(scenario.clone_a, t_c)
    scenario.faults.append("31")

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

    # 40: a third session (identity "agent-c", no claims) whose only commit
    # is pinned older than --stale-after relative to --now.
    #
    # clone_a is already marked as agent-a's working copy, and that session is
    # still active, so a plain register there would be a reuse of agent-a's
    # session rather than an allocation for agent-c — which is the writer being
    # honest about one working copy having one live session. This row wants a
    # second session file in the same tree, so the fixture asks for the file
    # without a commit and makes the (re-dated) commit itself below.
    scenario.sid_c = _register(scenario.clone_a, "agent-c", "clone-a", no_commit=True)
    session_rel = f"noni/sessions/{scenario.sid_c}.md"
    # The stale clock IS the fault this row plants, and only the commit that
    # touched this file can carry it: --strict fails the census on an active
    # session whose last commit is older than --stale-after, so the file is
    # committed once, here, with the date pinned -- one commit, no content
    # change after it, and no second commit a healthy build would not have.
    _commit(scenario.clone_a, session_rel,
            (scenario.clone_a / session_rel).read_text(encoding="utf-8"),
            f"register: {scenario.sid_c}", t_c)
    _push(scenario.clone_a, t_c)
    scenario.faults.append("40")


def _plant_fault_12(fresh: Path) -> None:
    """12: edit the committed decision record d1 in the fresh clone's working
    tree after cloning (never committed) — the ledger-edited finding."""
    path = fresh / "noni" / "decisions" / "2026-10-01-d1.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["date"] = _ts(0, 12)  # any committed-vs-disk byte change triggers 12
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
