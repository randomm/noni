"""The ``intent`` class's ``cannot-tell`` rows: every read this run could not make.

The class's own promise is that a symlinked, non-regular, unreadable or uncited-by-
history intent is a ``cannot-tell`` warn and never a crash and never silence. Every
state that can hand the class a fault is asserted here, whether the fault came from
the file's own bytes, the directory above it, a record it cites, or a path the
filesystem will not describe at all.

Split out of ``tests/test_census_intent_class.py``, which keeps the shape and
citation rows; the builders and runners are in ``tests/intent_fixtures.py``.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest
from _harness import SRC
from intent_fixtures import (
    RECORD_ID,
    BlindListing,
    _rows,
    _run,
    commit_intent,
    findings_of,
    install_intent,
    intent_kind_answers,
    record,
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
    """The source of the module that owns the intent class.

    Two of this suite's faults are not portable filesystem states (see
    :func:`intent_kind_answers`), and the census runs as a subprocess, so a
    monkeypatch cannot reach the reader either. What is left is to pin the handling
    itself: a reader that stopped catching the fault a symlink loop raises, or that
    asked for the root-relative identifier only after the read that can fault, fails
    here and fails at the line that regressed.
    """
    import noni.census_intent

    return Path(noni.census_intent.__file__).read_text(encoding="utf-8")


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


def test_a_symlink_at_the_cited_record_path_is_cannot_tell(tmp_path):
    """A planted link at the cited record path decides nothing.

    The link's target holds a record the class would have called
    ``uncited ... the record is superseded`` (exit 51) had it been read: the
    census classifies the cited path with its own classifier before any open, so
    the bytes behind the link are never opened and never become a verdict on the
    intent. The row names the cited id and the census's classification words, and
    quotes no byte of, and no path to, what stands behind the link.
    """
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo)
    record_path = repo / "noni" / "decisions" / f"{RECORD_ID}.json"
    outside = tmp_path / "outside-record.json"
    outside.write_text(json.dumps(record(status="superseded",
                                        supersedes=RECORD_ID)),
                       encoding="utf-8")
    record_path.unlink()
    record_path.symlink_to(outside)
    code, rows, _, _ = _run(repo)
    # The ledger group reports its own "record is unreadable: path is a symlink"
    # row beside this one, and that row is correct existing behaviour; this
    # assertion is the intent class's own row and nothing else.
    intent_rows = [row for row in rows if row["check"] == "intent"]
    assert subjects(intent_rows) == ["cannot-tell"]
    assert intent_rows[0]["severity"] == "warn"
    assert code == 0
    # No byte of the target's content, and no path to it, reaches the row.
    row_text = json.dumps(intent_rows[0])
    assert "superseded" not in row_text
    assert "outside-record" not in row_text
    assert str(outside) not in row_text
    assert RECORD_ID in intent_rows[0]["message"]


def test_a_dangling_symlink_at_the_cited_record_path_is_cannot_tell(tmp_path):
    """A link that goes nowhere is not a record that is not there.

    ``read_bytes`` on a dangling link raises ``ENOENT``, which is the errno the
    absence branch answers with, so a path this run never opened was reported as
    ``uncited ... which no file under noni/decisions/ carries`` at exit 51: a
    verdict on the direction, drawn from a path the census had not classified.
    The classification runs first, so the link is a ``cannot-tell`` warn and the
    absence branch never sees it.
    """
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo)
    record_path = repo / "noni" / "decisions" / f"{RECORD_ID}.json"
    record_path.unlink()
    record_path.symlink_to(tmp_path / "no-such-record.json")
    code, rows, _, _ = _run(repo)
    intent_rows = [row for row in rows if row["check"] == "intent"]
    assert subjects(intent_rows) == ["cannot-tell"]
    assert intent_rows[0]["severity"] == "warn"
    assert code == 0
    row_text = json.dumps(intent_rows[0])
    assert "no-such-record" not in row_text


def test_a_symlink_to_a_directory_at_the_cited_record_path_is_cannot_tell(tmp_path):
    """A link whose target is a directory is the same state, not an EISDIR accident.

    Unreadable, and not absent: the row is the classification's, whatever the
    errno a read would have raised would have been.
    """
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo)
    record_path = repo / "noni" / "decisions" / f"{RECORD_ID}.json"
    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()
    (outside_dir / f"{RECORD_ID}.json").write_text(
        json.dumps(record(status="superseded", supersedes=RECORD_ID)),
        encoding="utf-8")
    record_path.unlink()
    record_path.symlink_to(outside_dir)
    code, rows, _, _ = _run(repo)
    intent_rows = [row for row in rows if row["check"] == "intent"]
    assert subjects(intent_rows) == ["cannot-tell"]
    assert intent_rows[0]["severity"] == "warn"
    assert code == 0
    assert "outside-dir" not in json.dumps(intent_rows[0])


def test_a_directory_at_the_cited_record_path_is_cannot_tell(tmp_path):
    """A directory at the cited path stays a ``cannot-tell`` warn at exit 0.

    It was one before this fix too, by errno accident (``read_bytes`` on a
    directory raises ``EISDIR``, which is not an absence). Now it arrives by
    classification, which is why the row names the census's own words instead of
    the kernel's.
    """
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo)
    record_path = repo / "noni" / "decisions" / f"{RECORD_ID}.json"
    record_path.unlink()
    record_path.mkdir()
    code, rows, _, _ = _run(repo)
    intent_rows = [row for row in rows if row["check"] == "intent"]
    assert subjects(intent_rows) == ["cannot-tell"]
    assert intent_rows[0]["severity"] == "warn"
    assert code == 0


def test_the_cited_record_link_survives_a_filter_that_named_no_intent_class(tmp_path):
    """A run whose filter named no intent class still reports the planted link.

    The row is about the artifact the class was asked to read, so it is marked
    whole-artifact: without the marker the run printed no intent row at all and
    exited 0, which is a clean verdict bought by a path nobody opened.
    """
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo)
    record_path = repo / "noni" / "decisions" / f"{RECORD_ID}.json"
    outside = tmp_path / "outside-record.json"
    outside.write_text(json.dumps(record(status="superseded",
                                        supersedes=RECORD_ID)),
                       encoding="utf-8")
    record_path.unlink()
    record_path.symlink_to(outside)
    rows = _rows(repo, "--only", "session-double")
    intent_rows = [row for row in rows if row["check"] == "intent"]
    assert subjects(intent_rows) == ["cannot-tell"]
    assert intent_rows[0]["severity"] == "warn"


def test_strict_promotes_the_cited_record_link_row(tmp_path):
    """``--strict`` promotes the run's blindness, as it promotes every cannot-tell.

    The row is the intent class's own cannot-tell, so it leaves the run at 51 under
    ``--strict`` and at 0 without it: the same exit rule the intent-file row obeys.
    """
    repo = repo_with_record(tmp_path)
    install_intent(repo)
    commit_intent(repo)
    record_path = repo / "noni" / "decisions" / f"{RECORD_ID}.json"
    outside = tmp_path / "outside-record.json"
    outside.write_text(json.dumps(record(status="superseded",
                                        supersedes=RECORD_ID)),
                       encoding="utf-8")
    record_path.unlink()
    record_path.symlink_to(outside)
    assert _run(repo)[0] == 0
    assert _run(repo, "--strict")[0] == 51


def test_the_cited_record_is_classified_before_it_is_read(intent_class):
    """The order is the invariant, so it is pinned at the line that owns it.

    A fixture cannot state "no open was attempted" — a reader that classified and
    then opened anyway passes every filesystem assertion above on a machine whose
    target is readable. Pinned at the source instead, alongside the loop test:
    the classifier is asked of the cited path, the non-regular answer returns
    before the read, and the read takes a path the classification already decided.
    """
    classify = intent_class.index('file_kind(record)')
    read = intent_class.index("record.read_bytes()")
    assert classify < read, (
        "the cited decision record is read before the census's classifier is "
        "asked of it, so a planted link is followed and its bytes decide the "
        "intent verdict"
    )
    gate = intent_class.index("        return\n", classify)
    assert gate < read, (
        "a cited record the classifier did not call regular still reaches the "
        "read, so the classification is decoration and not a refusal"
    )
    assert "record.read_bytes()" in intent_class, (
        "the cited-record reader stopped taking the path the classification "
        "decided, so it can open a path nobody classified"
    )


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
    gate = (SRC / "noni" / "census_run.py").read_text(encoding="utf-8")
    body = gate[gate.index("def _intent_present"):gate.index("def _run(")]
    assert "_file_kind" in body, "the gate stopped asking the census's classifier"
    assert ".exists()" not in body, (
        "the intent gate re-derives the path state itself: a link it follows and a "
        "parent it cannot read both answer for a path the class would have reported"
    )


def test_a_symlink_loop_at_the_intent_path_is_cannot_tell(intent_class):
    """A loop is a fault the class owns, not a run that ends.

    ``read_bytes`` on a chain of links raises ``RuntimeError`` (``pathlib`` turns an
    ``ELOOP`` it cannot attach an errno to into its own type), and no layer of this
    group used to catch it: the class's own promise -- a symlinked, non-regular or
    unreadable file is a ``cannot-tell``, never a crash -- did not hold for the one
    link shape that loops.

    Pinned at the source rather than the filesystem: whether a loop reaches the run
    through the classifier, the reader, or not at all depends on how the link was
    written and on the filesystem beneath it, so a fixture could pass without the
    handling being reached. The two assertions below are the handling and the order
    it happens in -- the reader catches the loop's own type, and the path is named
    before the verdict on it, so the row that reports the fault always has an
    artifact to name.
    """
    assert "except (OSError, RuntimeError) as exc:" in intent_class, (
        "the intent reader stopped catching the fault a symlink loop raises"
    )
    read_bytes = intent_class.index("raw = intent.read_bytes()")
    asked_rel = intent_class.index("rel = rel_to_root(root, intent)")
    assert asked_rel < read_bytes, (
        "the root-relative identifier is asked for only after the read the fault "
        "can come from, so a run that could not read the file has no artifact to "
        "name in its cannot-tell row"
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
