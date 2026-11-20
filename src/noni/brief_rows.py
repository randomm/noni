"""The two rows the page composes for itself, and the ledger reader that feeds one of them.

Split from ``brief_page.py`` for the 500-line source cap, along the seam that module was itself
split for: ``brief_page.py`` owns the rule every printed line of foreign text passes through, and
this module owns the two lines the page builds out of more than one field of an artifact -- the
``top 10`` row and the ``recent decisions`` row -- together with the one read of
``noni/decisions/`` that produces the latter.

What the page's rules and the row builders share is exactly one name, :func:`page_line`: every part
of a row reaches the line through it, which is what keeps a control byte out of a terminal while the
operator's own words print as the artifact committed them. Nothing here re-decides that rule: the
bound, the collapse and the page's clip are asked of the module beside this one, so a row can never
print a line the page would have refused. The row builders name their own shapes -- the join between
two questions, the mark that opens a reason, the brackets around the record that set an order
position -- because those are the row's business and not the line rule's.
"""

from __future__ import annotations

from pathlib import Path

from . import ledger_schema, orderschema, orderstate
from .brief_page import REASON_SEPARATOR, TEXT_LIMIT, block_rows, page_line
from .census_text import _clipped

# The text of the one question the decisions block asks of every record it reads. Like
# :data:`noni.brief_page.NOT_READ` it is the tool's own sentence and never a word from a record, so
# no byte of a file this reader did not write reaches stdout on a line that carries it.
OPEN_ANSWER = "(open)"

# The separators of one row. The rows are built here and printed by the caller, so the three
# shapes the reader renders -- the join between two questions, the mark that opens the reason,
# and the brackets that hold the record an order position was set by -- are named once beside
# the reader rather than spelled at each end of the join.
QUESTION_SEPARATOR = "; "
DECISION_BRACKETS = ("(", ")")

# The two separators a row is assembled with before its reason is joined on: ``{position}. `` for
# an order row and ``{id}: `` for a decision row. Named beside the builders so neither a bound
# nor a caller can be the place the shape of a row is spelled twice.
ORDER_SUBJECT_SEPARATOR = ". "
RECORD_SEPARATOR = ": "


def order_row(position: int, *, issue: object, decision: object,
              why: object = None) -> str | None:
    """One ``top 10`` row: the position, the issue, the record that set it, and the reason.

    Three parts before the page's bound, in the order the reader needs them. The position and the
    issue are the line the block existed to print; the record id is what tells a reader what the
    entry *is* when the page reads no tracker for a title, and it is the id an agent takes to the
    ledger to read the decision itself. The entry's ``why`` rides at the end after its own mark
    when the entry carries a reason, for the reason :func:`_decision_row` states for a record's:
    the reason is what a cold start cannot recover anywhere else on the screen.

    Every part reaches the line through :func:`noni.brief_page.page_line`, so a control byte in a
    reason cannot reach the terminal while the reason's own words print as the artifact committed
    them. A reason that renders to nothing costs its mark and not the row: an entry written
    before the field existed holds no reason, and a mark standing over nothing is the page
    promising a line it did not print.
    """
    record = _rendered(decision)
    head = _order_subject(position, issue)
    if record:
        head += f" {DECISION_BRACKETS[0]}{record}{DECISION_BRACKETS[1]}"
    return _bounded_row(head, _rendered(why))


def _order_subject(position: int, issue: object) -> str:
    """The head of an order row: ``{position}. #{issue}``, or the shape a nameless row has.

    The reader refuses a document whose entry names no issue, so the fallback is the shape a row
    always has rather than a state a file can put it in, and it exists so a row stays one line
    instead of an exception.
    """
    named = isinstance(issue, int) and not isinstance(issue, bool)
    if not named:
        return f"{position}{ORDER_SUBJECT_SEPARATOR}(unnamed entry)"
    return f"{position}{ORDER_SUBJECT_SEPARATOR}#{issue}"


def _rendered(value: object) -> str:
    """A foreign field as it may be printed, or ``""`` for a field that renders to nothing.

    Two questions rather than one test of the field: it must be a string with something in it, and
    it must survive the page's own rules with something in it. A field of spaces passes the first
    and fails the second, and so does a field made only of what the renderer deletes (a category-C
    character, say), which is the shape a hand-edited artifact reaches when a reason is deleted
    and its quotes left behind. Asking the page's renderer is what makes a mark stand or fall on
    the same answer the row gets.
    """
    if not isinstance(value, str) or not value.strip():
        return ""
    return value if page_line(value, TEXT_LIMIT, frozenset()) else ""


