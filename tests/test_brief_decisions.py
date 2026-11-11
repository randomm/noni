"""The brief suite: the ``recent decisions`` block, one row per live record.

Split from ``test_brief_page.py`` for the 500-line source cap, the same seam that split
``src/noni/brief.py`` from ``src/noni/brief_page.py``. The block prints the operator's
settled answers, so the cases here are about the row's two shapes (a multi-question record
and a single-option one), the filter that keeps a closed or unanswered record off the
screen, and the bound that decides which half of a too-long row survives.

The planters and page readers are the suite's shared ones, so every case here runs against
the same committed tree the other brief files assert on.
"""


from __future__ import annotations

from pathlib import Path

import brief_page_rows
from brief_fixtures import (
    NOW,
    OPEN_RECORD_ID,
    RECORD_ID,
    SUPERSEDED_ID,
    ledger_dir,
    ledger_record_path,
    plant_brief_tree,
    record_document,
    run_brief,
    write_record,
)
from brief_support import dropped_of, rows

from noni import brief as brief_module
from noni import brief_page

# --- the recent decisions block ---------------------------------------------

# The five dates the page cases plant, in the order the block prints them (newest first). Kept
# beside the cases that use them so the newest-first assertion reads as a list a reader can see
# rather than as five literals scattered through the file.
DECISION_DATES = ("2026-10-24", "2026-10-23", "2026-10-22", "2026-10-21", "2026-10-20")


def _plant_decisions(root: Path, dates: tuple[str, ...], *, why: bool = False) -> list[str]:
    """Plant one live record per date in ``dates`` and hand back their ids.

    Each carries one answered question and, when asked for, one line of reason. The ids are the
    dates with a slug, which is the shape the ledger writer writes, so the row's first field is
    a real record id rather than a placeholder the assertion happens to match.
    """
    ids = []
    for index, date in enumerate(dates, 1):
        record_id = f"{date}-brief-page"
        write_record(root, record_document(
            record_id, f"{date}T00:00:00Z",
            question=f"Which of the {index} candidates ships first?",
            answer=f"candidate {index}",
            why="the operator's reason" if why else None))
        ids.append(record_id)
    return ids


def test_brief_recent_decisions_lists_the_live_records_newest_first(
        tmp_path: Path) -> None:
    """The block is the operator's settled answers, newest first, one line each.

    The fixture's committed record sits in the same ledger as the five planted ones, so the case
    also pins that a sixth live record is withheld rather than printed: the block shows five and
    says it withheld the sixth.
    """
    root = plant_brief_tree(tmp_path)
    _plant_decisions(root, DECISION_DATES)
    out = run_brief(root, "--now", NOW)[1]
    body = rows(out, brief_module.RECENT_DECISIONS_HEADER)
    assert len(body) == brief_module.RECENT_DECISIONS
    assert [line.split(":", 1)[0] for line in body] == [
        f"{date}-brief-page" for date in DECISION_DATES]
    # The committed fixture's record is the sixth live one, so it is the row the cap withholds.
    assert RECORD_ID not in out.split("recent decisions")[1]
    assert dropped_of(out) == 1


def test_brief_a_decision_row_carries_id_question_answer_and_reason(
        tmp_path: Path) -> None:
    """One row is ``id: text: answer`` plus the record's own ``why`` after a mark.

    Built from one record so the row's shape is the record's shape and not an artefact of a sort
    or a cap: the id opens the line, the question text and its answer follow, and the reason the
    operator gave rides at the end. The separator between the two is the tool's, never the
    record's, so a record with no ``why`` prints no trailing mark.
    """
    root = plant_brief_tree(tmp_path)
    ledger_dir(root).joinpath(f"{RECORD_ID}.json").unlink()
    write_record(root, record_document("2026-10-25-reason", "2026-10-25T00:00:00Z",
                                       question="Ship the beta this week?",
                                       answer="Wait a week",
                                       why="the train is staffed"))
    body = rows(run_brief(root, "--now", NOW)[1],
                brief_module.RECENT_DECISIONS_HEADER)
    assert body == ["2026-10-25-reason: Ship the beta this week?: Wait a week"
                    " \u2014 the train is staffed"]


