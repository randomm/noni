"""The shapes the writer's decoder refuses to answer for, and the reader that survives them.

Extracted from the decide writer suite (issue #102): the pathological half of
the writer's read of a target's committed bytes
(``noni.record_read.record_object``, reached through ``gitwrite.record_object``).
The decisions about *what* a writable record may hold, and the non-finite
refusals beside these, are owned by ``test_decide_hardening_shape.py``; this
file owns the shapes the decoder itself refuses to answer.

The two files are two halves of one deliverable, so each of them is a
declaration of what the other does not test: an edit to the writer's read that
passes one file and fails the other has moved a shape between the families
rather than handled it.

Three shapes escaped that read. ``json.loads`` raises ``RecursionError`` on a
nesting past the interpreter's own stack - which is no kind of ``ValueError``,
so the arm beside it did not catch it - and ``ValueError`` on an integer literal
past the 4300-digit conversion limit, which the old arm missed as well because
it names the decode failure and the refused token, not the fault ``int()``
raises. The third was inside the reader's own non-finite walk, which recursed, so
a value the decoder did build on a generous interpreter overflowed the inspection
that was supposed to report on it.

Each one walked past ``load_committed_target``, which catches only ``OSError``
around this read, and turned a ``decide`` run into a traceback at exit 1: no
refusal, no hint, and the operator left to guess which of the two records the
run had choked on. The writer's answer to all three is the existing
"not a readable JSON object" refusal, which the writer's own probe tests word in
detail; what this file pins is that the refusal is *reached*.

Every case here ends the same way -- exit 4, the target's committed bytes
exactly what they were, and no new record in the tree -- because a refusal is
only worth having if it refuses rather than rewrites.
"""

from __future__ import annotations

import inspect
import json

from _harness import _git_e2
from decide_fixtures import BASELINE_ID
from decide_hardening_fixtures import (
    _canonical_body,
    _porcelain,
    _refuse_raw_target,
    _refused_target_repo,
)
from decide_inprocess_fixtures import _supersede_in_process
from decide_target_shapes import (
    DEEP_ARRAY_IN_SCOPE,
    DEEP_RECORD_LEVELS,
    DIGIT_LIMIT_SCOPE,
    OPTION_LATER,
    SCOPE_FIELD,
    _deep_value,
    _target_body,
)
from ordering_shapes import DEEP, _deep

# The depth below which a rendered record is the writer's own shape and not a
# planted nest: the record, its questions list, a question, its options list and
# an option is five. A probe that has to tell "a normal record was rendered" from
# "a deep record was rendered" needs the line stated, not felt.
SHALLOW_RECORD_CEILING = 10


def _record_read_module():
    """The module that owns the writer's read of a record's bytes.

    Named through the package, as the harness names every product module: the
    writer reaches it as ``gitwrite.record_read``, and a test that trusted a bare
    name off ``sys.path`` would be testing a lookalike.
    """
    from noni import record_read

    return record_read


def _nested_record(kind: str, depth: int, leaf: object) -> dict:
    """A record whose option nests ``depth`` levels deep under one container kind.

    Built by hand rather than parsed: the value is the one the standard reader
    cannot build, so a fixture that decoded it first could not test the reader
    meant to survive it. ``kind`` picks the container - the version this
    replaces recursed through dict and list in separate arms.
    """
    node: object = leaf
    for _ in range(depth):
        node = {"k": node} if kind == "dict" else [node]
    return {"id": "x", "questions": [{"options": [node]}]}


