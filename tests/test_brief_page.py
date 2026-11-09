"""The brief suite, part 1 of 6: what the committed fixture renders.

The three blocks, their rows, and the shape of the printed page: one header per block,
one blank line between two blocks that printed something, and the body text a foreign
line is not mistaken for a header.
"""


from __future__ import annotations

import json
from pathlib import Path

from brief_fixtures import (
    NOW,
    ORDER_CITATION,
    PURPOSE_LINES,
    intent_path,
    order_path,
    plant_brief_tree,
    run_brief,
)
from brief_support import (
    DROPPED_PREFIX,
    HEADERS,
    sections,
    stripped,
    summary_line,
)

from noni import brief as brief_module
from noni import itemschema


def test_brief_renders_the_three_blocks_and_nothing_else(tmp_path: Path) -> None:
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


def test_brief_an_item_entry_prints_its_citation(tmp_path: Path) -> None:
    """The ``noni.order/2`` row: the cited idea named by the id the artifact holds.

    The fixture's fourth position cites ``idea-0009`` rather than naming issue 4, so the
    citation shape is exercised by the committed tree and not only by a planted variant.
    """
    code, out, _ = run_brief(plant_brief_tree(tmp_path), "--now", NOW)
    assert code == 0
    body = stripped(sections(out), brief_module.ORDER_HEADER)
    assert body[3] == f"4. item {ORDER_CITATION}"
    assert "4. #4" not in out


def test_brief_an_item_row_never_reads_the_item_store(tmp_path: Path) -> None:
    """The row of a cited idea holds the citation, and a broken item file changes nothing.

    The fixture's fourth position cites ``idea-0009``, whose file the page has no reason to open.
    The committed bytes are replaced by ones no reader can parse, and the row is asked for again:
    a page that read the store for its title would print a different line here, and a page that
    opened the file at all has no business promising to read only the two artifacts it names.
    """
    root = plant_brief_tree(tmp_path)
    artifact = root / "noni" / "items" / f"{ORDER_CITATION}.json"
    assert artifact.is_file(), "the fixture must hold the cited idea for this case to mean anything"
    artifact.write_bytes(b"{ broken\n")
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    assert stripped(sections(out), brief_module.ORDER_HEADER)[3] == \
        f"4. item {ORDER_CITATION}"


def test_brief_an_item_row_prints_the_id_at_the_stores_bound(tmp_path: Path) -> None:
    """The widest id an order may cite prints whole, and the row stays one line.

    The row is the tool's own word, the position, and the citation at the store's id bound, so the
    longest id the schema allows is the longest row the block can print. An id that lost characters
    on the way to the screen would name a different idea than the one the operator queued.
    """
    widest = "z" * itemschema.ID_MAX
    root = plant_brief_tree(tmp_path)
    assert brief_module._order_row(root, 4, {
        "item": widest, "decision": "d", "confirmed": "c"}) == f"4. item {widest}"


def test_brief_one_block_per_header_separated_by_one_blank_line(tmp_path: Path) -> None:
    """The page's shape is part of the contract: one blank line, and only one, between blocks.

    A blank line inside a body (a purpose file with a paragraph break, say) is content; the
    separators are what a reader of the page counts. The fixture's body has no blank line of
    its own, so the one blank line of the page is the separator between the two blocks and
    nothing else.
    """
    code, out, _ = run_brief(plant_brief_tree(tmp_path), "--now", NOW)
    assert code == 0
    # One separator and nothing else: after the 21-line purpose block. A blank line inside a
    # body would add a second index, which is how this case tells a separator from content that
    # happens to be empty.
    assert [index for index, line in enumerate(out.splitlines())
            if not line.strip()] == [22]
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
    assert body[-1] == f"{DROPPED_PREFIX}1 line(s)"