def test_brief_a_decision_without_a_reason_prints_no_mark(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    ledger_dir(root).joinpath(f"{RECORD_ID}.json").unlink()
    write_record(root, record_document("2026-01-25-bare", "2026-01-25T00:00:00Z",
                                       question="Rebuild the wheel?", answer="no"))
    assert rows(run_brief(root, "--now", NOW)[1],
                brief_module.RECENT_DECISIONS_HEADER) == [
        "2026-01-25-bare: Rebuild the wheel?: no"]


def test_brief_a_reason_of_nothing_prints_no_mark(tmp_path: Path) -> None:
    """A ``why`` that holds no reason is the same answer as a record that carries none.

    The shape a hand-edited ledger reaches when a reason is deleted and its quotes left behind.
    A bare mark is worse than no mark: the page promises the operator's reason after it, and a
    reader who meets "yes \u2014" at the end of a row has been told a reason exists and given
    nothing of it. The block's rule is that the mark belongs to a reason, so the mark goes with
    the reason.
    """
    root = plant_brief_tree(tmp_path)
    ledger_dir(root).joinpath(f"{RECORD_ID}.json").unlink()
    for record_id, why in (("2026-01-25-spaces", "   \t "),
                           ("2026-01-24-category-c", "\u2028\u00a0\u3000"),
                           ("2026-01-23-category-f", "\u200b"),
                           ("2026-01-22-both", " \u200b \u00ad ")):
        write_record(root, record_document(record_id, f"{record_id[:10]}T00:00:00Z",
                                           question="Ship it?", answer="yes", why=why))
    body = rows(run_brief(root, "--now", NOW)[1],
                brief_module.RECENT_DECISIONS_HEADER)
    assert len(body) == 4
    for line in body:
        assert not line.rstrip().endswith("\u2014")
        assert line.split(": ", 1)[1] == "Ship it?: yes"
    # A reason that is real still rides at the end of its row: the guard is about an empty
    # reason, not about the mark's existence, and a case that only planted empties would pass
    # with the mark never printed at all.
    write_record(root, record_document("2026-01-21-real", "2026-01-21T00:00:00Z",
                                       question="Ship it?", answer="yes",
                                       why="  the train is staffed  "))
    real = [line for line in rows(run_brief(root, "--now", NOW)[1],
                                  brief_module.RECENT_DECISIONS_HEADER)
            if line.startswith("2026-01-21-real")]
    assert real == ["2026-01-21-real: Ship it?: yes \u2014 the train is staffed"]


def test_brief_a_question_of_nothing_costs_the_record_its_row(tmp_path: Path) -> None:
    """A question whose text is spaces is a question nobody asked, and the row goes with it.

    The reader's own rule is that no row prints an answer with no question beside it, and a
    text of spaces passes a test for an empty string while leaving nothing in the text position,
    which is a row reading "id: : yes", the operator's word standing where a question belongs.
    It costs the record its row exactly as a non-object entry does, and the block says the row
    went.
    """
    root = plant_brief_tree(tmp_path)
    ledger_dir(root).joinpath(f"{RECORD_ID}.json").unlink()
    write_record(root, record_document("2026-01-22-blank-question", "2026-01-22T00:00:00Z",
                                       question="   ", answer="yes"))
    out = run_brief(root, "--now", NOW)[1]
    assert rows(out, brief_module.RECENT_DECISIONS_HEADER) == []
    assert dropped_of(out) == 1


def test_brief_an_unanswered_question_prints_the_tools_own_word(
        tmp_path: Path) -> None:
    """A live record's null answer is the page's word, not an empty field.

    The block prints only records the ledger calls ``decided``, so a null answer is the ordinary
    case of a decided record that asked a second question the operator left open -- and a row
    that printed nothing there would read as a question this page dropped. The word is the
    tool's, read from the reader rather than typed, so a rename moves the assertion with it.
    """
    from noni import brief_page

    root = plant_brief_tree(tmp_path)
    ledger_dir(root).joinpath(f"{RECORD_ID}.json").unlink()
    write_record(root, record_document(
        "2026-10-25-half-answered", "2026-10-25T00:00:00Z",
        question="Ship the beta?", answer="yes",
        extra_questions=[{"id": "q2", "text": "Name the release?",
                          "options": ["Fable", "Atlas"], "answer": None}]))
    body = rows(run_brief(root, "--now", NOW)[1],
                brief_module.RECENT_DECISIONS_HEADER)
    assert body == [f"2026-10-25-half-answered: Ship the beta?: yes; "
                    f"Name the release?: {brief_page.OPEN_ANSWER}"]


def test_brief_a_single_option_record_prints_its_statement(tmp_path: Path) -> None:
    """A one-option record is decided too, and its row is the statement and nothing else.

    The writer's ``--single-option`` marker says the one-option question was asked on purpose, so
    the question of such a record is boilerplate: it is the statement, restated as a question,
    and the answer is that statement again. The row prints the statement once and spends its
    width on the operator's reason instead, which is the part the row exists to carry.
    """
    root = plant_brief_tree(tmp_path)
    ledger_dir(root).joinpath(f"{RECORD_ID}.json").unlink()
    write_record(root, record_document("2026-10-25-statement", "2026-10-25T00:00:00Z",
                                       question="The census stays the arbiter.",
                                       answer="The census stays the arbiter.",
                                       options=["The census stays the arbiter."],
                                       single_option=True))
    assert rows(run_brief(root, "--now", NOW)[1],
                brief_module.RECENT_DECISIONS_HEADER) == [
        "2026-10-25-statement: The census stays the arbiter."]


def test_brief_a_single_option_row_prints_its_reason_after_the_statement(
        tmp_path: Path) -> None:
    """The reason of a single-option record rides at the end of its row.

    The statement alone tells an agent what was settled, not why it was settled that way, and
    the question text the row dropped was the boilerplate, not the reason.
    """
    root = plant_brief_tree(tmp_path)
    ledger_dir(root).joinpath(f"{RECORD_ID}.json").unlink()
    write_record(root, record_document("2026-10-25-statement", "2026-10-25T00:00:00Z",
                                       question="The census stays the arbiter.",
                                       answer="The census stays the arbiter.",
                                       options=["The census stays the arbiter."],
                                       single_option=True,
                                       why="a second arbiter argues with the first"))
    assert rows(run_brief(root, "--now", NOW)[1],
                brief_module.RECENT_DECISIONS_HEADER) == [
        "2026-10-25-statement: The census stays the arbiter. \u2014 a second arbiter "
        "argues with the first"]


def test_brief_a_long_statement_clips_and_the_reason_survives(tmp_path: Path) -> None:
    """When the row will not fit, the statement is what is cut: the reason is kept.

    The row is built reason-last on purpose, so the whole-row bound used to fall on the reason's
    tail and cut it mid-word ("...but we do ...") while printing a boilerplate question at full
    length. The reason is the part an agent cannot recover anywhere else on the screen, so the
    statement is clipped around it rather than the other way about.
    """
    root = plant_brief_tree(tmp_path)
    ledger_dir(root).joinpath(f"{RECORD_ID}.json").unlink()
    statement = "The census " + "stays the one arbiter of the state " * 9
    write_record(root, record_document("2026-10-25-long", "2026-10-25T00:00:00Z",
                                       question=statement, answer=statement,
                                       options=[statement], single_option=True,
                                       why="the census has the honest exit code"))
    row = rows(run_brief(root, "--now", NOW)[1],
               brief_module.RECENT_DECISIONS_HEADER)[0]
    assert row.startswith("2026-10-25-long: The census ")
    assert row.endswith("\u2014 the census has the honest exit code")
    assert brief_module.ELLIPSIS in row
    assert len(row) <= brief_page.TEXT_LIMIT


def test_brief_a_statement_too_long_to_share_the_row_loses_its_own_width(tmp_path: Path) -> None:
    """Even at the floor the reason is kept, and the statement yields the rest of the row.

    The one case where clipping the statement around the reason is not enough: the id, the
    separator and the reason together leave too little room for a clipped statement to say
    anything, and the row prints the reason rather than a clipped fragment no reader can use.
    Driven at the builder because no writer admits a record whose statement is that long.
    """
    row = brief_page_rows.decision_row(record_id="r" * 280,
                                       statement="s" * 280,
                                       why="the reason the operator gave")
    assert row is not None
    assert row.endswith("\u2014 the reason the operator gave")
    assert len(row) <= brief_page.TEXT_LIMIT


def test_brief_a_superseded_and_an_open_record_never_appear(tmp_path: Path) -> None:
    """The committed fixture holds both, and the block prints neither.

    The fixture's ledger carries the record the committed one closed and the record no operator
    answered, both dated around the live one: the superseded record is the newest-but-one of the
    three by date and the open one is the newest of all, so a filter that trusted the sort or the
    file names instead of the ``status`` field would put one of them on the screen.
    """
    root = plant_brief_tree(tmp_path)
    out = run_brief(root, "--now", NOW)[1]
    body = rows(out, brief_module.RECENT_DECISIONS_HEADER)
    assert body == [f"{RECORD_ID}: What should the run brief first?: the three newest"]
    assert SUPERSEDED_ID not in out
    assert OPEN_RECORD_ID not in out


def test_brief_ties_in_the_record_date_break_by_id(tmp_path: Path) -> None:
    """Two records dated to one instant still have one order between them.

    What a writer run twice, or a ``--date`` carried over, produces. The page's determinism claim
    is that one tree at one instant prints the same bytes twice, and a tie decided by the
    filesystem's listing order would leave that claim resting on a readdir.
    """
    root = plant_brief_tree(tmp_path)
    ledger_dir(root).joinpath(f"{RECORD_ID}.json").unlink()
    stamp = "2026-10-25T00:00:00Z"
    for record_id in ("2026-10-25-alpha", "2026-10-25-bravo", "2026-10-25-charlie"):
        write_record(root, record_document(record_id, stamp))
    first, second = (run_brief(root, "--now", NOW)[1], run_brief(root, "--now", NOW)[1])
    assert first == second
    assert [line.split(":", 1)[0]
            for line in rows(first, brief_module.RECENT_DECISIONS_HEADER)] == [
        "2026-10-25-charlie", "2026-10-25-bravo", "2026-10-25-alpha"]


def test_brief_a_record_that_is_a_symlink_contributes_no_row(tmp_path: Path) -> None:
    """A link in the ledger is refused, never followed, and costs only its own row.

    The rest of the ledger still prints, which is the brief's rule for a read it cannot make:
    one unreadable record is one missing row, not a page that stops. The bytes behind the link
    name a decision that is not the tree's, and a page that followed it would put them on the
    screen as if they were.
    """
    root = plant_brief_tree(tmp_path)
    outside = tmp_path / "outside-record.json"
    outside.write_text(ledger_record_path(root, RECORD_ID).read_text(encoding="utf-8"),
                       encoding="utf-8")
    ledger_record_path(root, RECORD_ID).unlink()
    ledger_record_path(root, RECORD_ID).symlink_to(outside)
    body = rows(run_brief(root, "--now", NOW)[1],
                brief_module.RECENT_DECISIONS_HEADER)
    assert body == []


