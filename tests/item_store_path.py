"""Where the item store path lives in the tests: the one name the fixtures own.

Two suites of the item family build store paths with their own literal (the writer's
fixtures and the census group's launch helpers). This module is the seam that keeps the
two the same path as the product spells it: each fixture reads its constant from here,
and the parity test in ``tests/test_item_writer_id_rule.py`` compares the value to
``itemschema.ITEM_DIR`` -- so a store that moved in the product and not in the tests
fails a check rather than quietly testing a directory the product never reads.

A helper module: never named ``test_*``.
"""

from __future__ import annotations

from noni import itemschema

# The one spelling of the store directory the test fixtures use, taken from the product
# rather than typed: a fixture that hard-codes the path keeps passing when the path
# moves, and then asserts about a directory nothing reads.
STORE = itemschema.ITEM_DIR
