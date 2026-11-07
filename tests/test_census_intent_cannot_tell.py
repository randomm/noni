"""The ``intent`` class's ``cannot-tell`` rows: every read this run could not make.

The class's own promise is that a symlinked, non-regular, unreadable or uncited-by-
history intent is a ``cannot-tell`` warn and never a crash and never silence. Every
state that can hand the class a fault is asserted here, whether the fault came from
the file's own bytes, the directory above it, or a path the filesystem will not
describe at all.

Split out of ``tests/test_census_intent_class.py``, which keeps the shape and
citation rows; the states of the record a citation names are in
``tests/test_census_intent_cited_record.py``. The builders and runners are in
``tests/intent_fixtures.py``, the structure pins' helpers in
``tests/intent_class_ast.py``.
"""

from __future__ import annotations

import contextlib

import pytest
from _harness import SRC

# The reader's structure pins read the module's syntax tree; the helpers live in
# ``intent_class_ast`` and the fixtures are decorated here, where pytest sees them.
from intent_class_ast import (
    assignment_line,
    call_line,
    excepts_line,
    intent_class_text,
    intent_module,
)
from intent_fixtures import (
    RECORD_ID,
    BlindListing,
    _run,
    commit_intent,
    findings_of,
    install_intent,
    intent_kind_answers,
    repo_with_record,
    run_census_in_process,
    subjects,
    write_intent,
)


@contextlib.contextmanager
def blind_listing(monkeypatch):
    """Take the run's ledger listing away, so the intent group reads it itself."""
    import noni.census as census

    monkeypatch.setattr(census, "_ledger_probe", lambda ledger: BlindListing())
    yield


@pytest.fixture
def intent_class():
    """The source of the module that owns the intent class; see the helper's doc."""
    return intent_class_text()


@pytest.fixture
def intent_ast(intent_class):
    """The same module parsed, for the pins that are about structure, not spelling."""
    return intent_module(intent_class)



def test_a_record_the_run_could_not_read_is_cannot_tell(tmp_path, monkeypatch):
    """An unreadable record is this run's blindness, never a verdict on the intent."""
    repo = repo_with_record(tmp_path)
    path = repo / "noni" / "decisions" / f"{RECORD_ID}.json"
    path.chmod(0o000)
    try:
        install_intent(repo)
        commit_intent(repo)
        with blind_listing(monkeypatch):
            code, rows, _, _ = _run(repo)
    finally:
        path.chmod(0o644)
    # The ledger group reports its own unreadable-directory row beside this one;
    # this test's assertion is the intent class's own row, and it is a warn.
    intent_rows = [row for row in rows if row["check"] == "intent"]
    assert subjects(intent_rows) == ["cannot-tell"]
    assert intent_rows[0]["severity"] == "warn"
    assert code == 0


def test_unreadable_bytes_in_the_file_are_cannot_tell(tmp_path):
    repo = repo_with_record(tmp_path)
    path = install_intent(repo)
    commit_intent(repo)
    path.write_bytes(b"\xff\xfe not utf-8 at all\n")
    code, rows, _, _ = _run(repo)
    # The ledger group reports its own unreadable-directory row beside this one;
    # this test's assertion is the intent class's own row, and it is a warn.
    intent_rows = [row for row in rows if row["check"] == "intent"]
    assert subjects(intent_rows) == ["cannot-tell"]
    assert intent_rows[0]["severity"] == "warn"
    assert code == 0


def test_a_symlink_at_the_intent_path_is_cannot_tell(tmp_path):
    repo = repo_with_record(tmp_path)
    target = install_intent(repo)
    body = target.read_text(encoding="utf-8")
    commit_intent(repo)
    target.unlink()
    # The bytes behind the link are the committed shape, so the row under test is
    # the classification of the path and not a missing-file answer.
    outside = tmp_path / "outside.md"
    outside.write_text(body, encoding="utf-8")
    target.symlink_to(outside)
    code, rows, _, _ = _run(repo)
    # The ledger group reports its own unreadable-directory row beside this one;
    # this test's assertion is the intent class's own row, and it is a warn.
    intent_rows = [row for row in rows if row["check"] == "intent"]
    assert subjects(intent_rows) == ["cannot-tell"]
    assert intent_rows[0]["severity"] == "warn"
    assert code == 0


