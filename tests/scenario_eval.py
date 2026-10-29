"""E5 scenario eval: a deterministic end-to-end harness over the direction layer.

The builder constructs a bare origin plus two agent clones in a throwaway
directory (a tmp_path in the tests; its own temp dir when run standalone
with no argument), drives the real register.py / claim.py scripts
(fetch-rebase-push), the real order.py writer for the ordering artifact, and
commits a healthy steering decision chain. In the faulted variant it plants
five disjoint faults (census codes 30, 31, 20, 40 committed to origin, and 12
planted in the fresh clone's working tree), each in its own artifact. Every
commit runs with pinned GIT_AUTHOR_DATE / GIT_COMMITTER_DATE, so a rebuilt
scenario is identical, and the census runs against a FRESH clone of the bare
origin with a fixed --now and --stale-after.

The ordering layer is exercised through its real entry points on both sides:
the artifact is written by order.py (``add`` for each position, then one
whole-file ``confirm`` that stamps every entry with the writer's own clock),
and the census is handed ``--ordering`` / ``--issue-state`` explicitly, so the
scenario measures the ordering group against the paths it names rather than
whatever the census would have guessed.

Determinism is asserted on the normalized finding multiset — the multiset of
(check, code, severity, masked-subject) tuples from the census --json output —
because session ids carry a random 6-hex suffix per build; a session finding
is identified by its build-time-known identity (agent-a / agent-b / agent-c),
which its register file carries, never by the random id.

Deletion is confined to what this run created: the builder and the standalone
no-arg path create their own directories and remove only those; a directory
that exists and is not empty is refused (exit 2, nothing deleted, nothing
created), never cleaned. The only other removal is of the ``fresh`` clone
under the scenario base, which ``fresh_clone`` itself created on an earlier
call.

Standalone: ``python tests/scenario_eval.py`` builds the faulted variant in
its own ``tempfile.mkdtemp(prefix="noni-scenario-")`` directory, prints the
census exit code plus the normalized finding set, and removes exactly that
directory before exiting 0. ``python tests/scenario_eval.py <path>`` refuses
an explicit path that exists and is non-empty (exit 2, clear message, no
deletion); an explicit path that does not exist or is an empty directory is
used as-is and left behind for the operator.

The bodies live in the ``scenario_*`` helper modules (issue #52, the file-size
ratchet) and are re-exported here: the four modules split the work one-way
(``scenario_core`` <- ``scenario_faults`` <- ``scenario_build`` <-
``scenario_report``: each imports only from the ones to its left), and this
file is the only module of the set with a ``__main__`` guard, so
``from scenario_eval import ...`` and ``python tests/scenario_eval.py`` both
keep working on the re-exported names. The standalone entry point itself is
``main`` in ``scenario_report``, which is what the paragraph above documents. A
helper module is never named ``test_*``; this file is the one import surface
its tests use.
"""

from __future__ import annotations

import sys

from scenario_build import build_scenario, fresh_clone
from scenario_core import (
    _CENSUS,
    BASE,
    ISSUE_STATE_REL,
    NOW,
    ORDER_ISSUES,
    ORDER_PLANS,
    SESSION_ID_RE,
    STALE_AFTER,
    Scenario,
    _claim,
    _commit,
    _ensure_branch,
    _git_pinned,
    _issue_state,
    _order_healthier,
    _push,
    _record,
    _register,
    _run_order,
    _ts,
)
from scenario_faults import _plant_fault_12, _plant_faults
from scenario_report import _mask, main, normalize_findings, run_census_json

__all__ = [
    "BASE",
    "ISSUE_STATE_REL",
    "NOW",
    "ORDER_ISSUES",
    "ORDER_PLANS",
    "SESSION_ID_RE",
    "STALE_AFTER",
    "Scenario",
    "_CENSUS",
    "_claim",
    "_commit",
    "_ensure_branch",
    "_git_pinned",
    "_issue_state",
    "_mask",
    "_order_healthier",
    "_plant_fault_12",
    "_plant_faults",
    "_push",
    "_record",
    "_register",
    "_run_order",
    "_ts",
    "build_scenario",
    "fresh_clone",
    "main",
    "normalize_findings",
    "run_census_json",
]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
