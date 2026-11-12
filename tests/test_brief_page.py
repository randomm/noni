"""The brief suite: the committed fixture's page and the ``top 10`` block's rows.

The blocks and their shape on the page: one header per block, one blank line between two
blocks that printed something, and body text a foreign line is not mistaken for a header.
The order rows live here because the block is the screen's answer to "what now": each row
is the position, the issue, the record that set the position, and the operator's reason
when the entry carries one.

The recent decisions block is in ``test_brief_decisions.py``, the hostile-bytes and
reader-direct cases in ``test_brief_scrub.py``; both were split off this file for the
500-line source cap, the same cap that split ``src/noni/brief_page.py`` from the tool.
"""


from __future__ import annotations

from pathlib import Path

import brief_page_rows
from brief_fixtures import (
    CONFIRMED,
    NOW,
    ORDER_WHY,
    PURPOSE_LINES,
    RECORD_ID,
    intent_path,
    plant_brief_tree,
    run_brief,
    write_order_entries,
)
from brief_support import (
    DROPPED_PREFIX,
    HEADERS,
    rows,
    sections,
    stripped,
    summary_line,
)

from noni import brief as brief_module
from noni import brief_page, orderschema


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
    """The block is the head of the order, one row per position, in the artifact's own order.

    Each row carries the decision that set the position, so the row answers what the entry *is*
    as well as where it sits: a fresh agent that sees ``1. #162`` alone cannot tell which
    operator record put that issue first, and noni never contacts a tracker for a title.
    """
    code, out, _ = run_brief(plant_brief_tree(tmp_path), "--now", NOW)
    assert code == 0
    body = stripped(sections(out), brief_module.ORDER_HEADER)
    assert len(body) == brief_module.TOP_ENTRIES
    # The fixture's head of the queue carries a reason and every other entry does not, so the
    # two shapes of the row are both the committed tree's: the head shows the reason after the
    # mark, and the tail is the position, the issue and the record that set it.
    assert body[0] == f"1. #1 ({RECORD_ID}) \u2014 {ORDER_WHY}"
    assert body[1] == f"2. #2 ({RECORD_ID})"
    assert body[-1] == (f"{brief_module.TOP_ENTRIES}. #{brief_module.TOP_ENTRIES}"
                        f" ({RECORD_ID})")
    # The fixture's eleventh position is the one the cap withholds.
    assert f"{brief_module.TOP_ENTRIES + 1}. #" not in out


def test_brief_an_order_row_carries_the_why_the_entry_holds(tmp_path: Path) -> None:
    """An entry that carries a reason prints it after a mark, in the operator's words.

    The row is what a cold start reads before it touches a tracker, and the order artifact
    already holds the operator's line of reason for the position: printed without it the page
    says what is first and not why, which is the question the head of the queue is for.
    """
    root = plant_brief_tree(tmp_path)
    write_order_entries(root, [
        orderschema.entry(issue=7, decision=RECORD_ID, confirmed=CONFIRMED,
                         why="the release train leaves Friday"),
        orderschema.entry(issue=9, decision=RECORD_ID, confirmed=CONFIRMED)])
    body = rows(run_brief(root, "--now", NOW)[1], brief_module.ORDER_HEADER)
    assert body == [f"1. #7 ({RECORD_ID}) \u2014 the release train leaves Friday",
                    f"2. #9 ({RECORD_ID})"]


def test_brief_an_order_row_without_a_why_prints_no_mark(tmp_path: Path) -> None:
    """No reason is no mark. A row ending in a lone separator promises a reason it does not give.

    The same rule the decision row obeys for the same reason: the mark belongs to a reason, and
    an entry written before the field existed (or written without it) prints its two parts.
    """
    root = plant_brief_tree(tmp_path)
    write_order_entries(root, [
        orderschema.entry(issue=3, decision=RECORD_ID, confirmed=CONFIRMED)])
    assert rows(run_brief(root, "--now", NOW)[1],
                brief_module.ORDER_HEADER) == [f"1. #3 ({RECORD_ID})"]


