"""Every state the cited decision record itself can stand in, and the row each earns.

The intent class answers "does the direction the citation names still stand", and
the answer is built from one path: ``noni/decisions/<id>.json``. Each state that
path can hold — a symlink to an outside file, a dangling link, a link to a
directory, a directory, a fifo, a hardlink — is asserted here, plus the structural
pins (the classifier runs before the read, the read itself refuses a link, the
gate names the kind it accepts) that no filesystem fixture can state.

A link at either directory *above* that path is the same defect one level up and is
asserted in ``tests/test_census_intent_cited_ledger.py``; the intent file's own
faults in ``tests/test_census_intent_cannot_tell.py``; the builders and runners in
``tests/intent_fixtures.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from intent_class_ast import (
    call_line as _call_line,
)
from intent_class_ast import (
    compare_against,
    intent_class_text,
    intent_module,
)
from intent_class_ast import (
    function_source as _function_source,
)
from intent_class_ast import (
    return_line as _return_line,
)
from intent_fixtures import (
    RECORD_ID,
    _intent_rows,
    _json_rows,
    _rows,
    _run,
    record,
    run_census_in_process,
    subjects,
)

# The planted-path builder, named for what it plants rather than for the fixture.
from intent_fixtures import planted_record_link as _planted_record_link


@pytest.fixture
def intent_class():
    """The source of the module that owns the intent class; see the helper's doc."""
    return intent_class_text()


@pytest.fixture
def intent_ast(intent_class):
    """The same module parsed, for the pins that are about structure, not spelling.

    A source-text substring pin constrains how the code is written: renaming a local
    or hoisting a helper breaks it, and an ordering check can pass because a function
    happens to sit below another one. ``lineno`` from the tree constrains the
    behaviour and nothing else.
    """
    return intent_module(intent_class)


def _assert_cannot_tell(intent_rows, code=0):
    """One ``cannot-tell`` warn from the intent class, at the exit that row decides.

    Every test in this file plants a state meant to earn the same row: one row, of
    this class, a warn, and the exit a warn leaves at 0 (the ``--strict`` half is
    asserted separately). Stating it once keeps a row that silently gained a second
    subject, or lost its severity, from passing a test that only looked at the first.
    """
    assert subjects(intent_rows) == ["cannot-tell"], intent_rows
    assert intent_rows[0]["severity"] == "warn", intent_rows
    assert code == 0, f"a cannot-tell warn must leave the run at 0, not {code}"
    return intent_rows[0]


def test_a_symlink_at_the_cited_record_path_is_cannot_tell(tmp_path):
    """A planted link at the cited record path decides nothing.

    The link's target holds a record the class would have called
    ``uncited ... the record is superseded`` (exit 51) had it been read: the
    census refuses the cited path before any open, so the bytes behind the link
    are never opened and never become a verdict on the intent. The row names the
    cited id and the census's classification words, and quotes no byte of, and no
    path to, what stands behind the link.
    """
    outside = tmp_path / "outside-record.json"
    outside.write_text(json.dumps(record(status="superseded",
                                        supersedes=RECORD_ID)),
                       encoding="utf-8")
    repo = _planted_record_link(tmp_path, "planted", target=outside)
    code, rows, _, _ = _run(repo)
    # The ledger group reports its own "record is unreadable: path is a symlink"
    # row beside this one, and that row is correct existing behaviour; this
    # assertion is the intent class's own row and nothing else.
    row = _assert_cannot_tell(_intent_rows(rows), code)
    # No byte of the target's content, and no path to it, reaches the row.
    row_text = json.dumps(row)
    assert "superseded" not in row_text
    assert "outside-record" not in row_text
    assert str(outside) not in row_text
    assert RECORD_ID in row["message"]


def test_a_dangling_symlink_at_the_cited_record_path_is_cannot_tell(tmp_path):
    """A link that goes nowhere is not a record that is not there.

    ``read_bytes`` on a dangling link raises ``ENOENT``, which is the errno the
    absence branch answers with, so a path this run never opened was reported as
    ``uncited ... which no file under noni/decisions/ carries`` at exit 51: a
    verdict on the direction, drawn from a path the census had not classified.
    The refusal comes first, so the link is a ``cannot-tell`` warn and the
    absence branch never sees it.
    """
    repo = _planted_record_link(tmp_path, "dangling", dangling=True)
    code, rows, _, _ = _run(repo)
    _assert_cannot_tell(_intent_rows(rows), code)
    assert "no-such-record" not in json.dumps(_intent_rows(rows)[0])


