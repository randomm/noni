"""The brief suite, part 1 of 6: what the committed fixture renders.

The three blocks, their rows, and the shape of the printed page: one header per block,
one blank line between two blocks that printed something, and the body text a foreign
line is not mistaken for a header.
"""


from __future__ import annotations

from pathlib import Path

from brief_fixtures import (
    NOW,
    OPEN_RECORD_ID,
    PURPOSE_LINES,
    RECORD_ID,
    SUPERSEDED_ID,
    intent_path,
    ledger_dir,
    ledger_record_path,
    plant_brief_tree,
    record_document,
    run_brief,
    write_record,
)
from brief_support import (
    DROPPED_PREFIX,
    HEADERS,
    dropped_of,
    rows,
    sections,
    stripped,
    summary_line,
)

from noni import brief as brief_module
from noni import ledger_schema


def test_brief_renders_the_three_blocks_and_nothing_else(tmp_path: Path) -> None:
    """The screen is three blocks, a dropped-count line and the verdict, and nothing else.

    The headers are read from the tool rather than typed, and so is their order: the fourth
    block this screen gained is the recent decisions, and a page that printed a fourth header no
    constant names (or repeated one) fails here before any block's content is looked at.
    """
    code, out, err = run_brief(plant_brief_tree(tmp_path), "--now", NOW)
    assert code == 0
    assert err == ""
    assert out.startswith(brief_module.PURPOSE_HEADER + "\n")
    assert list(sections(out)) == HEADERS
    assert summary_line(out).startswith(brief_module.SUMMARY_PREFIX)


def test_brief_purpose_block_is_the_intent_purpose_section(tmp_path: Path) -> None:
    """The block is the operator's own prose, and stops at the next section's heading."""
    root = plant_brief_tree(tmp_path)
    body = stripped(sections(run_brief(root, "--now", NOW)[1]),
                    brief_module.PURPOSE_HEADER)
    assert body[0] == PURPOSE_LINES[0]
    assert body[1] == PURPOSE_LINES[1]
    # The Principles section's first line is the boundary: a body that ran past it would
    # have swallowed the rest of the file, which is what a naive split-on-heading does.
    assert "Prefer the boring technology." not in body
    assert "Never force push." not in body


def test_brief_top_ten_lists_the_first_ten_positions(tmp_path: Path) -> None:
    code, out, _ = run_brief(plant_brief_tree(tmp_path), "--now", NOW)
    assert code == 0
    body = stripped(sections(out), brief_module.ORDER_HEADER)
    assert len(body) == brief_module.TOP_ENTRIES
    assert body[0] == "1. #1"
    assert body[-1] == f"{brief_module.TOP_ENTRIES}. #{brief_module.TOP_ENTRIES}"
    # The fixture's eleventh position is the one the cap withholds.
    assert f"{brief_module.TOP_ENTRIES + 1}. #" not in out








def test_brief_one_block_per_header_separated_by_one_blank_line(tmp_path: Path) -> None:
    """The page's shape is part of the contract: one blank line, and only one, between blocks.

    A blank line inside a body (a purpose file with a paragraph break, say) is content; the
    separators are what a reader of the page counts. The fixture's body has no blank line of
    its own, so the blank lines of the page are the two separators and nothing else -- one below
    the purpose block and one below the order block, which is the position each block's header
    sits at plus the lines above it.
    """
    code, out, _ = run_brief(plant_brief_tree(tmp_path), "--now", NOW)
    assert code == 0
    # Two separators and nothing else: after the 22-line purpose block and after the ten order
    # rows. A blank line inside a body would add a third index, which is how this case tells a
    # separator from content that happens to be empty.
    assert [index for index, line in enumerate(out.splitlines())
            if not line.strip()] == [23, 35]
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


