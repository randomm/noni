"""A pathological ledger record is a row, never a traceback.

``check_ledger_records`` parses every record with ``json.loads``. Before issue
#102 its one except arm named ``json.JSONDecodeError`` alone, and two shapes
that decoder raises for other reasons escaped it: a nesting past the
interpreter's own stack raises ``RecursionError`` (which is no kind of
``ValueError``), and an integer literal past the interpreter's 4300-digit
conversion limit raises ``ValueError``. Both left ``census.main`` with a
traceback at exit 1 and no rows at all, which is the same lie as a report that
prints "clean": an arbiter that crashes answers nothing.

The arm now names all three, so both shapes answer with the class's own row at
the class's own code. The depth these tests plant is ``DEEP`` from
``tests/ordering_shapes.py``: 100000 levels, past every supported
interpreter's decoder ceiling (measured: 3.11 gives up just under the recursion
limit, 3.12 and 3.13 near 10000, 3.14 near 60000, all four at 100000), so the
``RecursionError`` arm is exercised on every interpreter the suite gates on, CI
included.

What this file does NOT cover: the same shape reaching the ordering group's
reader (``tests/test_census_ordering_recursion.py``), and the writer's read of
committed record bytes (``tests/test_decide_hardening_deep_target.py``).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from _harness import SRC, _commit_file, _init_repo
from census_fixtures import _ndjson_rows, _valid_record
from census_ledger_fixtures import _code, _rows
from census_run import _run_census
from ordering_shapes import _deep

LEDGER_REL = "noni/decisions"
DEEP_NAME = "2026-10-01-deep.json"
DEEP_REL = f"{LEDGER_REL}/{DEEP_NAME}"
FRESH = "2026-10-02T00:00:00Z"


def _deep_record_repo(tmp_path: Path, name: str = DEEP_NAME) -> Path:
    """A committed tree whose ledger holds one record of ``_deep()`` bytes.

    The bytes are written and committed verbatim: a fixture that built the
    value with ``json`` first would have to survive the very decode the census
    is being asked to survive, and would then be testing its own reader.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "README.md", "# repo\n")
    _commit_file(repo, f"{LEDGER_REL}/{name}", _deep())
    return repo


def _record_rows(rows: list[dict]) -> list[dict]:
    """Only the record class, which is what this file's subject reports."""
    return [r for r in rows if r["check"] == "ledger-record"]


def test_a_deeply_nested_record_is_one_row_at_exit_10(tmp_path):
    """AC2: a record nested 100000 levels deep is the ordinary malformed-record row.

    The whole census, not a filtered run: the crash this test exists for
    discarded every finding of the run, so the assertion is made on the run an
    operator actually performs. ``subject`` and ``message`` are pinned as well
    as the code: exit 10 is also what an ordinary non-object record earns
    today ("record is not a JSON object"), so a run that asserted only the code
    would pass on a record refused for an unrelated reason.
    """
    repo = _deep_record_repo(tmp_path)
    rc, out, err = _run_census(repo, "--json", "--now", FRESH)
    combined = out + err
    assert "RecursionError" not in combined, combined[-2000:]
    assert "Traceback" not in combined, combined[-2000:]
    assert rc == 10, (rc, out, err[-2000:])
    records = _record_rows([r for r in _ndjson_rows(out) if r.get("kind") == "finding"])
    assert len(records) == 1, records
    assert records[0]["subject"] == DEEP_NAME, records[0]
    assert records[0]["message"] == "record is not valid JSON", records[0]


