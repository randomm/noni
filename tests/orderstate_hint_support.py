"""The shared pieces for the record-first refusal hint (issue #198).

Two things live here rather than in each test module, because four modules ask
for them and a copy in each would be four contracts for one wording: the fix
lines of a refusal's stderr, and the routes a launched-run parity check drives.

The product owns the wording (``noni.orderstate.RECORD_FIRST_HINT``); this
module imports it and never copies it.
"""

from __future__ import annotations

import subprocess

from _harness import ORDER, run_module, run_noni, run_wrapper
from order_fixtures import STAMP

from noni import orderstate

RECORD_FIRST = orderstate.RECORD_FIRST_HINT

# The label each writer prints its refusals under (``noni.labels`` owns the words).
ORDER_LABEL = "order.py:"
INTENT_LABEL = "intent.py:"


def fix_lines(stderr: str, label: str = ORDER_LABEL) -> list[str]:
    """Every ``<label> fix: ...`` line of a refusal, prefix stripped.

    The whole line is asserted rather than a substring of it: an ``in`` check on
    a fragment passes for a refusal that printed the sentence twice, dropped the
    rest of the hint, or printed it under the other writer's label, and none of
    those is what the hint's single owner promised.
    """
    prefix = f"{label} fix: "
    return [line[len(prefix):] for line in stderr.splitlines()
            if line.startswith(prefix)]


# One entry per route to the same command: the skill's in-place wrapper (what the
# page documents), the console module, and the package route the quickstart's
# PYTHONPATH form has. Each carries its own leading argv.
ADD_ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("wrapper", ()),
    ("noni", ("order",)),
    ("module", ("order",)),
)


def launch_add_without_decision(route: str, prefix: tuple[str, ...],
                               repo) -> subprocess.CompletedProcess[str]:
    """One route's launched ``order add 7`` with no ``--decision``."""
    argv = ["--repo", str(repo), "add", "7", "--now", STAMP]
    if route == "wrapper":
        return run_wrapper(ORDER, *argv)
    return (run_noni if route == "noni" else run_module)(*prefix, *argv)
