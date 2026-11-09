"""The duplicate half of the promote order read, at the module boundary.

:func:`noni.item_reads_order.rewrite_citation` answers three things: "some entry cites it,
rewrite this one", "nothing cites it", and "the rewrite would name one issue twice".
The third is the rewrite's own hazard, so it may only be answered when the first is
true; these cases call the function directly to pin that the answers stay three and
distinct.
"""

from __future__ import annotations

import pytest

from noni import item_reads_order as item_reads

FRESH = "2026-10-26T00:00:00Z"
ITEM = "idea-0001"


def _citing(issue=None):
    entry = {"item": ITEM, "decision": "2026-10-01-baseline", "confirmed": FRESH}
    if issue is not None:
        entry = {"issue": issue, "decision": "2026-10-01-baseline",
                 "confirmed": FRESH}
    return entry


def test_an_order_that_lists_the_issue_and_cites_nothing_owes_no_rewrite():
    """No citation, no rewrite, no duplicate -- whatever the order already lists."""
    assert item_reads.rewrite_citation([_citing(7)], ITEM, 7) is None


def test_an_order_that_cites_nothing_at_all_owes_no_rewrite():
    assert item_reads.rewrite_citation([_citing(9)], ITEM, 7) is None


def test_a_citing_order_whose_issue_is_already_listed_is_a_duplicate():
    entries = [_citing(), _citing(7)]
    with pytest.raises(item_reads.DuplicateIssue) as clash:
        item_reads.rewrite_citation(entries, ITEM, 7)
    assert clash.value.issue == 7
    assert "already in the order" in str(clash.value)
    assert entries[0]["item"] == ITEM, "the refusal read the caller's list"


def test_a_citing_order_that_lists_no_other_copy_of_the_issue_is_rewritten():
    entries = [_citing(), _citing(9)]
    rewritten = item_reads.rewrite_citation(entries, ITEM, 7)
    assert rewritten is not None
    assert rewritten[0] == {"decision": "2026-10-01-baseline", "confirmed": FRESH,
                            "issue": 7}
    assert rewritten[1] == _citing(9)


def test_the_entry_that_cites_the_item_may_already_name_the_issue_it_became():
    """One entry, one issue: the entry it cites is the entry that holds it.

    Not a duplicate -- the rewrite changes nothing about the issue and only drops the
    ``item`` key, which is the ordinary end of a promote whose entry was already keyed
    on its issue.
    """
    entry = {"item": ITEM, "issue": 7, "decision": "2026-10-01-baseline",
             "confirmed": FRESH}
    rewritten = item_reads.rewrite_citation([entry], ITEM, 7)
    assert rewritten is not None
    assert rewritten[0]["issue"] == 7
    assert "item" not in rewritten[0]