def decision_rows(ledger: Path, cap: int) -> tuple[list[str], int]:
    """At most ``cap`` decision rows, newest first, and how many of them cost a line.

    One read of ``noni/decisions/``, on the brief's own terms: it asks which records are live
    and prints one line for each of the newest ``cap``, and it forms no verdict about any of
    them. The census's ``ledger-*`` classes are the arbiter that words a fault, and they run
    in this same process a moment later to produce the brief's last line, so every state this
    reader cannot render -- the directory absent, empty, not a directory, reached through a
    symlink, unlistable, or holding a record it cannot read -- costs that record its row and
    prints nothing else. The caller renders the header either way, so a tree with no records
    shows an empty block rather than a fault it has no way to act on.

    The two answers travel together for the reason :func:`noni.brief_page.block_rows` states, over
    the records this reader could hold in hand: a record this reader refused is a row the reader
    asked for and did not get, and a block that withheld lines owes the count line that says so. A
    row that :func:`noni.brief_page.page_line` refused costs a line the same way. A record that
    never parsed is not among them: it is not a record this reader held, and the count line counts
    rows withheld from a page rather than files the census goes on to fault. A ledger directory
    this run could not list is the same shape one level up -- the block prints its header and pays
    no count line, and the census is what words that fault.
    """
    records = _live_records(ledger)
    rows, withheld = block_rows((_decision_row(record)
                                 for record in _newest_first(records)), cap)
    return rows, withheld + max(0, len(records) - cap)


def _live_records(ledger: Path) -> list[dict]:
    """The records the ledger directory holds whose ``status`` is ``decided``.

    Live is one predicate and it is the record's own word: :func:`noni.orderstate`'s reader
    already treats a record whose ``status`` is ``superseded`` as dead, and the census's chain
    class is what reports a chain holding two live records. Re-deriving liveness from the
    ``supersedes`` fields here would make the page a second arbiter that can disagree with the
    one the same command runs a moment later, so this reads one field and asks nothing of the
    rest of the chain.

    Nothing is opened before the path has been classified. The ledger and every name in it go
    through :func:`noni.orderstate.file_kind`, which asks ``lstat``: :meth:`pathlib.Path.is_file`
    follows a link and reports the file at its far end as this artifact, which is the rule the
    intent reader beside this file states the same way.
    """
    kind, _why = orderstate.file_kind(ledger)
    if kind != "dir":
        # Absent, a symlink, a plain file or a device: the block's header is the whole answer,
        # and the census is what names which of these the tree holds.
        return []
    try:
        names = sorted(path.name for path in ledger.iterdir()
                       if path.suffix == ".json")
    except OSError:
        # The listing did not answer. The census's ledger group performs its own listing and
        # words that fault; this reader has nothing to print for it.
        return []
    records: list[dict] = []
    for name in names:
        record = _read_record(ledger / name)
        if record is not None and record.get("status") == ledger_schema.STATUS_DECIDED:
            records.append(record)
    return records


def _read_record(path: Path) -> dict | None:
    """The record ``path`` holds as a mapping, or None for anything else.

    A link, a directory, a device, unreadable bytes, bytes that are not UTF-8, text that is
    not JSON, a document past the reader's depth bound, and a value that is not an object all
    answer None, and none of them prints: the exception text a decode fault carries quotes the
    offending bytes, so it is not quoted anywhere here (the census's ledger reader refuses a
    record the same reason). The strict reader is the order family's own, borrowed rather than
    re-implemented, so a record carrying ``NaN``, a key stated twice or a pathological nesting
    is refused here exactly as the writers refuse it.
    """
    kind, _why = orderstate.file_kind(path)
    if kind != "regular":
        return None
    try:
        value = orderschema.load_json_checked(path.read_bytes())
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        # ``RecursionError`` is named because it is no kind of ``ValueError``: the reader's
        # depth bound answers for a document short of the interpreter's own ceiling, and past
        # that ceiling the decoder raises first. A page that died with a traceback where a row
        # was promised is worse than one that printed no row.
        return None
    return value if isinstance(value, dict) else None


