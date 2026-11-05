"""Deeply nested JSON: refused, not a traceback, and the run stays alive.

The strict reader walks a deep value without recursing, and the census hands its own
reader to the group so the rule has one owner.

Split out of ``tests/test_census_ordering.py``; the builders are in
``tests/ordering_fixtures.py``.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys

from _harness import REPO, SRC
from ordering_fixtures import (
    _entry,
    _order,
    _ordering_record_read_faults,
    _repo,
    _run,
    _run_in_process,
    _seed,
)
from ordering_shapes import DEEP, _deep, _deep_artifact

BASELINE_ID = "2026-10-01-baseline"

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"
# The two halves of the census's own wiring, read where they now live: the
# record pass that reads its names off the probe is in the ledger split, the run
# that hands the ordering group the one listing is in the run split (issue #52).
LEDGER_CHECKS_PY = SRC / "noni" / "census_ledger_checks.py"
CENSUS_RUN_PY = SRC / "noni" / "census_run.py"

FRESH = "2026-10-26T00:00:00Z"

ORDER_REL = "noni/direction/order.json"

SCRIPTS = SRC / "noni"

# --- a pathological nesting ---------------------------------------------------

# ``json.loads`` walks nesting with the interpreter's own stack, so a document
# that nests past the recursion budget raises RecursionError -- which is NOT a
# ValueError, so it is not caught by the arms every reader here already has for
# a malformed file. Where the budget runs out depends on the interpreter: 3.11
# gives up near ``sys.getrecursionlimit()`` (default 1000: measured to break at
# about 990 levels under pytest), later builds go on to a few thousand before the
# C stack itself gives out. The ``RecursionError`` arms below are therefore
# reachable, not theoretical: on 3.11 the ordinary decoder refuses a document
# this deep before this product's bound is consulted.
# Before the bound, one such file ended the whole run with a traceback: an
# arbiter that crashes answers nothing, and a report that never prints is the
# same lie as one that prints "clean". The ``DEEP`` / ``_deep`` shapes live in
# ``tests/ordering_shapes.py`` (the module both ordering suites read), and
# ``_deep_artifact`` there takes the timestamp as ``confirmed`` so this file
# plants the census's own ``FRESH``.


def test_a_deeply_nested_artifact_is_malformed_and_not_a_traceback(tmp_path):
    """The pathological nesting is the ordinary ``ordering-malformed`` row: the
    artifact is there and is not the artifact, and the run exits at the class's
    own code with the class's own fixed wording."""
    repo = _repo(tmp_path, "deep-artifact")
    _order(repo, _deep_artifact(FRESH))
    code, rows, out, err = _run(repo)
    combined = out + err
    assert "RecursionError" not in combined, combined[-2000:]
    assert code == 15, (code, rows, combined[-2000:])
    assert [r["check"] for r in rows] == ["ordering-malformed"], rows
    assert rows[0]["subject"] == ORDER_REL, rows[0]
    assert rows[0]["message"] == "the order file is not valid JSON", rows[0]


def test_a_deeply_nested_state_file_is_malformed_and_not_a_traceback(tmp_path):
    """The ``--issue-state`` reader is a second call into the same decoder, so it
    needs the same answer: the row is the state file's own and the run still
    exits 15 rather than dying."""
    repo = _repo(tmp_path, "deep-state")
    _seed(repo, _entry(7, BASELINE_ID))
    path = repo / "issue-state.json"
    path.write_text(_deep(), encoding="utf-8")
    code, rows, out, err = _run(repo, "--issue-state", str(path))
    combined = out + err
    assert "RecursionError" not in combined, combined[-2000:]
    assert code == 15, (code, rows, combined[-2000:])
    assert [(r["check"], r["subject"]) for r in rows] == [
        ("ordering-malformed", "issue-state")], rows
    assert "is not valid JSON" in rows[0]["message"], rows[0]


def test_a_deep_document_is_refused_before_the_decoder_overflows():
    """Which rule refuses a pathological nesting, and why it has to be that one.

    ``json.loads`` walks nesting on the interpreter's own stack and gives up at
    a depth the build sets: on 3.11 that is near ``sys.getrecursionlimit()``,
    measured to break just under the default 1000, so the ``RecursionError`` arms
    of the readers are reachable there and not merely theoretical. Catching more
    exception types is still not the fix: a run is honest only if it never
    reaches the overflow. So the document here is one the standard reader can
    build on every supported interpreter -- past this product's bound, well
    inside the interpreter's budget -- and what refuses it is the bound alone. It
    raises the ``ValueError`` the callers already catch rather than leaving a
    ``RecursionError`` for them to miss.
    """
    module = importlib.import_module("census_json")
    # Above the product's bound, below the depth at which this interpreter's own
    # decoder gives up. That ceiling is a property of the build -- measured just
    # under the default limit of 1000 on 3.11, and several thousand on 3.12 and
    # 3.13 -- so twice the bound sits in that window on every supported version.
    # The assertion is the premise: a host that lowers the recursion limit below
    # the decoder's reach says so here, not on the line that reads the document.
    inside = module.MAX_DEPTH * 2
    budget = sys.getrecursionlimit()
    assert inside > module.MAX_DEPTH, (
        f"{inside} levels is not past the bound of {module.MAX_DEPTH}, so the "
        "bound is not what answered")
    assert inside < budget, (
        f"{inside} levels is not inside the recursion budget of {budget}")
    body = "[" * inside + "1" + "]" * inside
    assert json.loads(body), "the standard reader must still be able to build this"
    try:
        module.load_json_strict(("{" + '"a": ' + body + "}").encode())
    except ValueError as e:
        assert str(module.MAX_DEPTH) in str(e), \
            f"refused for another reason, so the bound is not what answered: {e}"
    else:
        raise AssertionError("a document nested past the bound was accepted")


