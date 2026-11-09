"""The read-only brief: one screen of what noni currently knows about a project.

``noni brief --repo REPO [--now ISO-8601]`` prints four blocks and nothing else:

    Purpose
    Ship the direction layer.

    top 10
    1. #7
    2. Cache the census (item idea-0001)

    candidates
    idea-0007 candidate 2026-10-24T00:00:00Z An idea

    summary: 1 warning(s); 1 finding(s); verdict ok

It reads and prints. It never writes, never contacts a tracker, and never recomposes the
census's own words: the last line of stdout is the final ``summary:`` line of the census's
human report for the same ``--repo`` and the same ``--now``, printed verbatim (see
:func:`_summary_line`). The census's ``note:`` lines and its finding rows are not part of
the brief -- the screen is four blocks and a verdict, and the report is one command away.

Three rules the tool is built around:

- **Bounded.** :data:`BRIEF_MAX_LINES` caps the lines the brief's own blocks print,
  headers and the blank lines between blocks included. A run that would print more drops
  candidates first (oldest first), then order entries, then the Purpose body, and closes
  its own blocks with one ``dropped: N line(s)`` line naming the total it withheld. The
  dropped-count line and the summary line sit outside the budget, so a reader always gets
  the verdict (see :func:`_render`).
- **Deterministic.** With one ``--now`` the bytes are the bytes of the next run. Every
  order comes from the artifact's own list order or from a sort over ``created`` and
  ``id``, and nothing in the brief reads the clock or the cwd: ``--repo`` is resolved once
  and every path is taken from it, and the instant is the caller's or taken once here.
- **Read-only.** Every read is an ``open`` or an ``lstat``. The tool writes no file,
  stages no commit, and runs no git call of its own; the census it launches runs in
  process with its output captured, so the census's own read-only promise is this tool's.

Nothing here re-derives a shape another module owns: the order is read through
:func:`noni.orderstate.read_order`, the item store and the intent file through the two
reader modules beside this file, the text of every row through ``census_text`` (the one
bounded and clipped scrub the census renders its rows with), and the verdict through the
census itself.

Exit codes: 0 whenever the brief rendered, whatever the census's verdict was; 2 for a bad
``--now``, a ``--repo`` that is not a directory, or anything besides those two flags, with
the reason on stderr and nothing on stdout.
"""

from __future__ import annotations

import argparse
import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from . import (
    brief_intent,
    brief_items,
    census_run,
    census_text,
    intentschema,
    itemschema,
    labels,
    orderschema,
    orderstate,
)
from ._safe_text import safe_path

# The two codes of this tool, published by this docstring and named nowhere else
# (docs/PRODUCT.md 7 gives ``brief`` 2 for a wrong command line, beside ``intent``,
# ``order``, ``item``, ``register`` and the census). There is no third: a census verdict
# is reported in the summary line rather than copied into the brief's exit code, because
# the brief's own job is to render and the census's job is to judge.
EXIT_OK: int = 0
EXIT_USAGE: int = 2

# The cap on the lines the brief's own blocks print. Counted over the three blocks
# together -- each header, its rows, and the blank line that separates one block from the
# next -- and not per block: a 200-entry order would otherwise crowd the other two blocks
# off the screen the brief exists to fit on. The dropped-count line and the census's
# summary line are outside the count, so a truncated run still ends with its verdict.
BRIEF_MAX_LINES = 200

# How many order entries the ``top 10`` block prints, and how many candidates the
# ``candidates`` block prints before the budget is consulted. Both are a reading aid: the
# order is what to work on next and the screen shows its head, and the candidates are
# listed newest first, so the ideas the budget keeps are the freshest ones.
TOP_ENTRIES = 10
TOP_CANDIDATES = 10

# The Purpose body is the operator's prose, not a report. Twenty lines is a paragraph or
# two; past that the block is an essay and the ellipsis line says so.
PURPOSE_MAX_LINES = 20

# The ellipsis line of a clipped Purpose body: a line holding exactly this, which is the
# census's own clip marker (``census_text._clipped``) rather than a third spelling.
ELLIPSIS = "..."

# What a block prints when the artifact it reads is not readable at all (a symlink, a
# directory, a device, or bytes this reader refuses). The refusal text the reader carries
# is deliberately not printed here: it names an environment fault, and the census -- which
# runs in this same process a moment later to produce the brief's last line -- is the
# arbiter that words it. The line says the same thing whatever the fault was, so no byte
# read from the tree reaches stdout on a line this constant appears in.
NOT_READ = "not readable"

