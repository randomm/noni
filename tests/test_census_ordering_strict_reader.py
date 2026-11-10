"""The strict reader: a refusal never echoes file content, and no row outruns the bound.

Split out of ``tests/test_census_ordering.py``; the builders are in
``tests/ordering_fixtures.py``.
"""

from __future__ import annotations

import json

import pytest
from ordering_fixtures import (
    _entry,
    _listing_faults,
    _many_huge_fields,
    _order,
    _repo,
    _run,
    _run_in_process,
    _seed,
    _strict_reader_copy,
    rows_without_unasked_closed,
)

BASELINE_ID = "2026-10-01-baseline"

FRESH = "2026-10-26T00:00:00Z"

def test_the_strict_reader_refusals_never_echo_file_content():
    """Both strict readers' own refusals are composed of this product's words.

    ``json``'s duplicate-key and constant refusals used to name the offending key
    or literal, and their ``ValueError`` is what the readers turn into a row: an
    artifact somebody else wrote would have had its content printed in a report
    that promises not to. The readers catch the exception and answer with fixed
    wording today, so the pin belongs one level down -- on the two refusals
    themselves, in both copies -- where a future author reaching for the
    offending token meets a failure instead of a row that leaks.
    """
    for name, filename in (("census_json", "census_json.py"),
                           ("orderschema", "orderschema.py")):
        module = _strict_reader_copy(name, filename)
        with pytest.raises(ValueError) as duplicate:
            module.reject_duplicate_keys([("secret-key", 1), ("secret-key", 2)])
        assert "secret-key" not in str(duplicate.value), (filename, duplicate.value)
        assert "duplicate key" in str(duplicate.value), (filename, duplicate.value)
        for token in ("NaN", "Infinity", "-Infinity"):
            with pytest.raises(ValueError) as constant:
                json.loads(token, parse_constant=module.refuse_constant)
            assert token not in str(constant.value), (filename, token, constant.value)
            assert "not a JSON number" in str(constant.value), (filename, constant.value)
        load = module.load_json_strict if name == "census_json" \
            else module.load_json_checked
        # The bytes are an unpaired surrogate: no UTF-8 sequence encodes one, so
        # the decode that opens the reader is what refuses them. Spelled as an
        # escape because the thing under test is bytes no encoder will produce.
        undecodable = b'{"a": "\xed\xa0\x80"}'
        with pytest.raises(UnicodeDecodeError):
            load(undecodable, depth=8)


def test_a_composed_row_keeps_the_paths_it_names_while_staying_bounded(tmp_path):
    """Clipping a row is not scrubbing it.

    The bound on a composed row exists to cap what an untrusted file can push into
    a report; it must not also rewrite the root-relative paths this census derived
    itself. A row that called the ledger ``<path>`` would tell the operator that a
    listing failed and nothing about what to look at, so the two halves of the
    census's message primitive stay separate: foreign text is stripped and
    clipped, this run's own sentence is clipped alone.
    """
    repo = _repo(tmp_path, "composed-paths")
    _seed(repo, _entry(3, "2026-10-01-ghost"))
    code, rows, out, err = _run(repo)
    assert code == 15, (code, rows, out, err)
    # The composed row under test is the citation row; the closed class's own
    # not-evaluated row (issue #148) is the fixture's and is not composed from the
    # ledger's fault, so it is not the message whose bound and paths are pinned here.
    malformed = rows_without_unasked_closed(rows)
    message = malformed[0]["message"]
    assert len(message) <= 300, f"{len(message)} chars: {message[:80]}"
    assert "noni/decisions" in message, message
    assert "<path>" not in message, message


def test_an_unlistable_ledger_row_stays_within_the_message_bound(tmp_path):
    """The listing fault a row quotes is foreign text and is bounded as a whole.

    The fault text is an ``OSError`` from this tree, so it arrives through the
    census's ``bounded`` for the piece inside the sentence -- but the finished row
    is that sentence around it, and a fault whose ``strerror`` runs to thousands
    of characters used to compose a row far past the bound every other row of the
    report keeps. The words this run chose still appear; the fault's own text
    still appears; neither is unbounded.

    In-process like the other injected-fault test here: the fault is inside the
    interpreter, and a subprocess would not see it.
    """
    repo = _repo(tmp_path, "long-listing-fault")
    _seed(repo, _entry(3, BASELINE_ID))
    with _listing_faults(repo / "noni" / "decisions",
                         "input/output error: " + "u" * 5000):
        code, rows, out, err = _run_in_process(repo)
    assert code == 15, (code, rows, out, err)
    malformed = rows_without_unasked_closed(rows)
    assert [r["check"] for r in malformed] == ["ordering-malformed"], rows
    message = malformed[0]["message"]
    assert len(message) <= 300, f"{len(message)} chars: {message[:80]}"
    assert "noni/decisions" in message, message
    assert "OSError" in message, message
    assert "input" in message, message
    assert "u" * 5000 not in message, message


def test_an_entry_value_of_any_length_is_bounded_in_the_row(tmp_path):
    """The per-entry shape problems are joined and bounded as one message.

    The problems the census composes from the artifact's own values went through
    ``bounded`` never at all: the row was the join of every complaint, each of
    which quotes a value read from a file somebody else wrote. One 5000-character
    ``issue`` value therefore composed a row of thousands of characters.
    """
    bodies = {
        "a huge issue value": '{"schema": "noni.order/1", "entries": '
                              '[{"issue": "' + "i" * 5000 + '", "decision": null, '
                              '"confirmed": "' + FRESH + '"}]}',
        "a huge decision value": '{"schema": "noni.order/1", "entries": '
                                 '[{"issue": 7, "decision": "' + "d" * 5000 + '", '
                                 '"confirmed": "' + FRESH + '"}]}',
        "many huge unknown fields": _many_huge_fields(),
    }
    for index, (label, body) in enumerate(sorted(bodies.items())):
        repo = _repo(tmp_path, f"long-value-{index}")
        _order(repo, body)
        code, rows, out, err = _run(repo)
        assert code == 15, f"{label}: exit {code} rows={rows} err={err[-500:]}"
        malformed = rows_without_unasked_closed(rows)
        assert [r["check"] for r in malformed] == ["ordering-malformed"], \
            f"{label}: {rows}"
        for row in malformed:
            assert len(row["message"]) <= 300, \
                f"{label}: {len(row['message'])} chars: {row['message'][:80]}"
        # The bound is asserted over the whole stream, not the filtered rows: an
        # unbounded foreign value reaching any row of the report is the failure this
        # test exists for, including the closed class's own row (issue #148).
        assert "i" * 5000 not in json.dumps(rows), label
        assert "d" * 5000 not in json.dumps(rows), label
