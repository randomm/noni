"""How a census human report line is shaped, and how the README shows it.

The census's summary line is read by more than one test: the README's try-it
tests compare a real run against the page, and the human-report tests pin the
renderer's three states. Both read it through this one shape, because two
regular expressions that drifted apart would let the page and the product each
pass against their own copy (the failure mode issue #117 was written up as).

The page holds both of its numbers open -- ``W warning(s); N finding(s)`` --
because how many rows a reader's tree carries is not something a page can
promise, so the shape admits the placeholders and the callers decide whether a
number was required of the page or only of the run.

Kept apart from ``tests/readme_support.py``, which holds the reading layer for
the page as a whole, and from the promises modules, which hold assertions: no
assertion lives here beyond the ones that refuse a line that is not a summary
line at all.
"""

from __future__ import annotations

import re

from readme_support import _CLEAN_RUN_WARN_ROWS, _try_it_section

# The one shape a census summary line has, shared by the page reader and the
# renderer tests so the two cannot match the line with copies that drift. Four
# groups: the fixed head, the human verdict word, the finding count, the machine
# tail. The verdict word is either the all-clear word or a warn count; the count
# is a number in a real run's line and ``N`` in the page's, where the page holds
# it open (see ``_summary_parts``).
_SUMMARY_SEGMENT = re.compile(
    r"^(summary: )(\d+ warning\(s\)|clean|W warning\(s\)); (\d+|N) finding\(s\); "
    r"(verdict (?:ok|fail))$"
)

# The page's own placeholder for the warn count, used by the try-it page the way
# ``N`` stands for the finding count: the number depends on how many warn rows
# the reader's tree carries, so the page cannot pin it. A run always prints a
# number, never this token.
_WARN_COUNT_PLACEHOLDER = "W warning(s)"

# The human verdict words the census's summary line may carry, and the one the
# all-clear banner belongs to. Data rather than two inline literals so the page
# test and the renderer test compare the same pair: the word `clean` is reserved
# for a run that counted no row of any severity and skipped no check (issue
# #117), and a warn-bearing run names its warn count instead. The machine tail
# of the line (`verdict ok` / `verdict fail`) is the other group, and no wording
# of the human half moves it.
_WARN_VERDICT_SHAPE = re.compile(r"^\d+ warning\(s\)$")
_ALL_CLEAR_VERDICT = "clean"
_ALL_CLEAR_BANNER = "census: no findings; all checks passed"


def _summary_parts(line: str) -> tuple[str, str, str, str]:
    """The ``(head, verdict word, count, tail)`` of a census summary line.

    Parsed as one whole shape rather than split on a substring, so a line that
    merely contains two of the phrases in some other arrangement does not parse.
    The caller decides whether the count must be a number: the page holds it
    open as ``N``, a run never does.
    """
    match = _SUMMARY_SEGMENT.match(line)
    assert match is not None, f"not a census summary line: {line!r}"
    return match.groups()


def _summary_verdict_word(line: str) -> str:
    """The human verdict word of a census summary line, group 2 of the segment.

    One reader for the word, so a page test and a renderer test cannot each
    match the line with their own copy of the shape and drift.
    """
    return _summary_parts(line)[1]


def _documented_summary_shape() -> tuple[str, str | None, bool]:
    """The census summary line the try-it section shows, as ``(line, word, open)``.

    The page prints ``summary: W warning(s); N finding(s); verdict ok`` and holds
    both numbers open, because how many rows a reader's tree carries is not
    something a page can promise. Reading the shape off the page keeps any
    assertion the page's own promise rather than a copy of it. The ``N`` of the
    finding count is filled with the rows a first run reports (see
    ``_CLEAN_RUN_WARN_ROWS``), which the page tells the reader to expect.

    The human word is read positionally rather than matched as the literal
    ``clean``: the run the try-it block performs carries warn rows, so the word
    the page has to show there is a warn count and the all-clear word belongs to
    a run with no rows at all (issue #117). A page that printed ``clean`` in that
    position is refused by whoever compares this line against a real run.

    Returns the line, the page's human word (``None`` when the page held it
    open), and whether it held it open: a page that pinned a number can be
    compared to it, a page that did not can only be held to naming one.
    """
    shown = [line.strip() for line in _try_it_section().splitlines() if line.strip()]
    candidates = [line for line in shown
                  if line.startswith("summary:") and line.endswith("verdict ok")]
    assert candidates, (
        "the try-it section no longer shows the census's summary line, so the "
        "assertion of the try-it tests would not be the page's own promise"
    )
    line = candidates[0]
    head, verdict, count, tail = _summary_parts(line)
    assert head == "summary: ", f"{line!r}"
    assert count == "N", (
        f"the documented summary line does not hold the finding count open the "
        f"way the page promises: {line!r}"
    )
    assert tail == "verdict ok", f"{line!r}"
    open_count = (verdict == _WARN_COUNT_PLACEHOLDER)
    shown_verdict = None if open_count else verdict
    filled = f"{len(_CLEAN_RUN_WARN_ROWS)} warning(s)" if open_count else verdict
    return (f"summary: {filled}; {len(_CLEAN_RUN_WARN_ROWS)} finding(s); "
            f"verdict ok", shown_verdict, open_count)
