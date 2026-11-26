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
    host_shaped_path,
    intent_path,
    plant_brief_tree,
    run_brief,
    write_order_entries,
)
from brief_support import (
    DROPPED_PREFIX,
    HEADERS,
    dropped_of,
    order_entries,
    sections,
    stripped,
    summary_line,
)

from noni import brief as brief_module
from noni import brief_page, orderschema

# What the standing rules and the blank under them cost at the top of the page. Every
# pinned line position in this file is measured from the blocks alone and sits this many
# lines further down: three rule lines and the separator that keeps them off the header.
_RULES = len(brief_module.STANDING_RULES) + 1

# The one line the ``top 10`` block prints above its rows over an order of issues, saying the
# queue was never checked for closed issues. Every line position below that sits past the order
# block counts it: it is a line of the block like the rows it leads.
_NOTICE = 1


def _rows(page: str) -> list[str]:
    """The ``top 10`` block's entry rows: the queue's rows, nothing else.

    Every case here is about a row the block built from an order entry, so the tool's own
    notice line and its count line are left out. The notice still reaches
    :func:`test_brief_the_order_block_notice_leads_the_rows`, which asserts it as printed.
    """
    return order_entries(page, brief_module.ORDER_HEADER)


def test_brief_renders_the_three_blocks_and_nothing_else(tmp_path: Path) -> None:
    """The screen is three blocks, a dropped-count line and the verdict, and nothing else.

    The headers are read from the tool rather than typed, and so is their order: the fourth
    block this screen gained is the recent decisions, and a page that printed a fourth header no
    constant names (or repeated one) fails here before any block's content is looked at.
    What sits above the first header is the standing rules, and the line that separates them
    from the page: the only other thing the tool prints ahead of the blocks.
    """
    code, out, err = run_brief(plant_brief_tree(tmp_path), "--now", NOW)
    assert code == 0
    assert err == ""
    head = out.splitlines()[:len(brief_module.STANDING_RULES)]
    assert head == list(brief_module.STANDING_RULES)
    assert out.splitlines()[len(head)] == ""
    assert out.splitlines()[len(head) + 1] == brief_module.PURPOSE_HEADER
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
    body = _rows(out)
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
    body = _rows(run_brief(root, "--now", NOW)[1])
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
    assert _rows(run_brief(root, "--now", NOW)[1]) == [f"1. #3 ({RECORD_ID})"]


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
    body = _rows(run_brief(root, "--now", NOW)[1])
    assert len(body) == 3
    for row in body:
        assert not row.rstrip().endswith("\u2014")
        assert row.endswith(f"({RECORD_ID})")
    # A reason that is real still rides at the end of its row, so the guard above cannot pass
    # with the reason never printed at all.
    write_order_entries(root, [orderschema.entry(
        issue=5, decision=RECORD_ID, confirmed=CONFIRMED,
        why="  the release train leaves Friday  ")])
    assert _rows(run_brief(root, "--now", NOW)[1]) == [
        f"1. #5 ({RECORD_ID}) \u2014 the release train leaves Friday"]


def test_brief_an_order_row_is_scrubbed_and_bounded(tmp_path: Path) -> None:
    """A hostile ``why`` loses its control bytes, keeps its committed text, and stays one line.

    The two fields the row gained are foreign text from a file the brief did not write, so they
    answer to the page's renderer: no control byte out, and the row bounded as one line rather than
    the field alone. What the operator committed does not move, so the host path the entry's
    ``why`` names prints as the artifact wrote it. The escape and the bell are written as json
    escapes and the path in plain text, which is how the record's own bytes carry them: the page's
    promise is about what it prints, not about what a file holds.
    """
    root = plant_brief_tree(tmp_path)
    path = host_shaped_path()
    write_order_entries(root, [
        orderschema.entry(issue=11, decision=RECORD_ID, confirmed=CONFIRMED,
                          why=f"ship \x1b[2J from {path} \x07 now")])
    out = run_brief(root, "--now", NOW)[1]
    assert "\x1b" not in out and "\x07" not in out
    row = _rows(out)[0]
    # Retargeted for #202: the committed path prints as written rather than as a scrub marker.
    assert path in row
    assert "<path>" not in row
    assert len(row.splitlines()) == 1
    assert len(row) <= brief_page.TEXT_LIMIT
    # The words around the dropped bytes survive: the renderer removes, it does not replace.
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
    # The head is what the bound clips, so it ends on the page's clip mark: the subject
    # opens the row and the reason keeps its whole end.
    assert row.startswith("1. #123456" + brief_module.ELLIPSIS)


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
    body = _rows(run_brief(root, "--now", NOW)[1])
    assert len(body) == 1
    row = body[0]
    assert len(row) <= brief_page.TEXT_LIMIT
    assert row.endswith(reason[-(brief_page.TEXT_LIMIT - 3):])