def test_brief_a_citation_that_is_not_an_id_prints_the_citation_it_was_given(tmp_path: Path) -> None:
    """An entry citing a name the store would not name a file for still prints that name.

    The order's reader insists on an id and refuses the artifact outright, so this is not a state
    the block ever reaches by reading the file -- it is the state the row's own shape rule has to
    keep honest, tested where the rule lives. A citation is an identifier and the row prints the
    citation the artifact holds; it is not filtered, replaced or guessed at, and the row is one
    line that names the idea the operator queued.
    """
    assert brief_module._citation("not an id at all") == "not an id at all"
    # The row built from it is the one shape the block has for a citation of any shape.
    entry = {"item": "not an id at all", "decision": "d", "confirmed": "c"}
    root = plant_brief_tree(tmp_path)
    assert brief_module._order_row(root, 3, entry) == "3. item not an id at all"


def test_brief_a_citation_with_control_bytes_prints_nothing_of_them(tmp_path: Path) -> None:
    """A citation carrying escape bytes reaches the screen with nothing of them left.

    The order's reader insists that an item citation be an identifier shaped like a file stem, so
    a name carrying an ESC never arrives at the row by way of a file this tool read -- the artifact
    is refused before any row is built, which is the right answer and is the case the faults suite
    holds. What remains, and what this case holds, is the rule the row is composed by: the page
    prints the citation and a citation is text somebody typed. Unrendered it would put an escape
    sequence on the terminal -- an OSC sequence could retitle the
    window, a CSI sequence could colour the rest of the page, a next-line byte could add rows the
    census never counted -- so the citation goes through the page's renderer, at the
    store's own id bound, and keeps the characters that identify the idea.
    """
    smuggled = "idea-0007" + chr(0x1b) + "[31m" + chr(0x07) + chr(0x85)
    shown = brief_module._citation(smuggled)
    assert_no_control_bytes(shown)
    # The printable half survives, escape bytes and their arguments gone: the reader still learns
    # which idea the operator queued.
    assert shown == "idea-0007[31m"
    # And the row is the shape the block prints for any citation it was given.
    entry = {"item": smuggled, "decision": "d", "confirmed": "c"}
    root = plant_brief_tree(tmp_path)
    assert brief_module._order_row(root, 11, entry) == "11. item idea-0007[31m"


def test_brief_a_citation_that_leaves_nothing_to_print_is_named_not_left_blank(
        tmp_path: Path) -> None:
    """A citation the renderer leaves nothing of prints the tool's word, not a hole.

    The row is built from the citation, so a citation the renderer left nothing of would have
    printed ``item ``: a row with a gap where its subject goes, which a reader could take
    for a second answer this tool invented. The one word the tool already uses for text it could not
    print answers instead, and the position keeps its row, so the queue below it is not renumbered by
    a citation nobody can read.

    The name is the one an order's reader would refuse, for the reason the case above states; what
    is under test is the row's own composition, which is where the gap would have appeared.
    """
    # Nothing but bytes the renderer drops, so nothing is left: the arguments of an escape
    # sequence are ordinary printable characters and would survive on their own.
    entry = {"item": chr(0x1b) + chr(0x07) + chr(0x85) + chr(0x2028) + chr(0x7f),
             "decision": "d", "confirmed": "c"}
    root = plant_brief_tree(tmp_path)
    row = brief_module._order_row(root, 11, entry)
    assert row == f"11. item {brief_module.NOT_READ}"
    assert_no_control_bytes(row)
    # The other rows are unaffected: the position keeps its row rather than vanishing.
    assert brief_module._order_row(root, 10, {"issue": 10, "decision": "d",
                                              "confirmed": "c"}) == "10. #10"


def assert_no_control_bytes(page: str) -> None:
    """No control byte of a planted artifact reaches stdout, in any of its forms.

    The check is a predicate over the whole page rather than a list of the bytes one case planted:
    the point of the page's renderer is that no category-C character leaves it, so a case that only
    looked for the bytes it happened to plant would pass while the renderer leaked any other. The
    page's own newlines are the tool's doing, not the artifact's bytes.
    """
    from noni import _safe_text

    leaked = sorted({char for char in page
                     if char != "\n" and _safe_text.is_control_char(char)})
    assert leaked == [], [hex(ord(char)) for char in leaked]


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
