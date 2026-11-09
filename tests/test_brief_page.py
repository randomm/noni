"""The brief suite, part 1 of 6: what the committed fixture renders.

The four blocks, their rows, and the shape of the printed page: one header per block,
one blank line between two blocks that printed something, and the body text a foreign
line is not mistaken for a header.
"""


from __future__ import annotations

import json
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
    order_path,
    plant_brief_tree,
    run_brief,
    write_item,
)
from brief_support import (
    DROPPED_PREFIX,
    HEADERS,
    candidate_rows,
    sections,
    stripped,
    summary_line,
)

from noni import brief as brief_module
from noni import itemschema, orderschema


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
    # The idea did not vanish quietly: the block says it withheld one row, so a reader of the
    # list can tell a store of nine ideas from a store of ten whose one idea could not be named.
    assert f"{DROPPED_PREFIX}1 line(s)" in out


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


def test_brief_a_title_of_only_control_bytes_costs_nothing_but_its_line(tmp_path: Path) -> None:
    """A title that leaves no visible text behind is a missing row, not an empty one.

    The row is composed of fields and a row whose title rendered to nothing would be a row of
    three fields, which a reader cutting the line by field would read as an idea with no title.
    :func:`noni.brief._page_line` refuses it and the block loses the row.
    """
    root = plant_brief_tree(tmp_path)
    item_path(root, "idea-0003").unlink()
    write_item(root, "idea-0003", "\x1b[31m\x1b\x0b", CREATED_NEWEST)
    rows = candidate_rows(run_brief(root, "--now", NOW)[1])
    assert "\x1b" not in run_brief(root, "--now", NOW)[1]
    assert not any(row.startswith("idea-0003 ") for row in rows)
    assert len(rows) == brief_module.TOP_CANDIDATES


def test_brief_a_row_whose_title_holds_control_bytes_keeps_its_text_and_drops_their_bytes(
        tmp_path: Path) -> None:
    """The control bytes of a foreign title never reach the terminal; the words still do.

    The bytes are planted as raw JSON bytes on the file rather than as a Python string written
    through a repr, so the case is about the tree's own bytes. :func:`noni._safe_text.safe_text`
    drops every category-C character, which is what stops an OSC or CSI sequence opening a
    colour or moving the cursor on a screen the brief promises is only a listing. What survives
    the drop is the idea's own words, which is the point of the block: a screen that hid the row
    instead would have lost the idea rather than the escape.
    """
    root = plant_brief_tree(tmp_path)
    # The words of the idea with an OSC sequence, a CSI sequence, a bell and a vertical tab cut
    # into them, written as the file's own bytes. ``ensure_ascii=False`` means the store's writer
    # would print these bytes the same way, so the tree is one a real store could hold.
    smuggled = "Keep the \x1b]0;owned\x07 order \x1b[31m short"
    item_path(root, "idea-0007").unlink()
    write_item(root, "idea-0007", smuggled, "2026-10-24T08:00:00Z")
    code, out, err = run_brief(root, "--now", NOW)
    assert code == 0
    assert err == ""
    for byte in ("\x1b", "\x00", "\x07", "\x0b"):
        assert byte not in out
    row = [row for row in candidate_rows(out) if row.startswith("idea-0007 ")]
    assert len(row) == 1
    # The idea is still listed, with its own words: what the row lost is the escape, not the
    # candidate. The printable fragments of the planted title are all still there.
    assert row[0].startswith("idea-0007 candidate 2026-10-24T08:00:00Z ")
    for word in ("Keep", "the", "order", "short"):
        assert word in row[0]


def test_brief_a_citation_that_is_not_an_id_prints_the_citation_it_was_given(tmp_path: Path) -> None:
    """An entry citing a name the store would not name a file for still prints that name.

    The order's reader insists on an id and refuses the artifact outright, so this is not a state
    the block ever reaches by reading the file -- it is the state the row's own shape rule has to
    keep honest, tested where the rule lives. A citation is an identifier and the row prints the
    citation the artifact holds; it is not filtered, replaced or guessed at, and the row is one
    line that says what the store does not hold.
    """
    assert brief_module._citation("not an id at all") == "not an id at all"
    # The row built from it is the one shape the block has for an idea it could not read.
    entry = {"item": "not an id at all", "decision": "d", "confirmed": "c"}
    root = plant_brief_tree(tmp_path)
    assert brief_module._order_row(root, 3, entry) == "3. item not an id at all not found"


def test_brief_a_citation_with_control_bytes_prints_nothing_of_them(tmp_path: Path) -> None:
    """A citation carrying escape bytes reaches the screen with nothing of them left.

    The order's reader insists that an item citation be an identifier shaped like a file stem, so
    a name carrying an ESC never arrives at the row by way of a file this tool read -- the artifact
    is refused before any row is built, which is the right answer and is the case the faults suite
    holds. What remains, and what this case holds, is the rule the row is composed by: the page
    prints the citation of an idea it could not read, and a citation is text somebody typed. Unren-
    dered it would put an escape sequence on the terminal -- an OSC sequence could retitle the
    window, a CSI sequence could colour the rest of the page, a next-line byte could add rows the
    census never counted -- so the citation goes through the same renderer a title does, at the
    store's own id bound, and keeps the words that identify the idea the store lacks.
    """
    smuggled = "idea-0007" + chr(0x1b) + "[31m" + chr(0x07) + chr(0x85)
    shown = brief_module._citation(smuggled)
    assert_no_control_bytes(shown)
    # The printable half survives, escape bytes and their arguments gone: the reader still learns
    # which idea the store does not hold.
    assert shown == "idea-0007[31m"
    # And the row is the one shape the block has for an idea it could not read.
    entry = {"item": smuggled, "decision": "d", "confirmed": "c"}
    root = plant_brief_tree(tmp_path)
    assert brief_module._order_row(root, 11, entry) == "11. item idea-0007[31m not found"