def test_a_deeply_nested_ledger_record_leaves_the_run_alive(tmp_path):
    """The ledger read is the group's third reader. A record that does not parse
    is left out of the map for the ledger group to report, so here the entry's
    citation simply matches no record: a deep record must not end the run."""
    repo = _repo(tmp_path, "deep-ledger")
    _seed(repo, _entry(7, "2026-01-01-ghost"))
    record = repo / "noni" / "decisions" / "2026-01-01-ghost.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(_deep(), encoding="utf-8")
    code, rows, out, err = _run(repo)
    combined = out + err
    assert "RecursionError" not in combined, combined[-2000:]
    assert code == 15, (code, rows, combined[-2000:])
    assert [r["check"] for r in rows] == ["ordering-malformed"], rows
    assert "matches no record file" in rows[0]["message"], rows[0]


def test_the_strict_reader_walks_a_deep_value_without_recursing():
    """The non-finite walk and the depth bound are both iterative with their own
    stack.

    ``json.loads`` cannot build a value this deep, so the value is assembled by
    hand -- which is exactly the shape a reader would have to survive if the
    decoder were ever to hand one over. A recursive walk answers the question by
    dying, and a reader that dies on the shape of a document reports nothing
    about it.
    """
    module = importlib.import_module("census_json")
    for depth in (DEEP,):
        deep: list = []
        cursor = deep
        for _ in range(depth):
            child: list = []
            cursor.append(child)
            cursor = child
        cursor.append("x")
        assert module.holds_non_finite(deep) is False, depth
        cursor[-1] = float("inf")
        assert module.holds_non_finite(deep) is True, depth


def test_the_census_lists_the_ledger_through_the_one_shared_helper():
    """The listing is one function, the run takes it once, and nothing uses ``glob``.

    ``census_ledger.listing_helper`` is the one rule for "which files are a
    ledger record", it is called from the probe alone, and the two passes that
    want the answer -- the record pass of ``census.py`` and the ordering readers
    -- are handed the probe's names. A second listing rule would be a second
    answer, and only the ``iterdir`` half would raise on a readdir fault: the
    ``glob`` half would report the unreadable directory as an empty one, which is
    the dishonesty the probe exists to prevent. This pins the wiring at the
    source, so a change back to ``glob``, or back to a second readdir, fails here
    and not in a silent row.

    The session register keeps its own ``glob`` deliberately: it lists ``*.md``
    registers, not ledger records, and is another class's business.

    The readers module reaches the helper through a module attribute and not a
    call it closes over, so the ordering group's own read stays a seam a test can
    fault on its own -- see ``_listing_faults``. Reaching it through a private
    name, or binding it at the call, would make every ordering-fault test here
    fault the ledger group's read as well."""
    ledger_checks_src = LEDGER_CHECKS_PY.read_text(encoding="utf-8")
    run_src = CENSUS_RUN_PY.read_text(encoding="utf-8")
    assert "if probe.state != \"ok\" or probe.names is None:" in ledger_checks_src, \
        "the record pass no longer reads its names off the probe"
    assert "names = sorted(probe.names)" in ledger_checks_src, \
        "the record pass no longer reads the probe's names"
    assert "_ledger.listing_helper(ledger)" not in ledger_checks_src, \
        "the record pass lists the ledger again: the run must take one readdir"
    assert "findings, ledger_probe.names)" in run_src, \
        "the ordering group is no longer handed the run's one listing"
    readers_src = (SCRIPTS / "census_ordering_readers.py").read_text(encoding="utf-8")
    assert "names = listing_helper(ledger)" in readers_src, \
        "the ordering group no longer lists the ledger through the shared helper"
    assert "from .census_ledger import listing_helper" in readers_src, \
        "the ordering group no longer reaches the shared helper by a patchable name"
    assert "if names is None:" in readers_src, \
        "the readers no longer fall back to their own listing, so the group's " \
        "read has no seam to fault on"
    assert "ledger.glob" not in readers_src, \
        "the ordering group lists the ledger with glob, which swallows the fault"
    assert "ledger.glob" not in run_src, \
        "the census run lists the ledger with glob, which swallows the fault"
    ledger_src = (SCRIPTS / "census_ledger.py").read_text(encoding="utf-8")
    assert "ledger.iterdir()" in ledger_src, \
        "the shared helper must list with iterdir, the call that raises"


