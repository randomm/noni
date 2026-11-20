"""The brief suite, part 5 of 6: the standing rules, the empty order, the word clip.

Three claims the page makes above its blocks (issue #196):

- **The standing rules print first.** The page is the payload a hook injects at session
  start, so it opens with the three lines that tell an agent where direction comes from.
  They are the tool's own constants, they print above the line budget, and the budget
  cannot cut them.
- **An empty order says so.** An order artifact that is absent or holds no entries prints
  its header and one fixed line, and that line is reserved so no foreign body line can
  impersonate it. An artifact that is there and unreadable keeps its own answer.
- **A clipped head ends on a word.** The head of a too-long row is cut at the last space
  that fits rather than mid-word, and still carries the clip mark.

The budget cases in ``test_brief_limits.py`` cut the same page from the other side; this
file holds the lines the page prints before and inside those blocks.
"""


from __future__ import annotations

from pathlib import Path

import brief_page_rows
from brief_fixtures import (
    NOW,
    RECORD_ID,
    ledger_dir,
    order_path,
    plant_brief_tree,
    record_document,
    run_brief,
    write_order_entries,
    write_record,
)
from brief_support import HEADERS, page_owed_lines, rows, sections, stripped
from quickstart_page import product_section_7

from noni import brief as brief_module
from noni import brief_page, orderschema

# --- the standing rules ------------------------------------------------------


def test_brief_the_standing_rules_are_three_plain_lines() -> None:
    """Three rules, one line each, worded once as module constants.

    The page is a payload an injected hook prints into somebody else's context, so the
    rules it carries name no harness, no tool outside noni and no project, and each is
    one line: a rule that wraps is a rule a budget can cut in half.
    """
    assert len(brief_module.STANDING_RULES) == 3
    for rule in brief_module.STANDING_RULES:
        assert isinstance(rule, str)
        assert rule.strip() == rule, rule
        assert "\n" not in rule and "\r" not in rule, repr(rule)
        assert "\u2014" not in rule, f"an em dash in a standing rule: {rule!r}"
    # Each of the three claims the page exists to carry is in the rules, by its subject.
    joined = " ".join(brief_module.STANDING_RULES).lower()
    for subject in ("noni", "order", "decide"):
        assert subject in joined, f"no standing rule names {subject!r}: {joined!r}"


def test_brief_the_standing_rules_print_first_and_exactly(tmp_path: Path) -> None:
    """The page opens with the three rules, in the module's own order, then a blank line."""
    code, out, _ = run_brief(plant_brief_tree(tmp_path), "--now", NOW)
    assert code == 0
    lines = out.splitlines()
    assert lines[:3] == list(brief_module.STANDING_RULES)
    assert lines[3] == ""
    assert lines[4] == brief_module.PURPOSE_HEADER


def test_brief_the_standing_rules_are_outside_the_blocks(tmp_path: Path) -> None:
    """The rules are not a block's body: the page still splits into its three blocks.

    A reader of the page counts headers, and the rules sit above the first of them. If a
    rule line ever landed inside a block the section reader would hand it back as content.
    """
    out = run_brief(plant_brief_tree(tmp_path), "--now", NOW)[1]
    blocks = sections(out)
    assert list(blocks) == HEADERS
    for header in HEADERS:
        for rule in brief_module.STANDING_RULES:
            assert rule not in blocks[header]
    assert out.splitlines().index(brief_module.PURPOSE_HEADER) == 4