def _newest_first(records: list[dict]) -> list[dict]:
    """``records`` in the order the block prints them: newest ``date`` first, then id.

    The sort is total and reads no clock. A record written with no ``--date`` carries the
    instant of its run, so the decisions of one day keep the order they were made in; two
    records at one identical instant -- what a ``--date`` carried over, or a writer run twice
    in a second, produces -- still have one order between them by their ids, the same
    tiebreak the candidates of the store beside this one use on their own two fields. A
    record that carries no usable ``date`` sorts as the oldest there is, which keeps it from
    crowding the recent records off a five-row block.
    """
    return sorted(records, key=lambda record: (_record_date(record),
                                               _record_id(record)), reverse=True)


def _record_date(record: dict) -> str:
    """``record``'s ``date`` for the sort: the string itself, or the oldest possible one.

    Compared as text, which is what an ISO-8601 stamp sorts correctly by. A record whose
    ``date`` is absent or not a string is not this reader's to refuse (the census's record
    class words that fault), so it sorts below every dated record rather than raising.
    """
    value = record.get("date")
    return value if isinstance(value, str) else ""


def _record_id(record: dict) -> str:
    """``record``'s ``id`` for the tiebreak, or the empty string when it carries none."""
    value = record.get("id")
    return value if isinstance(value, str) else ""


def _decision_row(record: dict) -> str | None:
    """One decision as one line: its id, what it settled, and the operator's reason.

    The record's own order is the order printed, all of its questions on the one line, because
    a record is one decision and a block that showed one question of a three-question record
    would report an answer to a question the record did not lead with. A question whose
    ``answer`` is ``null`` prints :data:`OPEN_ANSWER`, which is the tool's word and not the
    record's: the writer leaves an answer ``null`` on a record whose operator never answered,
    and a row that printed nothing there would read as a question the page dropped.

    A record that asked its one question on purpose (the writer's ``single_option`` marker) is
    the exception, and prints ``{id}: {statement}`` plus the reason: the question of such a
    record is the statement asked back as a question, so printing both halves spent the row's
    width on boilerplate and cut the operator's reason mid-word to pay for it.

    The reason rides at the end after its own mark when the record carries one, and it is the
    part the bound does not fall on: :func:`_bounded_row` clips the statement around the reason
    rather than the tail of the finished line, because a settled statement is readable in the
    record file and the reason is what the row exists to put on the screen. Every field reaches
    the line through :func:`noni.brief_page.page_line`, so a control byte in a question cannot
    reach the terminal while the operator's own words -- a slash command or a path they committed
    alike -- print as the record wrote them. A row whose rendered form is blank or one of the
    page's own words costs the block its row.
    """
    body = _decision_body(record)
    if body is None:
        return None
    head = _field(record.get("id")) + RECORD_SEPARATOR + body
    return _bounded_row(head, _rendered(record.get("why")))


def _decision_body(record: dict) -> str | None:
    """What a row states after the record's id, or ``None`` when it states nothing printable.

    The single-option form is the record's own word and not this reader's reading of its option
    counts: :data:`noni.ledger_schema.SINGLE_OPTION_MARKER` is what the writer sets when a
    one-option question was asked on purpose, and a record whose question holds one option
    without it is malformed and the census's to report. So this reads the marker and asks nothing
    of the options: the reader that refused a malformed record is the arbiter, and a page that
    guessed at the marker from the option count would be a second one.
    """
    questions = record.get("questions")
    if not isinstance(questions, list) or not questions:
        return None
    if record.get(ledger_schema.SINGLE_OPTION_MARKER) is True:
        return _statement_segment(questions[0])
    segments = [_question_segment(question) for question in questions]
    # A question the reader cannot render is a question it cannot answer for: one malformed entry
    # costs the whole record its row rather than printing half a decision.
    return QUESTION_SEPARATOR.join(segments) if all(segments) else None


def _statement_segment(question: object) -> str | None:
    """The statement a single-option record states: its question's answer, or nothing printable.

    The answer and not the question text, because the answer is what the operator wrote down and
    the question of such a record is that same statement dressed as a question. A record whose one
    question carries no answer is an ``open`` record that :func:`_live_records` stopped at the
    ledger, so an empty answer reaching here is the hand-edited shape, and it costs the record its
    row for the reason a malformed entry does.
    """
    if not isinstance(question, dict):
        return None
    return _rendered(question.get("answer")) or None