# The three block headers, spelled once so the budget, the truncation order, the readers
# and the tests all name one set of words.
PURPOSE_HEADER = "Purpose"
ORDER_HEADER = "top 10"
CANDIDATES_HEADER = "candidates"

# The prefix of the line the census's human report ends with, and the line the brief
# prints when the census printed no verdict to echo. Both are the brief's vocabulary and
# not the census's: the prefix is how the capture is searched, and the stand-in is what
# the brief says when the arbiter said nothing. The brief never builds a verdict of its
# own, which is why the stand-in is the only such sentence in this file.
SUMMARY_PREFIX = "summary: "
NOT_RUN_SUMMARY = "summary: not-run; 0 finding(s); verdict fail"

# One bound for every line this tool prints that has no field of its own to bound it: the
# census's row bound is the one number for "a message that came from outside", so a brief
# line and a census row built from the same text come out the same length. Field bounds are
# taken from the store's own constants at each call site instead.
TEXT_LIMIT = 300

# The three headers plus the two lines this tool itself can print below them, as a set:
# what one line of the page must never be.
#
# The block bodies are foreign text (an item title, a purpose line) and a reader splits the
# page on these words, so a candidate titled exactly ``candidates`` would open a second
# block and a purpose line of exactly ``top 10`` would make the reader of the page count
# blocks that are not there. A page is a page only while its headers are the only lines that
# say those words, so a body line that lands on one is dropped: an idea is one row of the
# list, and a row that cannot be told from the list's own name is worth less than the shape
# of the page it would break. The two tool-printed lines are in the set for the mirror
# reason -- the census report this page ends by echoing could itself hold a finding whose
# text is one of them.
PAGE_RESERVED = frozenset({PURPOSE_HEADER, ORDER_HEADER, CANDIDATES_HEADER,
                           ELLIPSIS, SUMMARY_PREFIX.strip()})


def _page_line(text: str, limit: int) -> str | None:
    """One body line of the page, or None when the text would not be a body line.

    The scrub, then the two shape tests a foreign line has to pass to reach stdout: it must
    survive the scrub as something with content in it, and it must not be one of the words
    the page is read by. ``None`` is the caller's signal to drop the row, and the callers
    are the two places that print foreign text -- a candidate's row and one line of the
    purpose body.
    """
    line = _scrub(text, limit)
    if not line.strip() or line in PAGE_RESERVED:
        return None
    return line


def _refuse(headline: str, hint: str) -> int:
    """The exit-2 refusal: two lines on stderr, nothing on stdout, code 2.

    One shape for every refusal of this tool -- the label, the reason, and a fix line
    naming what to change -- which is the shape the other noni writers print. The path in
    a headline is rendered by the caller through :func:`noni._safe_text.safe_path`, so a
    caller-supplied ``--repo`` cannot add a line to stderr or put a control sequence on
    the terminal. No path reaching here writes to stdout, which is what lets a caller
    read stdout as the report and nothing else.
    """
    print(f"{labels.BRIEF}: {headline}", file=sys.stderr)
    print(f"{labels.BRIEF}: fix: {hint}", file=sys.stderr)
    return EXIT_USAGE


