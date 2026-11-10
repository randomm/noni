"""The brief suite, part 1 of 6: what the committed fixture renders.

The three blocks, their rows, and the shape of the printed page: one header per block,
one blank line between two blocks that printed something, and the body text a foreign
line is not mistaken for a header.
"""


from __future__ import annotations

from pathlib import Path

from brief_fixtures import (
    NOW,
    PURPOSE_LINES,
    intent_path,
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
            if not line.strip()] == [23]
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
