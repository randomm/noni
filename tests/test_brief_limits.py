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
    dropped_of,
    dropped_line,
    page_with_budget,
    rows,
    sections,
    stripped,
    summary_line,
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
    debt never reaches the prose and the lines that went missing are order rows. The page is asked
    of a process that briefed no other tree: the census caches the tree it audits, so a parent that
    ran two trees would compare one tree's page against another's.
    """
    root = plant_brief_tree(tmp_path)
    full = page_lines(root)
    out = page_with_budget(root, full - 3, fresh=True)
    kept = rows(out, brief_module.ORDER_HEADER)
    assert kept and len(kept) < brief_module.TOP_ENTRIES
    assert len(stripped(sections(out), brief_module.PURPOSE_HEADER)) == \
        brief_module.PURPOSE_MAX_LINES + 1
    assert dropped_line(out) == f"{DROPPED_PREFIX}3 line(s)"


# The one-page shape the two budget cases measure against: the two headers, the purpose body and
# its ellipsis, the order's ten rows, and the single blank the page prints between two blocks that
# both held something. Spelled from the tool's constants so a change to a cap moves the cases with
# it rather than through them.
BRIEF_UNCUT = 2 + PURPOSE_MAX + 1 + TOP + 1


def test_brief_the_dropped_line_counts_the_lines_the_page_withheld(tmp_path: Path) -> None:
    """The count line names the lines the page withheld, and the page is what a reader counts.

    The budget counts the blank line between the two blocks as a line of the page, so a run that
    empties the order block withholds one line more than the rows it held: the ten entries go and
    the separator that stood under them goes with them. A count read off the arithmetic of the debt
    named ten where the screen was eleven lines shorter -- which is the line this case exists to
    pin, and why the expectation is written as rows plus separator rather than as the debt.
    """
    root = plant_brief_tree(tmp_path)
    for owed in range(1, TOP + 3):
        out = page_with_budget(root, BRIEF_UNCUT - owed, fresh=True)
        kept = len(rows(out, brief_module.ORDER_HEADER))
        # The page lost the order rows the cut took, and the separator that went with the last of
        # them once the block held nothing. The purpose block pays nothing at any of these cuts.
        assert dropped_of(out) == (TOP - kept) + (1 if kept == 0 else 0), (owed, out)
        assert len(stripped(sections(out), brief_module.PURPOSE_HEADER)) == PURPOSE_MAX + 1, owed
        # The verdict survives every cut. The budget governs the blocks, so the page as printed is
        # the blocks the tool kept, its own count line, and the verdict line beneath them.
        assert len(out.splitlines()) == BRIEF_UNCUT - owed + 2, owed


def test_brief_the_budget_drops_order_entries_and_not_the_purpose(tmp_path: Path) -> None:
    """The block that gives way is the one the spec names, and the count says how much.

    The truncation order is order entries first, then the purpose body. A budget the order can pay
    for on its own leaves the purpose block whole and every one of its lines on the screen, so the
    debt never reaches the prose and the lines that went missing are order rows.
    """
    root = plant_brief_tree(tmp_path)
    out = page_with_budget(root, BRIEF_UNCUT - 3, fresh=True)
    assert len(rows(out, brief_module.ORDER_HEADER)) == TOP - 3
    assert len(stripped(sections(out), brief_module.PURPOSE_HEADER)) == PURPOSE_MAX + 1
    assert dropped_of(out) == 3


def test_brief_the_budget_never_swallows_the_verdict(tmp_path: Path) -> None:
    """The count line closes the blocks and the verdict line still follows it.

    A reader who sees the page stop at a cut must not mistake the cut for the end of the report:
    whatever the budget was, the last line of the page is the arbiter's.
    """
    root = plant_brief_tree(tmp_path)
    out = page_with_budget(root, 3)
    lines = out.splitlines()
    assert lines[0] == brief_module.PURPOSE_HEADER
    assert dropped_line(out).startswith(DROPPED_PREFIX)
    assert lines[-1] == census_summary(root, NOW)
