"""The route-choice clause is stated, in its words, on the two pages that owe it.

A project whose rules require a pull request cannot grant Route A's assumption:
every noni writer commits onto whatever branch the ``--repo`` tree has checked
out (``current_branch`` and ``unsafe_branch_reason`` in
``src/noni/_session_push.py`` name that branch, and no writer ever passes a
branch or a ref of its own). A page that never said so left a pilot team
discovering it from a rejected push, so the clause that says it is a product
contract and not an editorial nicety: ``docs/QUICKSTART.md``'s ``## The state
root`` states it before the reader chooses a route, and ``docs/PRODUCT.md``
section 7 -- the page the quickstart itself calls binding -- states the same
rule in one sentence.

The clause is located by its two ends, following
``tests/test_session_symlink_docs.py``: the position the writers commit to
(:data:`quickstart_page.ROUTE_CHOICE_START`) and the recommendation that follows
from it (:data:`quickstart_page.ROUTE_CHOICE_CLOSE`). Neither phrase occurs
anywhere else on either page -- not in the route headings, not in the ignore-rule
prose -- so a page that dropped the clause matches neither, and a page that kept
only the neighbouring route bullets matches neither either. The symlink suite's
own docstring records the failure mode this guards against: a first version
asserted words that lived in the adjacent prose, and a page whose whole clause
had been deleted still passed.

The mutation proofs at the bottom are the other half of the file. A locator that
merely passes today is not evidence it would fail tomorrow, so each test deletes
a span from a copy of the raw page and asserts the locator raises: the clause's
opening gone, its close gone, its own bullet gone with the neighbouring bullets
left in place, and each fact between its ends gone. Deletions are applied to the
raw text and the result flowed by the caller, so a mutation cannot be undone --
or faked -- by the whitespace collapse the locator needs.

A mutation of one page is asserted against that page's own window: the quickstart
under its ``## The state root`` heading, the product page inside its section 7.
That scoping is what stops a clause moved to another section from passing a
whole-page search, and it is also what makes the product copy's shorter sentence
a claim of its own rather than a weaker version of the quickstart's.
"""

from __future__ import annotations

import re

import pytest
from docs_commands import read
from docs_promises import PRODUCT, section_body
from quickstart_page import (
    ROUTE_CHOICE_CLOSE,
    ROUTE_CHOICE_START,
    flowed_section,
    flowed_text,
    page_text,
    product_section_7,
)

# What the clause owes between its two pinned ends, per page. Facts are located
# inside the window rather than anywhere on the page: prose that names the same
# words in another section cannot satisfy them, which is the whole point of
# locating a clause by its ends.
#
# The quickstart's bullet names both routes, because it is the sentence a reader
# chooses between them with, and it names the fact that makes direct commits a
# demand rather than a habit ("never opens a branch"). The product page states the
# same rule in one sentence and calls the in-project route "the in-project route"
# rather than by the quickstart's heading, so it owes the two facts that carry the
# rule -- who is refused direct commits, and which route to take instead -- and not
# the quickstart's heading names.
CLAUSE_FACTS: dict[str, tuple[str, ...]] = {
    "quickstart": ("branch-protected", "PR-only", "Route A", "direct commits",
                   "never opens a branch"),
    "product": ("branch-protected", "PR-only", "direct commits"),
}

# The two pages, each keyed to the facts it owes. The raw text comes from
# :func:`_raw` and the section window from :func:`_window`, so the mutation tests
# loop over this table and a clause deleted from either page fails on its own row.
PAGES: tuple[tuple[str, str], ...] = (("quickstart", "docs/QUICKSTART.md"),
                                      ("product", "docs/PRODUCT.md"))


def _raw(key: str) -> str:
    """The page as committed, before any locator has touched it."""
    return page_text() if key == "quickstart" else read(PRODUCT)


def _occurrences(key: str, phrase: str) -> list[str]:
    """Every place ``key``'s page prints ``phrase``, wrapping and all.

    The page's own line breaks sit inside a phrase that does not fit a line, so a
    single literal cannot name the clause on both pages: the words are the contract
    and the column they wrap at is not. Each occurrence is matched word by word
    with any run of whitespace allowed between them, which is how one deletion can
    target the text a reader sees without assuming the page never wrapped.
    """
    raw = _raw(key)
    pattern = r"\s+".join(re.escape(word) for word in phrase.split())
    found = [match.group(0) for match in re.finditer(pattern, raw)]
    assert found, f"{key} does not state {phrase!r}"
    return found


