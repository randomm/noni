"""The deep paths of order.py: concurrency, the lock, and a git that lies.

Extracted from the order writer suite: the cases a single happy-path run never
reaches, driven through in-process seams and a stubbed git."""

import json
import subprocess
import sys

from _harness import (
    CENSUS,
    _git,
    git_pin_date,
    subprocess_env,
)
from order_fixtures import (
    BASELINE_ID,
    FIXTURE,
    NOW,
    ORDER_REL,
    OTHER_ID,
    STAMP,
    _assert_census_clean,
    _canonical,
    _census_ordering,
    _commit_record,
    _entry,
    _order,
    _order_path,
    _orderstate_module,
    _read,
    _repo,
    _schema_module,
    _seed,
)
from ordering_shapes import (
    DEEP,
    MALFORMED_SHAPES,
    _deep,
    _deep_artifact,
    commit_artifact,
    writer_text,
)
from parent_link_fixtures import (
    assert_outside_untouched,
    plant_parent_link,
    write_outside_decoy,
)

# ``json.loads`` walks nesting on the interpreter's own stack, so a document past
# the recursion budget raises RecursionError -- not a ValueError, and so not
# caught by the arms the writer's two JSON reads already had. Where the budget
# runs out depends on the interpreter: 3.11 gives up near
# ``sys.getrecursionlimit()`` (default 1000: measured to break at about 990
# levels under pytest), later builds go on to a few thousand before the C stack
# itself gives out, so the RecursionError arms are reachable on 3.11 and not
# merely theoretical. Before the bound, one such file at either path turned a
# writer run into a traceback. The ``DEEP`` / ``_deep`` / ``_deep_artifact``
# shapes live in ``tests/ordering_shapes.py``, the module the census's ordering
# suite reads too; this side passes its own ``STAMP``.


def test_a_deeply_nested_artifact_is_refused_at_four_and_not_a_traceback(tmp_path):
    """The writer's artifact read answers the pathological file with its existing
    malformed refusal (exit 4), leaving the operator's bytes exactly as they
    were: a crash would be worse than a refusal, and an overwrite worse still."""
    repo = _repo(tmp_path)
    before = _deep_artifact(STAMP)
    _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
    _order_path(repo).write_text(before, encoding="utf-8")
    proc = _order(repo, "confirm", "--now", NOW)
    combined = proc.stdout + proc.stderr
    assert "RecursionError" not in combined, combined[-2000:]
    assert proc.returncode == 4, (proc.returncode, combined[-2000:])
    assert "not valid JSON" in combined, combined[-2000:]
    assert _order_path(repo).read_text(encoding="utf-8") == before, \
        "a refused run must leave the artifact byte-identical"


def test_a_deeply_nested_decision_record_refuses_the_run_at_three(tmp_path):
    """The record read is the writer's other JSON read, and it shares the fate of
    any record it cannot read: exit 3, the environment fault, with its own fixed
    wording -- never a traceback and never an answer invented from nothing."""
    state = _orderstate_module()
    record = tmp_path / "noni" / "decisions" / "2026-10-01-baseline.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(_deep(), encoding="utf-8")
    found, refusal = state.read_record(record, 3, 4)
    assert found is None, found
    assert refusal is not None
    code, (headline, _hint) = refusal
    assert code == 3, refusal
    assert "not readable JSON" in headline, headline


def test_the_writer_walks_a_deep_value_without_recursing():
    """The writer's copy of the non-finite walk is iterative with its own stack.

    The value is assembled by hand because no decoder can build it: that is the
    shape a reader must survive, and a recursive walk answers the question by
    dying inside the read.
    """
    schema = _schema_module()
    deep: list = []
    cursor = deep
    for _ in range(DEEP):
        child: list = []
        cursor.append(child)
        cursor = child
    cursor.append("x")
    assert schema.holds_non_finite(deep) is False
    cursor[-1] = float("inf")
    assert schema.holds_non_finite(deep) is True


