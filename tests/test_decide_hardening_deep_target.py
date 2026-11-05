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

from decide_fixtures import BASELINE_ID
from decide_hardening_fixtures import _porcelain, _refuse_raw_target
from decide_target_shapes import (
    DEEP_ARRAY_IN_SCOPE,
    DIGIT_LIMIT_SCOPE,
    OPTION_LATER,
    SCOPE_FIELD,
    _target_body,
)
from ordering_shapes import DEEP, _deep


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