def test_brief_the_standing_rules_survive_the_deepest_cut(tmp_path: Path) -> None:
    """The budget cuts blocks and never the rules: past every block line they still print.

    The truncation order in :func:`noni.brief._render` drops block lines only, and the
    rules are prepended after the budget has run. A page cut deeper than every block line
    it can still print opens with the three rules, so the shape a hook injects never
    arrives ruleless.
    """
    root = plant_brief_tree(tmp_path)
    # A debt deeper than the whole page of blocks: the blocks are left as their headers
    # and the count line, which is the cut the rules would be swallowed by if they were
    # budgeted like a block.
    out = page_owed_lines(root, 30)
    assert out.splitlines()[:3] == list(brief_module.STANDING_RULES)
    assert out.splitlines()[3] == ""
    assert out.splitlines()[4] == brief_module.PURPOSE_HEADER
    # The cut reached everything the budget can take: the decisions block and the queue
    # are down to their headers, and the debt went into the purpose prose.
    assert rows(out, brief_module.RECENT_DECISIONS_HEADER) == []
    assert rows(out, brief_module.ORDER_HEADER) == []
    assert len(rows(out, brief_module.PURPOSE_HEADER)) < brief_module.PURPOSE_MAX_LINES


# --- the empty order ---------------------------------------------------------


def test_brief_the_empty_order_line_is_reserved() -> None:
    """The tool's own sentence about an empty order cannot be impersonated by the order.

    ``PAGE_RESERVED`` is the set no body line may equal. The empty-order line is printed
    by the tool under its own header, so an entry rendered to that same line would read as
    the tool's verdict about the queue.
    """
    assert brief_module.EMPTY_ORDER in brief_module.PAGE_RESERVED


def test_brief_the_empty_order_prints_one_line(tmp_path: Path) -> None:
    """The ``top 10`` header over one fixed line: an absent artifact and an empty one."""
    for name, plant in (("absent", lambda root: order_path(root).unlink()),
                        ("empty", lambda root: write_order_entries(root, []))):
        root = plant_brief_tree(tmp_path, name=name)
        plant(root)
        code, out, err = run_brief(root, "--now", NOW)
        assert code == 0 and err == ""
        assert stripped(sections(out), brief_module.ORDER_HEADER) == [
            brief_module.EMPTY_ORDER], name
        # Once, and only under its own header.
        assert out.count(brief_module.EMPTY_ORDER) == 1, name
        assert list(sections(out)) == HEADERS, name
        assert brief_module.NOT_READ not in out, name


def test_brief_an_unreadable_order_keeps_its_own_answer(tmp_path: Path) -> None:
    """The empty line is the answer to nothing to list, never to a read that failed.

    The two states the page distinguishes: an artifact that is not there prints the empty
    line, one that is there and cannot be read keeps printing :data:`NOT_READ`.
    """
    root = plant_brief_tree(tmp_path)
    order_path(root).write_text("{ not json\n", encoding="utf-8")
    out = run_brief(root, "--now", NOW)[1]
    assert stripped(sections(out), brief_module.ORDER_HEADER) == [
        brief_module.NOT_READ]
    assert brief_module.EMPTY_ORDER not in out


def test_brief_an_entry_rendering_to_the_empty_line_cannot_impersonate_it(
        tmp_path: Path) -> None:
    """A foreign order row shaped like the tool's empty line is dropped, and says it went.

    The reserved set is only worth having if the drop happens: an entry whose rendered row
    equals the tool's own sentence about an empty queue would print as that sentence.
    """
    root = plant_brief_tree(tmp_path)
    # A row is "{position}. #{issue} ({decision})" plus an optional reason, so the shape
    # can only be reached by a reason the row builder appends; plant one that completes
    # the line and check the page refuses the finished row rather than printing it.
    write_order_entries(root, [orderschema.entry(
        issue=4, decision=RECORD_ID, confirmed="2026-10-26T00:00:00Z",
        why=brief_module.EMPTY_ORDER)])
    out = run_brief(root, "--now", NOW)[1]
    body = stripped(sections(out), brief_module.ORDER_HEADER)
    assert brief_module.EMPTY_ORDER not in body