def _window(key: str, text: str) -> str:
    """The section of one page's ``text`` that the clause must sit inside.

    Scoped by heading on both pages rather than searched whole-page: a clause
    relocated under an unrelated heading is a page that lost the clause from where
    its reader is told to find it, and a whole-page search would call that a pass.
    """
    body = (section_body(text, "The state root") if key == "quickstart"
            else section_body(text, "7. State layout"))
    return flowed_text(body)


def locate(flowed: str, origin: str, facts: tuple[str, ...]) -> str:
    """The window of the already-flowed ``flowed`` text between the clause's two ends.

    ``origin`` names the page in the failure, so a red run says which page lost
    the clause rather than which phrase a search could not find. The text between
    the ends must carry every fact in ``facts``: a clause that kept its two
    pinned phrases and lost the reasoning between them is the clause
    ``tests/test_session_symlink_docs.py`` describes, and it fails here.
    """
    start = flowed.find(ROUTE_CHOICE_START)
    assert start >= 0, (
        f"{origin} no longer states where the writers commit, in the words the "
        f"docs test pins ({ROUTE_CHOICE_START!r})")
    stop = flowed.find(ROUTE_CHOICE_CLOSE, start)
    assert stop >= 0, (
        f"{origin} states the walked branch ({ROUTE_CHOICE_START!r}) but no "
        f"longer recommends {ROUTE_CHOICE_CLOSE!r} to a branch-protected or "
        "PR-only project")
    between = flowed[start:stop]
    for fact in facts:
        assert fact in between, (
            f"{origin}'s route-choice clause omits {fact!r}, which is the fact "
            f"the recommendation rests on: {between!r}")
    return between


def test_the_quickstart_locates_the_clause_in_its_state_root_section() -> None:
    """The clause sits under ``## The state root``, not merely somewhere on the page.

    Section-scoped on purpose: the same words planted under an unrelated heading
    would satisfy a whole-page search while leaving the reader who has not yet
    chosen a route without the sentence that decides the choice for them.
    """
    section = flowed_section("The state root")
    between = locate(section, "docs/QUICKSTART.md", CLAUSE_FACTS["quickstart"])
    # The clause comes after the two routes are introduced, which is the point of
    # it: a reader chooses with the commit rule in hand.
    assert section.find("Two routes") < section.find(ROUTE_CHOICE_START), (
        "the commit rule is stated before the routes exist, so it reads as a "
        "property of neither")
    assert between, "the clause is its two ends and nothing between them"


def test_product_md_section_7_states_the_same_rule() -> None:
    """The page the quickstart calls binding carries the clause, inside its section 7.

    Read from the page rather than against a copy of the sentence, so a rewording
    that drops the rule and a move of it out of the binding section both fail here:
    the facts are asserted inside the section body, which is where the whole-page
    reading cannot place them.
    """
    assert locate(product_section_7(), "docs/PRODUCT.md 7", CLAUSE_FACTS["product"])


def test_each_page_carries_the_clause_exactly_once() -> None:
    """One clause per page, and a second copy of either end is a failure.

    Two copies would mean two sentences to keep in step, and the locator's claim
    -- that these two phrases name one clause and nothing else -- would be false.
    The count is taken over the raw page with the page's own wrapping allowed
    inside the phrase, so a duplicate that was re-wrapped to fit a line is still
    counted, and so is the phrase split across a line break on the page that owns it.
    """
    for key, label in PAGES:
        for phrase in (ROUTE_CHOICE_START, ROUTE_CHOICE_CLOSE):
            found = _occurrences(key, phrase)
            assert len(found) == 1, (
                f"{label} states {phrase!r} {len(found)} times, so the locator "
                "cannot attribute the window to one clause")


def test_deleting_either_pinned_end_from_either_page_fails_the_locator() -> None:
    """Delete the clause's opening or its close, on each page, and the locator says so.

    The deletion is applied to the raw page at the span the page itself prints,
    wrapping included, so it cannot be undone by the whitespace collapse the
    locator applies. :func:`test_each_page_carries_the_clause_exactly_once` is what
    makes that single replacement a true removal.
    """
    for key, label in PAGES:
        facts = CLAUSE_FACTS[key]
        for phrase in (ROUTE_CHOICE_START, ROUTE_CHOICE_CLOSE):
            spelled = _occurrences(key, phrase)[0]
            mutated = _window(key, _raw(key).replace(spelled, "x" * len(spelled), 1))
            assert phrase not in mutated, (
                f"{phrase!r} survives the mutation on {label}, so this run does "
                "not test its removal")
            with pytest.raises(AssertionError):
                locate(mutated, f"{label} ({phrase!r} deleted)", facts)


