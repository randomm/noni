"""The page's own rules for a line of foreign text, and the counts that go with them.

Split from ``brief.py`` for the 500-line source cap, beside ``brief_intent.py`` and
for the same reason: ``brief.py`` owns the command line, the budget and
what each block prints, and this module owns the decision every printed line of foreign text
passes through on its way to the screen. The two rows the page composes for itself -- the order
row and the decision row, with the ledger read behind the latter -- live beside it in
``brief_rows.py``, which asks this module the one question a line answers to: :func:`page_line`.

The rules are the brief's and not the census's. :func:`noni.census_text._clipped` is the length
half of the census's row rule (a tail bounded to a count, with a mark when it was cut) and
:func:`noni._safe_text.safe_text` the renderer every noni refusal prints caller-supplied text
through (no control bytes, bounded). The census's other half -- whitespace collapsed, a
machine-local path replaced -- answers a row built from an ``OSError``, which quotes the filename it
failed on. A page line is the opposite kind of text: the operator committed every word of it, so it
prints as written, and the page's own third rule (a run of whitespace is one space, so a row stays
a row) is written here rather than borrowed.
"""

from __future__ import annotations

from ._safe_text import safe_text
from .census_text import _clipped

# The mark that opens a row's reason. It belongs to the row rather than to the line rule, but it
# is spelled here because :mod:`noni.brief` prints it: the order block and the decisions block each
# state their row shape in terms of this one string, which is why it is the tool's constant and not
# a private one of the module that composes the rows.
REASON_SEPARATOR = " — "

# What a block prints when the artifact it reads is not readable at all (a symlink, a directory,
# a device, or bytes this reader refuses). The refusal text the reader carries is deliberately
# not printed here: it names an environment fault, and the census -- which runs in this same
# process a moment later to produce the brief's last line -- is the arbiter that words it. The
# line says the same thing whatever the fault was, so no byte read from the tree reaches stdout
# on a line this constant appears in.
NOT_READ = "not readable"

# The prefix of a block's own count line, shared with the budget's line above the verdict: one
# spelling of "N line(s) of this block were withheld", so a reader of the page meets the same
# sentence whether the lines went missing to the cap or to the page's shape test.
DROPPED_PREFIX = "dropped: "

# The words a body line must never be, as a rule over a set the caller hands in: the caller's
# block headers, its ellipsis, and its verdict prefix.
#
# The block bodies are foreign text (a purpose line) and a reader splits the
# page on these words, so a purpose line of exactly ``top 10`` would make the reader of the page
# count blocks that are not
# there. A page is a page only while its headers are the only lines that say those words, so a
# body line that lands on one is dropped: a row that cannot
# be told from the list's own name is worth less than the shape of the page it would break. The
# tool's own printed lines belong in the set for the mirror reason -- the census report the page
# ends by echoing could itself hold a finding whose text is one of them.
#
# The set is named by the caller rather than built here from ``brief``'s headers: the headers are
# the tool's vocabulary and belong with the tool, and the rule here is about a set of words,
# whatever spells them.
def page_line(text: str, limit: int, reserved: frozenset[str]) -> str | None:
    """One body line of the page, or None when the text would not be a body line.

    Three rules, answering three different questions. A run of whitespace becomes one space, which is
    what makes a row one row. Then :func:`noni._safe_text.safe_text` drops every Unicode category-C
    character, which is what stops an ANSI or OSC sequence in foreign text reaching the terminal.
    The collapse runs both before and after the renderer, so neither a tab nor a byte the renderer
    deleted leaves a gap or padding behind: a tab is itself a control character, so a renderer run
    over the text first would delete it and leave ``two\tcandidates`` as one word, and a byte at a
    field's edge or between spaces would leave padding that made a reserved word read as something
    else. Neither rule rewrites a word the operator committed: the census's path arms belong to
    a row built from an ``OSError`` and have no business in the page, where they took a slash
    command out of the operator's own text.

    The line is bounded last, by the page's own clip: :func:`noni.census_text._clipped` cuts the
    finished line to ``limit`` and marks the cut, so a line can never leave this function longer
    than the page's bound. :func:`noni._safe_text.safe_text` is asked for roomier than the bound on
    purpose -- its truncation tail is longer than the tail the page's clip prints, so a line whose
    own renderer did the cutting would print past ``limit`` and carry the refusal renderer's word
    where the page's mark belongs.

    Then the two shape tests a foreign line has to pass to reach stdout: it must survive all three
    rules as something with content in it, and it must not be one of the words the page is read
    by. ``None`` is the caller's signal to drop the row, and the callers are the places that print
    foreign text -- a purpose line, and every part of a row built in ``brief_rows.py``.

    ``reserved`` is the set the caller names as the words the page is read by; it is named by the
    caller rather than built here from ``brief``'s headers, because the headers are the tool's
    vocabulary and belong with the tool while the rule here is about a set of words, whatever
    spells them.
    """
    collapsed = " ".join(text.split())
    line = _clipped(" ".join(safe_text(collapsed, limit + _RENDER_SLACK).split()), limit)
    return None if not line.strip() or line in reserved else line


