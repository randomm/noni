"""The closed record key set, and the two programs that must declare it alike.

The regression these fixtures pin: ``census.sh``'s closed set was a key COUNT, not
a set test. It accepted a junk key beside a real optional field (nine keys: the
eight required plus ``source``, and one name nobody declared for free), and it
accepted 10-, 11- and 12-key records carrying any names at all. ``origin/main``
answered exit 10 on every one of those shapes, and ``census.py`` -- which tested
membership rather than counting -- refused them throughout. So the symptom was a
record the writer committed and one of its two arbiters then reported at exit 10
while the other called it clean.

Two assertions, one per direction of the same contract:

- every golden fixture (one per key count, each carrying junk keys) earns exit 10
  from BOTH entry points, so tightening one program alone cannot pass; and
- the jq program's own key literal equals ``REQUIRED_LEDGER_FIELDS`` plus
  ``OPTIONAL_LEDGER_FIELDS``, parsed out of the program's text rather than retyped
  here -- a copy in the test would drift along with a drift it should catch.

The name rules and the marker rules, asserted through all three entry points, are
in ``tests/test_ledger_name_and_marker_rules.py``. The shared launchers are in
``tests/ledger_schema_fixtures.py``.
"""

from __future__ import annotations

import json
import re

from _harness import REPO
from ledger_schema_fixtures import (
    EXPECTED_KEYS,
    FIXTURES,
    JUNK_FIXTURES,
    SCHEMA_JQ,
    _assert_both_clean,
    _assert_both_refuse,
    _fixture,
)

# --- the closed set ----------------------------------------------------------

def test_each_junk_key_fixture_is_refused_by_both_censuses(tmp_path):
    """One golden fixture per key count (9, 10, 11, 12), each carrying junk keys,
    each refused with exit 10 by census.sh AND census.py, naming the junk key.

    The counts are asserted too, since the count is the regression: a fixture that
    drifted to a different number of keys would stop being the shape the count rule
    accepted.
    """
    for name, junk in JUNK_FIXTURES.items():
        record = _fixture(name)
        assert len(record) == EXPECTED_KEYS[name], (
            f"{name}: the fixture is {len(record)} keys; the point of it is the count "
            f"({EXPECTED_KEYS[name]})"
        )
        for key in junk:
            assert key in record, f"{name}: the fixture lost its junk key {key}"
        _assert_both_refuse(tmp_path / name, record, junk[0], f"{name} junk key",
                            subdir=name)


def test_the_closed_set_is_a_set_and_not_a_count(tmp_path):
    """The rule stated as the rule, not as the four fixtures: a record whose keys
    are all declared is clean at twelve keys, and one extra key makes it malformed
    at any count.

    A count and a set agree on every record that carries only declared keys, so the
    positive half matters: it is what shows the set test did not simply tighten
    until nothing passed.
    """
    full = _fixture("decision-valid-all-optional-fields.json")
    assert len(full) == 12, f"the control is the full twelve-key shape: {len(full)}"
    _assert_both_clean(tmp_path, full, "all four optional fields")

    with_junk = dict(full)
    with_junk["id"] = "2026-10-04-thirteen-keys"
    with_junk["junk"] = "one key over a count the old rule never reached"
    assert len(with_junk) == 13
    _assert_both_refuse(tmp_path, with_junk, "junk", "a thirteenth key",
                        subdir="thirteen")


def test_a_record_missing_a_required_field_is_still_reported(tmp_path):
    """The required-key check survived the rewrite: a record missing one of the
    eight says which one it is missing, from both censuses.

    The closed set and the required set are two tests, and a record can fail
    either alone; collapsing them into one would let a record missing three fields
    report as merely "unknown field" or vice versa.
    """
    record = _fixture("decision-invalid-missing-field.json")
    assert "supersedes" not in record
    _assert_both_refuse(tmp_path, record, "supersedes", "a missing required field")


# --- the two programs declare one schema ------------------------------------

def _jq_closed_set_literal() -> list[str]:
    """The closed-set keys, read out of the jq program's own text.

    Parsed from the ``closed8`` definition rather than hard-coded here: a copy in
    the test would drift alongside a drift in the program, which is the failure
    this assertion exists to catch. Returns the keys in the program's own order.
    """
    text = SCHEMA_JQ.read_text(encoding="utf-8")
    definition = re.search(r"def closed8:.*?== 0\);", text, re.S)
    assert definition, "closed8 no longer holds the bracketed key literal to parse"
    # The FIRST non-empty bracketed list inside closed8 is the closed set: the only
    # other bracket pair in the definition is the `keys_unsorted // []` default.
    bracket = re.search(r"\[([^\]]+)\]", definition.group(0), re.S)
    assert bracket, "closed8 no longer holds a non-empty bracketed key literal"
    return re.findall(r'"([^"]+)"', bracket.group(1))


def test_the_jq_closed_set_literal_is_the_python_schema_exactly():
    """The jq program's closed set IS ``REQUIRED_LEDGER_FIELDS`` plus
    ``OPTIONAL_LEDGER_FIELDS``: same names, same order, no extras on either side.

    Two programs, one schema: the jq file is what census.sh reads and the Python
    tuples are what census.py reads. A field added to one and not the other means
    the writer commits a record one arbiter calls unknown, which is the drift no
    behavioural test would notice until a ledger could not be read.
    """
    from noni import ledger_schema

    declared = list(ledger_schema.REQUIRED_LEDGER_FIELDS) + \
        list(ledger_schema.OPTIONAL_LEDGER_FIELDS)
    literal = _jq_closed_set_literal()
    assert literal == declared, (
        "the jq closed set and the Python schema have drifted apart:\n"
        f"  jq:     {literal}\n  python: {declared}"
    )
    assert len(literal) == len(set(literal)) == len(declared), literal
    # The required eight are the first eight, so a reader of either side reads the
    # same list in the same order.
    assert literal[:len(ledger_schema.REQUIRED_LEDGER_FIELDS)] == \
        list(ledger_schema.REQUIRED_LEDGER_FIELDS)


