"""The names and bounds the items group's two halves share.

Split out of ``census_items.py`` for the size limit, and placed below both of them
rather than inside either: the group's classes are declared in ``census_items.py`` and
its citations are checked in ``census_items_citations.py``, and the second cannot
import the first (the first imports the second). These are the six strings and three
numbers both need, and they are data, so the module holding them imports nothing but
the schema and breaks nothing.

The rule the constants exist to keep: one spelling per class id, per status word and
per artifact path, shared by every module of the group. A name typed twice in two
files is how a class comes to report a code its table does not carry.
"""

from __future__ import annotations

from . import itemschema

# The six ids, spelled once each so the group's set, every row's class and the tests'
# expected ids all read one declaration. ``census_report.CHECKS`` carries the codes and
# severities beside them.
ITEM_MALFORMED = "item-malformed"
ITEM_REFERENCE_UNRESOLVED = "item-reference-unresolved"
ITEM_PROMOTED_WITHOUT_ISSUE = "item-promoted-without-issue"
ITEM_DROPPED_IN_ORDER = "item-dropped-in-order"
ITEM_STALE = "item-stale"
ITEM_UNLISTABLE = "item-unlistable"

ITEM_CHECKS = frozenset({ITEM_MALFORMED, ITEM_REFERENCE_UNRESOLVED,
                         ITEM_PROMOTED_WITHOUT_ISSUE, ITEM_DROPPED_IN_ORDER,
                         ITEM_STALE, ITEM_UNLISTABLE})

# The subject of a row that is about the store rather than one item in it, the way
# hygiene's ``hygiene scan`` and ordering's ``issue-state`` are machine-readable
# discriminators: a consumer branches on ``subject``, not on message prose.
STORE_SUBJECT = "noni/items"

# The three status words, read from the schema rather than restated: a status the
# writer can produce and this group did not name would be reported as nothing.
STATUS_CANDIDATE = itemschema.STATUS_CANDIDATE
STATUS_PROMOTED = itemschema.STATUS_PROMOTED
STATUS_DROPPED = itemschema.STATUS_DROPPED

# The record states that answer "does this decision still stand". A record whose
# status is anything else decides nothing, so a citation to it is answered like a
# citation to no file at all -- the same rule the order group and the writer apply.
RECORD_STATUSES = ("decided", "open", "superseded")
STATUS_SUPERSEDED = "superseded"

# How far the successor search will walk a supersede chain before it stops and names
# no heir. A chain this long is not a chain; the census is read-only and must not spin
# on a hand-made ledger, and the loop itself is ``ledger-chain``'s finding, not this
# group's.
_CHAIN_STEPS = 32

# The ledger path, spelled from the module that owns it so a row names the artifact by
# the same string its own group names it by.
LEDGER_REL = "noni/decisions"