def _question_segment(question: object) -> str:
    """One question as ``text: answer``, or ``""`` for an entry that is not a question.

    A record whose ``questions`` holds something other than an object, or a question that
    carries no text, contributes nothing here and the caller drops the row. The answer is
    asked for after the text and never instead of it: a row that printed an answer with no
    question beside it would put the operator's word above a question nobody asked. "Carries no
    text" is therefore asked of the field stripped of its whitespace and not of the raw field:
    spaces are not a question either, and such an entry costs the record its row for exactly the
    reason a non-object entry does.
    """
    if not isinstance(question, dict):
        return ""
    text = _field(question.get("text"))
    if not text.strip():
        return ""
    answer = _field(question.get("answer"))
    return f"{text}: {answer or OPEN_ANSWER}"


def _bounded_row(head: str, reason: str) -> str | None:
    """One row of a head and a reason, bounded with the reason kept whole.

    The reason is rendered here and not by the callers, so the two rules a reason answers to --
    no reason at all, and a reason too long to share the row -- are held by one function. The row
    is composed reason-last and bounded reason-last, and that order is what decides what a
    too-long row loses. The head yields: it is a settled statement (or, on an order row, the
    position the artifact itself states), which the reader can go and read in the file the row
    names, while the reason is the half the row exists to put in front of an agent that has not
    read it. One rule bounds the row: the head is clipped around the reason and the finished line
    is bounded by :func:`noni.brief_page.page_line`. A reason is capped at
    :data:`noni._why.WHY_MAX`, which leaves the head room to clip in every case a writer, a census
    or a hand-edited artifact can hand this reader, so there is no second branch to keep.
    """
    reason = _rendered(reason)
    if not reason:
        return page_line(head, TEXT_LIMIT, frozenset())
    mark = REASON_SEPARATOR + reason
    room = TEXT_LIMIT - len(mark)
    head_text = head if len(head) <= room else _head_clip(head, room)
    return page_line(head_text + mark, TEXT_LIMIT, frozenset())


def _head_clip(head: str, room: int) -> str:
    """The head of a row too long for its row, cut at a word where one can be found.

    :func:`noni.census_text._clipped` keeps the page's bound and its clip mark, but it
    cannot promise that the cut lands between words, and a head cut mid-word leaves the
    reader to guess at the subject. So the boundary is asked here rather than of the
    clipper the census shares (whose own rows must not move): the head is kept whole up
    to the last space that leaves room for the mark, and the mark is the page's own
    :data:`noni.brief.ELLIPSIS` -- the same character string the clipped purpose body
    prints, spelled once in the tool and reached through the importer below so the page
    has one spelling of it and no second clipper.

    The row's bound is honoured as it always was: the kept head is at least three
    characters inside the room, so head and mark together never pass it. Where the head
    holds no space to cut at, or none far enough in to leave anything worth reading,
    there is no boundary to find and the character clip is the honest answer: a row
    still has to be printed, bounded and marked.
    """
    # Three of the room are the mark's own budget, and one more is the space the cut
    # lands on, which the row drops rather than prints.
    boundary = head.rfind(" ", 0, room - 4)
    if boundary < _HEAD_MIN:
        return _clipped(head, room)
    return head[:boundary] + _clip_mark()


def _field(value: object) -> str:
    """A record's field as printable text, or ``""`` for anything that is not a string."""
    return value if isinstance(value, str) else ""


# The shortest head the word-boundary clip will keep. Below it a row would print a mark
# over nothing readable, and the character clip -- which at least fills the room the
# reason left -- is the better answer. Three characters is no rule of its own: it is the
# length of the clip mark, the smallest thing the clipper prints beside a kept head.
_HEAD_MIN = 3


def _clip_mark() -> str:
    """The page's clip mark, read from the one place the tool spells it.

    A head cut at a word prints the same three dots the shared clipper prints, and they
    are spelled once in the product, as :data:`noni.brief.ELLIPSIS`. It is read through
    the module that owns it, at the call, rather than imported at the top of this file:
    ``brief`` imports this module's caller, so a top-level import of it back would be a
    cycle.
    """
    from . import brief as _brief

    return _brief.ELLIPSIS