def test_brief_the_empty_order_line_survives_the_budget(tmp_path: Path) -> None:
    """The one line the empty order prints is a line of the page, and the budget keeps it.

    A debt deep enough to take every decision row still leaves the order its line: the
    block is never omitted, which is what the page's shape test asserts elsewhere.
    """
    root = plant_brief_tree(tmp_path)
    write_order_entries(root, [])
    # A debt the decisions block alone can pay: the order block gives nothing up, so its
    # one line is still on the cut page.
    out = page_owed_lines(root, 1)
    assert stripped(sections(out), brief_module.ORDER_HEADER) == [
        brief_module.EMPTY_ORDER]


# --- the word-boundary clip --------------------------------------------------


def test_brief_a_clipped_row_head_ends_on_a_word(tmp_path: Path) -> None:
    """A row whose head must be cut ends at a space, keeps the clip mark, and stays bounded.

    Driven at the builder with a head of words: the cut used to land mid-word, and the
    promise is about the printed row, so the assertion reads the row rather than the
    arithmetic that produced it.

    A head past the room the reason leaves (the mark plus the reason below), so the
    clip has to fire, and a head of one repeated phrase, so every word the clip keeps
    is one the reader can check against the original.
    """
    reason = "the operator's reason for the position"
    head = ("1. #12 (2026-10-01-brief) "
            + "the census stays the one arbiter " * 40)
    assert len(head) > brief_page.TEXT_LIMIT - len(
        brief_page.REASON_SEPARATOR + reason)
    row = brief_page._bounded_row(head, reason)
    assert row is not None
    assert brief_module.ELLIPSIS in row
    assert row.endswith(brief_page.REASON_SEPARATOR + reason)
    assert len(row) <= brief_page.TEXT_LIMIT
    # The clipper spends its three characters on the mark, so the row loses the space
    # the cut landed on: the character the head ends on is the last of a word the head
    # actually holds, never a prefix of one.
    clipped_head = row[: row.rindex(brief_module.ELLIPSIS)]
    assert clipped_head and clipped_head in head
    assert head.startswith(clipped_head)
    assert head[len(clipped_head)] == " ", repr(head[len(clipped_head)])


def test_brief_a_clipped_head_of_one_long_word_falls_back_to_the_character_clip() -> None:
    """A head with no space to cut at is still bounded and still marked.

    The word rule is a preference, not a promise the page can always keep: a head made of
    one unbroken token has no boundary to stop at, and the row must still arrive, bounded
    and carrying the mark, rather than nothing at all.
    """
    head = "x" * (brief_page.TEXT_LIMIT + 100)
    row = brief_page._bounded_row(head, "the operator's reason")
    assert row is not None
    assert row.endswith(brief_page.REASON_SEPARATOR + "the operator's reason")
    assert len(row) <= brief_page.TEXT_LIMIT
    head_part = row[: row.rindex(brief_module.ELLIPSIS)]
    assert set(head_part) == {"x"}


def test_brief_a_row_that_fits_is_clipped_by_nobody(tmp_path: Path) -> None:
    """The word rule is only reached by a head too long for the row: a short head is whole."""
    row = brief_page_rows.order_row(3, issue=7, decision=RECORD_ID,
                                    why="the release train leaves Friday")
    assert row == f"3. #7 ({RECORD_ID}) \u2014 the release train leaves Friday"
    assert brief_module.ELLIPSIS not in row


def test_brief_a_clipped_head_on_a_launched_order_row_ends_on_a_word(
        tmp_path: Path) -> None:
    """The launched page prints the word-boundary clip too, not only the builder.

    The longest reason a writer admits fills the row and forces the head to yield; the
    printed row is the one a reader of the screen sees, so the boundary is asserted there.
    """
    root = plant_brief_tree(tmp_path)
    # The longest reason a writer admits fills the row, which is what forces the head
    # to yield: past it the artifact refuses the entry and the block reads unreadable.
    reason = ("the operator " * 28 + "final answer")[:orderschema.why_max()]
    assert not reason.endswith(" ")
    write_order_entries(root, [orderschema.entry(
        issue=21, decision=RECORD_ID, confirmed="2026-10-26T00:00:00Z", why=reason)])
    row = rows(run_brief(root, "--now", NOW)[1], brief_module.ORDER_HEADER)[0]
    assert len(row) <= brief_page.TEXT_LIMIT
    assert brief_module.ELLIPSIS in row
    assert row.endswith(brief_page.REASON_SEPARATOR + reason)