def block_rows(lines: object, cap: int) -> tuple[list[str], int]:
    """The rows one block keeps, and how many of its own lines it withheld.

    One walk for the block that builds rows from foreign text: a line its renderer refused costs
    the block its row and earns a line on the block's
    own count. The cap is applied to the rows that were built rather than to the entries that were
    read, which is what lets an order of twenty entries of which five read badly still print the
    ten positions the screen is for.
    """
    rows: list[str] = []
    withheld = 0
    for line in lines:
        if line is None:
            withheld += 1
            continue
        if len(rows) == cap:
            break
        rows.append(line)
    return rows, withheld


def page_lines(lines: list[str], limit: int,
               reserved: frozenset[str]) -> tuple[list[str], int]:
    """The lines of a foreign body that survived the page's shape test, and how many did not.

    A line whose rendered form is one of the page's own words (a purpose statement that reads
    exactly ``top 10``, say) is dropped for the reason the set's own name states, and the drop
    is counted rather than left silent: a page that withheld a line of the operator's prose owes
    the reader the number of lines it withheld, which is what the block's count line says. Without
    it, a statement of the operator's that happened to land on a header word would disappear from
    the screen and leave nothing behind to explain the gap.
    """
    kept: list[str] = []
    withheld = 0
    for text in lines:
        line = page_line(text, limit, reserved)
        if line is None:
            withheld += 1
        else:
            kept.append(line)
    return kept, withheld


def close_block(lines: list[str], withheld: int) -> list[str]:
    """One block, closed by its own count line when it withheld a line of foreign text.

    The count line sits inside the block, under its header, so a reader who sees an empty list
    under ``top 10`` can tell "the order holds none" from "the order holds entries this page
    could not print". The line is the tool's own sentence and counts against the budget like any
    other line of the block, which is the honest arithmetic: it is a line the page printed.
    """
    if withheld:
        return [*lines, f"{DROPPED_PREFIX}{withheld} line(s)"]
    return lines


# The bound the page asks of the foreign text it prints: the operator's purpose prose and the
# citation an order entry carries. The tool's ceiling for foreign text, asked of the artifact's
# own characters rather than of anything it parsed, so one number covers every row of the page.
TEXT_LIMIT = 300

# How much roomier than the bound :func:`page_line` asks its renderer for. The renderer truncates
# on its own when the text it was handed is longer than the limit it was given, and that tail is
# longer than the page's clip mark, so a renderer left to truncate would print a line past the
# bound and print its own word where the page's mark belongs. This slack is what keeps the
# renderer's truncation out of the page: it exceeds the tail's length, and the clip applied to the
# finished line is the only cut a page line ever answers to.
_RENDER_SLACK = len("... [truncated]")