def test_deleting_the_clause_bullet_leaves_the_locator_finding_nothing() -> None:
    """Drop the clause's own bullet and keep the route bullets above it: no match.

    The neighbouring bullets carry ``--repo``, the ignore rule and the choice
    criterion, so a locator that read the surrounding section rather than the
    clause would still find a state-root section here. It finds neither pinned
    end instead, which is the check the symlink suite's docstring says a first
    version needed.
    """
    raw = page_text()
    assert _occurrences("quickstart", ROUTE_CHOICE_START)[0] in raw
    # Cut the raw bullet, not the flowed one: the list marker is the only line
    # structure the bullet has, and the deletion must not depend on it surviving a
    # collapse. The span runs to the end of the clause's own bullet -- its end is
    # found, not assumed to be the section's last line, so a bullet added after the
    # clause (or a rename of the heading that follows) leaves this a test of one
    # deletion rather than a test that quietly removes the prose below it too.
    clause, start = _clause_window("quickstart")
    bullet_start = raw.rindex("- ", 0, start)
    bullet_end = start + len(clause)
    while raw[bullet_end:bullet_end + 1] == "\n":
        bullet_end += 1
    mutated = _window("quickstart", raw[:bullet_start] + raw[bullet_end:])
    assert ROUTE_CHOICE_START not in mutated
    assert "--repo" in mutated, "the neighbouring bullets are the text being passed on"
    with pytest.raises(AssertionError):
        locate(mutated, "docs/QUICKSTART.md (route-choice bullet removed)",
               CLAUSE_FACTS["quickstart"])


def test_a_clause_that_lost_its_reasoning_between_the_ends_fails() -> None:
    """Both ends kept, one fact between them gone: still a failure.

    The clause's purpose is the consequence it draws, so a locator that matched
    only its two ends would pass on a page that had been hollowed out. Each
    mutation deletes one occurrence from the raw page, inside the window the
    locator reads, and the assertion before the ``raises`` proves the deletion
    took rather than landing on a copy of the word in another section.
    """
    for key, label in PAGES:
        window = _window(key, _raw(key))
        for fact in CLAUSE_FACTS[key]:
            assert fact in window, f"{fact!r} is not inside {label}'s clause window"
            assert window.count(fact) == 1, (
                f"{fact!r} appears twice in {label}'s window, so the locator's "
                "fact list carries a word the clause does not depend on")
            # Strike only the occurrence inside the clause: the raw page may name
            # the word again in another section, and that copy is not this claim.
            mutated_raw = _replace_once_in_window(key, fact)
            mutated = _window(key, mutated_raw)
            assert fact not in mutated, (
                f"{fact!r} survives in {label}'s window, so this run does not test "
                "its removal")
            with pytest.raises(AssertionError, match=fact.replace("-", r"\-")):
                locate(mutated, f"{label} ({fact!r} deleted)", CLAUSE_FACTS[key])


def _clause_window(key: str) -> tuple[str, int]:
    """The page's route-choice clause as the raw page prints it, plus its offset.

    Both ends come from the raw text -- the close is taken from the match that
    opened the window, so it is the close *of this clause* and not the first copy
    of ``use Route B`` the page might carry elsewhere. The offset is an index into
    the raw page, which is what lets the mutations below splice text without
    assuming the locator's whitespace collapse has already happened.
    """
    raw = _raw(key)
    opened = _occurrences(key, ROUTE_CHOICE_START)[0]
    start = raw.index(opened)
    # The span searched for the close is sized from the page: the opening's own
    # wrapping plus a margin wide enough for the clause between the two ends.
    margin = max(opened.split("\n"), key=len)
    span = raw[start:start + len(opened) + len(margin) + 400]
    closed = re.search(r"\s+".join(re.escape(word)
                                   for word in ROUTE_CHOICE_CLOSE.split()), span)
    assert closed, f"{key}'s clause never reaches its close"
    return raw[start:start + closed.end()], start


def _replace_once_in_window(key: str, fact: str) -> str:
    """The page with the one occurrence of ``fact`` that sits in the clause removed.

    Locating the occurrence inside the clause's own span keeps the mutation honest:
    ``str.replace(fact, ..., 1)`` would strike the first copy on the page, which for
    ``PR-only`` on the quickstart is a sentence in the Route B section, and the
    clause would survive intact.
    """
    raw = _raw(key)
    clause, start = _clause_window(key)
    at = clause.find(fact)
    assert at != -1, f"{fact!r} is not inside {key}'s clause, so it is not a fact "
    "the locator can be accused of depending on"
    absolute = start + at
    return raw[:absolute] + "x" * len(fact) + raw[absolute + len(fact):]
