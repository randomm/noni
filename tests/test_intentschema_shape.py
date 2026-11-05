"""The intent file's shape rules, tested where they live.

``intentschema.problems`` is read by two products at once -- the writer's refusal
and the census's rows -- so the rules are pinned here rather than only through
either caller. Every case is a text and the sentence it earns, because the
sentence is what a refusal prints and what a row carries."""

from __future__ import annotations

import pytest

from noni import intentschema

GOOD = """# Intent
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


def test_the_shape_the_writer_writes_has_no_problems():
    assert intentschema.problems(GOOD) == []


def test_the_four_sections_are_named_once_and_in_order():
    """The contract the census row and the writer refusal both quote."""
    assert intentschema.REQUIRED_SECTIONS == ("Purpose", "Principles", "Never",
                                              "Ask first")


def test_a_headed_line_inside_a_fence_is_not_a_heading():
    fenced = GOOD + "\n```\n## Never\nan example, not a section\n```\n"
    assert intentschema.problems(fenced) == []


def test_a_tilde_fence_hides_its_headings_too():
    fenced = GOOD.replace("```\n## Ask first", "~~~\n## Ask first") + "~~~\n"
    text = GOOD + "\n~~~\n## Purpose\nan example\n~~~\n"
    assert intentschema.problems(text) == []
    assert "~~~" in fenced


def test_a_heading_line_with_four_hashes_is_not_a_section():
    """``#### Never`` is a sub-heading of the section above it, not the section."""
    assert intentschema.problems(GOOD + "#### Never\nsub-heading\n") == []


def test_an_indented_stamp_line_is_not_the_stamp_line():
    indented = GOOD.replace("## Purpose", "    Last-confirmed: 2020-01-01\n## Purpose")
    assert intentschema.problems(indented) == []


def test_a_stamp_line_with_no_date_is_not_the_stamp_line():
    """One recognised line remains (the real one), so the file is clean; a draft
    whose only stamp line is malformed is refused, not silently restamped."""
    assert intentschema.problems(GOOD.replace("2026-10-01", "last tuesday")) == [
        f"{intentschema.SUBJECT_SECTION_MISSING}: no "
        f"'{intentschema.LAST_CONFIRMED_PREFIX} YYYY-MM-DD' line"
    ]


def test_the_stamp_line_may_be_indented_inside_a_fence_and_stay_prose():
    fenced = GOOD + "\n```\nLast-confirmed: 2020-01-01\n```\n"
    assert intentschema.problems(fenced) == []


def test_an_unclosed_fence_is_refused_rather_than_read_as_one_big_example():
    """The rule that keeps the fence walk from becoming a shield.

    Everything after an unclosed opener is flagged as fenced, so without this rule
    a second section and a second stamp line written below a stray ``` were
    invisible to both rules at once, and the file censused clean. The sentence is
    what a refusal prints and a row carries, so it is pinned verbatim here, and it
    quotes none of the concealed lines.
    """
    concealed = (GOOD + "```\n## Principles\nPrefer the boring technology.\n"
                 "Last-confirmed: 2030-01-01\n")
    assert intentschema.problems(concealed) == [
        f"{intentschema.SUBJECT_SECTION_MISSING}: an unclosed code fence (a line "
        "starting with 3 or more of '`') leaves the rest of the file inside it, "
        "hidden from the section and stamp rules"
    ]
    for hidden in ("Prefer the boring technology", "2030-01-01"):
        assert hidden not in intentschema.problems(concealed)[0]


def test_an_unclosed_tilde_fence_is_refused_too():
    """A tilde block is closed only by a tilde, so it needs its own refusal."""
    found = intentschema.problems(GOOD + "~~~\n## Principles\nExtra.\n")
    assert len(found) == 1 and "unclosed code fence" in found[0]
    assert "'~'" in found[0]


def test_the_fences_that_balance_are_never_a_problem_however_many():
    """The control: balance is the rule, so examples stay writable.

    Two blocks, each carrying the very content the unclosed case hides away, is a
    file with nothing wrong with it. A refusal keyed on fence count rather than on
    an opener left open would fail here.
    """
    balanced = (GOOD + "\n```\n## Principles\nPrefer the boring technology.\n"
                "Last-confirmed: 2030-01-01\n```\n\n~~~\n## Never\nExtra.\n~~~\n")
    assert intentschema.problems(balanced) == []


@pytest.mark.parametrize("value, expected", [
    ("2026-10-01", "2026-10-01"),
    (" 2026-10-01 ", "2026-10-01"),
    ("2026-1-2", None),          # not four-two-two digits
    ("2026-13-04", None),        # a month no calendar has
    ("2026-02-30", None),        # a day that month does not
    ("2026-10-01T00:00:00", None),  # a timestamp is not a day
    ("", None),
])
def test_parse_stamp_accepts_only_a_day_the_calendar_has(value, expected):
    """fromisoformat accepts shapes the contract does not, so the parsed value has
    to re-spell itself as the digits the line carries or it is refused."""
    assert intentschema.parse_stamp(value) == expected


def test_the_line_cap_is_counted_and_named():
    over = GOOD + "filler\n" * intentschema.MAX_LINES
    problems = intentschema.problems(over)
    assert len(problems) == 1
    assert problems[0].startswith(f"{intentschema.SUBJECT_OVER_CAP}:")
    assert str(intentschema.MAX_LINES) in problems[0]


def test_a_file_at_the_cap_is_clean():
    """The cap is a maximum, not a threshold below which the file must sit."""
    lines = GOOD.split("\n")
    at_cap = "\n".join(lines[:len(lines) - 1] + ["tail"] *
                       (intentschema.MAX_LINES - len(lines) + 1))
    assert len(at_cap.split("\n")) == intentschema.MAX_LINES
    assert intentschema.problems(at_cap) == []


def test_a_problem_names_no_line_it_read():
    """A row must not echo the operator's prose: every entry is a fixed sentence."""
    secret = GOOD.replace("## Principles", "## Principles\nSECRET-TEXT-HERE")
    leaked = secret.replace("## Never", "## Never\nMORE-SECRET")
    for problem in intentschema.problems(leaked):
        assert "SECRET" not in problem, problem
