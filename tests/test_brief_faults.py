"""The brief suite, part 3 of 6: what one read failure costs.

Each block words its own artifact's state, one unreadable file costs its own row and
nothing else, and the verdict line prints whatever the census said a moment later.
"""


from __future__ import annotations

import shutil
from pathlib import Path

from brief_fixtures import (
    NOT_READ,
    NOW,
    intent_path,
    ledger_dir,
    ledger_record_path,
    order_path,
    plant_brief_tree,
    record_document,
    run_brief,
    write_record,
)
from brief_support import (
    HEADERS,
    census_summary,
    rows,
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


def test_brief_three_reads_failed_at_once_still_prints_the_verdict(tmp_path: Path) -> None:
    """Nothing readable is still a page: two headers and the arbiter's line."""
    root = plant_brief_tree(tmp_path)
    intent_path(root).unlink()
    order_path(root).unlink()
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


# --- the decision ledger's own fault arms -----------------------------------

# The words the brief has for the two states of an artifact it reads: nothing to
# list and nothing readable. The ledger block has one of them and not the other, which
# is what the arms below pin from both sides.


def test_brief_ledger_absent_prints_an_empty_decisions_block(tmp_path: Path) -> None:
    """No ledger directory is no decisions -- the state a freshly attached project is in.

    The whole directory goes, which is the shape of a tree that has never been steered. The
    header prints alone, nothing on the page reads :data:`NOT_READ`, and the exit code is 0: the
    census's ``ledger-empty`` class is the row that says a ledger is missing, and this page says
    only that it has nothing to show.
    """
    root = plant_brief_tree(tmp_path)
    shutil.rmtree(ledger_dir(root))
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    assert stripped(sections(out), brief_module.RECENT_DECISIONS_HEADER) == []
    assert NOT_READ not in out
    assert len(stripped(sections(out), brief_module.ORDER_HEADER)) == \
        brief_module.TOP_ENTRIES


def test_brief_ledger_empty_prints_an_empty_decisions_block(tmp_path: Path) -> None:
    """A ledger directory holding no record is the same answer as no directory at all.

    The census draws the distinction (``absent`` against ``empty``) and the brief does not: a
    project that has attached and not yet steered has no decision to show, and that is the
    honest content of the block rather than a fault in it.
    """
    root = plant_brief_tree(tmp_path)
    for path in ledger_dir(root).iterdir():
        path.unlink()
    assert ledger_dir(root).is_dir()
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    assert stripped(sections(out), brief_module.RECENT_DECISIONS_HEADER) == []
    assert NOT_READ not in out


def test_brief_ledger_of_no_json_records_prints_an_empty_block(tmp_path: Path) -> None:
    """A directory of files that are not records holds no records, and costs no row.

    The reader lists ``*.json`` and nothing else, which is the same closed set the census's
    ledger classes read. A stray note or a backup file beside the records is not a decision and
    does not earn a line of the screen.
    """
    root = plant_brief_tree(tmp_path)
    for path in ledger_dir(root).iterdir():
        path.unlink()
    (ledger_dir(root) / "notes.md").write_text("not a record\n", encoding="utf-8")
    (ledger_dir(root) / "record.json.bak").write_text("{}\n", encoding="utf-8")
    assert stripped(sections(run_brief(root, "--now", NOW)[1],
                            ), brief_module.RECENT_DECISIONS_HEADER) == []


def test_brief_ledger_that_is_a_symlink_prints_an_empty_block(tmp_path: Path) -> None:
    """A ledger reached through a link is refused, never followed, and prints no row.

    The link's target is a ledger of two live records held outside the state root. A reader that
    classified with :meth:`pathlib.Path.is_dir` would follow the link and print those records as
    the tree's own decisions; the ``lstat`` classifier the whole family uses refuses the path
    instead, and the block says nothing rather than printing somebody else's decisions.
    """
    outside = tmp_path / "outside-ledger"
    outside.mkdir()
    for index, record_id in enumerate(("2026-10-20-linked-one", "2026-10-21-linked-two")):
        write_record(outside.parent / "outside-seed", record_document(
            record_id, f"2026-10-2{index}T00:00:00Z"))
    root = plant_brief_tree(tmp_path)
    shutil.rmtree(ledger_dir(root))
    ledger_dir(root).symlink_to(ledger_dir(outside.parent / "outside-seed"))
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    body = stripped(sections(out), brief_module.RECENT_DECISIONS_HEADER)
    assert body == []
    assert "linked" not in out


def test_brief_ledger_that_is_a_plain_file_prints_an_empty_block(tmp_path: Path) -> None:
    """A non-directory at the ledger path is not a ledger, and the block says nothing.

    The census's ``ledger-empty`` class words that state (``not a directory``); the page's answer
    is the header alone, because there is no record to print and no half-read ledger to warn about.
    """
    root = plant_brief_tree(tmp_path)
    shutil.rmtree(ledger_dir(root))
    ledger_dir(root).write_text("not a directory\n", encoding="utf-8")
    assert stripped(sections(run_brief(root, "--now", NOW)[1]),
                    brief_module.RECENT_DECISIONS_HEADER) == []


def test_brief_ledger_records_that_are_unreadable_cost_only_their_rows(
        tmp_path: Path) -> None:
    """Every unreadable shape costs its own record its row and nothing else.

    Four records planted beside the fixture's live one: bytes that are not UTF-8, text that is not
    JSON, a JSON array where an object belongs, and a record that is a symlink out of the tree.
    None of them reaches the screen, none of them prints its own bytes or an exception's text, and
    the live record beside them still prints -- the brief's rule that a read failure costs its own
    row, applied to a ledger the page has no verdict about.
    """
    root = plant_brief_tree(tmp_path)
    # The fixture's own record stays in the ledger and is the newest live one after the planted
    # row, so it is the second line of the block: the fault of an unreadable neighbour must not
    # cost a readable record its row either.
    live = write_record(root, record_document("2026-10-25-live", "2026-10-25T00:00:00Z",
                                              answer="the live answer"))
    ledger_record_path(root, "2026-10-24-not-utf8").write_bytes(b"{\"a\": \xff\xfe}\n")
    ledger_record_path(root, "2026-10-23-not-json").write_text("{ nope\n", encoding="utf-8")
    ledger_record_path(root, "2026-10-22-array").write_text("[1, 2, 3]\n", encoding="utf-8")
    outside = tmp_path / "outside-record.json"
    outside.write_text('{"id": "2026-10-21-linked", "questions": '
                       '[{"text": "THE LINKED RECORD", "answer": "yes"}]}\n',
                       encoding="utf-8")
    ledger_record_path(root, "2026-10-21-linked").symlink_to(outside)
    code, out, _ = run_brief(root, "--now", NOW)
    assert code == 0
    body = rows(out, brief_module.RECENT_DECISIONS_HEADER)
    assert body == [f"{live.stem}: Ship the candidate?: the live answer",
                    "2026-10-01-brief: What should the run brief first?: the three newest"]
    for marker in ("THE LINKED RECORD", "not-utf8", "not-json", "array"):
        assert marker not in out
    # Four records were asked for and none could be rendered, and the block says so on its own
    # count line: a ledger fault leaves a mark on the page rather than passing silently, which is
    # what tells a reader who counts one row where five files sit that four of them were unreadable
    # rather than not decided.
