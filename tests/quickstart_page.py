"""The reading layer for the quickstart's page claims: the page text, and its sections.

``tests/test_quickstart.py`` runs the page's commands and
``tests/test_quickstart_promises.py`` checks what the page says; both read the same
file, and one of them needs a few of the same literals: where the page lives, how to
take one ``##`` section of it with its markdown wrapping collapsed, and the two ends
of the clause that tells a reader where the writers' commits land.

Kept in a helper module rather than duplicated, so the two halves of the quickstart's
enforcement cannot drift to reading two different things -- the same reason
``tests/readme_support.py`` holds the README's reading layer apart from its promises
and ``tests/docs_promises.py`` holds the shared page paths. No assertion lives here:
those stay with the test that makes them.
"""

from __future__ import annotations

import re

from docs_commands import read
from docs_promises import QUICKSTART

__all__ = ["COEXISTENCE_HEADING", "ROUTE_CHOICE_CLOSE", "ROUTE_CHOICE_START",
           "flowed_section", "flowed_text", "page_text", "product_section_7",
           "product_section_8"]

# The heading the driver-coexistence section publishes under, and the one locator
# its assertions scope to. Named here because two modules read that section --
# this page's promises and the docs-page CI-neutrality gate -- and a heading the
# page renamed in one of the two would leave the other checking a section that no
# longer exists (the same reason the route-choice clause below is a constant).
COEXISTENCE_HEADING = "Using noni alongside a driver that keeps its own claims"

# The two ends of the clause that tells a reader where the writers' commits land and
# which project should therefore take the private state route. Located by phrase
# rather than by line number -- the page moves, the contract does not -- and by its
# two ends rather than by a whole sentence, so a page that lost the clause fails
# instead of passing on the sentences around it (the failure mode
# ``tests/test_session_symlink_docs.py`` records for a first version that read
# neighbouring prose). The wording these phrases pin is the product's own behaviour:
# ``current_branch`` in ``src/noni/_session_push.py`` reads the branch the ``--repo``
# tree has checked out, and that is the branch every writer's commit lands on.
ROUTE_CHOICE_START = "commits straight to the branch it finds checked out"
ROUTE_CHOICE_CLOSE = "use Route B"


def page_text() -> str:
    """The whole page, as one string."""
    return read(QUICKSTART)


def flowed_text(text: str) -> str:
    """A whole page with its markdown line wrapping collapsed.

    The same collapse :func:`flowed_section` applies to one section, for a caller
    that reads a page over its length rather than under one heading: a locator
    that spans a page must not depend on where a paragraph happened to wrap.
    """
    return re.sub(r"\s+", " ", text)


def flowed_section(heading_start: str, text: str | None = None) -> str:
    """One ``##`` section of the page, with its markdown line wrapping collapsed.

    A page line-wraps at ~80 columns, so a phrase located by a literal ``find``
    would depend on where the wrapping happens to fall: rewrapping a sentence could
    break a pinned phrase across a newline and read as a missing clause. Collapsing
    the whitespace first means a locator tests the words a reader reads, and only the
    words. ``text`` lets a caller that has already read the page hand it over.
    """
    from docs_promises import section_body

    body = section_body(text if text is not None else page_text(), heading_start)
    return flowed_text(body)


def product_section_7() -> str:
    """``docs/PRODUCT.md`` section 7, wrapped as a reader reads it.

    The quickstart names that section as the binding statement of the state-root
    rule, so the clause the page pins lives there too. Located by heading prefix
    rather than by number-in-prose, and collapsed like every other locator here,
    so the check reads the words and not the column they wrapped at.
    """
    from docs_promises import PRODUCT

    return flowed_section("7. State layout", read(PRODUCT))


def product_section_8() -> str:
    """``docs/PRODUCT.md`` section 8 (the epic map), as the page prints it.

    Not whitespace-collapsed: this section's unit is the bullet, and the reader of
    it that the CI-neutrality gate reuses counts markdown lines inside one bullet.
    """
    from docs_promises import PRODUCT, section_body

    body = section_body(read(PRODUCT), "8. Epic map")
    assert body.lstrip().startswith("## 8."), (
        "docs/PRODUCT.md no longer opens its epic map with a `## 8.` heading, so "
        f"this locator is reading the wrong span: {body[:40]!r}")
    return body


def ordering_note_from_product() -> str:
    """The census's own ``ordering-closed`` note, assembled from its source.

    The sentence lives in one constant of ``census_report.py``: the human branch
    prints it with a ``note: `` prefix and the NDJSON branch carries it verbatim on
    the summary row's ``not_evaluated`` field. This reads the constant's own
    literals out of that file and returns the line exactly as human mode prints it,
    so the page and its test cannot agree with each other while both drift away
    from the tool. The prefix is added here and not stored in the constant: the
    NDJSON field carries the sentence, not the presentation.
    """
    from _harness import REPO

    source = (REPO / "src" / "noni" / "census_report.py").read_text(encoding="utf-8")
    match = re.search(r'ORDERING_CLOSED_NOT_EVALUATED\s*=\s*\(\s*'
                      r'((?:"(?:[^"\\]|\\.)*"\s*)+)\)', source, re.S)
    assert match, "the census no longer holds the ordering-closed note this test cites"
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', match.group(1))
    assert parts and parts[0].startswith("ordering-closed was not evaluated"), parts
    return "note: " + "".join(parts)