def test_hardening_a_target_nested_past_the_decoder_refuses_with_four(tmp_path):
    """A target nested ``DEEP`` levels deep is refused (exit 4), not traced back.

    Every supported interpreter gives up on this document (measured at the
    default recursion limit: 3.11 just under it, 3.12 and 3.13 near 10000, 3.14
    near 60000, all four at 100000), so the arm is exercised on CI's 3.11 and
    not merely theorised about. The tree assertion is the one a refusal test may
    never skip: a run that crashed after staging the target would have left a
    half-applied supersede behind, which is the failure this round exists to
    prevent.
    """
    target_id = f"{BASELINE_ID[:10]}-deep-target"
    raw = _target_body(target_id, SCOPE_FIELD, DEEP_ARRAY_IN_SCOPE)
    assert _deep() in raw, "the fixture planted no deep value"
    stderr, repo, rel = _refuse_raw_target(tmp_path, "deep-target", raw)
    assert "Traceback" not in stderr, stderr
    assert "RecursionError" not in stderr, stderr
    assert "not a readable JSON object" in stderr, stderr
    assert _porcelain(repo) == "", "a refused run must leave the tree alone"
    assert (repo / rel).read_text(encoding="utf-8") == raw


def test_hardening_a_deep_target_in_an_option_refuses_with_four(tmp_path):
    """The deep value inside an option, not a top-level field.

    A reader that only survived a shallow field would still die on the common
    shape: the nesting under ``questions``, which is where a record's real
    structure lives. The reader owns the parse at every depth, so the refusal
    must not depend on which field carried the bytes.
    """
    target_id = f"{BASELINE_ID[:10]}-deep-option"
    raw = _target_body(target_id, OPTION_LATER, _deep())
    assert _deep() in raw, "the fixture planted no deep value in the option"
    stderr, _repo, _rel = _refuse_raw_target(tmp_path, "deep-option", raw)
    assert "Traceback" not in stderr, stderr
    assert "not a readable JSON object" in stderr, stderr


def test_hardening_a_target_past_the_integer_digit_limit_refuses_with_four(tmp_path):
    """A target whose number literal is too long to convert is refused (exit 4).

    ``json.loads`` raises ``ValueError`` ("Exceeds the limit (4300 digits) for
    integer string conversion") out of ``int()``, not out of the decoder's
    grammar, so the old arm - which named the decode failure and the refused
    token - missed it on every interpreter rather than only the oldest. Same
    answer as the overflowing ``1e400`` the sibling file pins: a number this
    writer cannot name is not a record whatever field carries it.
    """
    target_id = f"{BASELINE_ID[:10]}-huge-int"
    raw = _target_body(target_id, SCOPE_FIELD, DIGIT_LIMIT_SCOPE)
    assert "1" + "0" * 99999 in raw, "the fixture planted no oversized literal"
    stderr, _repo, _rel = _refuse_raw_target(tmp_path, "huge-int", raw)
    assert "Traceback" not in stderr, stderr
    assert "not a readable JSON object" in stderr, stderr


def test_hardening_record_object_refuses_a_deep_or_unconvertible_record():
    """``record_object`` answers None for both crash classes, in either container.

    The unit half of the fix: every caller reads a None as "not a record" and
    prints its refusal, so the one thing that must not reach them is the
    exception. Array and object nests are both driven because the version this
    was written against recursed through the two containers separately and could
    have been fixed in one arm only.
    """
    record_read = _record_read_module()
    for label, body in (
        ("deep array in a field", '{"id": "x", "scope": [' + _deep() + "]}"),
        ("deep array in an option",
         '{"questions": [{"options": ["a", ' + _deep() + "]}]}"),
        ("oversized integer", '{"id": "x", "n": 1' + "0" * 100000 + "}"),
    ):
        assert record_read.record_object(body.encode("utf-8")) is None, label


def test_hardening_the_non_finite_walk_survives_a_value_no_decoder_builds():
    """The walk is iterative: it answers a hand-built deep record instead of dying on it.

    ``json.loads`` cannot build a value this deep, so the record is assembled by
    hand - exactly the shape the walk meets on an interpreter whose decoder went
    further than this one's. A recursive answer to "does this record hold a
    number we cannot write?" is the crash the question exists to prevent, and a
    reader that dies on the shape of a record answers nothing about it. The
    non-finite leaf is planted under both a dict nest and a list nest, and a
    finite control proves the walk is not a blanket refusal of every nested
    record.
    """
    record_read = _record_read_module()
    for kind in ("dict", "list"):
        assert record_read.holds_non_finite(_nested_record(kind, DEEP, 1)) is False, kind
        assert record_read.holds_non_finite(
            _nested_record(kind, DEEP, float("inf"))) is True, kind
        assert record_read.holds_non_finite(
            _nested_record(kind, DEEP, float("nan"))) is True, kind
    assert record_read.holds_non_finite({"a": [1, 2.5, {"b": True}, None]}) is False