def test_the_ordering_group_reads_the_probe_names_and_not_the_directory(
    tmp_path, monkeypatch
):
    """The wiring above, seen from the run: the group's own listing is never called.

    ``_ordering_record_read_faults`` faults the readers' ``listing_helper`` and
    leaves the census's names alone, so it reaches nothing while the run hands
    the group the probe's names. It is a control, not a duplicate of
    ``_listing_faults``: that one asks the group to read for itself and proves
    the fault is reported, this one proves a run that could have a second readdir
    does not have one. An ordering row naming a fault here is a group that walked
    the directory behind the probe's back.
    """
    repo = _repo(tmp_path, "group-reads-probe-names")
    _seed(repo, _entry(3, BASELINE_ID))
    with _ordering_record_read_faults(repo / "noni" / "decisions"):
        code, rows, out, err = _run_in_process(repo)
    assert code == 0, (code, rows, out, err)
    assert rows == [], rows


def test_the_readers_take_the_strict_reader_as_an_argument(tmp_path):
    """The strict reader is bound at the call, not imported by bare name.

    ``census.py`` loads every split-out module by path under a name of its own
    precisely so that nothing on ``sys.path`` can be trusted as the census's own
    code -- but a ``from census_json import ...`` inside the readers module put
    the choice of that reader back in ``sys.path``'s hands. Passing it in like
    ``file_kind``, ``bounded`` and ``parse_iso`` already are is what closes it. The
    message clipper arrives the same way, so the readers module carries no second
    definition of what a bounded row means.
    """
    source = (SCRIPTS / "census_ordering_readers.py").read_text(encoding="utf-8")
    assert "from census_json import" not in source
    assert "import census_json" not in source
    readers = importlib.import_module("noni.census_ordering_readers")

    def refusing(raw: bytes) -> object:
        raise ValueError("a reader from elsewhere on sys.path was used")

    order = tmp_path / "order.json"
    order.write_text('{"schema": "noni.order/1", "entries": []}', encoding="utf-8")
    entries, problem = readers.load_order(
        order, lambda path, kind="file": ("regular", None), lambda text: text,
        lambda text: None, lambda value: [], refusing, lambda text: text)
    assert entries is None, entries
    assert problem == "the order file is not valid JSON", problem

    ledger = tmp_path / "decisions"
    ledger.mkdir()
    (ledger / "2026-01-01-a.json").write_text("{}", encoding="utf-8")
    records, readable, unreadable, listed, fault = readers.ledger_records(
        ledger, lambda path, kind="file": ("regular", None), refusing)
    assert (records, readable, unreadable, listed, fault) == ({}, True, set(), True, None)


def test_the_census_hands_its_own_strict_reader_to_the_group():
    """The argument is wired, not merely available: the census passes the reader
    it loaded beside itself, so a lookalike cannot answer for the artifact.

    The clipper is pinned in the same breath: the rows this group composes are
    clipped by the census's own rule, not by a bound the group invents for itself.
    """
    source = CENSUS_RUN_PY.read_text(encoding="utf-8")
    assert "load_json_strict=_census_json.load_json_strict" in source, \
        "the ordering group is not handed the census's own strict reader"
    assert "clipped=census._clipped" in source, \
        "the ordering group is not handed the census's own message clipper"


def test_the_state_row_bounds_the_whole_composed_message(tmp_path):
    """The row's text is built out of keys and state words read from a file
    somebody else wrote.

    ``bounded`` was applied to the path inside the sentence and to each
    individual complaint, but never to the finished message, so four complaints
    of any length each composed a row far past the 300-character bound every
    other row of the report keeps. The bound now wraps the whole message, so
    neither a 5000-character key nor a 5000-character state word reaches a
    report verbatim.
    """
    for index, body in enumerate((json.dumps({"x" * 5000: "open"}),
                                  json.dumps({"7": "y" * 5000}),
                                  json.dumps({"7": "open", "y" * 5000: "nope",
                                              "z" * 5000: "perhaps",
                                              "w" * 5000: "maybe"}))):
        repo = _repo(tmp_path, f"long-state-{index}")
        _seed(repo, _entry(7, BASELINE_ID))
        path = repo / "issue-state.json"
        path.write_text(body, encoding="utf-8")
        code, rows, out, err = _run(repo, "--issue-state", str(path))
        assert code == 15, (index, code, rows, err[-500:])
        assert rows[0]["subject"] == "issue-state", rows[0]
        assert len(rows[0]["message"]) <= 300, \
            f"{index}: {len(rows[0]['message'])} chars: {rows[0]['message'][:80]}"
        assert "x" * 5000 not in rows[0]["message"], rows[0]
        assert "y" * 5000 not in rows[0]["message"], rows[0]
