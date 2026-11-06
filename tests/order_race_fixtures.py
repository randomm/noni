"""Fixtures shared by the two modules that cover the order writer's freshness guard.

``tests/test_order_writer_race.py`` races a rival commit against the writer;
``tests/test_order_writer_probe.py`` asks the probe what it does with each of the
answers it can get. Both assert against HEAD rather than the working copy, and both
drive the writer through ``order_fixtures._order_inprocess`` for the reason that
module gives: a patch on the probe is a patch on a module object, and the writer only
honours the copy it runs inside.
"""

import json

from _harness import _git_e2
from order_fixtures import (
    BASELINE_ID,
    ORDER_REL,
    SEED_STAMP,
    _committed_order,
    _entry,
    _read,
    _rival_commit,
)

REFUSAL = "the order changed since it was read; re-run"

# The stamp the rival's own entries carry, distinct from the fixtures' pinned NOW:
# a run that plans against a rival's entries has to hold a real write, or it takes
# the writer's no-change shortcut and the guard is never reached (see
# ``order_fixtures._rival_commit``).
RIVAL_STAMP = "2026-11-02T09:00:00Z"


def _head(repo):
    return _git_e2(repo, "rev-parse", "HEAD").stdout.strip()


def _checkout_head(repo):
    """Put the working copy back to what HEAD holds, the way a sync would.

    After a refusal the remedy is a re-run, and a re-run is only honest once the
    checkout agrees with HEAD again: ``git checkout HEAD -- <path>`` is what the
    operator does between the refusal and the retry.
    """
    _git_e2(repo, "checkout", "HEAD", "--", ORDER_REL)


def _issues_in_head(repo):
    """The issues HEAD holds at the artifact path, read straight from git.

    The surviving order is asserted from the committed blob and not from the working
    tree, because "the first writer's entry survives" is a claim about HEAD: a run
    that wrote the file but never committed it would otherwise pass it.
    """
    committed = _committed_order(repo)
    assert committed is not None, "HEAD holds no order at all"
    return [entry["issue"] for entry in json.loads(committed)["entries"]]


def _race_entry(issue, decision=BASELINE_ID):
    """One baseline entry for a race test, stamped at a time the race run restamps.

    Deliberately not the fixtures' default stamp: see ``order_fixtures.SEED_STAMP``.
    An entry already carrying the stamp the run is about to pass makes ``confirm`` a
    no-op that returns before the guard, and a race test of that verb would then be
    measuring the shortcut rather than the probe.
    """
    return _entry(issue, decision, SEED_STAMP)


def _rival_raced(repo, *extra):
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