def test_the_writer_refuses_a_deep_document_before_the_decoder_overflows():
    """The writer's read refuses the pathological document itself.

    ``json.loads`` walks nesting on the interpreter's own stack and gives up at a
    depth the build sets: on 3.11 that is near ``sys.getrecursionlimit()``,
    measured to break just under the default 1000, so the ``RecursionError`` arms
    of the two reads are reachable there and not merely theoretical. Catching
    more exception types is still not the fix: the run is honest only if it never
    reaches the overflow, so the document that proves the mechanism is one the
    standard reader can still build on every supported interpreter -- past this
    product's bound, well inside the interpreter's budget. The bound is what
    answers, raising the ``ValueError`` the two reads already catch instead of
    leaving a ``RecursionError`` that would slip past them and kill the run.
    """
    schema = _schema_module()
    # Above the product's bound, below the depth at which this interpreter's own
    # decoder gives up. That ceiling is a property of the build -- measured just
    # under the default limit of 1000 on 3.11, and several thousand on 3.12 and
    # 3.13 -- so twice the bound sits in that window on every supported version.
    # The assertion is the premise: a host that lowers the recursion limit below
    # the decoder's reach says so here, not on the line that reads the document.
    inside = schema.MAX_DEPTH * 2
    budget = sys.getrecursionlimit()
    assert inside > schema.MAX_DEPTH, (
        f"{inside} levels is not past the bound of {schema.MAX_DEPTH}, so the "
        "bound is not what answered")
    assert inside < budget, (
        f"{inside} levels is not inside the recursion budget of {budget}")
    body = "[" * inside + "1" + "]" * inside
    assert json.loads(body), "the standard reader must still be able to build this"
    try:
        schema.load_json_checked(("{\"a\": " + body + "}").encode())
    except ValueError as e:
        assert str(schema.MAX_DEPTH) in str(e), \
            f"refused for another reason, so the bound is not what answered: {e}"
    else:
        raise AssertionError("a document nested past the bound was accepted")


def test_the_writer_refuses_an_artifact_that_states_a_key_twice(tmp_path):
    """The artifact read refuses a repeated key before the shape rules or the
    canonical-bytes comparison are reached.

    Last-wins is an answer no line of the file supports: a document that states
    ``schema`` twice, once wrongly, is not a document that states it once
    correctly. The strict reader is what refuses it.
    """
    state = _orderstate_module()
    artifact = tmp_path / ORDER_REL
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text('{"schema": "noni.order/1", "schema": "nope", '
                        '"entries": []}\n', encoding="utf-8")
    read = state.read_order(artifact)
    assert isinstance(read, state.OrderRefused), read
    assert "not valid JSON" in read.headline, read.headline


def test_the_writer_refuses_a_decision_record_that_states_a_key_twice(tmp_path):
    """A record whose ``status`` is stated twice is not a record whose status is
    known: whichever line the standard reader kept would decide whether an order
    still stands. The read refuses it as the unreadable-record fault it is."""
    state = _orderstate_module()
    record = tmp_path / "noni" / "decisions" / "2026-10-01-baseline.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text('{"id": "2026-10-01-baseline", "status": "decided", '
                      '"status": "superseded", "supersedes": null}\n', encoding="utf-8")
    found, refusal = state.read_record(record, 3, 4)
    assert found is None, found
    assert refusal is not None
    code, (headline, _hint) = refusal
    assert code == 3, refusal
    assert "not readable JSON" in headline, headline


def test_the_writer_still_reads_the_bytes_it_writes(tmp_path):
    """The counter-case to the two refusals above: the strictness must not be a
    bug, so the canonical artifact and a well-formed record both still read."""
    state = _orderstate_module()
    artifact = tmp_path / ORDER_REL
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(_canonical([_entry(7, BASELINE_ID)]), encoding="utf-8")
    read = state.read_order(artifact)
    assert isinstance(read, state.OrderOk), read
    assert [entry["issue"] for entry in read.entries] == [7]
    record = tmp_path / "noni" / "decisions" / "2026-10-01-baseline.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text('{"id": "2026-10-01-baseline", "status": "decided", '
                      '"supersedes": null}\n', encoding="utf-8")
    found, refusal = state.read_record(record, 3, 4)
    assert refusal is None, refusal
    assert found is not None and found["status"] == "decided"


