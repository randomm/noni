"""Builders for a planted supersede target whose bytes differ in one fragment.

The decide writer's target suite drives refusals by committing a record whose
canonical bytes carry one altered fragment: a numeric ``date``, an ``options``
list holding ``NaN``, a ``scope`` holding a document 100000 levels deep. The
swap is spelled the same way every time -- take the canonical body, replace one
exact fragment -- so it lives here, and each caller asserts its own replacement
landed rather than trusting this one to report it.

The assertion belongs to the caller on purpose: a fixture whose needle drifted
would silently commit an ordinary record, and the test would then pass by
asserting a refusal the ordinary rules produce anyway.

Pure builders over ``decide_hardening_fixtures``; no fixtures run here, so this
module is never named ``test_*``.
"""

from __future__ import annotations

from decide_hardening_fixtures import _canonical_body
from ordering_shapes import _deep

# The record depth the writer's reader refuses. A record a few levels deeper than
# any writer renders, and far below the depth at which any supported
# interpreter's decoder gives up: the window where only this product's own bound
# can answer, which is exactly the window the lens review found unguarded.
DEEP_RECORD_LEVELS = 300

# The canonical ``scope`` and the canonical option the pathological fixtures
# replace. Named here so the cases that drive them differ only in which field
# carries the value, which is the point of driving both.
SCOPE_FIELD = '"scope": "release ordering"'
OPTION_LATER = '"later"'

# The swapped-in value for a ``scope`` that holds a deep array: an array and not
# an object, because the census's field rules call a non-string ``scope`` a
# schema violation on their own. The refusal under test has to be the reader's,
# made before any field rule is reached, so the value has to be one the field
# rules would never have been asked about at all.
DEEP_ARRAY_IN_SCOPE = '"scope": [' + _deep() + "]"

# An integer literal past the interpreter's 4300-digit conversion limit, planted
# in ``scope``: legal JSON syntax, so nothing in the decoder's grammar objects and
# the fault comes out of ``int()`` instead.
DIGIT_LIMIT_SCOPE = '"scope": 1' + "0" * 100000


def _deep_value(levels: int) -> str:
    """Legal JSON text holding a value that nests ``levels`` levels deep.

    Counts depth the way the bound does - one for the returned value, one more
    for each container round it - so a caller can say 'a value of exactly this
    depth' and have the reader's bound agree with it.

    Built by repeating the container rounds, never by ``json.dumps`` over an
    assembled structure: the encoder costs a frame per level and gives out at a
    depth the decoder has not reached yet (measured on 3.11 at the default limit
    of 1000: no ``dumps`` past roughly 950, decodes still succeeding at 950). An
    encoder that recursed first would raise on the fixture instead of handing
    the caller the text to plant, which is the crash this reader exists to
    refuse. The caller asserts its own replacement landed and, where the point
    is that the *bound* answered rather than the decoder, asserts that the
    standard reader builds the text; ``_deep`` beside this is the value no
    decoder builds, owned by the ``RecursionError`` arm.
    """
    if levels < 1:
        raise ValueError(f"{levels} levels is not a nest")
    return '{"k":' * (levels - 1) + '"deep"' + "}" * (levels - 1)


def _target_body(target_id: str, old: str, new: str) -> str:
    """The canonical body of ``target_id`` with one exact fragment swapped.

    The replacement is asserted by the caller rather than here: a fixture whose
    needle drifted would silently commit an ordinary record and then assert a
    refusal that the ordinary rules would have produced anyway.
    """
    return _canonical_body(target_id).replace(old, new)
