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
    order_path,
    plant_brief_tree,
    run_brief,
)
from brief_support import (
    HEADERS,
    census_summary,
    sections,
    stripped,
    summary_line,
)

from noni import brief as brief_module


def test_brief_intent_absent_prints_not_readable(tmp_path: Path) -> None:
    root = plant_brief_tree(tmp_path)
    intent_path(root).unlink()
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    assert stripped(sections(out), brief_module.PURPOSE_HEADER) == [NOT_READ]
    assert len(stripped(sections(out), brief_module.ORDER_HEADER)) == \
        brief_module.TOP_ENTRIES


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
    assert len(stripped(sections(out), brief_module.PURPOSE_HEADER)) == \
        brief_module.PURPOSE_MAX_LINES + 2


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


def test_brief_the_item_store_never_changes_the_page(tmp_path: Path) -> None:
    """Every fault the store can hold costs the page nothing, because the page reads none of it.

    The brief stopped listing candidates, so the store is no longer an input to the page: an
    absent directory, one that is a plain file, a file of bytes no reader can parse, and a
    directory that is a link out of the tree all print the same blocks as the pristine tree does,
    at exit 0 and with stderr empty. The suite keeps the cases the listing needed for one reason:
    they are what says the page is independent of the store rather than merely lucky about it. The
    census still reads the store for its own rows, which is why the verdict line is asked of the
    census for each tree rather than compared to the pristine one.
    """
    pristine = plant_brief_tree(tmp_path / "pristine")
    before = run_brief(pristine, "--now", NOW)[1]

    cases = {}

    def variant(name: str) -> Path:
        root = plant_brief_tree(tmp_path / name)
        cases[name] = root
        return root

    shutil.rmtree(variant("absent") / ITEMS_REL)

    store = variant("file") / ITEMS_REL
    shutil.rmtree(store)
    store.write_text("not a directory\n", encoding="utf-8")

    broken = variant("broken")
    (broken / ITEMS_REL / "idea-0001.json").write_bytes(b"{ broken\n")

    linked = variant("linked")
    outside = tmp_path / "outside-store"
    outside.mkdir()
    (outside / "idea-0099.json").write_text(
        "{\"id\": \"idea-0099\", \"title\": \"Idea that lives outside the tree\"}\n",
        encoding="utf-8")
    shutil.rmtree(linked / ITEMS_REL)
    (linked / ITEMS_REL).symlink_to(outside)

    for name, root in cases.items():
        code, out, err = run_brief(root, "--now", NOW)
        assert code == 0, (name, code, err)
        assert err == "", (name, err)
        # The blocks are the brief's own reads and none of them opens the store, so they are the
        # bytes of the pristine page. The verdict is the one line that may differ, because the
        # arbiter does read the store and a store of no files is not the same claim about a tree as
        # a store of twelve.
        assert out.splitlines()[:-1] == before.splitlines()[:-1], name
        assert "Idea that lives outside the tree" not in out, name
        assert summary_line(out) == census_summary(root, NOW), name


def test_brief_three_reads_failed_at_once_still_prints_the_verdict(tmp_path: Path) -> None:
    """Nothing readable is still a page: two headers and the arbiter's line."""
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
    assert summary_line(out) == census_summary(root, NOW)


def test_brief_an_empty_state_root_is_a_page_not_a_failure(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    code, out, err = run_brief(root, "--now", NOW)
    assert code == 0
    assert err == ""
    assert list(sections(out)) == HEADERS
    assert summary_line(out).startswith(brief_module.SUMMARY_PREFIX)