def test_brief_a_citation_that_leaves_nothing_to_print_is_named_not_left_blank(
        tmp_path: Path) -> None:
    """A citation the renderer leaves nothing of prints the tool's word, not a hole.

    The row is built from the citation, so a citation the renderer left nothing of would have
    printed ``item  not found``: a row with a gap where its subject goes, which a reader could take
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
    assert row == f"11. item {brief_module.NOT_READ} not found"
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


def order_rows(page: str) -> list[str]:
    """The ``top 10`` block's body lines, in the artifact's own order."""
    return stripped(sections(page), brief_module.ORDER_HEADER)


def _cited_item(root: Path, position: int) -> str:
    """The citation of the ``position``th entry of the artifact as the reader decoded it."""
    from noni import orderstate

    read = orderstate.read_order(order_path(root))
    assert isinstance(read, orderstate.OrderOk), _read_headline(root)
    return read.entries[position - 1]["item"]


def _read_headline(root: Path) -> str:
    """The order reader's own words about one artifact, "" when it read the file."""
    from noni import orderstate

    return getattr(orderstate.read_order(order_path(root)), "headline", "")


def _splice_citation(root: Path, cited: str) -> None:
    """Splice ``cited`` into the fixture's one item citation, as a hand edit of the artifact.

    Three rules decide the shape, and each is this case's point:

    - The citation is substituted as the *rendered* JSON value rather than by re-rendering the
      document. The strict JSON reader the block's own reader uses decodes those escapes back into
      the control characters the page then has to render away -- a control byte cannot be planted
      as a raw byte at all, since the artifact is JSON.
    - The name stays one the order's reader accepts. An item citation is an identifier shaped like a
      file stem and the artifact's text is escaped, not rejected, which is exactly what makes the
      case worth testing; a name the reader refused would be the block's unreadable answer instead,
      and that fault is covered in the faults suite.
    - Only this one value changes: the other ten entries, their record citations and the file's
      layout stay exactly as the committed fixture holds them, so the verdict line the page ends
      with stays the fixture's and this stays a case about the row.
    """
    path = order_path(root)
    document = json.loads(path.read_text(encoding="utf-8"))
    entry = next(entry for entry in document["entries"] if "item" in entry)
    old = json.dumps(entry["item"])
    text = path.read_text(encoding="utf-8")
    assert old in text, "the fixture's item citation is not the bytes this splice expects"
    path.write_text(text.replace(old, json.dumps(cited), 1), encoding="utf-8")

    entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
    assert orderschema.entry_item(next(e for e in entries if "item" in e)) == cited, (
        "the planted citation did not reach the artifact the brief reads")
    assert _read_headline(root) == "", (
        "the planted citation made the whole artifact unreadable; the case must reach the row, "
        "and an unreadable artifact is the block's own fault case")


def test_brief_the_widest_item_the_store_allows_prints_every_field(tmp_path: Path) -> None:
    """An id and a title both at the store's bound reach the row whole.

    The widest item the store can hold is an id of eighty characters and a title of two hundred; both
    are legal, and both are the fields the reader of the list cuts the line by. A row that quietly
    dropped or clipped one of them would print an idea under half its name, so this case plants the
    widest item the schema allows and asks that all four fields arrive.
    """
    longest_id = "z" * itemschema.ID_MAX
    longest_title = "W" * itemschema.TITLE_MAX
    stamp = "2027-01-01T00:00:00Z"
    root = plant_brief_tree(tmp_path)
    write_item(root, longest_id, longest_title, stamp)
    out = run_brief(root, "--now", NOW)[1]
    rows = [row for row in candidate_rows(out) if row.startswith(longest_id + " ")]
    assert len(rows) == 1
    assert rows[0] == (f"{longest_id} {itemschema.STATUS_CANDIDATE} {stamp} {longest_title}")


def test_brief_a_row_is_never_longer_than_the_bound_the_tool_states(tmp_path: Path) -> None:
    """Every row of the block obeys the bound the tool states for a row.

    A row is four fields joined by three spaces, so the longest row the page may print is the sum of
    the four bounds it composes plus those separators -- a number the tool states as
    :data:`noni.brief.ROW_FIELD_LIMITS` and :data:`noni.brief.ROW_FIELD_SEPARATORS` rather than as a
    total a reader has to add up by hand. The bound is asked of every row the page prints, the widest
    planted item included, because a bound nobody measures is a number somebody wrote down once: the
    day a field's own limit changes and the row stops obeying it, this is the case that says so.
    """
    bound = sum(brief_module.ROW_FIELD_LIMITS) + brief_module.ROW_FIELD_SEPARATORS
    widest_id = "z" * itemschema.ID_MAX
    root = plant_brief_tree(tmp_path)
    write_item(root, widest_id, "W" * itemschema.TITLE_MAX, "2027-01-01T00:00:00Z")
    out = run_brief(root, "--now", NOW)[1]
    rows = candidate_rows(out)
    assert widest_id in [row.split()[0] for row in rows]
    assert all(len(row) <= bound for row in rows), [len(row) for row in rows]
    # The widest idea the store allows prints every field whole rather than inside the bound by
    # having something dropped from it: an id of eighty characters, the status word, the stamp and a
    # title of two hundred characters all arrive, which is the row the four bounds were chosen to
    # hold.
    widest = [row for row in rows if row.startswith(widest_id + " ")][0]
    assert widest == (f"{widest_id} {itemschema.STATUS_CANDIDATE} 2027-01-01T00:00:00Z "
                      + "W" * itemschema.TITLE_MAX)
    assert widest.count(" ") == brief_module.ROW_FIELD_SEPARATORS


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
