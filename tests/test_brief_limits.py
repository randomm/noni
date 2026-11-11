"""The brief suite, part 4 of 6: the caps, then the budget.

The caps hold the page down before the budget is reached; when the budget is
reached, the block that gives way is the one the spec names, and the count line says
how much was withheld.
"""


from __future__ import annotations

from pathlib import Path

from brief_fixtures import (
    NOW,
    PURPOSE_LINES,
    RECORD_ID,
    intent_path,
    order_path,
    plant_brief_tree,
    run_brief,
    run_brief_with_history,
)
from brief_support import (
    DROPPED_PREFIX,
    census_summary,
    dropped_line,
    dropped_of,
    page_owed_lines,
    rows,
    sections,
    stripped,
)

from noni import brief as brief_module
from noni import orderschema

# Read off the tool so the budget cases below state a page length in the tool's own numbers.
PURPOSE_MAX = brief_module.PURPOSE_MAX_LINES
TOP = brief_module.TOP_ENTRIES


def test_brief_purpose_is_clipped_at_the_cap_with_an_ellipsis(tmp_path: Path) -> None:
    """The fixture's purpose body is 25 lines; the block shows 20 and says a line went missing."""
    code, out, _ = run_brief(plant_brief_tree(tmp_path), "--now", NOW)
    assert code == 0
    body = stripped(sections(out), brief_module.PURPOSE_HEADER)
    assert len(body) == brief_module.PURPOSE_MAX_LINES + 2
    assert body[-2] == brief_module.ELLIPSIS
    assert body[0] == PURPOSE_LINES[0]
    assert body[-3] == PURPOSE_LINES[brief_module.PURPOSE_MAX_LINES - 1]
    # The head is kept and the tail is what goes: line 21 of the fixture's 25 is not printed.
    assert PURPOSE_LINES[brief_module.PURPOSE_MAX_LINES] not in body


def test_brief_a_clipped_purpose_block_closes_with_the_lines_it_cut(tmp_path: Path) -> None:
    """A clipped Purpose owes the lines it cut, and the block closes with that count.

    The fixture's purpose body is twenty-five lines and the cap twenty, so the clip takes
    five off the top of the body and the block owes them: the head stays, the ellipsis marks
    the cut, and the count line names the five the reader does not see. The answer has to be
    the number of lines cut and not only a yes-or-no about whether a clip happened, because
    the number is what the screen and the sentence have to agree on.
    """
    root = plant_brief_tree(tmp_path)
    out = run_brief(root, "--now", NOW)[1]
    purpose = stripped(sections(out), brief_module.PURPOSE_HEADER)
    dropped = [line for line in purpose if line.startswith(DROPPED_PREFIX)]
    assert dropped == [f"{DROPPED_PREFIX}5 line(s)"]
    assert len(purpose) == brief_module.PURPOSE_MAX_LINES + 2
    assert purpose[-2] == brief_module.ELLIPSIS


def test_brief_a_purpose_of_exactly_the_cap_prints_no_ellipsis(tmp_path: Path) -> None:
    """The ellipsis marks a body that was longer than the cap, not one that filled it.

    The intent file is rewritten from the fixture's own tuple at the cap, so the length under
    test is the number the case is about and not an artefact of how a string was cut: a body of
    exactly ``PURPOSE_MAX_LINES`` lines prints every one of them and no mark of a line missing,
    and the two cases together pin the boundary from both sides.
    """
    root = plant_brief_tree(tmp_path)
    path = intent_path(root)
    kept = PURPOSE_LINES[:brief_module.PURPOSE_MAX_LINES]
    path.write_text(_intent_with_purpose(kept), encoding="utf-8")
    body = stripped(sections(run_brief_with_history(root, "--now", NOW)[1]),
                    brief_module.PURPOSE_HEADER)
    assert body == list(kept)
    assert brief_module.ELLIPSIS not in body