def test_a_field_added_to_the_python_schema_alone_would_be_caught():
    """The parity assertion bites: a name in the Python sets and not the jq
    literal is reported, not silently accepted.

    Stated as the negative case so a reader can see what the comparison above
    fails on, and built from the shipped source rather than a patched module, so
    the assertion is proved on the same code path it governs.
    """
    from noni import ledger_schema

    literal = set(_jq_closed_set_literal())
    declared = set(ledger_schema.REQUIRED_LEDGER_FIELDS) | \
        set(ledger_schema.OPTIONAL_LEDGER_FIELDS)
    assert literal == declared
    assert (declared | {"a_field_jq_does_not_know"}) != literal
    assert (literal | {"a_field_python_does_not_know"}) != declared


# --- the renderer and the totals --------------------------------------------

def test_render_refuses_a_key_outside_the_field_order():
    """``render`` raises on a key the writer's field order does not name, rather
    than printing a body missing it.

    Dropping it silently was the old behaviour: the bytes would not match the dict
    the caller believed it wrote, a supersede would then compare its target against
    bytes it never rendered, and the census would read back a record missing a field
    its writer had just committed. A ``ValueError`` is the refusal the callers
    already treat as their exit-4 event.
    """
    from noni.decide import FIELD_ORDER
    from noni.ledger_schema import render

    record = _fixture("decision-valid-all-optional-fields.json")
    assert render(record, FIELD_ORDER) == json.dumps(
        record, indent=2, ensure_ascii=False) + "\n"
    record["a_field_nobody_declared"] = "x"
    try:
        body = render(record, FIELD_ORDER)
    except ValueError as exc:
        assert "a_field_nobody_declared" in str(exc), (
            f"the refusal must name the key it refused: {exc}")
    else:
        raise AssertionError(f"a key outside the field order rendered: {body[:200]}")


def test_validate_source_is_total_and_the_caller_asks_it_anyway():
    """A record with no ``source`` key asks the provenance question and gets "no
    problem", and the record pass calls it unguarded so a key cannot dodge the check.

    The function used to index ``record["source"]`` while the caller guarded the
    call; either half kept the other honest by accident. Now the helper answers for
    a record that carries no provenance and the caller asks it of every record,
    which is the arrangement that cannot skip the check by a key-name slip.
    """
    from noni.census_ledger_checks import _validate_record
    from noni.ledger_schema import validate_source

    record = _fixture("decision-valid.json")
    assert "source" not in record
    assert validate_source(record) == []
    assert validate_source({**record, "source": None}) == []
    assert validate_source(
        {**record, "source": {"issue_number": 1, "comment_id": 2}}) == []
    half = validate_source({**record, "source": {"issue_number": 1}})
    assert any("comment_id" in problem for problem in half), half
    extra = validate_source(
        {**record, "source": {"issue_number": 1, "comment_id": 2, "who": "me"}})
    assert any("unknown" in problem for problem in extra), extra
    # And through the record pass, which no longer guards the call: a record whose
    # source is a bare string is refused the same way a record with a half-object is.
    assert any("source" in problem
               for problem in _validate_record({**record, "source": "42"})), record
    assert _validate_record({**record, "source": None}) == []


# --- census.sh's exit-3 sub-class -------------------------------------------

def test_the_schema_program_is_shipped_and_measured_by_the_size_gate():
    """The .jq file is counted as shipped content of the skill, and stays under the
    source line cap.

    census.sh reads the program by path, so a skill pack that shipped the script
    without the program is a census that exits 3 on every run -- the failure
    ``test_census_sh_exits_three_when_the_schema_program_is_missing`` plants
    deliberately and this one keeps from happening by accident. The cap itself is
    the repository's rule (AGENTS.md), enforced by
    ``tests/test_file_size_limit.py``: the assertion here is that the .jq file is
    measured by that gate rather than exempted for its suffix. The fixture
    directory is asserted alongside the program, since the golden records above are
    the other half of what makes the schema testable.
    """
    assert SCHEMA_JQ.is_file(), f"{SCHEMA_JQ} is not shipped"
    shipped = {p.name for p in SCHEMA_JQ.parent.iterdir()}
    assert {"census.sh", "census-schema.jq", "decide.py"} <= shipped, shipped
    for name in list(JUNK_FIXTURES) + ["decision-valid-all-optional-fields.json",
                                       "decision-valid.json"]:
        assert (FIXTURES / name).is_file(), f"the golden fixture {name} is missing"

    # Imported inside the test: the size gate lives beside this file on pytest's
    # bare-import path, the same route every test module here uses for the harness,
    # and importing it at module top would pull a test module's deps into every
    # collection of this one.
    from test_file_size_limit import _limit_for

    rel = "skills/steering-ledger/scripts/census-schema.jq"
    cap = _limit_for(rel, REPO / rel)
    assert cap is not None, (
        "the size gate exempts census-schema.jq, so the program the census reads "
        "could grow past the source cap unmeasured")
    lines = len(SCHEMA_JQ.read_text(encoding="utf-8").splitlines())
    assert lines <= cap, f"census-schema.jq is {lines} lines; the cap is {cap}"
