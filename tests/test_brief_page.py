"""The brief suite, part 1 of 6: what the committed fixture renders.

The four blocks, their rows, and the shape of the printed page: one header per block,
one blank line between two blocks that printed something, and the body text a foreign
line is not mistaken for a header.
"""


from __future__ import annotations

from pathlib import Path

import pytest
from brief_fixtures import (
    CREATED_NEWEST,
    CREATED_TIED,
    NOW,
    ORDER_CITATION,
    PURPOSE_LINES,
    intent_path,
    item_path,
    plant_brief_tree,
    run_brief,
)
from brief_support import (
    HEADERS,
    candidate_rows,
    sections,
    stripped,
    summary_line,
)

from noni import brief as brief_module


def test_brief_renders_the_four_blocks_and_nothing_else(tmp_path: Path) -> None:
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


def test_brief_an_item_entry_prints_its_title_and_citation(tmp_path: Path) -> None:
    """The ``noni.order/2`` row: the cited idea's title, with the id beside it.

    The fixture's fourth position cites ``idea-0009`` rather than naming issue 4, so the
    citation shape is exercised by the committed tree and not only by a planted variant.
    """
    code, out, _ = run_brief(plant_brief_tree(tmp_path), "--now", NOW)
    assert code == 0
    body = stripped(sections(out), brief_module.ORDER_HEADER)
    assert body[3] == f"4. Explain a failing census (item {ORDER_CITATION})"
    assert "4. #4" not in out


def test_brief_an_item_entry_whose_item_is_gone_says_not_found(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    item_path(root, ORDER_CITATION).unlink()
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    body = stripped(sections(out), brief_module.ORDER_HEADER)
    assert body[3] == f"4. item {ORDER_CITATION} not found"


def test_brief_candidates_are_newest_first_and_a_tie_breaks_on_id(tmp_path: Path) -> None:
    code, out, _ = run_brief(plant_brief_tree(tmp_path), "--now", NOW)
    assert code == 0
    rows = candidate_rows(out)
    assert len(rows) == brief_module.TOP_CANDIDATES
    # The two ideas sharing the newest stamp come first, and between them the id decides.
    assert rows[0].split()[0] == CREATED_TIED[1]
    assert rows[1].split()[0] == CREATED_TIED[0]
    assert rows[0].split()[2] == CREATED_NEWEST == rows[1].split()[2]
    stamps = [row.split()[2] for row in rows]
    assert stamps == sorted(stamps, reverse=True)


def test_brief_a_candidate_row_is_id_status_created_then_title(tmp_path: Path) -> None:
    code, out, _ = run_brief(plant_brief_tree(tmp_path), "--now", NOW)
    assert code == 0
    fields = candidate_rows(out)[0].split()
    assert fields[0] == CREATED_TIED[1]
    assert fields[1] == "candidate"
    assert fields[2] == CREATED_NEWEST
    assert " ".join(fields[3:]) == "Replay a decision into a fresh clone"


@pytest.mark.parametrize("status", ["promoted", "dropped"])
def test_brief_an_item_that_is_no_longer_a_candidate_leaves_the_block(tmp_path: Path,
                                                                     status: str) -> None:
    """The two statuses the store moves an idea to once it is taken or killed.

    Both are read from the store's own status tuple, so the block's one selection question is
    asked of the same set of words the writer is allowed to write: a rename of either side
    makes this table wrong rather than the assertion quietly vacuous.
    """
    root = plant_brief_tree(tmp_path)
    path = item_path(root, "idea-0012")
    text = path.read_text(encoding="utf-8")
    assert '"status": "candidate"' in text
    path.write_text(text.replace('"status": "candidate"', f'"status": "{status}"'),
                    encoding="utf-8")
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    assert not any(row.startswith("idea-0012 ") for row in candidate_rows(out))


def test_brief_the_tie_order_survives_a_rewrite_of_the_store(tmp_path: Path) -> None:
    """The tie order is the rule, not the order the names came back in.

    The two tied files are deleted and written back in the opposite order -- the only way a
    directory's own ordering could have been what the first run showed.
    """
    root = plant_brief_tree(tmp_path)
    paths = [item_path(root, item_id) for item_id in CREATED_TIED]
    saved = [(path, path.read_bytes()) for path in paths]
    for path, _ in saved:
        path.unlink()
    for path, raw in reversed(saved):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    rows = candidate_rows(out)
    assert rows[0].split()[0] == CREATED_TIED[1]
    assert rows[1].split()[0] == CREATED_TIED[0]


def test_brief_one_block_per_header_separated_by_one_blank_line(tmp_path: Path) -> None:
    """The page's shape is part of the contract: one blank line, and only one, between blocks.

    A blank line inside a body (a purpose file with a paragraph break, say) is content; the
    separators are what a reader of the page counts. The fixture's body has no blank line of
    its own, so the two blank lines of the page are the two separators and nothing else.
    """
    code, out, _ = run_brief(plant_brief_tree(tmp_path), "--now", NOW)
    assert code == 0
    # Two separators and nothing else: after the 21-line purpose block and after the
    # 10-line order block. A blank line inside a body would add a third index, which is how
    # this case tells a separator from content that happens to be empty.
    assert [index for index, line in enumerate(out.splitlines())
            if not line.strip()] == [22, 34]
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


def test_brief_two_runs_one_tree_one_instant_are_equal_bytes(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    assert run_brief(root, "--now", NOW) == run_brief(root, "--now", NOW)


def test_brief_a_title_shaped_like_a_header_is_body_text(tmp_path: Path) -> None:
    """A candidate titled exactly ``candidates`` cannot open a second block.

    The word is the page's own and the reader of the page splits on it, so the row is
    dropped rather than printed: an idea whose name cannot be told from the list's own title
    is worth less than a page a reader can still find the blocks of.
    """
    root = plant_brief_tree(tmp_path)
    path = item_path(root, "idea-0001")
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw.replace("Cache the census result",
                                brief_module.CANDIDATES_HEADER), encoding="utf-8")
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    assert out.count(brief_module.CANDIDATES_HEADER + "\n") == 1
    assert not any(row.startswith("idea-0001 ") for row in candidate_rows(out))


def test_brief_a_purpose_line_shaped_like_a_header_is_dropped(tmp_path: Path) -> None:
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