def main(argv: list[str] | None = None) -> int:
    """Print the brief. Returns 0 whenever the brief rendered, 2 for a bad command line.

    ``argv`` is the tool's own argv, ``sys.argv[1:]`` when none was handed in. The console
    route (``noni brief``) and ``python -m noni brief`` both hand their argv here rather
    than running a second copy of this file.

    The two defaults are decided here and nowhere else, so no read below is a question the
    process's own state can answer:

    - ``--repo`` has no default and gets no ``~`` expansion (docs/PRODUCT.md 7 grants that
      expansion to the census's six path overrides and nowhere else, and the brief runs the
      census with two flags, neither of them an override). The string is resolved once;
      every path the brief reads and the path it hands the census are taken from that one
      resolved directory, so a relative ``--repo`` cannot make the two audit different
      trees, and the cwd of the run is not an input to anything.
    - ``--now`` has no default either: absent means the current UTC instant, and a run
      that fixed no instant makes no determinism claim. It is validated by
      :func:`noni.orderstate.now_iso`, the writer's rule, which refuses a stamp carrying no
      UTC offset -- a stricter accepted set than the census's own parser has, which keeps
      every command line this tool accepts inside the census's exit-0 subset. The stamp is
      then normalised once and handed to both the brief's own readers and the census, so
      the two cannot disagree about the instant of one run.
    """
    parser = argparse.ArgumentParser(
        prog=labels.BRIEF,
        description="Read-only brief: the standing intent's purpose, the top of the "
                    "order, the filed candidates, and the census summary line.",
    )
    parser.add_argument("--repo", required=True, metavar="DIR",
                        help="the state root whose direction is briefed (no default)")
    parser.add_argument("--now", default=None, metavar="ISO-8601",
                        help="fixed UTC timestamp carrying an offset (e.g. "
                             "2026-10-27T09:00:00Z) for the census run; absent means the "
                             "current UTC time and no determinism claim")
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    except SystemExit as exit_:
        if exit_.code == 0:
            # ``--help``: argparse wrote its own page to stdout and asked to leave with 0.
            # The brief exits with the code it was handed and prints no report, because a
            # help page is an answer and not a run -- and not exit 2, which a caller reads as
            # "the command line was wrong" when it was only asked to be explained.
            return 0
        # argparse printed its own usage banner and reason on stderr, in the words that name
        # the flags this tool actually has. The brief adds nothing to them -- a second pair of
        # lines about a mistake already explained would be a longer refusal, not a clearer one
        # -- and prints no report: the code this tool owes for a wrong command line is 2 and
        # stdout stays empty, so a caller can tell a refusal from a brief on stdout alone.
        # The two refusal shapes this tool has are then told apart by what they name:
        # argparse's lines quote the flag list, and :func:`_refuse` opens with the label.
        return EXIT_USAGE

    stamp, problem = orderstate.now_iso(args.now)
    if problem:
        return _refuse(problem, "pass --now as e.g. 2026-10-27T09:00:00Z, with a UTC "
                                "offset, or drop it to use the current UTC time")
    root = Path(args.repo).resolve()
    if not root.is_dir():
        return _refuse(f"--repo {safe_path(args.repo)} is not a directory",
                       f"pass --repo naming the state root, the directory that holds "
                       f"(or will hold) {orderstate.DECISIONS_DIR}/")

    blocks = [_purpose_block(root), _order_block(root), _candidates_block(root)]
    print(_render(blocks))
    print(_summary_line(root, stamp))
    return EXIT_OK


def _render(blocks: list[list[str]]) -> str:
    """The brief's own blocks as one string: budgeted, and closed by the dropped line.

    The lines of the three blocks joined by the blank lines between them, in the order the
    brief prints them. The budget counts these lines and nothing else, so the summary line
    the caller prints after this one is never the line that tipped a run over.

    The truncation order is the spec's: candidates first, then order entries, then the
    Purpose body, and a run that still owes lines after all three has nothing left to give
    (only reachable if a header alone is past the cap, which the constants above make
    impossible). A run whose blocks total at most the cap prints no dropped-count line; a
    run past it prints exactly one, naming the number of its own block lines it withheld.
    """
    kept = [list(lines) for lines in blocks]
    total = sum(len(lines) for lines in kept)
    owed = total - BRIEF_MAX_LINES
    for index in (2, 1, 0):
        if owed <= 0:
            break
        owed = _drop(kept[index], owed)
    out: list[str] = []
    for lines in kept:
        # A blank line between two blocks that printed something: none before the first, and
        # none before one the budget left as its header alone. A reader counts these to find
        # the next section, and a page whose last block was cut to a header must not end in a
        # run of blanks before the verdict.
        if out and len(lines) > 1:
            out.append("")
        out.extend(lines)
    if total > BRIEF_MAX_LINES:
        out.append(f"dropped: {total - BRIEF_MAX_LINES} line(s)")
    return "\n".join(out)


def _drop(lines: list[str], owed: int) -> int:
    """Remove up to ``owed`` lines from the tail of one block; the lines still owed.

    A block's tail is what goes, so the head of every list stays on the screen: the head of
    the candidate list is its freshest ideas and the head of the order is what to work on
    next, which is the pair of questions the screen is for. The header line stays too -- a
    reader who cannot tell which block went missing has lost more than one who sees an
    empty block under its own name. When a block reaches its header the remaining debt moves
    on to the next block rather than being forgiven, which is what makes a whole-block drop
    cost exactly the lines that block printed.
    """
    remaining = owed
    while remaining and len(lines) > 1:
        lines.pop()
        remaining -= 1
    return remaining


