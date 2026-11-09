"""The brief suite's page readers: the printed page as blocks, and the two
measurements a case states rather than recomputes.

Every part of the suite parses the page through these, so "what a block holds" means
one thing across the six files -- including the budget's own ``dropped:`` line, which the
tool prints as the last line of the blocks and which :func:`rows` therefore keeps out of
a block's rows and :func:`dropped_line` reports on its own.
"""

from __future__ import annotations

from pathlib import Path

from brief_fixtures import NOW, census_stdout, run_brief_in_process

from noni import brief as brief_module
from noni import labels as labels_module

# The three block headers, in print order, and the prefix of the line the tool appends when
# its own budget forced it to withhold block lines.
HEADERS = [brief_module.PURPOSE_HEADER, brief_module.ORDER_HEADER,
           brief_module.CANDIDATES_HEADER]
DROPPED_PREFIX = "dropped: "

# The label every refusal of this tool opens with. The tool builds it from its own label
# module and the parser builds it from the same constant, so the assertion names the tool's
# label rather than a string a rename could strand.
LABEL = labels_module.BRIEF

def sections(text: str) -> dict[str, list[str]]:
    """The rendered page as ``{header: body lines}``, in print order.

    The page is small and its headers are the tool's own words, so the assertion reads as a
    lookup instead of as arithmetic on line numbers a reader cannot see. A header line that
    appears twice is an error here rather than a later block silently swallowing an earlier
    one: the tool prints each header once, and the case that plants a foreign line shaped like
    a header is exactly the case that checks it stays body text.

    The verdict line is not a block's body. The page ends with the census's line, which sits
    below the last header with nothing between them, so a reader of the page that stopped
    nowhere would report it as the last block's last row -- and a case about the size of a
    block would then be a case about the arbiter's sentence. The last line is read by
    :func:`summary_line` and by nothing else here.
    """
    lines = text.splitlines()
    if lines and lines[-1].startswith(brief_module.SUMMARY_PREFIX):
        lines = lines[:-1]
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        if line in HEADERS:
            assert line not in blocks, f"{line} printed twice: {text}"
            current = line
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return blocks


def stripped(blocks: dict[str, list[str]], header: str) -> list[str]:
    """One block's body without its blank edges."""
    body = list(blocks[header])
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return body


def summary_line(text: str) -> str:
    """The verdict line: the last non-blank line of the page."""
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines, text
    return lines[-1]


def census_summary(root: Path, now: str = NOW) -> str:
    """The census's own last non-blank stdout line for one tree at one instant."""
    code, text = census_stdout(root, "--now", now)
    assert code == 0, (code, text)
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1]


def candidate_rows(out: str) -> list[str]:
    """The ``candidates`` block's body lines."""
    return stripped(sections(out), brief_module.CANDIDATES_HEADER)




def is_refusal(err: str) -> bool:
    """Whether ``err`` is one of the tool's two refusal shapes, and nothing else.

    The brief has exactly two ways to say no. A command line the parser cannot read is
    answered by argparse itself -- a ``usage:`` banner and one reason line, in the words that
    name the flags the tool actually has. Anything the parser read but the tool will not act on
    is answered by :func:`noni.brief._refuse` -- the tool's label, a headline, and a line
    beginning ``fix:``. Both go to stderr and both leave stdout empty. A refusal that was
    neither (a traceback, or a report line) is what this returns False for.
    """
    lines = err.strip().splitlines()
    assert lines, err
    if lines[0].startswith("usage:"):
        return len(lines) == 2 and lines[1].startswith(f"{LABEL}: error:")
    return (lines[0].startswith(f"{LABEL}: ")
            and any(line.startswith(f"{LABEL}: fix:") for line in lines[1:]))


def counts_more(page: str, other: str) -> bool:
    """Whether ``page``'s verdict line reports more findings than ``other``'s.

    The fallback half of the stall case's last assertion. The census puts a stalled session on a
    row, and its summary line counts findings rather than naming classes, so the difference the
    two instants have to show is in a count -- the word itself is a convenience when the row is
    printed on the line, not a requirement.
    """
    return finding_count(summary_line(page)) > finding_count(summary_line(other))


def finding_count(line: str) -> int:
    """How many findings the verdict line says the run found."""
    head = line.split(";", 1)[0]
    digits = "".join(char for char in head if char.isdigit())
    return int(digits) if digits else 0


def block_lines(root: Path) -> int:
    """How many lines the tool counts against its budget for one tree.

    Asked of the tool and not derived from its constants, and asked through the same in-process
    route the budget cases use. The budget counts the three headers, each block's rows, and the
    blank line the page puts between two blocks that printed something -- so the blank lines are
    counted where they are printed, which is not a fixed number of them. A case that restated the
    list in arithmetic would be a second answer to that question and would go quietly wrong when
    the rule for a separator changes. The page without its verdict line is the count.
    """
    page = run_brief_in_process(root, "--now", NOW)[1]
    return len(page.splitlines()) - 1


def page_with_budget(root: Path, cap: int) -> str:
    """The page for one tree under a budget of ``cap`` block lines.

    The budget is the tool's own module constant and no page the four content caps allow is long
    enough to trip it, so a case has to lower it to reach the branch at all -- which is why these
    three cases run the brief in process. In a launched child the constant is a value in that
    child's own module and a parent rebinding it here would change nothing out there, so the case
    would silently run at the real cap and assert about a cut that never happened.

    Restored in a ``finally``, because a case that left the budget at 3 would truncate every page
    the rest of the file asks for, and their failures would be about this one. The in-process call
    still reads the tree from disk, so the copy under ``tmp_path`` is the one being briefed.
    """
    original = brief_module.BRIEF_MAX_LINES
    brief_module.BRIEF_MAX_LINES = cap
    try:
        code, out, err = run_brief_in_process(root, "--now", NOW)
    finally:
        brief_module.BRIEF_MAX_LINES = original
    assert code == 0, (code, out, err)
    return out