def test_a_symlink_to_a_directory_at_the_cited_record_path_is_cannot_tell(tmp_path):
    """A link whose target is a directory is the same state, not an EISDIR accident.

    Unreadable, and not absent: the row is the classification's, whatever the
    errno a read would have raised would have been.
    """
    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()
    (outside_dir / f"{RECORD_ID}.json").write_text(
        json.dumps(record(status="superseded", supersedes=RECORD_ID)),
        encoding="utf-8")
    repo = _planted_record_link(tmp_path, "dir-link", target=outside_dir)
    code, rows, _, _ = _run(repo)
    _assert_cannot_tell(_intent_rows(rows), code)
    assert "outside-dir" not in json.dumps(_intent_rows(rows)[0])


def test_a_directory_at_the_cited_record_path_is_cannot_tell(tmp_path):
    """A directory at the cited path stays a ``cannot-tell`` warn at exit 0.

    It was one before this fix too, by errno accident (``read_bytes`` on a
    directory raises ``EISDIR``, which is not an absence). Now it arrives by
    classification, which is why the row names the census's own words instead of
    the kernel's.
    """
    repo = _planted_record_link(tmp_path, "directory", is_dir=True)
    code, rows, _, _ = _run(repo)
    _assert_cannot_tell(_intent_rows(rows), code)


def test_a_superseded_record_behind_a_hardlink_is_reported_not_silent(tmp_path):
    """A hardlink is a state the classifier cannot see, and is not a silent clean.

    ``lstat`` cannot tell a hardlink from an ordinary file, so outside bytes can still
    stand at the cited path and produce an ``uncited`` verdict: that is the limit of
    what any leaf classification reaches, and the limit is stated rather than assumed
    (see the hardlink note in the direction skill). What keeps the state from passing
    unnoticed is the sibling ``ledger-edited`` fail, which compares the working tree
    against the committed blob — the outside bytes are reported, by the class that
    can see them. The run names the ledger group because the plain intent runner
    filters to this class alone.
    """
    outside = tmp_path / "hardlink-target.json"
    outside.write_text(json.dumps(record(status="superseded",
                                        supersedes=RECORD_ID)),
                       encoding="utf-8")
    repo = _planted_record_link(tmp_path, "hardlink", hardlink_to=outside)
    rows = _rows(repo, "--only", "intent", "--only", "ledger-edited")
    intent_rows = _intent_rows(rows)
    assert subjects(intent_rows) == ["uncited"], (
        "a cited record whose bytes come from outside the tree produced neither a "
        f"verdict nor a row: {intent_rows}"
    )
    assert "ledger-edited" in {row["check"] for row in rows}, (
        "the only class that can see outside bytes standing at a record path went "
        "silent, so a hardlink would decide the intent verdict with nothing beside it"
    )


def test_the_cited_record_row_quotes_no_stat_fault_text(tmp_path, monkeypatch):
    """The row quotes the classification, never the classifier's fault text.

    ``census._file_kind`` folds an ``OSError`` from the stat into its problem half,
    and every other row built from such text is passed through the census's bounder.
    This row is built from fixed words instead (see ``_classify_words``), which bounds
    it and keeps a host path out of a report that promises to be path-free without
    depending on the bounder being reached at all.
    """
    import noni.census as census

    repo = _planted_record_link(tmp_path, "fault", is_dir=True)
    long_text = "/home/operator/secret-dir " + "x" * 4000
    real = census._file_kind

    def answer(path, kind="file"):
        if Path(path).name == f"{RECORD_ID}.json":
            return "nonregular", long_text
        return real(path, kind)

    monkeypatch.setattr(census, "_file_kind", answer)
    code, out, err = run_census_in_process(repo, "--only", "intent")
    intent_rows = [row for row in _json_rows(out) if row["check"] == "intent"]
    assert subjects(intent_rows) == ["cannot-tell"]
    assert code == 0
    message = intent_rows[0]["message"]
    assert len(message) <= 300, f"a row past the census's own bound: {message!r}"
    assert "/home/" not in message, f"a host path reached the row: {message!r}"
    assert "xxxx" not in message, f"fault text reached the row: {message!r}"
    assert err == ""