def _purpose_block(root: Path) -> list[str]:
    """The ``Purpose`` block: the intent's purpose body, clipped to 20 lines.

    One header and the body, plus the ellipsis line when the body was longer than the cap.
    An absent intent file, one whose sections do not validate and one this run cannot read
    all print the header and :data:`NOT_READ`. Each printed line is the census's scrub of
    the operator's own prose: a control byte cannot reach the terminal out of a file the
    brief did not write, and a host path in a purpose statement prints as ``<path>`` here
    exactly as it would in a census row.
    """
    body = brief_intent.purpose_block(root / intentschema.INTENT_REL,
                                      PURPOSE_MAX_LINES)
    if body is None:
        return [PURPOSE_HEADER, NOT_READ]
    lines, clipped = body
    kept = [line for line in (_page_line(text, TEXT_LIMIT) for text in lines)
            if line is not None]
    if clipped:
        kept.append(ELLIPSIS)
    return [PURPOSE_HEADER, *kept]


def _order_block(root: Path) -> list[str]:
    """The ``top 10`` block: the head of the order, in the artifact's own order.

    The read is :func:`noni.orderstate.read_order` and the entries are rendered without
    branching on the document's schema version: an entry naming an issue prints
    ``{position}. #{issue}``, one citing an item prints ``{position}. {title} (item {id})``,
    and one citing an item the store does not hold prints ``{position}. item {id} not
    found`` instead of a title this run did not read. Both shapes are asked through
    :func:`noni.orderschema.entry_issue` / :func:`noni.orderschema.entry_item`, which is
    where the two versions' one-subject rule lives.

    ``decision`` and ``confirmed`` are not printed: this is a screen, and the order writer's
    own listing is the tool that shows the provenance of a position. A refusal or a fault of
    the read prints the header and :data:`NOT_READ` -- the artifact is the census's to
    report on -- and an absent file is the empty order, which prints its header alone.
    """
    read = orderstate.read_order(root / orderschema.ORDER_REL)
    if not isinstance(read, orderstate.OrderOk):
        return [ORDER_HEADER, NOT_READ]
    rows = [_order_row(root, position, entry)
            for position, entry in enumerate(read.entries[:TOP_ENTRIES], 1)]
    return [ORDER_HEADER, *rows]


def _order_row(root: Path, position: int, entry: dict) -> str:
    """One line of the ``top 10`` block, whichever version the entry is of.

    The subject is the issue or the cited item; a document naming neither was refused by
    the reader before this line was reached, so the third branch is the shape a row always
    has rather than a state a file can put it in, and it exists so a row is one line instead
    of an exception. Every piece of text here is the store's or the operator's and goes
    through the scrub, including the id of an entry whose item is missing: an id is a token
    somebody typed.
    """
    issue = orderschema.entry_issue(entry)
    if issue is not None:
        return f"{position}. #{issue}"
    cited = orderschema.entry_item(entry)
    if cited is None:
        return f"{position}. (unnamed entry)"
    title = brief_items.candidate_title(root, cited)
    if title is None:
        return f"{position}. item {cited} not found"
    # The title is the one foreign word in the row and the one that can read as a header, so
    # it goes through the page's own shape test; a refused title costs the row its subject,
    # which is what the citation branch already prints for an unreadable item.
    line = _page_line(title, itemschema.TITLE_MAX)
    if line is None:
        return f"{position}. item {cited} not found"
    return f"{position}. {line} (item {cited})"


def _candidates_block(root: Path) -> list[str]:
    """The ``candidates`` block: the store's candidates, newest ``created`` first.

    At most :data:`TOP_CANDIDATES` rows, and an empty store or an absent one prints the
    header alone. A row is ``{id} candidate {created} {title}``: the four fields of an idea
    the listing of the store is asked for, in that order, with the title last because it is
    the field that may hold a space and a reader cuts the line by field, not by column.
    """
    bodies = brief_items.candidates(root / itemschema.ITEM_DIR)
    # The cap counts rows that were built, not files that were read, so the listing is walked
    # in order and the cap is applied at the end: a candidate whose row was refused costs the
    # block nothing but its own row, and fifteen candidates of which five read badly still
    # print the ten ideas the screen is for. A block that took the ten freshest bodies first
    # would show fewer ideas than the store holds, for a reason the reader cannot see.
    rows: list[str] = []
    for body in bodies:
        if len(rows) == TOP_CANDIDATES:
            break
        row = _candidate_line(body)
        if row is not None:
            rows.append(row)
    return [CANDIDATES_HEADER, *rows]


