"""The census arbitrates order.py's writes: stale, malformed and closed.

Extracted from the order writer suite: the three ordering checks as the gate in
front of the writer, both the refusal and the state it leaves behind."""

import json
import os
import subprocess
from pathlib import Path

from ledger_schema_fixtures import arbiter_why_max, product_why_max
from order_fixtures import (
    _gitwrite_module,
    _schema_case,
    _schema_module,
)
from ordering_shapes import CLEAN_SHAPES, MALFORMED_SHAPES


def test_the_arbiter_copy_of_the_rationale_bound_is_the_owner():
    """The one legitimate second spelling of the bound is held to its owner by reading.

    ``census_ordering`` is loaded by path and imports nothing from the writer's
    package, so it keeps its own copy of the number -- the same reason it keeps copies
    of the field lists and the two character sets. A copy nobody reads back is how the
    writer and the arbiter came to disagree about a value one of them wrote, so this
    asserts the two numbers are equal at the moment the suite runs, and that neither is
    a test's own figure. The shape table
    (``tests/ordering_shapes.py``) drives the same bound through both sides; this is
    the assertion that says the arbiter's copy is the product's number and not a
    bystander that happens to match today.
    """
    owner = product_why_max()
    copy = arbiter_why_max()
    assert copy == owner, (
        f"the ordering arbiter holds {copy} and the item store owns {owner}: a reason "
        "the writer emits is an artifact this class faults, and no verb can rewrite "
        "what the writer will not re-render")


def test_the_git_helper_is_bounded_hardened_and_makes_no_signing_promise(tmp_path):
    """The helper's own contract, tested where it lives: one call, a timeout, and
    the four -c overrides that keep hooks, signing, fsmonitor and external
    transports off the order's commit. A helper that silently dropped one would
    still pass every behavioural test above, because a real repo has none."""
    helper = _gitwrite_module()
    seen: list[list[str]] = []
    real_run = subprocess.run

    bounds: list[dict] = []

    def spy(cmd, *args, **kwargs):
        seen.append(list(cmd))
        bounds.append(dict(kwargs))
        # A stubbed answer: the point is the command line, not git's verdict.
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    subprocess.run = spy
    try:
        proc = helper.git(Path("/nonexistent-repo"), "status", "--porcelain")
    finally:
        subprocess.run = real_run
    assert proc.returncode == 0
    assert len(seen) == 1, seen
    cmd = seen[0]
    assert cmd[:2] == ["git", "-C"], cmd
    assert cmd[2] == "/nonexistent-repo", cmd
    joined = " ".join(cmd)
    for hardening in ("-c commit.gpgsign=false", f"-c core.hooksPath={os.devnull}",
                      "-c protocol.ext.allow=never", "-c core.fsmonitor=false"):
        assert hardening in joined, f"{hardening} missing from {joined}"
    assert cmd[-2:] == ["status", "--porcelain"], cmd
    # The call is bounded by the helper, not the caller: no caller can leave it
    # running, so no caller is trusted to bound it.
    assert bounds[0].get("timeout") == helper.GIT_TIMEOUT, bounds