def test_the_run_survives_a_path_it_cannot_classify(tmp_path, monkeypatch):
    """The gate and the class agree, and neither crashes, on a path the filesystem
    will not describe.

    The gate opens the group for anything the census's classifier does not call
    absent -- the same answer the rows are built from -- so the input this run
    cannot stat has to come out as the class's own ``cannot-tell`` row and the exit
    that row's severity decides, whatever the filter named. A gate that re-derived
    the path state for itself (a bare ``Path.exists`` did) reached that ``OSError``
    first and ended a ``--only`` run with a traceback, which both crashed and bought
    back the clean verdict of a run that never opened the file.

    Driven through the classifier rather than a file mode: a directory at ``0o000``
    is readable whenever the suite runs as root, so the mode would test the
    operator's uid and not the run.
    """
    import noni.census as census

    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo)
    monkeypatch.setattr(census, "_file_kind",
                        intent_kind_answers("nonregular", "lstat: Permission denied"))

    code, out, err = run_census_in_process(repo, "--only", "session-double")
    assert findings_of(out, "intent") == [("intent", "cannot-tell", "warn")], out
    assert err == "", "the run's blindness must not reach the operator as a traceback"
    assert code == 0
    # --strict promotes the run's own blindness, as it promotes every cannot-tell.
    assert run_census_in_process(repo, "--only", "session-double",
                                 "--strict")[0] == 51

    # And the gate got that answer from the census's classifier and nowhere else.
    # A bare ``.exists`` is invisible to the patch above (the fault never happens on
    # this machine), so the shape is pinned too: ``Path.exists`` follows links and
    # propagates the ``OSError`` of a parent it cannot read, which is the crash this
    # gate caused and the reason a dangling link read as no read owed.
    # The gate lives in ``census_items_gate.py`` (it moved there when the items group
    # was wired in); the assertion is about the gate itself, not the file that calls it.
    gate = (SRC / "noni" / "census_items_gate.py").read_text(encoding="utf-8")
    body = gate[gate.index("def _intent_present"):]
    body = body[:body.index("\ndef ") + 1]
    assert "_file_kind" in body, "the gate stopped asking the census's classifier"
    assert ".exists()" not in body, (
        "the intent gate re-derives the path state itself: a link it follows and a "
        "parent it cannot read both answer for a path the class would have reported"
    )


def test_a_symlink_loop_at_the_intent_path_is_cannot_tell(intent_ast):
    """A loop is a fault the class owns, not a run that ends.

    ``read_bytes`` on a chain of links raises ``RuntimeError`` (``pathlib`` turns an
    ``ELOOP`` it cannot attach an errno to into its own type), and no layer of this
    group used to catch it: the class's own promise -- a symlinked, non-regular or
    unreadable file is a ``cannot-tell``, never a crash -- did not hold for the one
    link shape that loops.

    Pinned at the syntax tree rather than the filesystem: whether a loop reaches the
    run through the classifier, the reader, or not at all depends on how the link was
    written and on the filesystem beneath it, so a fixture could pass without the
    handling being reached. The two assertions below are the handling and the order
    it happens in -- the reader catches the loop's own type, and the path is named
    before the read that can fault, so the row that reports the fault always has an
    artifact to name. Read off the tree, not the source text: a reworded line moves
    a token and must not be reported as a bare ``ValueError`` from a substring search.
    """
    caught = excepts_line(intent_ast, "check_intent", "RuntimeError")
    read = call_line(intent_ast, "check_intent", "read_bytes")
    assert caught > read, (
        "the intent reader no longer wraps its read of the file in the handler for "
        "the fault a symlink loop raises, so a chain of links ends the census "
        f"instead of earning a cannot-tell row (read on line {read}, handler on "
        f"line {caught})"
    )
    asked_rel = assignment_line(intent_ast, "check_intent", "rel")
    assert asked_rel < read, (
        "the root-relative identifier is computed only after the read that can fault, "
        f"so a run that could not read the file has no artifact to name (identifier "
        f"on line {asked_rel}, read on line {read})"
    )


def test_an_unreadable_ledger_directory_is_cannot_tell(tmp_path):
    """A listing that faulted travels back as a row rather than becoming a
    citation that passed: the ledger read is the citation's only evidence.

    Driven by the file mode rather than a monkeypatch, because the census runs as
    a subprocess: the state under test is the directory the run has to open.
    """
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo)
    ledger = repo / "noni" / "decisions"
    ledger.chmod(0o000)
    try:
        code, rows, _, _ = _run(repo)
    finally:
        ledger.chmod(0o755)
    # The ledger group reports its own unreadable-directory row beside this one;
    # this test's assertion is the intent class's own row, and it is a warn.
    intent_rows = [row for row in rows if row["check"] == "intent"]
    assert subjects(intent_rows) == ["cannot-tell"]
    assert intent_rows[0]["severity"] == "warn"
    assert code == 0


def test_no_commit_touching_the_file_is_cannot_tell(tmp_path):
    """An uncommitted intent has no citation to read, and is not called clean."""
    repo = repo_with_record(tmp_path)
    write_intent(repo)
    code, rows, _, _ = _run(repo)
    # The ledger group reports its own unreadable-directory row beside this one;
    # this test's assertion is the intent class's own row, and it is a warn.
    intent_rows = [row for row in rows if row["check"] == "intent"]
    assert subjects(intent_rows) == ["cannot-tell"]
    assert intent_rows[0]["severity"] == "warn"
    assert code == 0