def test_hardening_the_target_reader_names_its_refusals_and_walks_iteratively():
    """The arm and the walk, read off the source that owns them.

    A behaviour test cannot tell a reachable arm from a decorative one, and the
    arm's whole point is the two types an earlier version of this line omitted:
    ``RecursionError`` is no kind of ``ValueError``, so naming one is not naming
    the other. Beside it the walk is checked for a self-call - an iterative walk
    that quietly grew recursive again would put the crash back inside the reader,
    past the arm that catches only what the decoder itself raises.
    """
    record_read = _record_read_module()
    arm = next(line.strip() for line in inspect.getsource(record_read.record_object)
               .splitlines()
               if "except (" in line and "json.JSONDecodeError" in line)
    assert "UnicodeDecodeError" in arm, arm
    assert "ValueError" in arm, arm
    assert "RecursionError" in arm, arm
    walk = inspect.getsource(record_read.holds_non_finite)
    assert "holds_non_finite(" not in walk.replace("def holds_non_finite(", "", 1), (
        f"the non-finite walk recurses again: {walk}")


def test_hardening_record_object_refuses_a_record_past_the_depth_bound():
    """``record_object`` answers None for a record the decoder can build but no
    writer renders, and still accepts one inside the bound.

    The crash class the arm cannot reach. On 3.12 and later ``json.loads`` builds
    a value thousands of levels deep, so the record reaches the writer's
    renderer, whose own ``json.dumps`` is the recursion that dies - outside every
    arm this reader has. The bound is what answers here, at the same
    ``census_json.MAX_DEPTH`` the strict readers enforce, so the depth is asserted
    rather than trusted: past the bound, and below this interpreter's recursion
    budget, which is what makes the bound the only rule that could have refused
    it. The control inside the bound proves the bound is not a blanket refusal of
    every nested record.
    """
    import sys

    record_read = _record_read_module()
    from noni import census_json

    assert DEEP_RECORD_LEVELS > census_json.MAX_DEPTH, (
        f"{DEEP_RECORD_LEVELS} levels is not past the bound of "
        f"{census_json.MAX_DEPTH}, so the bound is not what answered")
    assert DEEP_RECORD_LEVELS < sys.getrecursionlimit(), (
        f"{DEEP_RECORD_LEVELS} levels is inside no decoder's reach on this "
        f"build (limit {sys.getrecursionlimit()}), so the arm is what answered")
    # ``_depth_of`` counts the record itself as one level, so a value of N levels
    # makes a record of N + 1 and the bound refuses at N = MAX_DEPTH. Both edges
    # are driven because a bound off by one on either side passes a test that
    # only asks the middle question.
    at_bound = census_json.MAX_DEPTH - 1
    deep = '{"id": "x", "scope": ' + _deep_value(DEEP_RECORD_LEVELS) + "}"
    assert json.loads(deep)["scope"]["k"], "the standard reader cannot build the fixture"
    assert record_read.record_object(deep.encode("utf-8")) is None
    inside = '{"id": "x", "scope": ' + _deep_value(at_bound) + "}"
    inside_record = record_read.record_object(inside.encode("utf-8"))
    assert isinstance(inside_record, dict), (
        f"a record of {at_bound + 1} levels is inside the bound and must still parse")
    over = '{"id": "x", "scope": ' + _deep_value(at_bound + 1) + "}"
    assert record_read.record_object(over.encode("utf-8")) is None


