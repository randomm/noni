"""Building the E5 scenario: the healthy baseline and its fresh clone.

Moved out of ``scenario_eval.py`` for the file-size ratchet (issue #52).
A helper module: never named ``test_*``. It sits in the middle of the one-way
scenario layering (``scenario_core`` <- ``scenario_faults`` <- this file <-
``scenario_report``): the healthy baseline is built here, and the planters it
deleges to for the faulted variant are imported inside the function rather
than at module level, so no module of the set imports back up the stack.

"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from scenario_core import (
    FAULT_CLOCK,
    Scenario,
    _commit,
    _ensure_branch,
    _item_healthier,
    _order_healthier,
    _push,
    _record,
    _ts,
)


def build_scenario(base: Path, faulted: bool = False) -> Scenario:
    """Build the healthy baseline (and, with ``faulted``, its planted faults too)
    under base, returning the scenario handle.

    ``faulted`` is a keyword the callers pass, so it stays in the signature;
    the planters themselves live in ``scenario_faults`` and stay imported inside
    this function, never at module level, which is what keeps the scenario
    layering one-way (``scenario_core`` <- ``scenario_faults`` <- this file <-
    ``scenario_report``).

    The planter import is the first statement of the body, before any tree is
    built, so a broken ``scenario_faults`` fails here rather than after the
    origin and clones exist.

    base must not exist, or must exist as an empty directory: the builder
    never deletes anything. It creates only its own entries (``origin.git``,
    ``clone-a``, ``clone-b``) directly under base — a path outside the
    given base is never touched. Callers that need a rebuild at a
    pre-existing, non-empty base must clean it up themselves, and only if
    they know the contents are their own.

    Healthy baseline: a bare origin plus two clones; clone-a seeds the shared
    starting point and both clones push through the fetch-rebase-push loop; a
    healthy steering decision chain (d1 superseded by d2) sets the ordering
    between the two issues; the ordering artifact itself is
    written by the real order.py writer and stamped healthy by one confirm run;
    the item store is written by the real item.py writer; every commit uses a
    pinned recent date.
    """
    from _harness import _git_ok

    # Function-local on purpose: a module-level scenario_faults import here is
    # what would close the cycle with scenario_report's import of this file.
    from scenario_faults import _plant_faults

    if base.exists():
        if not base.is_dir():
            raise RuntimeError(f"refusing to build at {base}: path exists and is not a directory")
        if any(base.iterdir()):
            raise RuntimeError(
                f"refusing to build at {base}: directory is not empty; "
                "it must not exist or be an empty directory"
            )
    else:
        base.mkdir(parents=True, exist_ok=True)

    origin = base / "origin.git"
    clone_a = base / "clone-a"
    clone_b = base / "clone-b"

    # Build the bare origin.
    origin.mkdir(parents=True, exist_ok=True)
    _git_ok(origin, "init", "-q", "--bare")

    # Build clone_a from scratch.
    clone_a.mkdir(parents=True, exist_ok=True)
    _git_ok(clone_a, "init", "-q", "-b", "main")
    (clone_a / "README.md").write_text("test repo\n")
    _git_ok(clone_a, "add", "README.md")
    _git_ok(clone_a, "commit", "-q", "-m", "initial commit")
    _git_ok(clone_a, "remote", "add", "origin", str(origin))
    _git_ok(clone_a, "push", "-q", "-u", "origin", "main")

    # Build clone_b as a clone of origin, on main by name: the suite's
    # sandboxed HOME carries no init.defaultbranch, so a plain clone would
    # check out git's own default (master) and register.py's own commit would
    # land there, leaving nothing on main to push.
    clone_b.mkdir(parents=True, exist_ok=True)
    _git_ok(base, "clone", "-q", "-b", "main", str(origin), str(clone_b))
    _ensure_branch(clone_b, "main")

    t_task = _ts(0)
    t_d1 = _ts(0, 6)
    t_d2 = _ts(0, 8)
    t_c = FAULT_CLOCK

    # Baseline commit on origin (pinned date): the shared starting point.
    _commit(clone_a, "tasks/1.md", "# task 1\n", "task: #1", t_task)
    _push(clone_a, t_task)

    # clone-b does the work the sessions layer used to occupy: it commits its
    # own file and pushes through the same fetch-rebase-push loop, so the
    # two-clone topology still exercises concurrent writers on one origin and
    # both commits land linearly.
    _commit(clone_b, "tasks/2.md", "# task 2\n", "task: #2", _ts(0, 1))
    _push(clone_b, _ts(0, 1))

    # Healthy steering decision chain: d1 superseded by d2; d2 sets the
    # ordering (task #1 before task #2).
    _commit(clone_a, "noni/decisions/2026-10-01-d1.json",
            _record("2026-10-01-d1", t_d1, "superseded", None,
                    "release ordering", "Order task #1 against task #2?"),
            "decision d1", t_d1)
    _push(clone_a, t_d1)
    _commit(clone_a, "noni/decisions/2026-10-02-d2.json",
            _record("2026-10-02-d2", t_d2, "decided", "2026-10-01-d1",
                    "release ordering", "Confirm task #1 before task #2?"),
            "decision d2", t_d2)
    _push(clone_a, t_d2)

    # The ordering artifact, written by the real writer and stamped healthy by
    # one confirm run, then the issue-state map the census is handed, then the
    # item store, written by its own real writer.
    _order_healthier(clone_a)
    _item_healthier(clone_a)
    scenario = Scenario(base=base, origin=origin, clone_a=clone_a, clone_b=clone_b)

    if faulted:
        _plant_faults(scenario, t_c)
    return scenario


def fresh_clone(scenario: Scenario, name: str = "fresh") -> Path:
    """A fresh clone of the scenario's bare origin (local directory clone).

    The destination must sit directly under the scenario base and must be
    the builder's own ``fresh`` clone for anything to be removed: a
    pre-existing, non-empty, foreign destination is refused, never deleted.
    """
    dest = scenario.base / name
    if dest.exists():
        if name != "fresh" or not dest.is_dir():
            raise RuntimeError(f"refusing to remove {dest}: not this run's own clone directory")
        shutil.rmtree(dest)
    subprocess.run(["git", "clone", "-q", "--branch", "main", str(scenario.origin), str(dest)],
                   check=True, capture_output=True, timeout=60)
    return dest