def test_a_cited_record_classified_with_no_problem_names_no_none(tmp_path, monkeypatch):
    """A classifier that named a kind and no problem does not print ``(None)``.

    The tuple the classifier returns has no type that rules the ``None`` half out,
    so the row must supply words of its own rather than interpolating the absence.
    """
    import noni.census as census

    repo = _planted_record_link(tmp_path, "unnamed", is_dir=True)
    real = census._file_kind

    def answer(path, kind="file"):
        if Path(path).name == f"{RECORD_ID}.json":
            return "nonregular", None
        return real(path, kind)

    monkeypatch.setattr(census, "_file_kind", answer)
    code, out, _err = run_census_in_process(repo, "--only", "intent")
    intent_rows = [row for row in _json_rows(out) if row["check"] == "intent"]
    assert subjects(intent_rows) == ["cannot-tell"]
    assert code == 0
    assert "None" not in intent_rows[0]["message"], intent_rows[0]["message"]


def test_the_cited_record_link_survives_a_filter_that_named_no_intent_class(tmp_path):
    """A run whose filter named no intent class still reports the planted link.

    The row is about the artifact the class was asked to read, so it is marked
    whole-artifact: without the marker the run printed no intent row at all and
    exited 0, which is a clean verdict bought by a path nobody opened.
    """
    repo = _planted_record_link(tmp_path, "filter", dangling=True)
    rows = _rows(repo, "--only", "session-double")
    intent_rows = _intent_rows(rows)
    assert subjects(intent_rows) == ["cannot-tell"]
    assert intent_rows[0]["severity"] == "warn"


def test_strict_promotes_the_cited_record_link_row(tmp_path):
    """``--strict`` promotes the run's blindness, as it promotes every cannot-tell.

    The row is the intent class's own cannot-tell, so it leaves the run at 51 under
    ``--strict``: the same exit rule the intent-file row obeys. The unfiltered exit
    is already asserted by every test above, so only the promoted half is asked here.
    """
    repo = _planted_record_link(tmp_path, "strict", dangling=True)
    assert _run(repo, "--strict")[0] == 51


def test_the_cited_record_is_classified_before_it_is_read(intent_ast):
    """The order is the invariant, so it is pinned where the order lives.

    A fixture cannot state "no open was attempted" — a reader that classified and
    then opened anyway passes every filesystem assertion above on a machine whose
    target is readable. Pinned at the syntax tree instead, alongside the loop test:
    inside ``check_intent`` the classifier is asked of the cited path, a ``return``
    follows that answers the non-regular case, and only then is the reader called.

    Pinned by ``lineno`` rather than by string position: renaming the local, hoisting
    a helper, or moving the reader above ``check_intent`` all preserve the invariant,
    and a substring index breaks on each of them — or keeps passing for the wrong
    reason when the reader merely happens to be defined below the class.
    """
    classify = _call_line(intent_ast, "check_intent", "file_kind")
    refusal = _return_line(intent_ast, "check_intent", after=classify)
    read = _call_line(intent_ast, "check_intent", "_record_body")
    assert classify < refusal < read, (
        "the cited decision record is no longer classified first and refused before "
        "the read: a planted link would be followed, or a path the classifier did not "
        "call regular would still be opened, and its bytes would decide the verdict"
    )


def test_the_cited_record_open_refuses_a_link_without_following_it(intent_ast,
                                                                   intent_class):
    """The refusal lives at the open, not only in the caller's classification.

    A separate ``lstat`` and ``open`` leave an interval in which a path swapped for a
    link after the classification is still followed, so the promise holds only while
    the open itself refuses: ``O_NOFOLLOW``, so a link faults instead of being read,
    and an ``fstat`` of the descriptor that was opened, so nothing non-regular is
    read. Pinned at the syntax tree for the reason above: no fixture can plant the
    swap.
    """
    opened = _call_line(intent_ast, "_record_body", "open")
    inspected = _call_line(intent_ast, "_record_body", "fstat")
    source = _function_source(intent_ast, "_record_body", intent_class)
    assert opened < inspected, (
        "the cited-record reader no longer opens and then inspects the descriptor it "
        "opened, so a link planted after the classification is read through and its "
        "bytes decide the intent verdict"
    )
    assert "O_NOFOLLOW" in source and "S_ISREG" in source, (
        "the cited-record reader lost the flag or the descriptor check that keep a "
        "link and a non-regular path from being read"
    )


def test_the_cited_record_gate_requires_the_readable_kind(intent_ast):
    """The gate names the kind it accepts, so an unknown answer cannot reach the read.

    An allow-list of the two answers this class happens to handle would let a kind the
    classifier gains later fall into the read branch; every other census reader tests
    the kind it refuses. Pinned so the shape cannot silently invert.
    """
    compared = compare_against(intent_ast, "check_intent", "record_kind")
    assert ("NotEq", "regular") in compared, (
        "the cited-record gate no longer requires the classifier to have answered "
        "'regular', so a kind it does not name reaches the read"
    )