def test_hardening_a_target_deeper_than_the_bound_refuses_and_reaches_no_renderer(tmp_path):
    """A supersede target nested past the bound is refused (exit 4) with its bytes intact.

    The end-to-end half of the bound: the deep record is one this interpreter's
    decoder builds, so without the bound it is handed on to the writer's
    ``_render``, whose ``json.dumps`` is the recursion that dies - and a run that
    dies there exits 1 with a traceback, having staged nothing and refused
    nothing. Whether the bound actually closes that route is a fact about the
    render call, so it is measured rather than asserted: the writer's renderer is
    replaced for this run by one that refuses every record the way the real one
    refuses a value it cannot name. A run that reached the render fails on its
    exit code; a run that refused at the reader passes without ever asking.
    """
    from noni import decide as writer

    target_id = f"{BASELINE_ID[:10]}-deep-record"
    raw = _target_body(target_id, SCOPE_FIELD,
                       '"scope": ' + _deep_value(DEEP_RECORD_LEVELS))
    assert '"scope": {' in raw, "the fixture planted no deep object in scope"
    repo, _rel = _refused_target_repo(tmp_path, "deep-record", raw)
    rendered: list[str] = []
    original_render = writer._render

    def _refusing_render(record: dict) -> str:
        # Stands in for the real renderer at the one point it can die: a record
        # this deep overflows its encoder, so reaching it here is the crash the
        # bound exists to prevent, spelled as a refusal the writer already knows.
        rendered.append(str(record.get("id")))
        raise ValueError("the record nests past what this renderer can name")

    writer._render = _refusing_render
    try:
        proc = _supersede_in_process(repo, write_fails_on=None, monkeypatch=None,
                                     target_id=target_id, render_observer=None)
    finally:
        writer._render = original_render
    assert proc.returncode == 4, f"expected exit 4, got {proc.returncode}: {proc.stderr}"
    assert "Traceback" not in proc.stderr, proc.stderr
    assert "RecursionError" not in proc.stderr, proc.stderr
    assert "not a readable JSON object" in proc.stderr, proc.stderr
    assert rendered == [], (
        f"the bound must refuse before the renderer is asked: {rendered}")
    assert _porcelain(repo) == "", "a refused run must leave the tree alone"
    assert _git_e2(repo, "show", f"HEAD:noni/decisions/{target_id}.json").stdout == raw, (
        "the refused target's committed bytes must be exactly what they were")


def test_hardening_the_record_reader_shares_the_bound_the_strict_readers_use():
    """The bound is one number with one walk, not a copy kept beside it.

    A second ``MAX_DEPTH = 256`` in the writer's reader would drift the moment one
    side moved, and a recursive depth walk would put the crash back inside the
    reader the bound exists to keep out. The identity is what says the writer's
    read and the census's strict read answer to the same rule.
    """
    record_read = _record_read_module()
    from noni import census_json

    assert record_read.MAX_DEPTH is census_json.MAX_DEPTH
    assert record_read._depth_of is census_json._depth_of
    walk = inspect.getsource(census_json._depth_of)
    assert "_depth_of(" not in walk.replace("def _depth_of(", "", 1), (
        f"the depth walk recurses: {walk}")