def _intent_with_purpose(lines: tuple[str, ...] | list[str]) -> str:
    """An intent file whose ``## Purpose`` body is exactly ``lines``, rest of the file intact.

    Written whole rather than by patching the fixture's text: a section's length is the fact a
    case is asserting, and a case that reached it by deleting a line out of a string has to get
    the deletion right before it can test anything about the length.
    """
    return ("# Intent\nLast-confirmed: 2026-10-01\n\n## Purpose\n\n"
            + "\n".join(lines)
            + "\n\n## Principles\n\nPrefer the boring technology.\n\n"
            "## Never\n\nNever force push.\n\n## Ask first\n\n"
            "Anything that costs money.\n")


def test_brief_a_hundred_order_entries_render_ten(tmp_path: Path) -> None:
    """The cap is asked of the rows the block built, and each row is the full form.

    One hundred entries, ten rows, each of them the position, the issue and the record that
    set the position: the row gained two parts and the cap stayed the count of rows.
    """
    root = plant_brief_tree(tmp_path)
    entries = [orderschema.entry(issue=number, decision=RECORD_ID,
                                 confirmed="2026-10-26T00:00:00Z")
               for number in range(1, 101)]
    order_path(root).write_bytes(orderschema.order_bytes(
        {"schema": orderschema.ORDER_SCHEMA, "entries": entries}))
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    assert stripped(sections(out), brief_module.ORDER_HEADER) == \
        [f"{n}. #{n} ({RECORD_ID})" for n in range(1, brief_module.TOP_ENTRIES + 1)]


def test_brief_the_page_never_exceeds_the_cap(tmp_path: Path) -> None:
    """Every cap at once: the page is 39 lines, and the cap is a backstop none of them reaches.

    The expected count is built from the tool's own constants -- three headers, the purpose body
    and its ellipsis, 10 order rows, the five decision rows the committed ledger's one live record
    leaves at one, the two separators, one verdict -- so the case
    follows a change to a cap instead of pinning a number nobody chose. The order is filled
    with 200 entries on the way: the page reads no list past its cap, so the count must not
    move.
    """
    root = plant_brief_tree(tmp_path)
    entries = [orderschema.entry(issue=number, decision=RECORD_ID,
                                 confirmed="2026-10-26T00:00:00Z")
               for number in range(1, 200)]
    order_path(root).write_bytes(orderschema.order_bytes(
        {"schema": orderschema.ORDER_SCHEMA, "entries": entries}))
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    # The committed fixture's ledger holds three records and exactly one of them is live, so the
    # decisions block prints one row: the count below reads that fact off the tool's own cap and
    # the fixture's one live record rather than from a number typed here.
    decisions_rows = len(rows(out, brief_module.RECENT_DECISIONS_HEADER))
    assert decisions_rows == 1
    expected = (3 + brief_module.PURPOSE_MAX_LINES + 2 + brief_module.TOP_ENTRIES
                + decisions_rows + 2 + 1)
    assert len(out.splitlines()) == expected <= brief_module.BRIEF_MAX_LINES
    assert DROPPED_PREFIX in out


def test_brief_the_budget_drops_order_entries_and_not_the_purpose(tmp_path: Path) -> None:
    """The block that gives way is the one the spec names, and the count says how much.

    The truncation order is the recent decisions first, then the order entries, then the purpose
    body. A budget deeper than the decisions block can pay for on its own reaches into the order
    rows -- and leaves the purpose block whole, every one of its lines on the screen: the debt
    never reaches the prose, and the tool counts exactly the lines that came off the page.
    """
    root = plant_brief_tree(tmp_path)
    out = page_owed_lines(root, 3)
    assert len(rows(out, brief_module.ORDER_HEADER)) == TOP - 2
    assert len(stripped(sections(out), brief_module.PURPOSE_HEADER)) == PURPOSE_MAX + 2
    # The decisions block paid its one row first: the debt of three took the row, the separator
    # above it and one order row, and the count line says three, which is what the reader misses.
    assert rows(out, brief_module.RECENT_DECISIONS_HEADER) == []
    assert dropped_of(out) == 3