def test_brief_two_runs_one_tree_one_instant_are_equal_bytes(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    assert run_brief(root, "--now", NOW) == run_brief(root, "--now", NOW)


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
    """A one-option record is decided too, and its answer is its statement.

    The writer's ``--single-option`` marker is what makes a one-option question well formed; the
    block reads no options at all, so the row is the question text and the answer the operator
    gave, which for such a record is the statement itself.
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
        "2026-10-25-statement: The census stays the arbiter.: "
        "The census stays the arbiter."]


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


def test_brief_a_record_of_control_bytes_is_scrubbed_before_it_prints(
        tmp_path: Path) -> None:
    """A hostile question and reason reach the screen scrubbed, not raw.

    The page's own scrub is what stands between a record's bytes and a terminal, so the case
    plants the two shapes that matter: an escape sequence that would move the cursor or clear the
    screen, and a machine-local absolute path that the page promises never to print. Neither
    survives, and the row still carries the words around them.
    """
    root = plant_brief_tree(tmp_path)
    ledger_dir(root).joinpath(f"{RECORD_ID}.json").unlink()
    write_record(root, record_document(
        "2026-10-25-hostile", "2026-10-25T00:00:00Z",
        question="Ship\x1b[2J from /home/someone/build?", answer="yes",
        why="\x07because of /home/someone/secret"))
    out = run_brief(root, "--now", NOW)[1]
    assert "\x1b" not in out and "\x07" not in out
    assert "/home/someone" not in out
    row = rows(out, brief_module.RECENT_DECISIONS_HEADER)[0]
    assert "<path>" in row
    assert "Ship" in row and "from" in row and "yes" in row


def test_brief_the_decisions_reader_answers_its_own_three_questions(
        tmp_path: Path) -> None:
    """The reader's live filter, its cap and its order, called directly.

    The page cases above reach the reader through a launched run, which is the route the operator
    has; this drives the function itself, so the three numbers the block is defined by -- which
    statuses it prints, how many rows it keeps, what order it keeps them in -- are pinned where
    they are decided rather than inferred from a screen.
    """
    from noni import brief_page

    # The writer-shaped tree the page reads: ``write_record`` plants under ``<root>/noni/decisions``
    # because that is the path the block reaches through ``--repo``, and the reader is handed the
    # ledger directory the state root would hold.
    for record_id, (date, status) in {
            "a": ("2026-10-01T00:00:00Z", ledger_schema.STATUS_DECIDED),
            "b": ("2026-10-02T00:00:00Z", ledger_schema.STATUS_SUPERSEDED),
            "c": ("2026-10-03T00:00:00Z", ledger_schema.STATUS_OPEN),
            "d": ("2026-10-04T00:00:00Z", ledger_schema.STATUS_DECIDED)}.items():
        write_record(tmp_path / "seed", record_document(record_id, date, status=status))
    rows, withheld = brief_page.decision_rows(ledger_dir(tmp_path / "seed"), cap=1)
    assert rows == ["d: Ship the candidate?: yes"]
    # One live record fitted the cap and the other cost the block its count line; the superseded
    # and open records were never live, so they cost nothing at all.
    assert withheld == 1



def test_brief_a_purpose_line_shaped_like_a_header_is_dropped(tmp_path: Path) -> None:
    """A purpose line that reads exactly ``top 10`` cannot open a second block, and says it went.

    The word is the page's own and the reader of the page splits on it, so the line is dropped
    rather than printed. The drop is not silent: the block closes with its own count of the lines
    it withheld, so a reader who counts nineteen statements where the file holds twenty-five can
    tell "the intent says less than that" from "the page refused one".
    """
    root = plant_brief_tree(tmp_path)
    path = intent_path(root)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(PURPOSE_LINES[2], brief_module.ORDER_HEADER),
                    encoding="utf-8")
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    body = stripped(sections(out), brief_module.PURPOSE_HEADER)
    assert brief_module.ORDER_HEADER not in body
    assert PURPOSE_LINES[3] in body
    # One statement refused. The ellipsis is the mark of the clip at the twenty-line cap and is
    # not itself one of the withheld lines the count speaks of.
    assert body[-2] == brief_module.ELLIPSIS
    assert body[-1] == f"{DROPPED_PREFIX}6 line(s)"


def test_brief_a_blank_purpose_line_costs_nothing_but_its_line(tmp_path: Path) -> None:
    """A purpose line of only whitespace is not a line of the page; the block is intact."""
    root = plant_brief_tree(tmp_path)
    path = intent_path(root)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(PURPOSE_LINES[4], "   \t"), encoding="utf-8")
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    body = stripped(sections(out), brief_module.PURPOSE_HEADER)
    assert PURPOSE_LINES[3] in body and PURPOSE_LINES[5] in body
