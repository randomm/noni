"""The page's own rules for a line of foreign text, and the counts that go with them.

Split from ``brief.py`` for the 500-line source cap, beside ``brief_intent.py`` and
``brief_items.py`` and for the same reason: ``brief.py`` owns the command line, the budget and
what each block prints, and this module owns the decision every printed line of foreign text
passes through on its way to the screen.

The rules are the brief's and not the census's, and two modules hold a piece of each:
:func:`noni.census_text._bounded` is the scrub the census renders its rows with (whitespace
collapsed, machine-local paths replaced, tail bounded), and :func:`noni._safe_text.safe_text` is
the renderer every noni refusal prints its caller-supplied text through (no control bytes,
bounded). Neither is enough on its own for a line of the page: the census scrub is a whitespace
and path rule and leaves an escape byte standing, and the refusal renderer keeps runs of
whitespace and knows nothing about paths. A screen that prints an operator's prose and an
item's title takes both, in the order that makes the bound mean what it says.
"""

from __future__ import annotations

from ._safe_text import safe_text
from .census_text import _bounded
from .itemschema import ID_MAX, STATUS_CANDIDATE, TITLE_MAX

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
# The block bodies are foreign text (an item title, a purpose line) and a reader splits the page
# on these words, so a candidate titled exactly ``candidates`` would open a second block and a
# purpose line of exactly ``top 10`` would make the reader of the page count blocks that are not
# there. A page is a page only while its headers are the only lines that say those words, so a
# body line that lands on one is dropped: an idea is one row of the list, and a row that cannot
# be told from the list's own name is worth less than the shape of the page it would break. The
# tool's own printed lines belong in the set for the mirror reason -- the census report the page
# ends by echoing could itself hold a finding whose text is one of them.
#
# The set is named by the caller rather than built here from ``brief``'s headers: the headers are
# the tool's vocabulary and belong with the tool, and the rule here is about a set of words,
# whatever spells them.
def page_line(text: str, limit: int, reserved: frozenset[str]) -> str | None:
    """One body line of the page, or None when the text would not be a body line.

    Two scrubs, because they answer two different questions and neither is a superset of the
    other. :func:`noni._safe_text.safe_text` drops every Unicode category-C character, which is
    what stops an ANSI or OSC sequence in a title reaching the terminal; :func:`noni.census_text
    ._bounded` collapses whitespace and replaces a machine-local path, which is what makes a brief
    row read like a census row. The order of the two matters: the control bytes have to go before
    the bound is applied, so the characters a title loses to the escape being deleted cannot push
    a visible word past the limit and have it replaced by an ellipsis.

    Then the two shape tests a foreign line has to pass to reach stdout: it must survive both
    scrubs as something with content in it, and it must not be one of the words the page is read
    by. ``None`` is the caller's signal to drop the row, and the callers are the places that print
    foreign text -- a candidate's row, a purpose line, an order row's subject.

    ``reserved`` is the set the caller names as the words the page is read by; it is named by the
    caller rather than built here from ``brief``'s headers, because the headers are the tool's
    vocabulary and belong with the tool while the rule here is about a set of words, whatever
    spells them.
    """
    line = _bounded(safe_text(text, limit), limit)
    if not line.strip() or line in reserved:
        return None
    return line


def block_rows(lines: object, cap: int) -> tuple[list[str], int]:
    """The rows one block keeps, and how many of its own lines it withheld.

    One walk for both blocks that build rows from foreign text, so the two answer one question the
    same way: a line its renderer refused costs the block its row and earns a line on the block's
    own count. The cap is applied to the rows that were built rather than to the files that were
    read, which is what lets fifteen candidates of which five read badly still print the ten ideas
    the screen is for.
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
    under ``candidates`` can tell "the store holds none" from "the store holds ideas this page
    could not print". The line is the tool's own sentence and counts against the budget like any
    other line of the block, which is the honest arithmetic: it is a line the page printed.
    """
    if withheld:
        return [*lines, f"{DROPPED_PREFIX}{withheld} line(s)"]
    return lines


# The bound of the ``created`` field as the row prints it. The store's own rule for the field is a
# UTC instant, and the longest spelling of one is a couple of dozen characters, so no item the store
# can hold reaches this number: it is a backstop for the one field of the row whose text this tool
# does not produce, asked of the artifact's own characters rather than of an instant it parsed. The
# tool's ceiling for foreign text is used rather than the store's ``why`` bound, which is the ceiling
# of a sentence and not of a stamp.
TEXT_LIMIT = 300


# The bounds of the four fields a candidate row composes, in the order the row prints them: an id at
# the store's own bound, the status word (the tool's own word, hence its own length), the ``created``
# stamp at the tool's backstop for foreign text, and a title at the title bound. Summed with the
# separators between them, these are the longest candidate row the page can print, stated as the parts
# rather than as a total a reader would have to add up by hand. The row a legal store can produce that
# comes closest to it is an id and a title both at their bounds; the ``created`` field never does.
ROW_FIELD_LIMITS: tuple[int, ...] = (ID_MAX, len(STATUS_CANDIDATE), TEXT_LIMIT, TITLE_MAX)
ROW_FIELD_SEPARATORS = len(ROW_FIELD_LIMITS) - 1