def test_brief_an_order_why_with_a_slash_word_prints_it_as_committed(
        tmp_path: Path) -> None:
    """A slash command in an entry's committed ``why`` reaches the screen whole.

    The same census arm that took ``/deploy`` out of a record's text took it out of an order
    entry's, because the mangling sat in the one function every printed line passes through. The
    entry cites an ordinary record id: an id is ``<date>-<slug>`` over ``[a-z0-9-]``, so a slash
    cannot reach the row through the citation.
    """
    root = plant_brief_tree(tmp_path)
    write_order_entries(root, [
        orderschema.entry(issue=31, decision=RECORD_ID, confirmed=CONFIRMED,
                          why="ship the /deploy job before the freeze")])
    row = _rows(run_brief(root, "--now", NOW)[1])[0]
    assert row == (f"1. #31 ({RECORD_ID}) \u2014 ship the /deploy job before the freeze")
    assert "<path>" not in row


def test_brief_an_order_why_of_tabs_and_spaces_collapses_to_one_line(
        tmp_path: Path) -> None:
    """The page still folds a committed ``why`` to one line: a tab and a run of spaces go.

    The row's one-line rule belongs to the page and not to the census, so the whitespace collapse
    stays where the row is built even now the path arms have left. The artifact's own rationale
    rule refuses a line break and admits a tab, so those are the two shapes this case plants.
    """
    root = plant_brief_tree(tmp_path)
    write_order_entries(root, [
        orderschema.entry(issue=32, decision=RECORD_ID, confirmed=CONFIRMED,
                          why="ship   two\tcandidates   now")])
    row = _rows(run_brief(root, "--now", NOW)[1])[0]
    assert row == f"1. #32 ({RECORD_ID}) \u2014 ship two candidates now"


def test_brief_a_purpose_line_with_a_slash_word_prints_it_and_owes_nothing(
        tmp_path: Path) -> None:
    """A slash command in a Purpose line prints intact and costs the block no extra line.

    The Purpose body is the third family of committed text on the page, and it reaches the screen
    through the same renderer as the two row builders. The block's own withheld count is compared
    with the same tree unplanted, so the word surviving cannot be paid for by a silent drop.
    """
    root = plant_brief_tree(tmp_path)
    baseline = dropped_of(run_brief(root, "--now", NOW)[1])
    path = intent_path(root)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(PURPOSE_LINES[2], "Run /deploy before the release."),
                    encoding="utf-8")
    out = run_brief(root, "--now", NOW)[1]
    body = stripped(sections(out), brief_module.PURPOSE_HEADER)
    assert "Run /deploy before the release." in body
    assert "<path>" not in out
    assert dropped_of(out) == baseline

def test_brief_one_block_per_header_separated_by_one_blank_line(tmp_path: Path) -> None:
    """The page's shape is part of the contract: one blank line, and only one, between blocks.

    A blank line inside a body (a purpose file with a paragraph break, say) is content; the
    separators are what a reader of the page counts -- and the standing rules' own blank is
    the first of them, since the rules are the tool's lines and not a body's. The fixture's
    body has no blank line of
    its own, so the blank lines of the page are that one and the two separators and nothing
    else: one below the rules, one below
    the purpose block and one below the order block, each the position of the block above it
    plus the lines above that.
    """
    code, out, _ = run_brief(plant_brief_tree(tmp_path), "--now", NOW)
    assert code == 0
    # The rules' blank, then the two separators: after the 22-line purpose block and after
    # the notice line and the ten order rows. A blank line inside a body would add a fourth
    # index, which is how this case tells a separator from content that happens to be empty.
    # The page opens with
    # the standing rules and one blank below them, so all three indices sit four lines
    # further down than the blocks alone would put them: 3 rule lines and their separator
    # ahead of line 0.
    assert [index for index, line in enumerate(out.splitlines())
            if not line.strip()] == [_RULES - 1, _RULES + 23, _RULES + 35 + _NOTICE]
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


def test_brief_the_order_block_notice_leads_the_rows(tmp_path: Path) -> None:
    """The queue's own notice is the first line under ``top 10``, above the rows.

    The reader of the order is the audience of the line: it says the entries below it were
    never read against closed issues. It is the tool's own sentence (so it is the constant,
    never a retyped copy), it is the only one of its kind on the page, and it sits where a
    cut from the tail cannot reach it before the rows it qualifies.
    """
    code, out, _ = run_brief(plant_brief_tree(tmp_path), "--now", NOW)
    assert code == 0
    body = stripped(sections(out), brief_module.ORDER_HEADER)
    assert body[0] == brief_page.NOT_CHECKED_CLOSED
    assert body[1] == f"1. #1 ({RECORD_ID}) \u2014 {ORDER_WHY}"
    assert out.count(brief_page.NOT_CHECKED_CLOSED) == 1


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