def test_the_cited_record_row_marks_itself_whole_artifact(tmp_path):
    """The marker is what stops a filtered run reporting itself clean.

    ``--only`` survival is asserted elsewhere, but survival can also be bought by a
    row that was never filtered at all; the marker is the thing the run's row filter
    reads, so it is asserted on the row the group itself appended. ``_rows`` reads
    the rendered report, which drops the marker, so the group is called directly.
    """
    # The package form: ``tests/census_run.py`` is a fixture module of its own and
    # would win the plain-name import.
    import noni.census as census
    from noni import census_run

    repo = _planted_record_link(tmp_path, "marker", dangling=True)
    found: list[dict] = []
    # The group's own composition, with the census's own row factory reached through
    # the module the census is: ``_row`` is what stamps the marker, so the marker is
    # asserted where it is set rather than after the report stripped it.
    census_run._check_intent(repo / "noni" / "direction" / "intent.md",
                             repo / "noni" / "decisions", repo, False, found)
    intent_rows = _intent_rows(found)
    assert subjects(intent_rows) == ["cannot-tell"], found
    assert intent_rows[0][census.WHOLE_ARTIFACT_KEY] is True, (
        "the cited-record cannot-tell row is not marked whole-artifact, so a run "
        "whose --only named no intent class drops it and reports itself clean"
    )


def test_a_record_swapped_for_a_link_after_classification_is_not_read(tmp_path):
    """A link planted between the classification and the read is refused at the open.

    A check-then-read leaves an interval, and a run that classifies and then opens
    anyway is exactly the state no filesystem fixture can produce — by the time the
    census looks, the path is whatever the planter left. Driven in-process through
    the census's own classifier seam: the classifier answers "regular" for the cited
    path, and only then is the path replaced by a link to an outside file holding a
    superseded record. A reader that trusted the earlier answer would print
    ``uncited ... the record is superseded`` at exit 51 from outside bytes; the
    reader that refuses at the open reports the class's own ``cannot-tell``.
    """
    import noni.census as census
    from noni import census_run

    repo = _planted_record_link(tmp_path, "swap")
    record_path = repo / "noni" / "decisions" / f"{RECORD_ID}.json"
    outside = tmp_path / "swapped-target.json"
    outside.write_text(json.dumps(record(status="superseded",
                                        supersedes=RECORD_ID)),
                       encoding="utf-8")
    real_kind = census._file_kind

    def classify_then_swap(path, kind="file"):
        """Answer for real, then plant the link the classification just approved.

        Positional ``kind``, like the census's own classifier: the class asks this
        seam for the ledger and its parent with ``kind="dir"``, so a keyword-only
        signature would fault before the state under test was reached.
        """
        answer = real_kind(path, kind)
        if Path(path).name == f"{RECORD_ID}.json" and answer[0] == "regular":
            if record_path.is_file():
                record_path.unlink()
                record_path.symlink_to(outside)
        return answer

    found: list[dict] = []
    census._file_kind = classify_then_swap
    try:
        census_run._check_intent(repo / "noni" / "direction" / "intent.md",
                                 repo / "noni" / "decisions", repo, False, found)
    finally:
        census._file_kind = real_kind

    intent_rows = _intent_rows(found)
    assert subjects(intent_rows) == ["cannot-tell"], (
        "a path swapped for a link after the classification was read through, so "
        f"bytes outside the repo decided the intent verdict: {intent_rows}"
    )
    row_text = json.dumps(intent_rows[0])
    assert "superseded" not in row_text
    assert "swapped-target" not in row_text


def test_a_fifo_at_the_cited_record_path_is_cannot_tell(tmp_path):
    """A fifo passes the leaf classifier and is refused by the descriptor check.

    A pipe is a regular-looking target for a classifier that follows links: it
    exists, it is not a symlink, and a read of it would block rather than answer.
    The only thing that stops it is ``fstat`` of the descriptor the reader actually
    opened, so this is the state the structural half of the refusal exists for, and
    the row must be the class's ``cannot-tell`` and never the ``uncited`` an absence
    errno would have produced.
    """
    import os

    repo = _planted_record_link(tmp_path, "fifo")
    record_path = repo / "noni" / "decisions" / f"{RECORD_ID}.json"
    record_path.unlink()
    os.mkfifo(record_path)
    code, rows, _, _ = _run(repo)
    intent_rows = _intent_rows(rows)
    assert subjects(intent_rows) == ["cannot-tell"], intent_rows
    assert intent_rows[0]["severity"] == "warn"
    assert code == 0
