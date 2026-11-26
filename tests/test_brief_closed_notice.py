"""The brief suite: the ``top 10`` block's closed-state notice.

The claim the file exists for (issue #241): a queue whose entries name issues was never read
against closed issues, because the brief runs the census with ``--repo`` and ``--now`` and can
never hand it an ``--issue-state`` map. A pilot run of an order that still listed closed issues
printed ten rows and a verdict line carrying a warning count with no row beside it, and nothing
on the screen told the reader the order had never been checked. The block now says so itself, in
one tool-authored line above the rows.

Split from ``test_brief_rules.py`` for the 500-line source cap -- the same seam that split
``src/noni/brief_page.py`` from the tool and this suite's other parts from each other. The empty
order's own line, the standing rules and the word clip stay in that file; the two lines the tool
prints under its own header are reserved vocabulary, and the empty order's reservation case is the
pattern the notice's is written against.

The sentence is always read from the product, never typed: a reword moves an assertion here
rather than leaving a copy of the sentence pinned to a page the tool no longer prints.
"""


from __future__ import annotations

from pathlib import Path

from brief_fixtures import (
    NOW,
    ORDER_WHY,
    RECORD_ID,
    order_path,
    plant_brief_tree,
    run_brief,
    write_order_entries,
)
from brief_support import page_owed_lines, rows, sections, stripped

from noni import brief as brief_module
from noni import brief_page


def _entry_rows(page: str) -> list[str]:
    """The ``top 10`` block's body without the tool's own notice line.

    A case here is about the notice or about the states that owe it none, and the rows are read
    whole. The notice is asserted by the constant, never by a copy of the sentence.
    """
    return [row for row in rows(page, brief_module.ORDER_HEADER)
            if row != brief_page.NOT_CHECKED_CLOSED]


def test_brief_an_order_of_issues_says_the_closed_check_never_ran(
        tmp_path: Path) -> None:
    """One plain line, once, over a queue the closed check never read.

    The reading this pins is the pilot's: ten rows of stale issues above a summary line whose
    warning count had no row beside it. The brief cannot pass the census an issue-state map, so
    for this page the check always goes unasked over an order of issues, and the block now says
    so in its own words. The line leads the block, prints once, and is the tool's sentence read
    from the tool rather than typed here.
    """
    root = plant_brief_tree(tmp_path)
    code, out, err = run_brief(root, "--now", NOW)
    assert code == 0 and err == ""
    body = stripped(sections(out), brief_module.ORDER_HEADER)
    assert body[0] == brief_page.NOT_CHECKED_CLOSED
    assert _entry_rows(out) == [f"1. #1 ({RECORD_ID}) \u2014 {ORDER_WHY}"] + [
        f"{n}. #{n} ({RECORD_ID})" for n in range(2, brief_module.TOP_ENTRIES + 1)]
    assert out.count(brief_page.NOT_CHECKED_CLOSED) == 1


def test_brief_the_notice_is_one_plain_sentence_of_the_tools_own() -> None:
    """The sentence is prose a reader parses, not a machine string: short, flat, and portable.

    The brief's page is injected into somebody else's context by a hook, so the line carries no
    em dash, no path, no harness name and no project name, and it stays a sentence a terminal
    shows on one line. The flag it names is the one that turns the check on, which is the whole
    remedy the line can offer a reader who cannot reach a tracker from here.
    """
    notice = brief_page.NOT_CHECKED_CLOSED
    assert notice == notice.strip() and "\n" not in notice
    assert len(notice) <= 160, repr(notice)
    assert "\u2014" not in notice and "was not evaluated" not in notice
    assert not notice.startswith(("http://", "https://", "/", "~"))
    assert "--issue-state" in notice
    # Nothing that reads as a path or a home directory: no slash outside the flag, no backslash.
    assert "/" not in notice.replace("--issue-state", "") and "\\" not in notice