def test_a_writer_run_leaves_the_ordering_census_clean(tmp_path):
    """The contract the two halves share: what the writer writes, the arbiter
    accepts. Every verb in turn, then the census."""
    repo = _repo(tmp_path)
    # ``add`` is the second commit in the tree and ``move --decision`` the third, so the
    # record exists before any run cites it: each fixture step is itself a commit, and
    # HEAD read before them would not be HEAD after them.
    _commit_record(repo, OTHER_ID, "decided", None)
    assert _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW).returncode == 0
    assert _order(repo, "add", "8", "--at", "1", "--decision", BASELINE_ID,
                    "--now", NOW).returncode == 0
    # The queue is now 8 then 7, and the re-citation reaches 7 by its number: a move of a
    # decision changes no position, so the entry is found at the place the last move put
    # it and stays there.
    assert _order(repo, "move", "7", "--to", "2", "--now", NOW).returncode == 0
    # A re-citation, the other thing ``move`` now writes (issue #134): the entry keeps
    # its place and names a different record, and the arbiter still calls the order
    # clean -- an entry citing a record the ledger holds is well-formed either way.
    assert _order(repo, "move", "7", "--decision", OTHER_ID, "--now", NOW).returncode == 0
    by_issue = {entry["issue"]: entry for entry in _read(repo)["entries"]}
    assert by_issue[7]["decision"] == OTHER_ID, by_issue
    assert by_issue[8]["decision"] == BASELINE_ID, by_issue
    assert [entry["issue"] for entry in _read(repo)["entries"]] == [8, 7], _read(repo)
    assert _order(repo, "confirm", "--now", NOW).returncode == 0
    assert _order(repo, "remove", "8", "--now", NOW).returncode == 0
    _assert_census_clean(repo, "the full verb round trip")


def test_the_committed_fixture_is_the_shape_the_writer_accepts(tmp_path):
    """The shared fixture is the documented artifact: it is valid JSON, the
    census calls it clean, and the writer extends it rather than refusing it.
    A fixture that only the writer liked would keep the arbiter's half of the
    contract unpinned."""
    repo = _repo(tmp_path)
    body = FIXTURE.read_text(encoding="utf-8")
    _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
    _order_path(repo).write_text(body, encoding="utf-8")
    _git(repo, "add", ORDER_REL)
    git_pin_date(repo, NOW, "commit", "-q", "-m", "direction: seed from the fixture")
    _assert_census_clean(repo, "the committed fixture")
    assert _order(repo, "confirm", "--now", NOW).returncode == 0


def test_the_fixture_bytes_are_the_writer_canonical_form(tmp_path):
    """The fixture is byte-identical to what the writer would emit for the same
    entries, so it can serve as the canonical-form reference in either
    direction."""
    body = FIXTURE.read_text(encoding="utf-8")
    value = json.loads(body)
    assert _schema_module().order_bytes(value).decode() == body


def test_the_ordering_census_reports_what_the_writer_refused(tmp_path):
    """One shape each, on both sides of the contract: the census reports as
    ``ordering-malformed`` exactly what the writer refuses to extend, and the
    row names the same reason in its own words. A file the writer refuses and
    the census calls clean is a file nobody would notice had rotted.

    The list is the shared table, plus the one shape the table cannot carry:
    a citation whose record is absent from the ledger is well-formed JSON and
    refused for a reason only the ledger can answer (the census's own
    ``ordering-malformed`` row for it lives in tests/test_census_ordering_malformed.py).
    """
    extra = {
        "a decision that matches no record": '{"schema": "noni.order/1", "entries": '
                                             '[{"issue": 3, "decision": '
                                             '"2026-01-01-ghost", "confirmed": '
                                             '"2026-10-26T00:00:00Z"}]}',
    }
    shapes = {label: (body, _needle) for label, (body, _needle) in MALFORMED_SHAPES.items()}
    shapes.update({label: (body, None) for label, body in extra.items()})
    for index, (label, (body, _needle)) in enumerate(sorted(shapes.items())):
        repo = _repo(tmp_path, f"arb-{index}")
        commit_artifact(repo, body)
        writer = _order(repo, "confirm", "--now", NOW)
        assert writer.returncode == 4, f"{label}: writer exit {writer.returncode}"
        code, rows, output = _census_ordering(repo)
        assert code == 15, f"{label}: census exit {code}: {output}"
        assert [r["check"] for r in rows] == ["ordering-malformed"], f"{label}: {rows}"