def test_a_hung_git_call_reports_the_timeout_code_the_writer_classifies(tmp_path):
    """The helper converts its own timeout instead of raising, so the writer can
    classify the answer (exit 3, the file named) rather than end in a traceback.
    The code is the helper's constant, and it is not zero."""
    helper = _gitwrite_module()
    real_run = subprocess.run

    def hang(cmd, *args, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", helper.GIT_TIMEOUT))

    subprocess.run = hang
    try:
        proc = helper.git(Path("/nonexistent-repo"), "commit", "-m", "x")
    finally:
        subprocess.run = real_run
    assert proc.returncode == helper.GIT_TIMEOUT_RC != 0
    assert "timed out" in proc.stderr
    assert "commit" in proc.stderr, "the message names which git call hung"


def test_the_atomic_writer_leaves_the_old_bytes_when_the_replace_fails(tmp_path):
    """write_atomic is the only way the artifact changes: a crash after the temp
    file is written must leave the previous order on disk, not a truncated one
    and not a stray temp file the next census would trip over."""
    helper = _gitwrite_module()
    target = tmp_path / "order.json"
    helper.write_atomic(target, b'{"schema": "noni.order/1", "entries": []}\n')
    first = target.read_bytes()

    def refuse(src, dst):
        raise OSError(5, "Input/output error")

    real_replace = helper.os.replace
    helper.os.replace = refuse
    try:
        try:
            helper.write_atomic(target, b"truncated")
        except OSError:
            pass
        else:
            raise AssertionError("write_atomic swallowed the replace failure")
    finally:
        helper.os.replace = real_replace
    assert target.read_bytes() == first
    assert [q.name for q in tmp_path.iterdir() if q.name != "_noni_isolated_home"] == \
        ["order.json"], "a temp file was left behind"


def test_a_created_artifact_carries_the_mode_the_umask_allows(tmp_path):
    """mkstemp's 0600 must not land: an order the census cannot read is an order
    nobody can trust, and a file that replaces an existing one keeps its mode."""
    helper = _gitwrite_module()
    helper.os.umask(0o022)
    fresh = tmp_path / "order.json"
    helper.write_atomic(fresh, b"a\n")
    assert fresh.stat().st_mode & 0o777 == 0o644, oct(fresh.stat().st_mode & 0o777)
    os.chmod(fresh, 0o600)
    helper.write_atomic(fresh, b"b\n")
    assert fresh.stat().st_mode & 0o777 == 0o600, "a replace must not widen who can read"


def test_the_schema_refuses_a_non_finite_number_in_any_position(tmp_path):
    """The renderer refuses a NaN or an overflowed literal wherever it sits, and
    the reader refuses the token: an order whose issue or stamp is not a number
    is not an order, and a silent inf would sort into a position nobody chose."""
    schema = _schema_module()
    entry = {"issue": 1, "decision": None, "confirmed": "2026-10-27T12:00:00Z"}
    for body in ({"schema": schema.ORDER_SCHEMA, "entries": [dict(entry, issue=float("nan"))]},
                 {"schema": schema.ORDER_SCHEMA, "entries": [dict(entry, issue=float("inf"))]}):
        try:
            schema.order_bytes(body)
        except ValueError:
            pass
        else:
            raise AssertionError(f"rendered a non-finite issue: {body}")
    assert schema.holds_non_finite({"entries": [{"issue": float("inf")}]})
    assert not schema.holds_non_finite({"entries": [{"issue": True, "n": 1}]})
    try:
        json.loads('{"a": NaN}', parse_constant=schema.refuse_constant)
    except ValueError:
        pass
    else:
        raise AssertionError("refuse_constant accepted NaN")


def test_the_schema_reports_the_first_defect_it_finds(tmp_path):
    """problems() names what is wrong with a value the writer may not extend:
    each documented defect shape is reported, and a well-formed order is not."""
    schema = _schema_module()
    assert schema.problems(_schema_case()) == []
    assert schema.problems([]), "a list is not an order"
    assert schema.problems({"entries": []}), "no schema key"
    assert schema.problems({"schema": "noni.order/3", "entries": []}), "wrong schema"
    # ``noni.order/2`` is a version the writer reads and emits, not a defect: it is
    # the shape of an order whose entries cite items (#123).
    assert schema.problems({"schema": "noni.order/2", "entries": []}) == [], \
        "the item version is a schema, not a defect"
    assert schema.problems({"schema": schema.ORDER_SCHEMA, "extra": 1,
                            "entries": []}), "unknown field"
    assert schema.problems({"schema": schema.ORDER_SCHEMA, "entries": {}}), "entries not a list"
    assert schema.problems(_schema_case(extra_key=1)), "entry with an unknown field"
    short = {"schema": schema.ORDER_SCHEMA, "entries": [{"issue": 1}]}
    assert schema.problems(short), "entry missing fields"
    assert schema.problems(_schema_case(issue="1")), "issue is not an int"
    assert schema.problems(_schema_case(issue=True)), "issue is a bool"
    assert schema.problems(_schema_case(issue=0)), "issue is not positive"
    assert schema.problems(_schema_case(decision="")), "decision is blank"
    assert schema.problems(_schema_case(decision=3)), "decision is neither str nor null"
    assert schema.problems(_schema_case(confirmed="nope")), "confirmed is not a timestamp"
    assert schema.problems(_schema_case(confirmed=5)), "confirmed is not a string"
    assert schema.problems({"schema": schema.ORDER_SCHEMA,
                            "entries": [[], {"issue": 2, "decision": None,
                                             "confirmed": "2026-10-27T12:00:00Z"}]}), \
        "an entry that is not an object"
    assert schema.problems({"schema": schema.ORDER_SCHEMA,
                            "entries": [{"issue": 4, "decision": None,
                                         "confirmed": "2026-10-27T12:00:00Z"},
                                        {"issue": 4, "decision": None,
                                         "confirmed": "2026-10-27T12:00:00Z"}]}), \
        "a duplicate issue"
    # A non-finite number anywhere in the document is a defect, and a bool is
    # never a number: the two rules the renderer also refuses to emit.
    assert schema.holds_non_finite(_schema_case(issue=float("nan"))), "NaN in an entry"
    assert not schema.holds_non_finite(_schema_case()), "a clean order"


def test_the_schema_reads_a_utc_stamp_and_refuses_a_bare_one():
    """parse_confirmed is the census's and the writer's one reading of a stamp:
    a Z-suffixed or offset time is a time, a bare one is not, and neither is a
    mis-ordered digit string."""
    schema = _schema_module()
    assert schema.parse_confirmed("2026-10-27T12:00:00Z") is not None
    assert schema.parse_confirmed("2026-10-27T12:00:00+02:00") is not None
    assert schema.parse_confirmed("2026-10-27T12:00:00") is None
    assert schema.parse_confirmed("yesterday") is None


def test_the_writer_and_the_arbiter_answer_one_entry_list_alike():
    """The two rule sets are one contract written twice, and this says so per shape.

    ``orderschema.problems`` gates the write and ``census_ordering.order_problems``
    is what the census reports as ``ordering-malformed``. The census loads its group
    by path and imports nothing from the writer's package, so the two lists are two
    copies -- which is exactly how they drift, and the ``/2`` entry is the shape a
    wrong copy breaks: an entry that owed *both* ``issue`` and ``item`` made every
    file the writer emitted a permanent refusal, since no verb can rewrite an
    artifact the arbiter faults and the writer will not open.

    So the shapes are driven through both sides here, on the shared table, and the
    two verdicts are required to agree in both directions: what one refuses the other
    must refuse, and what one calls clean the other must call clean.
    """
    from harness_module import load_package_module

    schema = load_package_module("orderschema")
    arbiter = load_package_module("census_ordering")

    def _iso(text):
        """A UTC stamp parses; a stamp with no offset does not.

        The arbiter takes the parse as an argument because the census's own ``_parse_iso``
        is the census's, and the two differ on purpose: a bare time names no instant, so
        the ordering group refuses it exactly as ``orderschema.parse_confirmed`` does. A
        stub that accepted one would hide the drift this test exists to catch.
        """
        import datetime
        if not text.endswith("Z") and "+" not in text:
            return None
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))

    for label, text in sorted(CLEAN_SHAPES.items()):
        value = json.loads(text)
        assert schema.problems(value) == [], f"{label}: the writer refuses: " \
                                             f"{schema.problems(value)}"
        assert arbiter.order_problems(value, _iso, lambda _t: True) == [], \
            f"{label}: the arbiter faults what the writer emits: " \
            f"{arbiter.order_problems(value, _iso, lambda _t: True)}"

    for label, (text, _needle) in sorted(MALFORMED_SHAPES.items()):
        try:
            value = json.loads(text)
        except ValueError:
            continue  # a document no JSON reader parses is refused by both readers
        writer = schema.problems(value)
        census = arbiter.order_problems(value, _iso, lambda _t: True)
        assert bool(writer) == bool(census), \
            f"{label}: writer={writer} census={census}"
