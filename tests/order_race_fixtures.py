"""Fixtures shared by the two modules that cover the order writer's freshness guard.

``tests/test_order_writer_race.py`` races a rival commit against the writer;
``tests/test_order_writer_probe.py`` asks the probe what it does with each of the
answers it can get. Both assert against HEAD rather than the working copy, and both
drive the writer through ``order_fixtures._order_inprocess`` for the reason that
module gives: a patch on the probe is a patch on a module object, and the writer only
honours the copy it runs inside.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from _harness import _git_e2
from order_fixtures import (
    BASELINE_ID,
    ORDER_REL,
    RIVAL_DATE,
    SEED_STAMP,
    _committed_order,
    _entry,
    _read,
    _rival_commit,
)

REFUSAL = "the order changed since it was read; re-run"

# The other exit-4 cause the guard reports, pinned from the product's own constant by
# the tests that assert the two arms stay distinguishable.
FILE_CHANGED = "the file changed since it was read; restore it or discard the change"

# The rival's entry stamp is ``order_fixtures.RIVAL_DATE`` under this module's own
# name: one literal, one explanation (see that module), imported rather than spelled
# a second time so the two can never drift -- a rival that carried NOW's stamp would
# leave every race verb a no-change run that never reaches the guard.
RIVAL_STAMP = RIVAL_DATE


@contextlib.contextmanager
def interrupt_read(order_module, name: str, replacement):
    """Replace one of the writer's own reads for one run, then put the real one back.

    The deterministic way into the window the guard covers: the run takes its
    baseline, the fixture then changes the world (the file, or HEAD), and the run
    reaches its write phase in the state a real second writer would have left. The
    restore sits in the same context manager as the swap, so a test cannot leave the
    product's reader replaced for every later test in the module.
    """
    state = order_module.orderstate
    real = getattr(state, name)
    setattr(state, name, replacement)
    try:
        yield
    finally:
        setattr(state, name, real)


def _head(repo: Path) -> str:
    return _git_e2(repo, "rev-parse", "HEAD").stdout.strip()


def _checkout_head(repo: Path) -> None:
    """Put the working copy back to what HEAD holds, the way a sync would.

    After a refusal the remedy is a re-run, and a re-run is only honest once the
    checkout agrees with HEAD again: ``git checkout HEAD -- <path>`` is what the
    operator does between the refusal and the retry.
    """
    _git_e2(repo, "checkout", "HEAD", "--", ORDER_REL)


def _issues_in_head(repo: Path) -> list[int]:
    """The issues HEAD holds at the artifact path, read straight from git.

    The surviving order is asserted from the committed blob and not from the working
    tree, because "the first writer's entry survives" is a claim about HEAD: a run
    that wrote the file but never committed it would otherwise pass it.
    """
    committed = _committed_order(repo)
    assert committed is not None, "HEAD holds no order at all"
    return [entry["issue"] for entry in json.loads(committed)["entries"]]


def _race_entry(issue: int, decision: str = BASELINE_ID) -> dict:
    """One baseline entry for a race test, stamped at a time the race run restamps.

    Deliberately not the fixtures' default stamp: see ``order_fixtures.SEED_STAMP``.
    An entry already carrying the stamp the run is about to pass makes ``confirm`` a
    no-op that returns before the guard, and a race test of that verb would then be
    measuring the shortcut rather than the probe.
    """
    return _entry(issue, decision, SEED_STAMP)


def _rival_raced(repo: Path, *extra: tuple[int, str]) -> None:
    """Move HEAD behind the run's back, and leave the file alone.

    The deterministic half of the race: the file keeps the bytes the losing run is
    about to read (its plan, and the baseline the guard compares), while HEAD has
    moved to the rival's own committed order. One commit does both, and the
    assertions that follow capture HEAD and the file *after* it -- HEAD has
    legitimately moved by then, and what must not move again is the refused run's
    own doing. See ``order_fixtures._rival_commit`` for why a rival that also left
    its own bytes in the tree would be testing a correct run, not this one.

    ``extra`` are entries of the rival's own to add to the order it commits, given
    as ``(issue, decision)``. They matter for more than realism: a rival that
    committed a mere restamp of the same entries would leave HEAD holding bytes a
    later ``confirm --now`` reproduces exactly, and that run takes the no-change
    shortcut and exits 0 having written nothing -- so the verb under test would
    never reach the guard at all. A rival with work of its own keeps every verb a
    real write.
    """
    _rival_commit(repo, _read(repo)["entries"]
                  + [_entry(issue, decision, RIVAL_STAMP) for issue, decision in extra])
