"""The brief suite's page readers: the printed page as blocks, and the two
measurements a case states rather than recomputes.

Every part of the suite parses the page through these, so "what a block holds" means
one thing across the six files -- including the budget's own ``dropped:`` line, which the
tool prints as the last line of the blocks and which :func:`rows` therefore keeps out of
a block's rows and :func:`dropped_line` reports on its own.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from brief_fixtures import NOW, census_stdout, run_brief_in_process
from harness_runners import subprocess_env

from noni import brief as brief_module
from noni import labels as labels_module

# The two block headers, in print order, and the prefix of the line the tool appends when
# its own budget forced it to withhold block lines.
HEADERS = [brief_module.PURPOSE_HEADER, brief_module.ORDER_HEADER]
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


def dropped_line(page: str) -> str:
    """The budget's own count line of a page, or ``""`` when it printed none.

    Read from the page rather than from a block: the count line is the blocks' last line and sits
    directly under the last header, so a reader of the page sees it as the last block's last row.
    That is the tool's rule and not a fault to route around -- the count line belongs to the blocks
    and the verdict line belongs to the page.
    """
    for line in reversed(page.splitlines()):
        if line.startswith(DROPPED_PREFIX):
            return line
    return ""


def rows(page: str, header: str) -> list[str]:
    """One block's rows, with the budget's own count line left out.

    The count line is printed as the last line of the blocks, which puts it under the last header
    and inside the last block as a reader of the page sees it. Every budget case asks about the
    rows the block kept, so the count line is asked for separately, by :func:`dropped_line`, and
    excluded here -- and a case can then say "the order block holds nothing" and mean the
    entries, not the tool's arithmetic.
    """
    return [row for row in stripped(sections(page), header)
            if not row.startswith(DROPPED_PREFIX)]


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


def dropped_of(page: str) -> int:
    """How many lines the tool says it withheld from the blocks, 0 when it printed no count."""
    line = dropped_line(page)
    return int(line[len(DROPPED_PREFIX):].split()[0]) if line else 0


def page_with_budget(root: Path, cap: int, *, fresh: bool = False) -> str:
    """The page for one tree under a budget of ``cap`` block lines.

    The budget is the tool's own module constant and no page the content caps allow is long
    enough to trip it, so a case has to lower it to reach the branch at all. The constant lives in
    whichever process renders the page, so the child sets it itself from the environment before it
    calls the tool: a parent rebinding its own copy would change nothing out there, and the case
    would silently run at the real cap and assert about a cut that never happened.

    Restored in a ``finally``, because a case that left the budget at 3 would truncate every page
    the rest of the file asks for, and their failures would be about this one. The child still reads
    the tree from disk, so the copy under ``tmp_path`` is the one being briefed.
    """
    if fresh or cap < brief_module.BRIEF_MAX_LINES:
        return _run_child(root, cap, count=False)
    original = brief_module.BRIEF_MAX_LINES
    brief_module.BRIEF_MAX_LINES = cap
    try:
        code, out, err = run_brief_in_process(root, "--now", NOW)
    finally:
        brief_module.BRIEF_MAX_LINES = original
    assert code == 0, (code, out, err)
    return out


# The child's program, as one string. With no cap in its environment it rebinds the tool's own
# budget constant and prints the page, which is what the launched route of the suite is for: the
# census caches the tree it audits for the life of a process, so a case that measured one tree and
# then briefed another in the parent would be reading the first tree's page. With
# ``NONI_BRIEF_TEST_LINES`` set it stops at the two blocks and prints the number of lines they
# hold, which is the budget's own count rather than a page the caller would have to parse.
_CHILD = """
import os, sys
from pathlib import Path
from noni import brief

root = Path(os.environ["NONI_BRIEF_TEST_ROOT"])
if os.environ.get("NONI_BRIEF_TEST_LINES"):
    blocks = [brief._purpose_block(root), brief._order_block(root)]
    print(sum(len(lines) for lines in blocks))
    sys.exit(0)
cap = os.environ.get("NONI_BRIEF_TEST_CAP")
if cap:
    brief.BRIEF_MAX_LINES = int(cap)
sys.exit(brief.main(["--repo", str(root), "--now", os.environ["NONI_BRIEF_TEST_NOW"]]))
"""


def _run_child(root: Path, cap: int | None, *, count: bool):
    """One brief run in an interpreter of its own, optionally at the budget ``cap``.

    ``count`` asks the child for the number of lines its blocks hold instead of for the page: that
    is the measurement the budget cases compare a cut page against, and it has to come from a
    process that briefed no other tree, so the page a budget case measures is the page of the tree
    the case named.
    """
    env = dict(subprocess_env())
    env["NONI_BRIEF_TEST_ROOT"] = str(root)
    env["NONI_BRIEF_TEST_NOW"] = NOW
    if cap is not None:
        env["NONI_BRIEF_TEST_CAP"] = str(cap)
    if count:
        env["NONI_BRIEF_TEST_LINES"] = "1"
    launched = subprocess.run([sys.executable, "-c", _CHILD],
                              capture_output=True, text=True, env=env, timeout=120)
    assert launched.returncode == 0, (launched.stdout, launched.stderr)
    return int(launched.stdout.strip()) if count else launched.stdout
