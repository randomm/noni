"""The brief suite: a record whose bytes are hostile, and the reader called directly.

Split from ``test_brief_page.py`` for the 500-line source cap (the same seam that split
``src/noni/brief.py`` from ``src/noni/brief_page.py``): the page cases assert what a screen
prints, and these two ask what the page refuses to print -- the bytes a record carries that
must not reach a terminal, and the three numbers the decisions reader is defined by when a
test drives it instead of reading them off a page.

The page readers and the planters are the suite's shared ones, so a case here is about the
same planted tree every other brief case uses.
"""


from __future__ import annotations

from pathlib import Path

from brief_fixtures import (
    NOW,
    RECORD_ID,
    host_shaped_path,
    ledger_dir,
    plant_brief_tree,
    record_document,
    run_brief,
    write_record,
)
from brief_support import rows

from noni import brief as brief_module
from noni import ledger_schema


def test_brief_a_record_of_control_bytes_is_scrubbed_before_it_prints(
        tmp_path: Path) -> None:
    """A record's control bytes never reach the screen; its committed text does.

    The page's own renderer is what stands between a record's bytes and a terminal, so the case
    plants both shapes a record's bytes can hold: an escape sequence that would move the cursor or
    clear the screen, which must not survive, and a machine-local absolute path the operator
    committed themselves, which prints exactly as the record wrote it. The row still carries the
    words around them.
    """
    root = plant_brief_tree(tmp_path)
    ledger_dir(root).joinpath(f"{RECORD_ID}.json").unlink()
    path = host_shaped_path()
    write_record(root, record_document(
        "2026-10-25-hostile", "2026-10-25T00:00:00Z",
        question=f"Ship\x1b[2J from {path}?", answer="yes",
        why=f"\x07because of {path}"))
    out = run_brief(root, "--now", NOW)[1]
    assert "\x1b" not in out and "\x07" not in out
    row = rows(out, brief_module.RECENT_DECISIONS_HEADER)[0]
    # Retargeted for #202: the committed path prints as written rather than as a scrub marker.
    assert path in row
    assert "<path>" not in row
    assert "Ship" in row and "from" in row and "yes" in row


def test_brief_a_record_of_a_slash_word_prints_it_as_committed(
        tmp_path: Path) -> None:
    """A slash command in committed record text reaches the screen whole.

    The census's path arm answers "an ``OSError`` quoted a host path", and it has no floor on the
    number of components, so it took ``/deploy`` out of the operator's own question, answer and
    reason. A launched run is the route the operator and a hook have, so the row is read off the
    printed page.
    """
    root = plant_brief_tree(tmp_path)
    ledger_dir(root).joinpath(f"{RECORD_ID}.json").unlink()
    write_record(root, record_document(
        "2026-10-25-slash", "2026-10-25T00:00:00Z",
        question="Run /deploy first?", answer="yes, /deploy first",
        why="the /deploy job is the gate"))
    out = run_brief(root, "--now", NOW)[1]
    assert out.count("/deploy") == 3
    row = rows(out, brief_module.RECENT_DECISIONS_HEADER)[0]
    assert row == ("2026-10-25-slash: Run /deploy first?: yes, /deploy first"
                   " \u2014 the /deploy job is the gate")
    assert "<path>" not in row


def test_brief_page_line_collapses_whitespace_before_it_renders() -> None:
    """A tab between two words is a word boundary, so the row reads as two words.

    Called directly on the row builder: the collapse is what keeps ``two\\tcandidates`` from
    printing as one word once the renderer has taken the tab out.
    """
    from noni import brief_page

    assert brief_page.page_line("two\tcandidates", brief_page.TEXT_LIMIT,
                                frozenset()) == "two candidates"


def test_brief_page_line_a_control_byte_at_the_edge_cannot_dodge_a_reserved_word() -> None:
    """A BEL in front of a page's own word still reads as that word, so the row is dropped.

    The renderer deletes the byte, and a row left behind with padding would not compare equal to
    the reserved word, so the line the page is read by would reach stdout as a body line.
    """
    from noni import brief_page

    assert brief_page.page_line("\x07 top 10", brief_page.TEXT_LIMIT,
                                frozenset({"top 10"})) is None


def test_brief_page_line_a_control_byte_between_words_leaves_no_padding() -> None:
    """The gap a deleted control byte leaves closes, so a row stays one row."""
    from noni import brief_page

    assert brief_page.page_line("a \x07 b", brief_page.TEXT_LIMIT,
                                frozenset()) == "a b"


def test_brief_page_line_no_escape_byte_survives_the_renderer() -> None:
    """An ANSI sequence in foreign text never reaches the screen, whatever order the rules run in."""
    from noni import brief_page

    rendered = brief_page.page_line("\x1b[2Jok", brief_page.TEXT_LIMIT, frozenset())
    assert rendered is not None and "\x1b" not in rendered


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



