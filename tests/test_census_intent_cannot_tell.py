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

import ast
import contextlib
import json
import shutil
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
    planted_ledger_link as _planted_ledger_link,
    planted_record_link as _planted_record_link,
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


@pytest.fixture
def intent_ast(intent_class):
    """The same module parsed, for the pins that are about structure, not spelling.

    A source-text substring pin constrains how the code is written: renaming a local
    or hoisting a helper breaks it, and an ordering check can pass because a function
    happens to sit below another one. ``lineno`` from the tree constrains the
    behaviour and nothing else.
    """
    return ast.parse(intent_class)


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    """The module-level function ``name``, with a message when it is gone."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"census_intent.py defines no function {name}")


def _call_line(tree: ast.Module, func: str, callee: str) -> int:
    """The line where ``func`` calls ``callee``, or a failure naming both."""
    body = _function(tree, func)
    for node in ast.walk(body):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", None))
                == callee):
            return node.lineno
    raise AssertionError(f"{func}() no longer calls {callee}(), so the invariant "
                         "this pin exists for is not the code any more")


def _return_line(tree: ast.Module, func: str, *, after: int) -> int:
    """The first ``return`` inside ``func`` at or after line ``after``."""
    body = _function(tree, func)
    lines = sorted(node.lineno for node in ast.walk(body)
                   if isinstance(node, ast.Return) and node.lineno >= after)
    if not lines:
        raise AssertionError(f"{func}() returns nothing after line {after}, so the "
                             "refusal this pin guards has been removed")
    return lines[0]


def _function_source(tree: ast.Module, name: str, source: str) -> str:
    """The text of the module-level function ``name`` in ``source``."""
    return ast.get_source_segment(source, _function(tree, name)) or ""


def _json_rows(stdout: str) -> list[dict]:
    """The finding rows an in-process run printed, as dicts."""
    return [row for row in (json.loads(line) for line in stdout.splitlines()
                            if line.strip())
            if row.get("kind") == "finding"]


def _intent_rows(rows: list[dict]) -> list[dict]:
    """The intent class's own rows of a run that reported other classes too.

    The ledger group always reports its own row beside a planted link, and that row
    is correct existing behaviour: the assertion under test is this class's.
    """
    return [row for row in rows if row["check"] == "intent"]


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
    intent_rows = _intent_rows(rows)
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
    The refusal comes first, so the link is a ``cannot-tell`` warn and the
    absence branch never sees it.
    """
    repo = _planted_record_link(tmp_path, "dangling",
                                target=tmp_path / "no-such-record.json")
    code, rows, _, _ = _run(repo)
    intent_rows = _intent_rows(rows)
    assert subjects(intent_rows) == ["cannot-tell"]
    assert intent_rows[0]["severity"] == "warn"
    assert code == 0
    assert "no-such-record" not in json.dumps(intent_rows[0])


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
    intent_rows = _intent_rows(rows)
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
    repo = _planted_record_link(tmp_path, "directory", is_dir=True)
    code, rows, _, _ = _run(repo)
    intent_rows = _intent_rows(rows)
    assert subjects(intent_rows) == ["cannot-tell"]
    assert intent_rows[0]["severity"] == "warn"
    assert code == 0


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


def test_a_symlinked_ledger_directory_is_cannot_tell(tmp_path):
    """A link above the cited path is the same defect one level up, and is refused.

    With ``noni/decisions`` itself a link to a directory outside the tree, the leaf
    classification calls the record an ordinary file and the read follows the parent
    link, so an outside file decided the verdict. The class classifies the ledger
    and the directory above it, the way ``probe_ledger`` does, before composing a
    path under them.

    The link is planted over the directory the intent cites, not alongside a missing
    one: an intent whose tree the run cannot reach earns no row from any class, and
    the state under test is the link, not an empty tree.
    """
    repo = _planted_ledger_link(tmp_path, "ledger-link")
    code, rows, _, _ = _run(repo)
    intent_rows = _intent_rows(rows)
    assert subjects(intent_rows) == ["cannot-tell"]
    assert intent_rows[0]["severity"] == "warn"
    assert code == 0
    row_text = json.dumps(intent_rows[0])
    # Neither the target's bytes nor the path to it reaches the row.
    assert "superseded" not in row_text
    assert "ledger-lives-here" not in row_text
    assert RECORD_ID in intent_rows[0]["message"]


def test_a_symlinked_parent_of_the_ledger_is_cannot_tell(tmp_path):
    """``noni/`` itself as a link is refused too — one level up is still outside.

    The state the ledger group calls "symlink" and refuses to list; the intent group
    reads a record under the same path, so it asks the same two questions. The link
    is planted over the directory that holds the committed intent as well, so the run
    owes the read: the group is entered for a file it can reach, and the cited record
    behind the link is the thing it must refuse.
    """
    repo = _planted_ledger_link(tmp_path, "parent-link", parent=True)
    assert (repo / "noni" / "direction" / "intent.md").is_file(), (
        "the fixture lost the intent the run has to be owed a read of"
    )
    code, rows, _, _ = _run(repo)
    intent_rows = _intent_rows(rows)
    assert subjects(intent_rows) == ["cannot-tell"]
    assert intent_rows[0]["severity"] == "warn"
    assert code == 0
    assert "outside-nonni" not in json.dumps(intent_rows[0])


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
    repo = _planted_record_link(tmp_path, "filter")
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
    repo = _planted_record_link(tmp_path, "strict")
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
    compared = {
        (type(node.ops[0]).__name__, node.comparators[0].value)
        for node in ast.walk(_function(intent_ast, "check_intent"))
        if isinstance(node, ast.Compare) and len(node.ops) == 1
        and isinstance(node.left, ast.Name) and node.left.id == "record_kind"
        and isinstance(node.comparators[0], ast.Constant)
    }
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
    from noni import census_run
    import noni.census as census

    repo = _planted_record_link(tmp_path, "marker")
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
