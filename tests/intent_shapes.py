"""The shapes the ``intent`` class reports and the writer refuses, in one table.

Read by both suites on purpose: every row here is a draft that ``intent.py``
refuses to install and that the census must report, so the artifact and the
arbiter are checked against the same list rather than two lists that drift.
``tests/ordering_shapes.py`` is the model this file copies.
"""

from __future__ import annotations

GOOD_INTENT = """# Intent
Last-confirmed: 2026-10-01
## Purpose
Ship the beta.
## Principles
Prefer the boring technology.
## Never
Never force push.
## Ask first
Anything that costs money.
"""


def _missing(heading: str) -> str:
    """The good intent with one section (heading and body) removed."""
    marker = f"## {heading}\n"
    head, _, rest = GOOD_INTENT.partition(marker)
    body, _, tail = rest.partition("\n## ")
    return head + ("## " + tail if tail else "")


def _duplicated(heading: str) -> str:
    """The good intent with one section repeated at the end."""
    marker = f"## {heading}\n"
    _, _, rest = GOOD_INTENT.partition(marker)
    body = rest.partition("\n## ")[0]
    return GOOD_INTENT + f"## {heading}\n{body} again\n"


def _out_of_order() -> str:
    """The good intent with ``Never`` moved before ``Principles``."""
    head, _, rest = GOOD_INTENT.partition("## Principles\n")
    principles, _, never = rest.partition("## Never\n")
    never_body, _, ask = never.partition("## Ask first\n")
    return head + "## Never\n" + never_body + "## Principles\n" + principles \
        + "## Ask first\n" + ask


def _over_cap() -> str:
    return GOOD_INTENT + "filler\n" * 200


def _unclosed_fence() -> str:
    """The good intent followed by an opener that is never closed.

    The shape the fence walk used to read as one enormous example: everything
    after the opener is flagged as fenced, so a second `## Principles` and a
    second stamp line hidden there were invisible to both rules at once.
    """
    return (GOOD_INTENT + "```\n## Principles\nPrefer the boring technology.\n"
            "Last-confirmed: 2030-01-01\n")


# (name, text, census subject) for every shape the class reports and the writer
# refuses. ``section-missing`` covers the missing, repeated and misordered cases:
# one shape cannot tell them apart and neither does the row, which names the
# headings the file does carry in its message.
INTENT_REFUSAL_SHAPES = [
    ("missing-purpose", _missing("Purpose"), "section-missing"),
    ("missing-principles", _missing("Principles"), "section-missing"),
    ("missing-never", _missing("Never"), "section-missing"),
    ("missing-ask-first", _missing("Ask first"), "section-missing"),
    ("duplicated-never", _duplicated("Never"), "section-missing"),
    ("out-of-order", _out_of_order(), "section-missing"),
    ("no-stamp-line", GOOD_INTENT.replace("Last-confirmed: 2026-10-01\n", ""),
     "section-missing"),
    ("twice-stamped",
     GOOD_INTENT.replace("## Purpose", "Last-confirmed: 2026-09-30\n## Purpose"),
     "section-missing"),
    ("over-cap", _over_cap(), "over-cap"),
    ("unclosed-fence", _unclosed_fence(), "section-missing"),
]

# A heading written inside a fenced block is prose, not structure: the file keeps
# its four sections and gains no fifth, and both readers must agree.
FENCED_HEADING = GOOD_INTENT.replace(
    "## Never\nNever force push.\n",
    "## Never\nNever force push.\n\n```\n## Ask first\n(this is an example, not "
    "the section)\n```\n",
)

# The stamp line indented is not the stamp line: one recognised line remains, and
# the indented one is prose. The file is clean, and the writer restamps only the
# line at column 0.
INDENTED_STAMP = GOOD_INTENT.replace("## Purpose", "    Last-confirmed: 2020-01-01\n"
                                                   "## Purpose")

# Balanced fences are not the defect: the same second heading and stamp line that
# an unclosed opener hides, written inside a block the file closes again, is a
# file both readers accept. The pair of rows pins that the refusal is about the
# unclosed opener and not about a draft that carries examples.
FENCED_EXAMPLES = GOOD_INTENT.replace(
    "## Ask first\nAnything that costs money.\n",
    "## Ask first\nAnything that costs money.\n\n```\n## Principles\nPrefer the "
    "boring technology.\nLast-confirmed: 2030-01-01\n```\n",
)