def test_hardening_no_decide_path_hands_the_renderer_a_record_past_the_bound(tmp_path):
    """The question the fix leaves open, probed rather than assumed: does any
    decide path still reach the renderer with a record deeper than the bound?

    ``gitwrite.load_committed_target`` has exactly two routes into the render -
    the ``record_object`` read and the ``canonical(record)`` comparison beside it,
    whose arm names only ``ValueError`` - so the probe wraps that ``canonical``
    argument and reports the depth of every record the run actually handed over.
    Three depths are driven, spanning the window past the bound up to a nesting
    no supported decoder builds at all (the ``RecursionError`` arm's own ground),
    and each is expected to be refused by the reader without reaching the render.
    The baseline's own canonical render - the new record this run writes - is
    filtered out of the report, since it is bytes the writer built itself and
    never came from the target; what must stay empty is the deep entries, and an
    entry carrying the planted nest is the crash still standing.
    """
    from noni import census_json
    from noni import decide as writer

    handed: list[int] = []
    rendered: list[str] = []
    original_canonical = writer._render

    def _reporting_canonical(record: dict) -> str:
        # ``record_object`` is the one read whose result reaches this call, so its
        # own verdict is the second half of the evidence: the depth report says
        # what the renderer was handed, the None report says what it was not.
        handed.append(census_json._depth_of(record, 10 ** 9))
        rendered.append(str(record.get("id")))
        return original_canonical(record)

    refused: list[int] = []
    from noni import record_read as _reader

    real_record_object = _reader.record_object
    accepted: list[object] = []

    def _counting_record_object(raw: bytes) -> "dict | None":
        record = real_record_object(raw)
        (refused if record is None else accepted).append(len(raw))
        return record

    from noni import gitwrite

    original_record_object = gitwrite.record_object
    writer._render = _reporting_canonical
    gitwrite.record_object = _counting_record_object
    try:
        for levels in (DEEP_RECORD_LEVELS, 1500, 8000):
            target_id = f"{BASELINE_ID[:10]}-deeper-{levels}"
            body = _target_body(target_id, SCOPE_FIELD,
                                '"scope": ' + _deep_value(levels))
            assert '"scope": {' in body, f"no deep object at {levels} levels"
            repo, _ = _refused_target_repo(tmp_path, f"deeper-{levels}", body)
            proc = _supersede_in_process(repo, write_fails_on=None, monkeypatch=None,
                                         target_id=target_id, render_observer=None)
            assert proc.returncode == 4, f"{levels}: {proc.returncode} {proc.stderr}"
            assert "not a readable JSON object" in proc.stderr, f"{levels}: {proc.stderr}"
            # The reader was asked and answered None, and the renderer was asked
            # nothing bearing this target's id: that pair is the fix, stated for
            # each depth rather than inferred from the exit code alone.
            assert refused, f"{levels}: the reader was never asked"
            assert accepted == [], f"{levels}: the reader accepted a deep record"
        # The probe is not a blanket silence: the same spy on a well-formed
        # target does see renders, so the absence above is a refusal and not a
        # hook that was never reached.
        ordinary_id = f"{BASELINE_ID[:10]}-shallow-control"
        ordinary, _ = _refused_target_repo(tmp_path, "shallow-control",
                                           _canonical_body(ordinary_id))
        control = _supersede_in_process(ordinary, write_fails_on=None,
                                        monkeypatch=None, target_id=ordinary_id,
                                        render_observer=None)
        assert control.returncode == 0, f"control: {control.returncode} {control.stderr}"
        assert ordinary_id in rendered, (
            f"the render probe never fired even for an ordinary record: {rendered}")
    finally:
        writer._render = original_canonical
        gitwrite.record_object = original_record_object
    deep = [d for d in handed if d > SHALLOW_RECORD_CEILING]
    assert deep == [], f"a record past the bound reached the renderer: {deep}"


def test_hardening_the_refused_token_is_never_named_back():
    """``refuse_constant``'s wording is fixed and quotes no content.

    The token is text read from an untrusted record. ``record_object`` never
    echoes it, so the only route by which record content reaches an operator's
    terminal through this reader is the exception's own text, and as long as it
    carries the token it does. The comparison is with ``census_json``, which
    already refuses by the same fixed wording.
    """
    record_read = _record_read_module()
    from noni import census_json

    stolen = 'NaN"or""1=1'
    for module in (record_read, census_json):
        try:
            json.loads(stolen, parse_constant=module.refuse_constant)
        except ValueError as exc:
            assert str(exc) == "not a JSON number", f"{module.__name__}: {exc}"
            assert stolen not in str(exc)
            assert "NaN" not in str(exc), f"{module.__name__} names the token back"
        else:
            raise AssertionError(f"{module.__name__}: refuse_constant accepted the token")
