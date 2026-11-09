"""The brief suite, part 4 of 6: the caps, then the budget.

The caps hold the page down before the budget is reached; when the budget is
reached, the block that gives way is the one the spec names, and the count line says
how much was withheld.
"""


from __future__ import annotations

from pathlib import Path

from brief_fixtures import (
    CREATED_NEWEST,
    NOW,
    PURPOSE_LINES,
    RECORD_ID,
    intent_path,
    item_path,
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
    assert len(body) == brief_module.PURPOSE_MAX_LINES + 1
    assert body[-1] == brief_module.ELLIPSIS
    assert body[0] == PURPOSE_LINES[0]
    assert body[-2] == PURPOSE_LINES[brief_module.PURPOSE_MAX_LINES - 1]
    # The head is kept and the tail is what goes: line 21 of the fixture's 25 is not printed.
    assert PURPOSE_LINES[brief_module.PURPOSE_MAX_LINES] not in body


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
    root = plant_brief_tree(tmp_path)
    entries = [orderschema.entry(issue=number, decision=RECORD_ID,
                                 confirmed="2026-10-26T00:00:00Z")
               for number in range(1, 101)]
    order_path(root).write_bytes(orderschema.order_bytes(
        {"schema": orderschema.ORDER_SCHEMA, "entries": entries}))
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    assert stripped(sections(out), brief_module.ORDER_HEADER) == \
        [f"{n}. #{n}" for n in range(1, brief_module.TOP_ENTRIES + 1)]


def test_brief_the_page_never_exceeds_the_cap(tmp_path: Path) -> None:
    """Every cap at once: the page is 34 lines, and the cap is a backstop none of them reaches.

    The expected count is built from the tool's own constants -- two headers, the purpose body
    and its ellipsis, 10 order rows, one separator, one verdict -- so the case
    follows a change to a cap instead of pinning a number nobody chose. The store is filled with
    200 ideas and the order with 200 entries on the way: the page reads neither list past its
    cap, so the count must not move.
    """
    root = plant_brief_tree(tmp_path)
    entries = [orderschema.entry(issue=number, decision=RECORD_ID,
                                 confirmed="2026-10-26T00:00:00Z")
               for number in range(1, 200)]
    order_path(root).write_bytes(orderschema.order_bytes(
        {"schema": orderschema.ORDER_SCHEMA, "entries": entries}))
    template = item_path(root, "idea-0001").read_bytes().decode("utf-8")
    for number in range(13, 200):
        item_id = f"idea-{number:04d}"
        item_path(root, item_id).write_text(
            template.replace("idea-0001", item_id)
            .replace(CREATED_NEWEST, "2026-12-31T09:00:00Z"), encoding="utf-8")
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    expected = (2 + brief_module.PURPOSE_MAX_LINES + 1 + brief_module.TOP_ENTRIES
                + 1 + 1)
    assert len(out.splitlines()) == expected <= brief_module.BRIEF_MAX_LINES
    assert DROPPED_PREFIX not in out


def test_brief_the_budget_drops_order_entries_and_not_the_purpose(tmp_path: Path) -> None:
    """The block that gives way is the one the spec names, and the count says how much.

    The truncation order is order entries first, then the purpose body. A budget the order can pay
    for on its own leaves the purpose block whole and every one of its lines on the screen, so the
    debt never reaches the prose: the lines the reader misses are order rows, and the tool counts
    exactly the rows that came off the list.
    """
    root = plant_brief_tree(tmp_path)
    out = page_owed_lines(root, 3)
    assert len(rows(out, brief_module.ORDER_HEADER)) == TOP - 3
    assert len(stripped(sections(out), brief_module.PURPOSE_HEADER)) == PURPOSE_MAX + 1
    assert dropped_of(out) == 3


def test_brief_a_dropped_block_takes_its_separator_with_it(tmp_path: Path) -> None:
    """The count names the separator too, which is the line the debt arithmetic did not know.

    The budget charges the blank line between the two blocks as a line of the page, so a cut that
    empties the order block takes that separator away with the last of its rows: the reader misses
    the header, the ten rows and the blank above them, one line more than the debt named. A count
    read off the arithmetic of the debt printed the smaller number, and a reader who counted the
    screen and the sentence got two answers. This case is that line: it pins the count to the rows
    that came off the list plus the separator that went with the last of them.
    """
    root = plant_brief_tree(tmp_path)
    # Ten lines off the page, which is the point the order block runs out: its ten rows go, the block
    # is left at its header alone, and the separator above it goes with the last of them -- so the
    # tool owes one line more than the ten rows it took, and the purpose block still prints whole.
    out = page_owed_lines(root, TOP)
    assert rows(out, brief_module.ORDER_HEADER) == []
    # The purpose block pays nothing: its header, its twenty lines and the ellipsis all print.
    assert len(stripped(sections(out), brief_module.PURPOSE_HEADER)) == PURPOSE_MAX + 1
    assert dropped_of(out) == TOP + 1
    # The verdict survives the deepest cut the content caps leave reachable.
    assert out.splitlines()[-1].startswith("summary:")


def test_brief_the_budget_never_swallows_the_verdict(tmp_path: Path) -> None:
    """The count line closes the blocks and the verdict line still follows it.

    A reader who sees the page stop at a cut must not mistake the cut for the end of the report:
    whatever the budget was, the last line of the page is the arbiter's.
    """
    root = plant_brief_tree(tmp_path)
    # A budget three lines long: every line of both blocks is past it, so the debt runs through the
    # order block and on into the Purpose body, which is the shape where the tool is left printing
    # two headers and its own count line.
    out = page_owed_lines(root, 30)
    lines = out.splitlines()
    assert lines[0] == brief_module.PURPOSE_HEADER
    assert dropped_line(out).startswith(DROPPED_PREFIX)
    assert lines[-1] == census_summary(root, NOW)