def test_brief_a_clipped_decision_row_ends_on_a_word(tmp_path: Path) -> None:
    """The same rule on a decision row: the statement yields at a word, the reason survives."""
    root = plant_brief_tree(tmp_path)
    ledger_dir(root).joinpath(f"{RECORD_ID}.json").unlink()
    statement = "The census " + "stays the one arbiter " * 20
    write_record(root, record_document(
        "2026-10-25-long", "2026-10-25T00:00:00Z", question=statement,
        answer=statement, options=[statement], single_option=True,
        why="the census has the honest exit code"))
    row = rows(run_brief(root, "--now", NOW)[1],
               brief_module.RECENT_DECISIONS_HEADER)[0]
    assert row.endswith("\u2014 the census has the honest exit code")
    assert brief_module.ELLIPSIS in row
    assert len(row) <= brief_page.TEXT_LIMIT


# --- docs/PRODUCT.md section 7, read against the product constants ------------


def test_product_section_7_states_the_rules_and_the_empty_order_line() -> None:
    """The binding reference describes the page the tool actually prints.

    Section 7 is the reference AGENTS.md makes binding, and it is the page a reader of
    the brief trusts for what the screen prints. The claims are located against the
    product's own constants -- the rule lines, the empty-order sentence and the page's
    clip mark -- so a rename in the tool fails this page rather than leaving it quietly
    describing a page that no longer exists.
    """
    section = product_section_7()
    # The standing rules, named as what the page opens with, above the budget.
    assert "standing rules" in section
    assert "budget" in section
    # The three things the rules say, each in the words the tool itself prints.
    for rule in brief_module.STANDING_RULES:
        for token in _rule_tokens(rule):
            assert token in section, f"section 7 lost the rule's {token!r}: {rule!r}"
    # The empty order: the tool's own sentence, and the heading it sits under.
    assert brief_module.EMPTY_ORDER in section
    assert brief_module.ORDER_HEADER in section
    # The unreadable arm is still worded as its own answer, and the clip mark is named.
    assert brief_page.NOT_READ in section
    assert brief_module.ELLIPSIS in section


def _rule_tokens(rule: str) -> tuple[str, ...]:
    """The words of one standing rule that section 7 has to carry.

    The subject words rather than the whole sentence: the page states the rules in its
    own prose, and a locator pinned to the tool's wording would be pinned to a line
    break rather than to a claim.
    """
    return tuple(word for word in _RULE_TOKEN_MAP.get(rule, ()) if word)


# What each rule must be recognisable by, in the reference's own words: the artifact it
# points at, and the act it tells the reader to take or not take.
_RULE_TOKEN_MAP: dict[str, tuple[str, ...]] = {
    brief_module.STANDING_RULES[0]: ("noni", "direction", "order", "decisions"),
    brief_module.STANDING_RULES[1]: ("order", "decisions", "invent direction"),
    brief_module.STANDING_RULES[2]: ("operator", "noni decide"),
}


def test_product_section_7_carries_no_rule_it_cannot_back() -> None:
    """The reference still states the budget the tool enforces, and its truncation order.

    The section gained claims about the rules and the empty order; the numbers it already
    carried are the product's own caps, read from the tool here so the page cannot drift
    from them while the constants move.
    """
    section = product_section_7()
    for number in (str(brief_module.PURPOSE_MAX_LINES),
                   str(brief_module.TOP_ENTRIES),
                   str(brief_module.RECENT_DECISIONS),
                   str(brief_module.BRIEF_MAX_LINES)):
        assert number in section, f"section 7 no longer names the cap {number}"