def test_brief_an_order_that_names_no_issue_owes_no_notice() -> None:
    """An entry that names no issue leaves no closed state unstated, so the block says nothing.

    The predicate is the census's own, imported from :mod:`noni.census_ordering_closed` rather
    than retyped, so the shapes that arbiter refuses to raise a row for owe no line here either.
    Driven at the predicate rather than through a launched run because the artifact's own schema
    refuses an entry that names no subject: the only orders a run can hold are ones whose entries
    name issues, and the nameless, boolean, string and null shapes are what a hand-edited artifact
    could hand the block. A page that asked its own question would be a second arbiter beside the
    one it echoes a moment later.
    """
    confirmed = {"decision": RECORD_ID, "confirmed": "2026-10-26T00:00:00Z"}
    for unnamed in (confirmed, dict(confirmed, issue=True), dict(confirmed, issue="7"),
                    dict(confirmed, issue=None)):
        assert brief_page.order_owes_closed_check([unnamed]) is False, unnamed
    # And the shapes that do owe it, so the four above cannot pass on a predicate that only ever
    # answers False: the same entry naming a real issue, and a queue holding one among nameless
    # entries.
    assert brief_page.order_owes_closed_check([dict(confirmed, issue=7)]) is True
    assert brief_page.order_owes_closed_check(
        [confirmed, dict(confirmed, issue=7)]) is True


def test_brief_the_closed_check_predicate_is_the_census_imported_not_retyped() -> None:
    """The brief asks the census's own predicate, so the two cannot disagree about one order.

    The equality is asked of the two functions over the same documents rather than of words in a
    file: a brief that kept its own reading of "this order left the closed question unasked" is a
    second arbiter, and the screen would then say something about the queue that the verdict line
    it prints a moment later does not.
    """
    from noni import census_ordering_closed

    for entries in ([{"issue": 7}], [{"issue": "7"}], [], None,
                    [{"issue": True}, {"issue": 3}]):
        assert brief_page.order_owes_closed_check(entries) == \
            census_ordering_closed.owed(entries), entries


def test_brief_a_notice_free_order_prints_nothing_extra(tmp_path: Path) -> None:
    """The two states that hold nothing, and the one that cannot be read: no notice at all.

    An absent artifact and an empty list both answer an order with no entries, and an artifact
    that is there and unreadable keeps its own one-word answer with a fail-class census row behind
    it. None of the three owes a line about a check that had nothing to check, and a page that
    printed one would warn about the closed state of a queue it could not read at all.
    """
    for name, plant in (("absent", lambda root: order_path(root).unlink()),
                        ("empty", lambda root: write_order_entries(root, [])),
                        ("unreadable",
                         lambda root: order_path(root).write_text("{ not json\n",
                                                                  encoding="utf-8"))):
        root = plant_brief_tree(tmp_path, name=name)
        plant(root)
        code, out, _ = run_brief(root, "--now", NOW)
        assert code == 0, name
        assert brief_page.NOT_CHECKED_CLOSED not in out, name


def test_brief_the_notice_survives_a_cut_that_took_every_row(tmp_path: Path) -> None:
    """A queue reduced to its header keeps the line that speaks for the whole of it.

    Rows are what a debt pays itself back from: the head of the order is what to work on next, and
    the notice is neither a row nor a row's tail -- it is the block's statement that those rows
    were never read against closed issues. A reader who sees ten rows gone and a header left must
    still be told the queue was never checked, which is what keeps a stale order from reading as a
    current one at the deepest cut the content caps leave reachable.
    """
    root = plant_brief_tree(tmp_path)
    # A debt past every row of the queue: the block is down to its header and its notice, and the
    # debt it could not pay there went on into the purpose prose.
    out = page_owed_lines(root, brief_module.TOP_ENTRIES + 2)
    assert stripped(sections(out), brief_module.ORDER_HEADER) == [
        brief_page.NOT_CHECKED_CLOSED]
    assert _entry_rows(out) == []