def _candidate_line(body: dict) -> str | None:
    """One line of the ``candidates`` block, or None when the row would not be a row.

    The four fields of an item this listing selected: the id, the word ``candidate``, the
    ``created`` stamp and the title, in that order. Each is the store's or the operator's
    text and goes through :func:`_page_line`, which is where the shape of a row is decided:
    a blank field or a title that is one of the page's own words costs the row, because a
    row missing a field cannot be cut by field and a row that reads as a header cannot be
    told from one.
    """
    fields = [_page_line(body["id"], itemschema.ID_MAX),
              itemschema.STATUS_CANDIDATE,
              _page_line(body["created"], itemschema.WHY_MAX),
              _page_line(body["title"], itemschema.TITLE_MAX)]
    if any(field is None for field in fields):
        return None
    return " ".join(fields)


def _scrub(text: str, limit: int) -> str:
    """``text`` as the census renders a message: host paths replaced, whitespace collapsed,
    bounded to ``limit`` with the census's own ellipsis.

    :func:`noni.census_text._bounded` is the census's scrub and this is its only use outside
    that tool. An item title, an order entry's cited id or a purpose line is text somebody
    else wrote, and the line that prints it must not smuggle a machine-local path onto the
    terminal or stay unbounded. The limit is passed through rather than defaulted so each
    call site names the bound of the field it prints.
    """
    return census_text._bounded(text, limit)


def _summary_line(root: Path, stamp: str) -> str:
    """The last ``summary:`` line of the census's human report for this tree, verbatim.

    The census runs in process through :func:`noni.census_run._run` with ``--repo`` and
    ``--now`` and nothing else, under both :func:`contextlib.redirect_stdout` and
    :func:`contextlib.redirect_stderr` (a census that fails writes a sentence to stderr, and
    the brief owns that stream: its refusals print there and nothing may arrive from a
    captured run). The capture is the whole of the brief's relationship to the arbiter: no
    flag is added, no signature changed, no parser touched, and the line is the bytes
    ``census_render._render_human`` printed. The brief never recomposes a verdict word,
    because a brief that rebuilt one would be a second report to keep in step with the first.

    The line is the LAST captured line opening with the summary prefix. ``_render_human``
    prints its ``note:`` lines above the verdict and its non-ok sentence on stderr, so the
    verdict is what the search finds first, and the search from the end is what keeps a
    report that somehow printed twice from being read from the top.

    Two states answer :data:`NOT_RUN_SUMMARY`, both without an exception reaching the
    caller: a census that printed no summary line at all (a usage refusal, a missing
    ``git``, or any run that returned after writing only to stderr), and a census that
    raised on the way there -- the exceptional case, given the arbiter's own fault arms, but
    a tool that died with a traceback where a verdict was promised is worse than one that
    says it could not get one. The brief still printed its own blocks and still exits 0.
    """
    out = io.StringIO()
    err = io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            census_run._run(["--repo", str(root), "--now", stamp])
    except Exception:
        # One guard for the whole capture: a census fault is a missing verdict here, not
        # a crash of the brief. The arbiter's own fault arms make this the rare path, and
        # the one the caller must not meet as a traceback.
        return NOT_RUN_SUMMARY
    lines = out.getvalue().splitlines()
    # The last non-blank line the census printed, which is its verdict: ``_render_human`` puts
    # its ``note:`` lines above it and writes its non-ok sentence to a stream this capture keeps
    # out of ``out``, so there is exactly one such line and it sits at the end. The blank-line
    # filter is what makes a report ending in empty lines a missing verdict rather than a verdict
    # of "", which would be a blank last line on a page whose last line is the reader's answer to
    # "what did the arbiter say".
    content = [line for line in lines if line.strip()]
    if content and content[-1].startswith(SUMMARY_PREFIX):
        return content[-1]
    return NOT_RUN_SUMMARY


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