def test_brief_a_dropped_block_takes_its_separator_with_it(tmp_path: Path) -> None:
    """The count names the separator too, which is the line the debt arithmetic did not know.

    The budget charges the blank line above a block as a line of the page, so a cut that empties a
    block takes that separator away with its last row: the reader misses the header, its rows and
    the blank above them, one line more than the debt named for the rows alone. A count read off the
    arithmetic of the debt printed the smaller number, and a reader who counted the screen and the
    sentence got two answers. This case is that line, and the block it cuts is the order block --
    the decisions block ahead of it is emptied first (the case below pins that), so by the time the
    debt reaches the queue the separator above it is the line the debt cannot see coming.
    """
    root = plant_brief_tree(tmp_path)
    # Eleven lines off the page: the decisions block's row and the separator above it, then the
    # order block's ten rows. The queue is left at its header alone and the separator above it goes
    # with the last of its rows, so the tool owes one line more than the eleven it took by the
    # arithmetic -- the count names twelve, which is what the reader counts missing.
    out = page_owed_lines(root, TOP + 1)
    assert rows(out, brief_module.ORDER_HEADER) == []
    assert rows(out, brief_module.RECENT_DECISIONS_HEADER) == []
    # The purpose block pays nothing: its header, its twenty lines and the ellipsis all print.
    assert len(stripped(sections(out), brief_module.PURPOSE_HEADER)) == PURPOSE_MAX + 2
    assert dropped_of(out) == TOP + 2
    # The verdict survives the deepest cut the content caps leave reachable.
    assert out.splitlines()[-1].startswith("summary:")


def test_brief_the_budget_never_swallows_the_verdict(tmp_path: Path) -> None:
    """The count line closes the blocks and the verdict line still follows it.

    A reader who sees the page stop at a cut must not mistake the cut for the end of the report:
    whatever the budget was, the last line of the page is the arbiter's.
    """
    root = plant_brief_tree(tmp_path)
    # A budget three lines long: every line of all three blocks is past it, so the debt runs
    # through the order block, on through the recent decisions and into the Purpose body, which is
    # the shape where the tool is left printing three headers and its own count line.
    out = page_owed_lines(root, 30)
    lines = out.splitlines()
    assert lines[0] == brief_module.PURPOSE_HEADER
    assert dropped_line(out).startswith(DROPPED_PREFIX)
    assert lines[-1] == census_summary(root, NOW)


def test_brief_the_recent_decisions_block_drops_before_the_order(
        tmp_path: Path) -> None:
    """The spec's precedence, stated: the queue outlasts the decisions block.

    The tool's rule is that a block's tail is what goes, and the block that prints newest-first
    has its oldest record at that tail -- so the positional rule alone decides which block empties
    first, and the page puts the decisions last precisely so it is the decisions that go. The head
    of the order is what to work on next, which is the question the screen exists to answer, and a
    budget deep enough to cost a decision row must not cost an order row as well until the
    decisions block has given everything it has. The purpose block, which holds the operator's
    prose, is last in line either way.
    """
    root = plant_brief_tree(tmp_path)
    # A debt of one: the decisions block's one row goes and no order row does.
    out = page_owed_lines(root, 1)
    assert rows(out, brief_module.RECENT_DECISIONS_HEADER) == []
    assert len(rows(out, brief_module.ORDER_HEADER)) == TOP
    assert dropped_of(out) == 1
    # A debt of two has taken the separator above the block too, so the block is empty and one
    # order row has gone with it: the decisions block gave up the two lines it had left to give
    # before the queue was touched at all, and the purpose prose is untouched.
    deeper = page_owed_lines(root, 2)
    assert rows(deeper, brief_module.RECENT_DECISIONS_HEADER) == []
    assert len(rows(deeper, brief_module.ORDER_HEADER)) == TOP - 1
    assert len(stripped(sections(deeper), brief_module.PURPOSE_HEADER)) == PURPOSE_MAX + 2
