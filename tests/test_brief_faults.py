"""The brief suite, part 3 of 6: what one read failure costs.

Each block words its own artifact's state, one unreadable file costs its own row and
nothing else, and the verdict line prints whatever the census said a moment later.
"""


from __future__ import annotations

import shutil
from pathlib import Path

from brief_fixtures import (
    ITEMS_REL,
    NOT_READ,
    NOW,
    intent_path,
    item_path,
    order_path,
    plant_brief_tree,
    run_brief,
)
from brief_support import (
    HEADERS,
    candidate_rows,
    census_summary,
    sections,
    stripped,
    summary_line,
)

from noni import brief as brief_module

# The title of an idea that lives outside the tree. A symlink planted into the state root points
# at a file holding it, and the assertion of every such case is that this string never reaches
# stdout: a listing that read through the link would print the outside content and the case fails
# on the one line that makes it about the link rather than about a store that holds nothing.
OUTSIDE_TITLE = "Idea that lives outside the tree"


def test_brief_intent_absent_prints_not_readable(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    intent_path(root).unlink()
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    assert stripped(sections(out), brief_module.PURPOSE_HEADER) == [NOT_READ]
    assert len(stripped(sections(out), brief_module.ORDER_HEADER)) == \
        brief_module.TOP_ENTRIES
    assert len(candidate_rows(out)) == brief_module.TOP_CANDIDATES


def test_brief_intent_non_utf8_prints_not_readable(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    path = intent_path(root)
    path.unlink()
    path.write_bytes(b"\xff\xfe\x00not utf-8\n")
    assert run_brief(root, "--now", NOW)[1].count(NOT_READ) == 1
    assert stripped(sections(run_brief(root, "--now", NOW)[1]),
                    brief_module.PURPOSE_HEADER) == [NOT_READ]


def test_brief_intent_that_is_a_directory_prints_not_readable(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    path = intent_path(root)
    path.unlink()
    path.mkdir()
    assert stripped(sections(run_brief(root, "--now", NOW)[1]),
                    brief_module.PURPOSE_HEADER) == [NOT_READ]


def test_brief_intent_that_is_a_symlink_prints_not_readable(tmp_path: Path) -> None:
    """A link out of the tree is refused, not followed, and the block says so in one word."""
    root = plant_brief_tree(tmp_path)
    outside = tmp_path / "outside-intent.md"
    outside.write_text(intent_path(root).read_text(encoding="utf-8"), encoding="utf-8")
    intent_path(root).unlink()
    intent_path(root).symlink_to(outside)
    assert stripped(sections(run_brief(root, "--now", NOW)[1]),
                    brief_module.PURPOSE_HEADER) == [NOT_READ]


def test_brief_intent_past_its_line_cap_prints_not_readable(tmp_path: Path) -> None:
    from noni import intentschema

    root = plant_brief_tree(tmp_path)
    path = intent_path(root)
    filler = "\n".join(f"Filler line {index}." for index in range(intentschema.MAX_LINES))
    path.write_text(path.read_text(encoding="utf-8") + filler + "\n", encoding="utf-8")
    assert stripped(sections(run_brief(root, "--now", NOW)[1]),
                    brief_module.PURPOSE_HEADER) == [NOT_READ]


def test_brief_intent_malformed_prints_not_readable(tmp_path: Path) -> None:
    """A file the intent schema refuses reads as ``not readable``, never as its own text.

    The brief has no verdict of its own about a file it cannot interpret: the census's
    ``intent`` class is what names which state the tree is in, and this page says only that it
    could not read the section.
    """
    root = plant_brief_tree(tmp_path)
    path = intent_path(root)
    path.write_text(path.read_text(encoding="utf-8").replace("## Purpose", "## Purposex"),
                    encoding="utf-8")
    out = run_brief(root, "--now", NOW)[1]
    assert stripped(sections(out), brief_module.PURPOSE_HEADER) == [NOT_READ]
    assert "Purposex" not in out


def test_brief_order_absent_prints_an_empty_top_block(tmp_path: Path) -> None:
    """An absent artifact is the empty order -- the state the first ``add`` extends.

    The order's own arbiter answers ``OrderOk`` with no entries for a file that is not there,
    so the header prints alone and the other two blocks keep their content. The distinction
    the spec asks for: nothing read is :data:`NOT_READ`, and nothing to list is an empty block.
    """
    root = plant_brief_tree(tmp_path)
    order_path(root).unlink()
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    assert stripped(sections(out), brief_module.ORDER_HEADER) == []
    assert NOT_READ not in out
    assert len(candidate_rows(out)) == brief_module.TOP_CANDIDATES


def test_brief_order_malformed_prints_not_readable(tmp_path: Path) -> None:
    """A file that is there and cannot be read is a different answer from an absent one."""
    root = plant_brief_tree(tmp_path)
    order_path(root).write_text("{ not json\n", encoding="utf-8")
    assert stripped(sections(run_brief(root, "--now", NOW)[1]),
                    brief_module.ORDER_HEADER) == [NOT_READ]


def test_brief_order_non_canonical_prints_not_readable(tmp_path: Path) -> None:
    """A well-formed order the writer would render differently is refused, and so unreadable.

    The arbiter refuses to overwrite an order it did not produce; the brief has nothing to
    print for that state but the one word, because the artifact is the census's to report on.
    """
    root = plant_brief_tree(tmp_path)
    order_path(root).write_bytes(order_path(root).read_bytes().replace(b"  ", b"    ", 1))
    assert stripped(sections(run_brief(root, "--now", NOW)[1]),
                    brief_module.ORDER_HEADER) == [NOT_READ]


def test_brief_order_that_is_a_directory_prints_not_readable(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    order_path(root).unlink()
    order_path(root).mkdir()
    assert stripped(sections(run_brief(root, "--now", NOW)[1]),
                    brief_module.ORDER_HEADER) == [NOT_READ]


def test_brief_items_absent_prints_an_empty_candidates_block(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    shutil.rmtree(root / ITEMS_REL)
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    assert candidate_rows(out) == []
    assert len(stripped(sections(out), brief_module.ORDER_HEADER)) == 10


def test_brief_items_directory_that_is_a_file_prints_an_empty_block(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    items = root / ITEMS_REL
    shutil.rmtree(items)
    items.write_text("not a directory\n", encoding="utf-8")
    assert candidate_rows(run_brief(root, "--now", NOW)[1]) == []


def test_brief_one_malformed_item_costs_only_its_own_row(tmp_path: Path) -> None:
    """A single bad file is one row lost, not the block.

    The census's items group refuses a store holding a malformed file -- the store's arbiter
    fails closed on it. The brief's rule is narrower and ``brief_items`` says so: a listing
    drops what it could not read and keeps the ideas it could, because a screen is not a gate.
    """
    root = plant_brief_tree(tmp_path)
    item_path(root, "idea-0009").write_text("{ broken\n", encoding="utf-8")
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    # The cap counts rows the block could build, so the eleventh candidate fills in behind
    # the broken one: nine rows is a block that stopped at the fault, and ten is a block that
    # read the store.
    rows = candidate_rows(out)
    assert len(rows) == brief_module.TOP_CANDIDATES
    assert not any(row.startswith("idea-0009 ") for row in rows)
    assert any(row.startswith("idea-0010 ") for row in rows)


def test_brief_one_unreadable_item_costs_only_its_own_row(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    item_path(root, "idea-0007").write_bytes(b"\xff\xfe not utf-8\n")
    rows = candidate_rows(run_brief(root, "--now", NOW)[1])
    assert len(rows) == brief_module.TOP_CANDIDATES
    assert not any(row.startswith("idea-0007 ") for row in rows)


def test_brief_an_item_whose_id_disagrees_with_its_stem_is_no_row(tmp_path: Path) -> None:
    """The id is what the row prints, so an idea listed under a name its file denies is dropped."""
    root = plant_brief_tree(tmp_path)
    path = item_path(root, "idea-0005")
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw.replace('"id": "idea-0005"', '"id": "idea-0099"'), encoding="utf-8")
    rows = candidate_rows(run_brief(root, "--now", NOW)[1])
    assert not any(row.startswith(("idea-0005 ", "idea-0099 ")) for row in rows)
    assert len(rows) == brief_module.TOP_CANDIDATES


def test_brief_a_title_that_would_make_one_file_two_rows_is_dropped(tmp_path: Path) -> None:
    """A title carrying a newline would break the one-row-per-idea shape; the row goes."""
    root = plant_brief_tree(tmp_path)
    path = item_path(root, "idea-0003")
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw.replace("Show the kill list beside the queue", "two\nrows"),
                    encoding="utf-8")
    rows = candidate_rows(run_brief(root, "--now", NOW)[1])
    assert not any(row.startswith("idea-0003 ") for row in rows)
    assert len(rows) == brief_module.TOP_CANDIDATES


def test_brief_a_symlinked_store_is_not_read_through(tmp_path: Path) -> None:
    """A store that is a link out of the tree contributes nothing, and its bytes stay unseen.

    The listing classifies ``noni/items/`` with the lstat of :func:`noni.orderstate.file_kind`,
    the way :mod:`noni.item_reads` classifies every path it opens. ``Path.is_file`` follows a
    link and answers True for the file at its far end, so a store that is a link to a directory
    elsewhere would have been listed and printed as though the tree held those ideas.
    """
    root = plant_brief_tree(tmp_path)
    outside = tmp_path / "outside-store"
    outside.mkdir()
    smuggled = item_path(root, "idea-0001").read_text(encoding="utf-8")
    (outside / "idea-0099.json").write_text(
        smuggled.replace("idea-0001", "idea-0099")
        .replace("Cache the census result", OUTSIDE_TITLE), encoding="utf-8")
    shutil.rmtree(root / ITEMS_REL)
    (root / ITEMS_REL).symlink_to(outside)
    code, out, err = run_brief(root, "--now", NOW)
    assert code == 0
    assert err == ""
    assert candidate_rows(out) == []
    assert OUTSIDE_TITLE not in out


def test_brief_a_symlinked_item_is_not_read_through(tmp_path: Path) -> None:
    """One item file that is a link out of the tree is no row, and its text never prints.

    The sibling of the case above: the directory and the file are classified apart, so a tree
    whose store is a plain directory holding one link must lose that row and nothing else. The
    other nine ideas are still listed, which is what separates "this file is not a candidate"
    from "this store could not be read".
    """
    root = plant_brief_tree(tmp_path)
    outside = tmp_path / "outside-item.json"
    smuggled = item_path(root, "idea-0001").read_text(encoding="utf-8")
    outside.write_text(smuggled.replace("idea-0001", "idea-0001")
                       .replace("Cache the census result", OUTSIDE_TITLE),
                       encoding="utf-8")
    item_path(root, "idea-0001").unlink()
    item_path(root, "idea-0001").symlink_to(outside)
    code, out, err = run_brief(root, "--now", NOW)
    assert code == 0
    assert err == ""
    rows = candidate_rows(out)
    assert OUTSIDE_TITLE not in out
    assert not any(row.startswith("idea-0001 ") for row in rows)
    # The block still prints its ten rows because it never ran out of ideas: the store holds
    # eleven readable candidates once this one is refused, and the cap -- not the refusal -- is
    # what stops the block at ten. The assertion above is the one about the link.
    assert len(rows) == brief_module.TOP_CANDIDATES


def test_brief_a_subdirectory_of_the_store_is_not_a_candidate(tmp_path: Path) -> None:
    """A directory in the store is not an idea, and costs the block nothing.

    The counterweight of the pair: one more entry in the listing that is not a candidate and
    the block still holds its full ten rows, because a row is not lost when nothing was
    refused.
    """
    root = plant_brief_tree(tmp_path)
    (root / ITEMS_REL / "not-an-item").mkdir()
    assert len(candidate_rows(run_brief(root, "--now", NOW)[1])) == \
        brief_module.TOP_CANDIDATES


def test_brief_a_file_of_another_suffix_is_not_a_candidate(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    (root / ITEMS_REL / "notes.md").write_text("idea-9999\n", encoding="utf-8")
    rows = candidate_rows(run_brief(root, "--now", NOW)[1])
    assert len(rows) == brief_module.TOP_CANDIDATES
    assert not any("idea-9999" in row for row in rows)


def test_brief_a_status_the_store_does_not_know_is_not_a_candidate(tmp_path: Path) -> None:
    """Only the store's own ``candidate`` rows reach the block, whatever the file claims."""
    root = plant_brief_tree(tmp_path)
    path = item_path(root, "idea-0005")
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw.replace('"status": "candidate"', '"status": "wip"'),
                    encoding="utf-8")
    assert not any(row.startswith("idea-0005 ")
                   for row in candidate_rows(run_brief(root, "--now", NOW)[1]))


def test_brief_three_reads_failed_at_once_still_prints_the_verdict(tmp_path: Path) -> None:
    """Nothing readable is still a page: three headers and the arbiter's line."""
    root = plant_brief_tree(tmp_path)
    intent_path(root).unlink()
    order_path(root).unlink()
    shutil.rmtree(root / ITEMS_REL)
    code, out, err = run_brief(root, "--now", NOW)
    assert code == 0
    assert err == ""
    blocks = sections(out)
    assert stripped(blocks, brief_module.PURPOSE_HEADER) == [NOT_READ]
    assert stripped(blocks, brief_module.ORDER_HEADER) == []
    assert candidate_rows(out) == []
    assert summary_line(out) == census_summary(root, NOW)


def test_brief_an_empty_state_root_is_a_page_not_a_failure(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    code, out, err = run_brief(root, "--now", NOW)
    assert code == 0
    assert err == ""
    assert list(sections(out)) == HEADERS
    assert summary_line(out).startswith(brief_module.SUMMARY_PREFIX)