def test_every_malformed_shape_is_refused_by_the_writer_and_reported_by_the_census(
        tmp_path):
    """One table, both sides, no drift: the writer refuses (exit 4) and the
    census reports (exit 15) the same shapes, with the same reason named on both
    sides.

    The two rule sets live in two files on purpose -- a writer's reader and an
    arbiter's reader -- and that is how they part company: the census's
    ``_parse_iso`` read a bare stamp as UTC while the writer's
    ``orderschema.parse_confirmed`` refused it, so a committed artifact nobody
    could repair sat clean under the census and un-writable under the writer.
    A needle is a fragment the refusal and the row must both carry, so a rule
    implemented on one side only fails here rather than in an operator's tree.
    """
    # A needle of None is a shape the two sides reach by different routes; its
    # verdict (exit code, class, untouched file) is pinned in the two tests above.
    drift = {label: (body, needle) for label, (body, needle) in MALFORMED_SHAPES.items()
             if needle is not None}
    for index, (label, (body, needle)) in enumerate(sorted(drift.items())):
        repo = _repo(tmp_path, f"drift-{index}")
        commit_artifact(repo, body)
        writer = _order(repo, "confirm", "--now", NOW)
        assert writer.returncode == 4, f"{label}: writer exit {writer.returncode}"
        assert needle in writer_text(writer), \
            f"{label}: the writer refused for another reason: {writer_text(writer)}"
        code, rows, output = _census_ordering(repo)
        assert code == 15, f"{label}: census exit {code}: {output}"
        assert [r["check"] for r in rows] == ["ordering-malformed"], f"{label}: {rows}"
        assert needle in rows[0]["message"], f"{label}: {rows[0]}"


def test_a_stale_entry_is_reported_by_the_census_and_cleared_by_confirm(tmp_path):
    """The staleness half of the contract, end to end: a confirmed time past the
    threshold is a warn at 45, --strict promotes it, and the writer's confirm
    clears the row. The threshold is the ordering default (30 days) when
    --stale-after was not given, and the caller's number when it was."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID, "2026-10-15T00:00:00Z"))
    code, rows, _ = _census_ordering(repo)
    assert code == 0 and rows == [], (
        f"a 12-day-old entry is inside the 30-day ordering default: {rows}")
    code, rows, _ = _census_ordering(repo, "--stale-after", "7")
    # The census's own rule, re-asserted here: a warn-class row never moves the
    # exit code on its own, so the row is the report and 0 is the verdict.
    assert code == 0, code
    assert [r["check"] for r in rows] == ["ordering-stale"], rows
    assert rows[0]["severity"] == "warn"
    assert rows[0]["subject"] == "#7", rows[0]
    code, rows, _ = _census_ordering(repo, "--stale-after", "7", "--strict")
    assert code == 45 and rows[0]["severity"] == "fail", (code, rows)
    assert _order(repo, "confirm", "7", "--now", NOW).returncode == 0
    _assert_census_clean(repo, "confirm of the stale entry", "--stale-after", "7")


def test_a_closed_issue_is_reported_and_removed_by_the_writer(tmp_path):
    """Closed state reaches the census only through --issue-state (the census
    never contacts a tracker): the row is a warn at 46, the writer's remove
    clears it, and an issue the map omits gets a cannot-tell row rather than
    silence."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID), _entry(8, BASELINE_ID))
    state = repo / "issue-state.json"
    state.write_text(json.dumps({"7": "closed", "9": "open"}), encoding="utf-8")
    code, rows, _ = _census_ordering(repo, "--issue-state", str(state))
    assert code == 0, code
    assert [(r["check"], r["subject"]) for r in rows] == [
        ("ordering-closed", "#7"), ("ordering-closed", "#8")], rows
    assert "closed: issue 7" in rows[0]["message"], rows[0]
    assert rows[1]["message"].startswith("cannot-tell:"), rows[1]
    assert _order(repo, "remove", "7", "--now", NOW).returncode == 0
    _seed_entries = _read(repo)["entries"]
    assert [e["issue"] for e in _seed_entries] == [8]
    # Only the cannot-tell row is left, and the class stays a warn at exit 0.
    code, rows, _ = _census_ordering(repo, "--issue-state", str(state))
    assert code == 0 and [r["subject"] for r in rows] == ["#8"], (code, rows)