def test_a_record_past_the_integer_digit_limit_is_one_row_at_exit_10(tmp_path):
    """The second crash class: an integer literal too long to convert.

    ``json.loads('1' + '0'*100000)`` raises ``ValueError`` ("Exceeds the limit
    (4300 digits) for integer string conversion") out of ``int()``, not a
    decode error, so the old arm missed it on every interpreter. Same row and
    same code: the census does not quote the number back.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "README.md", "# repo\n")
    _commit_file(repo, f"{LEDGER_REL}/2026-10-01-huge.json", "1" + "0" * 100000)
    rc, out, err = _run_census(repo, "--json", "--now", FRESH)
    combined = out + err
    assert "Traceback" not in combined, combined[-2000:]
    assert rc == 10, (rc, out, err[-2000:])
    records = _record_rows([r for r in _ndjson_rows(out) if r.get("kind") == "finding"])
    assert len(records) == 1, records
    assert records[0]["message"] == "record is not valid JSON", records[0]


def test_a_deep_record_survives_each_ledger_filter(tmp_path):
    """The crash was filter-independent, so the fix is proved per filter.

    The whole ledger group is gated on one probe, so ``--only ledger-record``,
    ``--only ledger-edited`` and ``--only ledger-chain`` each reached the same
    parse and each died identically: the filter chose which rows the run
    reported, never whether it read the records. One case per filter, each
    asserting the row that filter now gets - the record row, or nothing at all
    where the class has no complaint about this tree. The fourth filter case is
    the run the operator performs, in
    :func:`test_a_deeply_nested_record_is_one_row_at_exit_10`.
    """
    expected = {
        # The class of the row itself, and the cannot-tell pair of a filtered
        # group: a chain pass with one refused record has nothing to say, and
        # so does an edit check whose record matches its commit.
        "ledger-record": ["ledger-record"],
        "ledger-edited": [],
        "ledger-chain": [],
    }
    for check, checks in expected.items():
        repo = _deep_record_repo(tmp_path, f"deep-{check}.json")
        rows = _rows(repo, "--skip", "hygiene", "--only", check)
        assert "RecursionError" not in str(rows), (check, rows)
        assert "Traceback" not in str(rows), (check, rows)
        assert [r["check"] for r in rows] == checks, (check, rows)
        if checks:
            assert rows[0]["subject"] == f"deep-{check}.json", (check, rows[0])
            assert rows[0]["message"] == "record is not valid JSON", (check, rows[0])


def test_a_refused_record_still_gets_the_edited_check(tmp_path):
    """A record the parser refuses lands in ``unparseable``, not ``valid``.

    The record pass hands its two lists to two different consumers: the
    git-backed edit check walks both, the chain check walks only ``valid``. A
    deep record appended to ``valid`` instead would crash the chain pass on
    ``obj["supersedes"]`` - the same crash by another road - and left out of
    both lists it would silence the integrity check for bytes an operator can
    still edit.

    The observable is the edit row, which only the ``unparseable`` list can
    produce for a record that does not parse. The committed bytes are the deep
    document, so the deep read is what the record pass met at commit time, and
    the working-tree bytes are a shorter malformed record: one run, one
    ledger-record row for the bytes on disk and one ledger-edited row proving
    the refused record reached the integrity check. The run's own code is the
    record class's 10, not 12: the lowest class code of the fired classes wins,
    and both classes fired.
    """
    repo = _deep_record_repo(tmp_path)
    (repo / DEEP_REL).write_text("{not json", encoding="utf-8")
    rows = _rows(repo, "--skip", "hygiene")
    assert sorted(r["check"] for r in rows) == ["ledger-edited", "ledger-record"], rows
    edited = [r for r in rows if r["check"] == "ledger-edited"][0]
    assert edited["subject"] == DEEP_NAME, edited
    assert edited["message"].startswith("record was edited after commit"), edited
    assert _code(repo, "--skip", "hygiene") == 10, rows


def test_the_refusal_quotes_nothing_from_the_record(tmp_path):
    """The row's wording is fixed, so untrusted content stays out of the report.

    The deep text is content of a file somebody else wrote, and the census's
    promise is that a row never carries it. A row built from the decoder's own
    message would have printed the shape that broke it.
    """
    repo = _deep_record_repo(tmp_path)
    rows = _rows(repo, "--skip", "hygiene")
    records = _record_rows(rows)
    assert len(records) == 1, rows
    assert records[0]["message"] == "record is not valid JSON", records[0]
    assert "[" * 20 not in str(rows), rows


def test_a_valid_record_beside_a_deep_one_is_still_censused(tmp_path):
    """The run reports the whole ledger instead of dying at the bad record.

    The record pass reads the ledger in name order, so the good record sorts
    after the deep one: before the fix the run died before reaching it and
    printed nothing at all, clean records included.
    """
    repo = _deep_record_repo(tmp_path)
    _commit_file(repo, f"{LEDGER_REL}/2026-10-02-zeta.json",
                 json.dumps(_valid_record("2026-10-02-zeta"), indent=2))
    rows = _rows(repo, "--skip", "hygiene")
    assert [r["subject"] for r in rows] == [DEEP_NAME], rows
    rc, out, err = _run_census(repo, "--json", "--now", FRESH)
    assert rc == 10, (rc, out, err[-2000:])
    # The chain pass read the good record and found nothing to report, which it
    # could only have done by parsing it: a deep record handed over as valid
    # would have raised there instead of being named by one row here.
    assert not [r for r in rows if r["check"] == "ledger-chain"], rows


def test_the_record_pass_names_all_three_decode_refusals() -> None:
    """The except arm is the three refusals, read off the tree it lives in.

    From outside, a test cannot tell a reachable arm from a decorative one, and
    the arm's whole point is the two types an earlier version of this line
    omitted. ``RecursionError`` is no kind of ``ValueError``, so naming one is
    not naming the other; an edit that drops either puts a traceback back into
    the run, and this is the assertion that says so. Read from the syntax tree
    rather than the text, as the census's other structural pins are: a reworded
    comment keeps passing and a dropped type fails with the reason.
    """
    tree = ast.parse((SRC / "noni" / "census_ledger_checks.py").read_text(encoding="utf-8"))
    parse_pass = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.Try) and _calls_json_loads(node))
    handled = {_handler_name(name) for handler in parse_pass.handlers
               if isinstance(handler.type, ast.Tuple)
               for name in handler.type.elts}
    assert "ValueError" in handled, handled
    assert "RecursionError" in handled, handled
    assert "json.JSONDecodeError" in handled, handled


def _handler_name(node: ast.expr) -> str:
    """The dotted name an ``except`` element carries (``json.JSONDecodeError``).

    Qualified names are how the module spells the decode failure, so the reader
    is a dotted path and not a bare ``Name``: reading only ``Name`` nodes would
    drop the one type the arm has always named and report it as a dropped one.
    """
    return ast.unparse(node)


def _calls_json_loads(node: ast.Try) -> bool:
    """Whether this ``try`` wraps the record's parse, and not another try of the pass.

    Located by what it calls rather than by a line number or a name, so the pin
    follows the parse into whichever function reports "record is not valid JSON"
    and cannot be satisfied by some other arm of the same pass.
    """
    for inner in ast.walk(node):
        call = inner.func if isinstance(inner, ast.Call) else None
        if isinstance(call, ast.Attribute) and call.attr == "loads" \
                and isinstance(call.value, ast.Name) and call.value.id == "json":
            return True
    return False
