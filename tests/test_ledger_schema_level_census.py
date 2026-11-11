"""The census's side of the ledger schema level: an undeclared field says what it is.

The drift these tests and ``tests/test_ledger_schema_level_skew.py`` exist for: a
project pins one noni commit for its CI census and runs a newer one locally. On the
day the newer writer emits a field the pinned census does not declare, the record
commits cleanly and the census refuses it hours later in a red run. The fix is one
integer and one committed file -- :data:`noni.ledger_level.LEDGER_SCHEMA_LEVEL` and
``noni/direction/census-level.json`` -- and the writer's half of it lives in the
sibling test file.

This file is the arbiter's half: what a census prints when a record carries a field
its closed set does not know, what it prints for a project that declared nothing,
and the contract of the reader that both sides share.

Both census entry points are driven throughout, via
``tests/ledger_schema_fixtures._census_verdicts``: the unified script and the
``census.sh`` shim over the same ledger. The shim reaches the census through
``noni.census_wrapper``, so a clause that lived in only one of the run's two routes
would show up here as a disagreement between them.

Every census is pinned with ``--now`` (the ledger-empty class reads the clock) and
runs offline: the trees come from ``tests/ledger_level_fixtures``, which builds them
with the harness's own git helpers, no network and no real accounts.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _harness import REPO, _harness_source, _init_repo
from ledger_level_fixtures import (
    CAUSE_PHRASES,
    DECLARATION,
    KNOWN_NOTES,
    SKEW_FIELD,
    _attached_project,
    _census_rows,
    _findings,
    _older_level,
    _writer_level,
)
from ledger_schema_fixtures import (
    _assert_both_clean,
    _assert_both_refuse,
    _baseline,
    _census_verdicts,
    _with_skew_field,
)

from noni import _decide_state_root, ledger_level

# The phrases that must never appear in the report of a project that declared
# nothing. The census's own fault wording is absent too, because a clean ledger has
# no fault to report: these are the strings the change introduces, listed so their
# absence is a claim rather than an untested hope.
SILENCE_PHRASES = ("unknown field", "census pin", ledger_level.SCHEMA_LEVEL_FILE,
                   ledger_level.SCHEMA_LEVEL_KEY, *CAUSE_PHRASES)


def _declaration(level: int) -> str:
    """The one document the reader accepts, for a given level.

    Built from the module's own key rather than spelled out, so a test cannot pass
    against a key the product no longer reads.
    """
    return '{' + f'"{ledger_level.SCHEMA_LEVEL_KEY}": {level}' + '}\n'


# --- the row that reports an undeclared field --------------------------------

def test_a_record_from_a_newer_writer_names_the_cause_and_not_just_the_fault(tmp_path):
    """AC1, the census half: the row that refuses an undeclared field says what it
    usually is, and quotes the level this census runs at.

    The same record on both entry points, the same refusal (exit 10), and one more
    clause. The "unknown field(s)" wording is asserted intact as well as the cause,
    because a rewording that dropped the fault would break every consumer that
    matched it.
    """
    record = _with_skew_field(_baseline())
    record["id"] = "2026-10-04-from-a-newer-writer"
    verdicts = _assert_both_refuse(tmp_path, record, SKEW_FIELD,
                                   "a field this census does not declare",
                                   subdir="skew-row")
    for name, (_code, out) in verdicts.items():
        assert "unknown field" in out.lower(), f"{name}: the fault went missing: {out}"
        assert SKEW_FIELD in out, f"{name}: the field is not named: {out}"
        assert f"{ledger_level.SCHEMA_LEVEL_KEY} {_writer_level()}" in out, (
            f"{name}: the row must quote the level this census runs at: {out}")
        for phrase in CAUSE_PHRASES:
            assert phrase in out, f"{name}: the cause must name {phrase!r}: {out}"


def test_a_clean_record_still_gains_no_cause_clause(tmp_path):
    """The positive control for the clause above: a well-formed record adds nothing.

    Without it the test above would be satisfied by a row that always appended the
    sentence, which diagnoses nothing.
    """
    record = _baseline()
    record["id"] = "2026-10-04-ordinary-record"
    _assert_both_clean(tmp_path, record, "an ordinary eight-field record")


def test_the_cause_clause_names_the_census_level_and_the_one_act_that_clears_it():
    """The census's clause, on its own: wording, the level, and no newline.

    Kept as a unit beside the end-to-end row test because the row test cannot tell a
    clause that lost the level from one that never had it -- the level it quotes is
    the same number the writer declares, so only this assertion fixes it as the
    census's own constant rather than a figure in prose. One sentence, because the
    reporter puts it in a row's message field and a newline there would split it.
    """
    clause = ledger_level.unknown_field_cause(3)
    assert "newer" in clause and "census pin" in clause, clause
    assert f"{ledger_level.SCHEMA_LEVEL_KEY} 3" in clause, clause
    assert clause.endswith("noni") and "\n" not in clause, repr(clause)


# --- the project that declared nothing --------------------------------------

def test_a_project_with_no_declaration_reports_exactly_as_before(tmp_path):
    """AC2, the census half: no declaration file, no new output, either entry point.

    One attached-project tree, asked three ways -- the unified ``--json`` run, its
    summary row, and the ``census.sh`` shim -- and the claim each time is an absence:
    exit 0, no ``ledger-record`` row, none of the cause wording, and a
    ``not_evaluated`` list holding exactly the sentences the run already carried.
    Comparing that list against the known notes is what makes a new note fail here,
    since every note rides that one field with no row kind to tell them apart.
    """
    repo = _attached_project(tmp_path, "no-declaration")
    assert not (repo / DECLARATION).exists(), "the fixture shipped a declaration"

    rows = _census_rows(repo)
    findings = _findings(rows)
    assert findings == [], f"a run with no declaration reported rows: {findings}"
    summary = [r for r in rows if r.get("kind") == "summary"]
    assert len(summary) == 1, rows
    carried = summary[0].get("not_evaluated", [])
    assert isinstance(carried, list), summary[0]
    assert len(carried) == len(KNOWN_NOTES), (
        "a no-declaration run must carry exactly the notes it carried before: "
        f"{carried}")
    for note, known in zip(carried, KNOWN_NOTES, strict=True):
        assert known in str(note), f"an unexpected note appeared: {note!r}"
    for phrase in SILENCE_PHRASES:
        assert phrase not in str(rows), f"a new phrase appeared: {phrase!r}"

    for name, (code, text) in _census_verdicts(tmp_path / "clean-pair",
                                               _baseline(), subdir="clean-pair").items():
        assert code == 0, f"{name}: expected 0, got {code}\n{text}"
        for phrase in SILENCE_PHRASES:
            assert phrase not in text, f"{name}: a new phrase appeared: {phrase!r}"


def test_the_declaration_is_not_counted_as_a_ledger_record(tmp_path):
    """A declaration under ``noni/direction/`` earns no ledger row at all.

    The path was chosen as a sibling of ``decisions/`` for exactly this reason: the
    ledger probe's ``*.json`` listing is the census's one readdir of the ledger, and
    a declaration inside ``decisions/`` would have been read as a record and refused
    as a malformed one. Asserted on the rows rather than the exit code, since a warn
    and a clean run share 0.
    """
    repo = _attached_project(tmp_path, "declaration-rows", _declaration(_writer_level()))
    findings = _findings(_census_rows(repo))
    assert findings == [], (
        f"a declaration is not a record and must report nothing: {findings}")


# --- the reader both sides share --------------------------------------------

def test_the_reader_answers_the_declared_level_and_the_shapes_that_are_not_one(tmp_path):
    """The reader's own contract, in process: a level, an absence, and every refusal.

    ``None`` is only ever the absence of the file -- including when a parent is
    absent, the shape of a project that has never held noni state. Everything else
    raises :class:`DeclarationError` with a reason that names the relative path and
    quotes none of the file's content, and a link at the path is refused rather than
    read through.

    ``0`` is in the admitted list and not the refused one: it is the level of a
    census predating the first declared set, which is an answer about a census rather
    than a file that says nothing.
    """
    assert ledger_level.read_schema_level(_init_repo(tmp_path / "bare")) is None
    assert ledger_level.read_schema_level(
        _attached_project(tmp_path, "reader-ok", _declaration(7))) == 7
    assert ledger_level.read_schema_level(
        _attached_project(tmp_path, "reader-zero", _declaration(0))) == 0
    for body in ("{", "[]", '"x"', "null", "5", "{}", '{"schema_level": null}',
                 '{"schema_level": -3}', '{"schema_level": true}',
                 '{"schema_level": "2"}', '{"schema_level": 1.5}'):
        shape = _attached_project(tmp_path, f"reader-{abs(hash(body))}", body)
        with pytest.raises(ledger_level.DeclarationError) as raised:
            ledger_level.read_schema_level(shape)
        assert ledger_level.SCHEMA_LEVEL_FILE in raised.value.why, raised.value.why
        assert body not in raised.value.why, (
            f"a refusal must not echo the file's content: {raised.value.why}")
    linked = _attached_project(tmp_path, "reader-link")
    outside = tmp_path / "outside-level.json"
    outside.write_text(_declaration(4), encoding="utf-8")
    (linked / ledger_level.SCHEMA_LEVEL_DIR).mkdir(parents=True, exist_ok=True)
    (linked / DECLARATION).symlink_to(outside)
    with pytest.raises(ledger_level.DeclarationError):
        ledger_level.read_schema_level(linked)


def test_the_refusal_reads_the_declaration_through_the_one_reader(tmp_path):
    """The refusal seam asks its question once, in process, and maps the answers.

    Four states of one tree, driven through the shared module rather than a whole
    ``decide`` run, so each answer is attributed to the reader's own value: a level
    below the writer's is the collision code, one at or above it is no refusal, an
    absent file is no refusal, and an unreadable file is the usage code. The exit
    codes are pinned by :func:`noni.decide.main`, which is what keeps this module a
    leaf that imports no exit code of its own.

    The refusal count is asserted at each step, not only at the end: a seam that
    printed on the absent file would still end with the codes this test expects.
    """
    calls: list[tuple[int, str, str | None]] = []

    def _fail(code: int, reason: str, hint: str | None = None) -> int:
        calls.append((code, reason, hint))
        return code

    def _drive(repo: Path) -> int | None:
        return _decide_state_root.refuse_schema_level_skew(_fail, 2, 4, repo)

    below = _attached_project(tmp_path, "seam-below", _declaration(_older_level()))
    assert _drive(below) == 4, calls
    assert len(calls) == 1, f"the collision answer printed twice: {calls}"
    assert _drive(_init_repo(tmp_path / "seam-absent")) is None, calls
    assert len(calls) == 1, f"an absent file must print nothing: {calls}"
    admitted = _attached_project(tmp_path, "seam-ok", _declaration(_writer_level()))
    assert _drive(admitted) is None, calls
    assert _drive(_attached_project(tmp_path, "seam-bad", "{")) == 2, calls
    assert [c[0] for c in calls] == [4, 2], calls


def test_the_level_and_the_reader_have_one_owner_each():
    """No second copy of the level, and no second reader of the declaration.

    The writer's refusal, the census's cause clause and these tests all read the one
    constant, and the census's record pass reaches the declaration through the one
    reader. This is the parity assertion that keeps the two sides from drifting again:
    the day either keeps its own number is the day they disagree in silence, which is
    the original bug wearing a new disguise.
    """
    census = _harness_source(REPO / "src" / "noni" / "census_ledger_checks.py")
    writer = _harness_source(REPO / "src" / "noni" / "decide.py")
    state_root = _harness_source(REPO / "src" / "noni" / "_decide_state_root.py")
    assert "unknown_field_cause" in census, (
        "the census no longer asks the shared module for the cause clause")
    assert "_level.LEDGER_SCHEMA_LEVEL" in census, (
        "the census keeps its own level rather than the shared constant")
    assert "_decide_state_root.refuse_run" in writer, (
        "decide.py no longer reaches the level check through its state-root module")
    assert "read_schema_level" in state_root, (
        "the level question is no longer asked where the tree question is asked")
    for text, where in ((census, "census_ledger_checks.py"),
                        (writer, "decide.py"),
                        (state_root, "_decide_state_root.py")):
        assert "LEDGER_SCHEMA_LEVEL = " not in text, (
            f"{where} declares its own level instead of reading the shared one")