def test_brief_an_order_why_of_nothing_prints_no_mark(tmp_path: Path) -> None:
    """An entry whose ``why`` renders to nothing is an entry that carries no reason.

    The order analogue of the decision block's rule for an empty ``why``: a field the artifact's
    own rationale rule lets through and the page's scrub empties (a field of format characters, or
    one of spaces round them) is not the operator's reason, and a mark with nothing after it is
    the page promising a line it did not print. The shapes a field of plain spaces or of line
    breaks is the artifact's own refusal to print at all, so the reader stops that one before the
    row is built.
    """
    root = plant_brief_tree(tmp_path)
    write_order_entries(root, [
        orderschema.entry(issue=n, decision=RECORD_ID, confirmed=CONFIRMED, why=why)
        for n, why in ((1, "\u200b"), (2, " \u200b \u00ad "), (3, "\u00ad\u200b\ufeff"))])
    body = rows(run_brief(root, "--now", NOW)[1], brief_module.ORDER_HEADER)
    assert len(body) == 3
    for row in body:
        assert not row.rstrip().endswith("\u2014")
        assert row.endswith(f"({RECORD_ID})")
    # A reason that is real still rides at the end of its row, so the guard above cannot pass
    # with the reason never printed at all.
    write_order_entries(root, [orderschema.entry(
        issue=5, decision=RECORD_ID, confirmed=CONFIRMED,
        why="  the release train leaves Friday  ")])
    assert rows(run_brief(root, "--now", NOW)[1], brief_module.ORDER_HEADER) == [
        f"1. #5 ({RECORD_ID}) \u2014 the release train leaves Friday"]


def test_brief_an_order_row_is_scrubbed_and_bounded(tmp_path: Path) -> None:
    """A hostile ``why`` reaches the screen scrubbed, and every row stays one line.

    The two fields the row gained are foreign text from a file the brief did not write, so they
    answer to the same scrub every other line of the page does: no control byte out, no host
    path printed, and the row bounded as one line rather than the field alone. The escape and the
    bell are written as json escapes and the path in plain text, which is how the record's own
    bytes carry them: the page's promise is about what it prints, not about what a file holds.
    """
    root = plant_brief_tree(tmp_path)
    write_order_entries(root, [
        orderschema.entry(issue=11, decision=RECORD_ID, confirmed=CONFIRMED,
                          why="ship \x1b[2J from /home/someone/build \x07 now")])
    out = run_brief(root, "--now", NOW)[1]
    assert "\x1b" not in out and "\x07" not in out and "/home/someone" not in out
    row = rows(out, brief_module.ORDER_HEADER)[0]
    assert "<path>" in row
    assert len(row.splitlines()) == 1
    assert len(row) <= brief_page.TEXT_LIMIT
    # The words around the scrubbed bytes survive: the scrub removes, it does not replace.
    assert "ship" in row and "from" in row and "now" in row


def test_brief_an_order_row_stays_within_the_pages_bound(tmp_path: Path) -> None:
    """The longest row the row builder can be handed is still one bounded line.

    Driven at the builder rather than through a launched run because the bound is the
    builder's: an entry's ``why`` is capped at the artifact's own bound, so a run can print no
    longer row than this one hands back. The subject, the record id and the reason are
    composed and then bounded, so neither a long id nor a long reason can tip the row over.
    """
    row = brief_page_rows.order_row(1, issue=123456, decision="d" * 300,
                                    why="w" * 280)
    assert row is not None
    assert len(row) <= brief_page.TEXT_LIMIT
    assert row.startswith("1. #123456 ")


def test_brief_an_order_row_keeps_a_reason_that_fills_the_row(tmp_path: Path) -> None:
    """A reason too long for the row keeps its tail, and the head of the row yields.

    The row is composed reason-last and bounded reason-last, so the longest reason the artifact
    admits does not lose its end to the position, the issue and the record id: the reason is the
    part a cold start cannot recover anywhere else on the screen, and the statement of a settled
    decision is readable in the record file the row names. The bound is read from the page and the
    rationale bound from the artifact, so a change to either moves this case rather than leaving it
    pinned to a length nothing states.
    """
    root = plant_brief_tree(tmp_path)
    reason = "a" * orderschema.why_max()
    write_order_entries(root, [
        orderschema.entry(issue=21, decision=RECORD_ID, confirmed=CONFIRMED,
                          why=reason)])
    body = rows(run_brief(root, "--now", NOW)[1], brief_module.ORDER_HEADER)
    assert len(body) == 1
    row = body[0]
    assert len(row) <= brief_page.TEXT_LIMIT
    assert row.endswith(reason[-(brief_page.TEXT_LIMIT - 3):])








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
