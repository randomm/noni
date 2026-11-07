"""The closed record key set, stated as the rule that replaced the key count.

The regression these fixtures pin: the second arbiter's closed set was a key
COUNT, not a set test. It accepted a junk key beside a real optional field (nine
keys: the eight required plus ``source``, and one name nobody declared for free),
and it accepted 10-, 11- and 12-key records carrying any names at all. ``origin/main``
answered exit 10 on every one of those shapes, and ``census.py`` -- which tested
membership rather than counting -- refused them throughout. So the symptom was a
record the writer committed and one of its two arbiters then reported at exit 10
while the other called it clean.

The second arbiter is gone (issue #99): ``census.sh`` is a thin wrapper over the
unified census, so the parity assertion that compared the jq program's key
literal against ``REQUIRED_LEDGER_FIELDS`` plus ``OPTIONAL_LEDGER_FIELDS`` has no
second literal to read, and it is deleted with the program. What the fixtures
still prove is the behaviour: every golden fixture (one per key count, each
carrying junk keys) earns exit 10 from both the wrapper and the census it runs,
and a record whose keys are all declared stays clean at twelve.

The name rules and the marker rules, asserted through every entry point, are in
``tests/test_ledger_name_and_marker_rules.py``. The shared launchers are in
``tests/ledger_schema_fixtures.py``.
"""

from __future__ import annotations

import json

from _harness import REPO
from ledger_schema_fixtures import (
    EXPECTED_KEYS,
    FIXTURES,
    JUNK_FIXTURES,
    _assert_both_clean,
    _assert_both_refuse,
    _fixture,
)

# --- the closed set ----------------------------------------------------------

def test_each_junk_key_fixture_is_refused_by_both_censuses(tmp_path):
    """One golden fixture per key count (9, 10, 11, 12), each carrying junk keys,
    each refused with exit 10 by the shim AND the census, naming the junk key.

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
    eight says which one it is missing, from both entry points.

    The closed set and the required set are two tests, and a record can fail
    either alone; collapsing them into one would let a record missing three fields
    report as merely "unknown field" or vice versa.
    """
    record = _fixture("decision-invalid-missing-field.json")
    assert "supersedes" not in record
    _assert_both_refuse(tmp_path, record, "supersedes", "a missing required field")


def test_the_schema_field_sets_are_the_only_declaration_of_the_set():
    """The field sets live in ``ledger_schema`` and nowhere else a census reads.

    The parity this test used to run was behavioural in one direction only: the
    second arbiter declared the twelve names in its own literal, and a copy in a
    program the census never ran is what the comparison caught. With that program
    deleted, the assertion that still means something is that the set has one
    owner — the census's record pass and the writer both read these two tuples
    rather than keeping a list of their own.
    """
    from noni import ledger_schema
    from noni.census_ledger_checks import (
        OPTIONAL_LEDGER_FIELDS,
        REQUIRED_LEDGER_FIELDS,
    )

    assert REQUIRED_LEDGER_FIELDS == ledger_schema.REQUIRED_LEDGER_FIELDS
    assert OPTIONAL_LEDGER_FIELDS == ledger_schema.OPTIONAL_LEDGER_FIELDS
    declared = (set(ledger_schema.REQUIRED_LEDGER_FIELDS)
                | set(ledger_schema.OPTIONAL_LEDGER_FIELDS))
    assert len(declared) == 12, sorted(declared)
    # No third copy: the record pass names the sets it validates by importing
    # them, so a name added to the schema alone changes the census too.
    assert set(ledger_schema.REQUIRED_LEDGER_FIELDS) & \
        set(ledger_schema.OPTIONAL_LEDGER_FIELDS) == set()


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


def test_the_golden_fixtures_the_suite_reads_are_all_present():
    """The fixture set these tests plant from exists on disk, by name.

    Every refusal above is only as good as the fixture it loads, and a fixture
    deleted or renamed out of ``tests/fixtures/`` would otherwise turn a loop over
    the shapes into a loop over nothing that still ends green.
    """
    for name in list(JUNK_FIXTURES) + ["decision-valid-all-optional-fields.json",
                                       "decision-valid.json"]:
        assert (FIXTURES / name).is_file(), f"the golden fixture {name} is missing"
    assert REPO.is_dir()
