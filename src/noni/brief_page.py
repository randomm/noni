"""The page's own rules for a line of foreign text, and the counts that go with them.

Split from ``brief.py`` for the 500-line source cap, beside ``brief_intent.py`` and
for the same reason: ``brief.py`` owns the command line, the budget and
what each block prints, and this module owns the decision every printed line of foreign text
passes through on its way to the screen.

The rules are the brief's and not the census's, and two modules hold a piece of each:
:func:`noni.census_text._bounded` is the scrub the census renders its rows with (whitespace
collapsed, machine-local paths replaced, tail bounded), and :func:`noni._safe_text.safe_text` is
the renderer every noni refusal prints its caller-supplied text through (no control bytes,
bounded). Neither is enough on its own for a line of the page: the census scrub is a whitespace
and path rule and leaves an escape byte standing, and the refusal renderer keeps runs of
whitespace and knows nothing about paths. A screen that prints an operator's prose takes
both, in the order that makes the bound mean what it says.
"""

from __future__ import annotations

from pathlib import Path

from . import ledger_schema, orderschema, orderstate
from ._safe_text import safe_text
from .census_text import _bounded, _clipped

# The text of the one question the decisions block asks of every record it reads. Like
# :data:`NOT_READ` it is the tool's own sentence and never a word from a record, so no byte
# of a file this reader did not write reaches stdout on a line that carries it.
OPEN_ANSWER = "(open)"

# The shape tests :func:`_decision_row` applies to the row it composed: the page's bound, and
# no reserved word at all. The header is excluded on purpose. A page that refused a decision
# whose first question happened to be titled exactly like the block would hide a decision for
# the reason a body line shaped like the *order's* header is refused -- that one splits the
# page for a reader -- whereas this one would silently lose the newest answer the block exists
# to print. A row always opens with a record id, so nothing printable can collide with a header
# anyway.

# The separators of one row. The rows are built here and printed by the caller, so the three
# shapes the reader renders -- the join between two questions, the mark that opens the reason,
# and the brackets that hold the record an order position was set by -- are named once beside
# the reader rather than spelled at each end of the join.
QUESTION_SEPARATOR = "; "
REASON_SEPARATOR = " — "
DECISION_BRACKETS = ("(", ")")

# The floor of a clipped statement: the shortest rendering the row keeps a statement for. Below
# it the ellipsis would be most of what stood where the operator's sentence was, and the row is
# better printed with the reason alone than with a fragment no reader can use.
_MIN_CLIPPED_PART = 4

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

    Every part reaches the line through :func:`page_line`, so a control byte in a reason cannot
    reach the terminal and a host path in one prints as ``<path>`` here exactly as it would in a
    census row. A reason that renders to nothing costs its mark and not the row: an entry written
    before the field existed holds no reason, and a mark standing over nothing is the page
    promising a line it did not print.
    """
    record = _rendered(decision)
    head = _order_subject(position, issue)
    if record:
        head += f" {DECISION_BRACKETS[0]}{record}{DECISION_BRACKETS[1]}"
    return _bounded_row(head, _rendered(why), ORDER_SUBJECT_SEPARATOR)


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
    it must survive the page's own scrub with something in it. A field of spaces passes the first
    and fails the second, and so does a field made only of what the scrub deletes (a category-C
    character, say), which is the shape a hand-edited artifact reaches when a reason is deleted
    and its quotes left behind. Asking the page's scrub is what makes a mark stand or fall on the
    same answer the row itself gets.
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

    The two answers travel together for the reason :func:`block_rows` states, over the records
    this reader could hold in hand: a record this reader refused is a row the reader asked for
    and did not get, and a block that withheld lines owes the count line that says so. A row
    that :func:`page_line` refused costs a line the same way. A record that never parsed is not
    among them: it is not a record this reader held, and the count line counts rows withheld
    from a page rather than files the census goes on to fault. A ledger directory this run could
    not list is the same shape one level up -- the block prints its header and pays no count
    line, and the census is what words that fault.
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

    The sort is total and reads no clock. Two records dated to the same instant -- what a
    writer run twice in one second, or a ``--date`` carried over, produces -- still have one
    order between them, the same tiebreak the candidates of the store beside this one use on
    their own two fields. A record that carries no usable ``date`` sorts as the oldest there
    is, which keeps it from crowding the recent records off a five-row block.
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
    the line through :func:`page_line`, so a control byte in a question cannot reach the terminal
    and a host path in a reason prints as ``<path>`` here exactly as it would in a census row. A
    row whose rendered form is blank or one of the page's own words costs the block its row.
    """
    body = _decision_body(record)
    if body is None:
        return None
    head = _field(record.get("id")) + RECORD_SEPARATOR + body
    return _bounded_row(head, _rendered(record.get("why")), RECORD_SEPARATOR)


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


def _bounded_row(head: str, reason: str, keep: str) -> str | None:
    """One row of a head and a reason, bounded with the reason kept whole.

    The reason is scrubbed here and not by the callers, so the two rules a reason answers to --
    no reason at all, and a reason too long to share the row -- are held by one function. The row
    is composed reason-last and bounded reason-last, and that order is what decides what a
    too-long row loses. The head yields: it is a settled statement (or, on an order row, the
    position the artifact itself states), which the reader can go and read in the file the row
    names, while the reason is the half the row exists to put in front of an agent that has not
    read it. Below :data:`_MIN_CLIPPED_PART` a clipped head is mostly the ellipsis that marks it
    clipped, so at that floor the row keeps the parts that identify the row rather than a
    fragment: the head up to the first ``keep`` (the position of an order row, the id of a
    decision row), plus the word that follows it, which is the ``#{issue}`` the order row names
    its subject by. The separator is the caller's, so it is the caller's word that is kept.
    """
    reason = _rendered(reason)
    if not reason:
        return page_line(head, TEXT_LIMIT, frozenset())
    mark = REASON_SEPARATOR + reason
    room = TEXT_LIMIT - len(mark)
    if room < _MIN_CLIPPED_PART:
        subject = head.split(keep, 1)
        kept = subject[0] + keep
        if len(subject) > 1:
            kept += subject[1].split(" ", 1)[0]
        return page_line(kept + REASON_SEPARATOR + reason,
                         TEXT_LIMIT, frozenset())
    head_text = head if len(head) <= room else _clipped(head, room)
    return page_line(head_text + mark, TEXT_LIMIT, frozenset())


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


def _field(value: object) -> str:
    """A record's field as printable text, or ``""`` for anything that is not a string."""
    return value if isinstance(value, str) else ""

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

    Two scrubs, because they answer two different questions and neither is a superset of the
    other. :func:`noni._safe_text.safe_text` drops every Unicode category-C character, which is
    what stops an ANSI or OSC sequence in foreign text reaching the terminal; :func:`noni.census_text
    ._bounded` collapses whitespace and replaces a machine-local path, which is what makes a brief
    row read like a census row. The order of the two matters: the control bytes have to go before
    the bound is applied, so the characters a line loses to the escape being deleted cannot push
    a visible word past the limit and have it replaced by an ellipsis.

    Then the two shape tests a foreign line has to pass to reach stdout: it must survive both
    scrubs as something with content in it, and it must not be one of the words the page is read
    by. ``None`` is the caller's signal to drop the row, and the callers are the places that print
    foreign text -- a purpose line, an order row's subject.

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
