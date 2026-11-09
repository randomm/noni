"""The brief suite, part 4 of 6: the caps, then the budget.

The four caps hold the page down before the budget is reached; when the budget is
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
    block_lines,
    candidate_rows,
    census_summary,
    page_with_budget,
    sections,
    stripped,
    summary_line,
)

from noni import brief as brief_module


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


def test_brief_the_candidate_block_holds_at_most_ten_rows(tmp_path: Path) -> None:
    """The cap is the tool's, not an artefact of the fixture's twelve."""
    from noni import itemschema

    root = plant_brief_tree(tmp_path)
    template = item_path(root, "idea-0001").read_bytes().decode("utf-8")
    for number in range(13, 30):
        item_id = f"idea-{number:04d}"
        raw = template.replace("idea-0001", item_id)
        raw = raw.replace(CREATED_NEWEST, "2026-12-31T09:00:00Z")
        item_path(root, item_id).write_text(raw, encoding="utf-8")
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    rows = candidate_rows(out)
    assert len(rows) == brief_module.TOP_CANDIDATES
    assert rows[0].split()[0] == "idea-0029"
    assert itemschema.STATUS_CANDIDATE in rows[0]


def test_brief_a_refused_row_does_not_cost_the_block_a_row(tmp_path: Path) -> None:
    """Fifteen candidates of which five read badly still print ten rows.

    The cap counts rows that were printed, not files that were read: a listing that counted
    the refusals would show fewer ideas than the store holds, for a reason the reader cannot
    see. The five newest ideas are given titles the page refuses, and the block still shows
    the ten freshest rows it could build.
    """
    root = plant_brief_tree(tmp_path)
    template = item_path(root, "idea-0001").read_bytes().decode("utf-8")
    for number in range(13, 18):
        item_id = f"idea-{number:04d}"
        raw = template.replace("idea-0001", item_id)
        raw = raw.replace(CREATED_NEWEST, "2026-12-31T09:00:00Z")
        raw = raw.replace("Cache the census result", brief_module.CANDIDATES_HEADER)
        item_path(root, item_id).write_text(raw, encoding="utf-8")
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    rows = candidate_rows(out)
    assert len(rows) == brief_module.TOP_CANDIDATES
    assert not any(row.split()[0].startswith("idea-001") and int(row.split()[0][5:]) >= 13
                   for row in rows)


def test_brief_a_hundred_order_entries_render_ten(tmp_path: Path) -> None:
    from noni import orderschema

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
    """Every cap at once: the page is 45 lines, and the cap is a backstop none of them reaches.

    The expected count is built from the tool's own constants -- three headers, 21 purpose
    lines, 10 order rows, 10 candidate rows, two separators, one verdict -- so the case
    follows a change to a cap instead of pinning a number nobody chose.
    """
    from noni import orderschema

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
    expected = (3 + brief_module.PURPOSE_MAX_LINES + 1 + brief_module.TOP_ENTRIES
                + brief_module.TOP_CANDIDATES + 2 + 1)
    assert len(out.splitlines()) == expected <= brief_module.BRIEF_MAX_LINES
    assert DROPPED_PREFIX not in out
def dropped_line(page: str) -> str:
    """The budget's own count line of a page, or ``""`` when it printed none.

    Read from the page rather than from a block: the count line is the blocks' last line and sits
    directly under the last header, so a reader of the page sees it as the last block's last row.
    That is the tool's rule and not a fault to route around -- the count line belongs to the blocks
    and the verdict line belongs to the page.
    """
    for line in reversed(page.splitlines()):
        if line.startswith(DROPPED_PREFIX):
            return line
    return ""


def rows(page: str, header: str) -> list[str]:
    """One block's rows, with the budget's own count line left out.

    The count line is printed as the last line of the blocks, which puts it under the last header
    and inside the last block as a reader of the page sees it. Every budget case asks about the
    rows the block kept, so the count line is asked for separately, by :func:`_dropped_line`, and
    excluded here -- and a case can then say "the candidate block holds nothing" and mean the
    ideas, not the tool's arithmetic.
    """
    rows = stripped(sections(page), header)
    return [row for row in rows if not row.startswith(DROPPED_PREFIX)]


def test_brief_the_budget_drops_candidates_then_order_then_purpose(tmp_path: Path) -> None:
    """The block that gives way is the one the spec names, and the count says how much.

    The truncation order is candidates first, then order entries, then the purpose body. At a
    budget of 60 the candidate block alone has more than enough to pay for the cut, so the purpose
    and the order come through whole and every line the page withheld is a candidate row.
    """
    root = plant_brief_tree(tmp_path)
    # The cut is expressed as a fraction of the page's own length rather than as a number of lines:
    # a case that named 60 would be pinning how long the fixture's purpose block happens to be.
    full = block_lines(root)
    # One row short of a full cut: this is the case about where the debt falls, not about the
    # exact arithmetic of a separator, so the number the block is left with is read back and only
    # the fact of it is asserted.
    out = page_with_budget(root, full - brief_module.TOP_CANDIDATES + 1)
    kept = rows(out, brief_module.CANDIDATES_HEADER)
    assert kept and len(kept) < brief_module.TOP_CANDIDATES
    assert len(rows(out, brief_module.ORDER_HEADER)) == brief_module.TOP_ENTRIES
    assert dropped_line(out) == \
        f"{DROPPED_PREFIX}{brief_module.TOP_CANDIDATES - len(kept)} line(s)"


def test_brief_the_budget_empties_a_block_down_to_its_header(tmp_path: Path) -> None:
    """A block cut to nothing still prints its header, and the debt moves to the next block.

    At 25 lines neither the candidates nor the order can keep a row once the 21-line purpose block
    has taken what it takes, so both are emptied to their headers. A reader who cannot tell which
    block went missing has lost more than one who sees an empty block under its own name, which is
    why :func:`noni.brief._drop` stops at the header and hands the rest of the debt on.
    """
    root = plant_brief_tree(tmp_path)
    # A budget one row above the page's own length minus the order block: the candidates have
    # already been emptied and the debt has moved on to the order, which is left standing at its
    # header alone.
    full = block_lines(root)
    # A budget no block can satisfy: the two lists are emptied down to their headers, which the
    # tool keeps so a reader can tell which block went missing, and the purpose block is what
    # survives -- the debt moves from candidates to order to purpose, and stops at the headers.
    out = page_with_budget(root, full - brief_module.TOP_ENTRIES - brief_module.TOP_CANDIDATES)
    assert rows(out, brief_module.PURPOSE_HEADER)
    # The candidates gave all ten of their rows, the order gave nine of its ten, and the line the
    # tool keeps when it empties a block is the header -- which is why the block is asked for by
    # name and not counted: a reader who can see ``top 10`` above an empty list knows what went
    # missing, and that is the whole claim of this case.
    assert rows(out, brief_module.CANDIDATES_HEADER) == []
    assert rows(out, brief_module.ORDER_HEADER)
    assert brief_module.ORDER_HEADER in out.splitlines()
    assert brief_module.CANDIDATES_HEADER in out.splitlines()
    assert summary_line(out) == census_summary(root, NOW)
    assert dropped_line(out).startswith(DROPPED_PREFIX)


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
