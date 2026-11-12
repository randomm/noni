"""The brief suite's row builders: the two lines of foreign text the page composes itself.

A helper module (never named ``test_*``, so pytest never collects it as a suite of its own),
beside ``brief_fixtures.py``. The page builds two of its lines out of more than one field of an
artifact: an order row joins a position, an issue, a decision id and the entry's ``why``, and a
decision row joins an id, a statement or a ``text: answer`` segment per question, and the
record's ``why``. The bound each row is asked to respect is :data:`noni.brief_page.TEXT_LIMIT`
and the composition rule is that row's own, so the longest row the builders can be handed is
driven at the builder rather than through a launched run: the artifacts bound both rationale
fields below that number, so no run of the tool reaches the shape that would clip.

The tests that assert what a screen prints go through :func:`tests.brief_fixtures.run_brief` and
read the printed page. This module is for the one question a launched run cannot ask: what the
builder does with a row whose parts are already at their bounds.
"""

from __future__ import annotations

from noni import brief_page


def order_row(position: int, *, issue: int | None, decision: str | None,
              why: str | None = None) -> str | None:
    """One ``top 10`` row, built through the page's own row builder.

    The three parts an entry contributes are named as arguments rather than as an entry
    document: the caller is asking about the composition, and a caller that had to build a
    well-formed artifact to reach the builder would be testing the artifact's schema as well.
    """
    return brief_page.order_row(position, issue=issue, decision=decision,
                                why=why)


def decision_row(*, record_id: str, statement: str | None = None,
                 why: str | None = None) -> str | None:
    """One ``recent decisions`` row of a single-option record, built directly.

    A record whose one question carries the writer's ``single_option`` marker is the shape the
    block prints as ``{id}: {statement}`` plus the reason, so the row's statement is the
    question's answer. Driven at the builder because the ledger's own field bounds keep a writer
    from committing a statement long enough to reach the row's bound: the caller is asking what
    the row does when the head and the reason cannot both fit.
    """
    text = statement if statement is not None else ""
    return brief_page._decision_row({
        "id": record_id, "status": "decided",
        "questions": [{"id": "q1", "text": text, "options": [text], "answer": text}],
        "single_option": True, **({"why": why} if why is not None else {})})