def test_the_closed_class_says_so_when_no_state_file_is_given(tmp_path):
    """The census never contacts a tracker, so without --issue-state the closed
    question is not asked. A run that simply printed nothing would read as
    'every ordered issue is open', so the human-readable run says once that the
    class was not evaluated; the --json stream stays findings-only."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID))
    proc = subprocess.run(
        [sys.executable, str(CENSUS), "--repo", str(repo), "--now", NOW,
         "--only", "ordering-closed"],
        capture_output=True, text=True, env=subprocess_env(), timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ordering-closed was not evaluated" in proc.stdout, proc.stdout
    assert "never contacts a tracker" in proc.stdout, proc.stdout
    # The same run in --json mode: no notice line in the NDJSON stream, and the class's
    # own row. Issue #148 made the unasked question a verdict the exit code can carry, so
    # a rowless stream is no longer what this state prints: warn without --strict (hence
    # code 0, which is the half that keeps this test from being a pass on a run that
    # failed its own check), and pinned to the artifact rather than an issue, because the
    # fact is about the run and not about any one ordered issue.
    code, rows, _ = _census_ordering(repo)
    assert code == 0, (code, rows)
    assert [(r["check"], r["severity"], r["subject"]) for r in rows] == [
        ("ordering-closed", "warn", ORDER_REL)], rows


# --- A linked ledger above the citation read (issue #104) --------------------
#
# ``--decision`` is answered by reading ``noni/decisions/<id>.json``, and the
# parent of that ledger was the one path the writer never inspected: ``is_dir()``
# and ``mkdir(parents=True)`` both follow links, so a committed ``noni`` that is a
# link to a directory outside the state repository let the read reach bytes nobody
# committed here, and the committed route then heard git object to a path "beyond a
# symbolic link". The two tests below are the read and the run: the reader's own
# verdict, and the writer refusing the shape before it opens anything.


def test_a_ledger_reached_through_a_linked_parent_is_read_by_the_writer(tmp_path):
    """The leak, pinned: the reader follows the link and answers from outside bytes.

    This is not a refusal test -- ``orderstate.read_record`` takes one path and the
    guard above it asks the directory question, not the file question. It is here
    because it says what the guard is holding back: a record whose committed bytes
    stand outside the state repository still reads as a decided record, so a writer
    that asked only its leaf would cite a decision nobody made here.
    """
    state = _orderstate_module()
    repo = _repo(tmp_path / "reader")
    outside = tmp_path / "outside-reader"
    plant_parent_link(repo, outside, "noni")
    linked = repo / "noni" / "decisions" / f"{BASELINE_ID}.json"
    assert linked.is_file(), "the fixture moved the committed record out of the tree"

    found, refusal = state.read_record(linked, 3, 4)

    assert refusal is None, refusal
    assert found is not None and found["status"] == "decided"
    assert not str(linked).startswith(str(outside)), (
        "the fixture's link must be the thing that resolves, not the path the test wrote")


def test_a_run_citing_a_record_behind_a_linked_ledger_is_refused_before_the_read(tmp_path):
    """The same tree, run through the writer: exit 2 naming ``noni``, nothing read.

    The outside tree holds the decoy at the record's own name and at the artifact's,
    so both halves of the old fault -- the read that reached outside bytes and the
    write that landed there -- are checked against bytes the fixture wrote. The
    committed route is the one under test (no ``--no-commit``): it is where git used
    to answer with its pathspec error, after the bytes had already gone out.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    outside = tmp_path / "outside"
    plant_parent_link(repo, outside, "noni")
    write_outside_decoy(outside, "noni", "order.json")

    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)

    text = proc.stdout + proc.stderr
    assert proc.returncode == 2, text
    assert "symlink" in text.lower(), text
    assert "noni" in text, text
    assert "pathspec" not in text.lower() and "fatal:" not in text.lower(), text
    assert (repo / "noni").is_symlink(), "the run unmade the planted link"
    assert_outside_untouched(outside, "noni", "order.json")
