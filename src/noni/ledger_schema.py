"""The record schema shared by noni's census and its decision writer.

``census_ledger_checks.py`` owns the ``ledger-record`` pass; both it and
``decide.py`` read the field sets and the two rules declared here, and
``decide.py`` holds the writer to the same rules before a record is committed:
the flag check in ``_decide_flags.refuse_name`` and the supersede-target check in
``targetschema.refuse_target_fields`` ask the predicates below rather than keeping
a copy of the shape. One owner for the vocabulary is what keeps a writer and the
census from drifting apart in silence -- the symptom of a drift is
a record the writer happily committed and the census then reports at exit 10.

The level this schema is at, the path an attached project declares its census's
level at, and the reader of that declaration live in ``ledger_level.py`` beside
this file: the schema is the vocabulary and that module is the one number drawn
from it, and both are named by the writer and the census alike rather than by
either one. Nothing here prints, exits or appends a finding: these are the sets
and the predicates, and each caller words its own refusal.
"""

from __future__ import annotations

import json
import re

from . import _why

# The eight required ledger fields, in the order the writer renders them. This is
# the closed required set: a record missing one is a ``ledger-record`` failure.
REQUIRED_LEDGER_FIELDS = (
    "id",
    "date",
    "asked_by",
    "questions",
    "by",
    "scope",
    "status",
    "supersedes",
)

# The optional (but validated) ledger fields. ``source`` carries the tracker
# provenance of a record produced from a tracker-sourced answer (an adapter's
# question-legitimacy verdict): an object with ``issue_number`` (int) and
# ``comment_id`` (int). ``null`` (or absent) for records that did not come from a
# tracker. ``decided_by`` and ``on_behalf_of`` are the two attribution names: who
# made the decision, and the party it was made for (see ``NAME_LINE_FIELDS``).
# ``single_option`` is the writer's marker that a one-option question was asked on
# purpose rather than malformed; the bound it relaxes is stated at
# ``OPTION_MIN_WITH_MARKER``. ``why`` is the operator's one line of reason for the
# decision, written by ``decide.py --why`` and held to ``why_max()`` on top of the
# single-line rule below. A record without any of them is the eight-field shape
# and stays valid, which is what keeps every record written before these fields
# existed censusable.
OPTIONAL_LEDGER_FIELDS = ("source", "decided_by", "on_behalf_of", "single_option",
                          "why")

# The two attribution names, typed as ``asked_by`` is typed (a non-empty string)
# plus the one rule that makes them reportable: the value is one line, so it cannot
# smuggle a second line into a report or a log line. The census checks these
# shapes (here, as the predicate below) and nothing more -- the census
# never verifies an identity, and no signature or forge check lives here. The
# pairing (``on_behalf_of`` without ``decided_by``) is the writer's rule alone: a
# hand-edited record carrying one name and not the other is well formed, and
# the census does not refuse it.
NAME_LINE_FIELDS = ("decided_by", "on_behalf_of")

# The option bounds. Both censuses and the writer agree on these: 2-4 options per
# question normally, and 1-4 for a record that carries the ``single_option`` marker
# written by ``decide.py --single-option``. The marker is the discriminator: a
# one-option record cannot be told apart from a broken multiple-choice form by its
# content alone, so the lower bound is never relaxed by content.
OPTION_MIN = 2
OPTION_MAX = 4
OPTION_MIN_WITH_MARKER = 1

# The marker's key, and the only value it may hold. Anything else present at that
# key -- ``false``, a string, a number -- is a malformed marker, not a relaxed bound.
SINGLE_OPTION_MARKER = "single_option"

# What ``str.splitlines`` honours and json writes into the bytes without escaping:
# U+0085 and the two Unicode separators. A value carrying one is a single JSON
# string that is not one line, which is exactly what the single-line rule refuses;
# the plain controls (\n, \r, \v, \f) and the three separators U+001C-U+001E
# (file, group, record) json escapes, and are listed alongside for the
# hand-edited record: ``str.splitlines`` -- the documented basis of this rule --
# breaks a line on all ten, so a value carrying one of them is not one line
# however it was written. Shared by the census and the writer so the four of
# them never disagree on what a line is.
LINE_BREAKS = ("\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85",
               "\u2028", "\u2029")

# The four characters the blank-name rule refuses, spelled out: space, tab,
# U+000B and U+000C. A value made of nothing but these names nobody. The set is
# not "what ``str.strip`` removes": ``str.strip`` also removes U+001C-U+001F,
# U+0085, U+00A0, U+1680, the U+2000-U+200A run, U+202F, U+205F and U+3000, and a
# name made of one of those is not blank to this rule -- the four breaks among
# them (U+001C-U+001E, U+0085, U+2028, U+2029 and the rest of ``LINE_BREAKS``) are
# refused as more than one line, never as a blank, and the others name somebody.
# The census reads the same four through this set, so a hand-edited record holding
# a blank name is refused by the census and not only at the flag.
BLANKS = (" ", "\t", "\v", "\f")

# A UTC ISO-8601 second-resolution timestamp (the record date shape).
DATE_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$"
)


def is_single_line(value: object) -> bool:
    """Whether ``value`` is the shape the census accepts for a name field: a
    string that is neither blank nor more than one line.

    Two rules, one predicate, so a writer, the census and the supersede-target
    read cannot drift on either. Blankness is folded in here rather than kept as
    a separate check the caller has to remember: a name that is only whitespace
    names nobody, so it is refused wherever the shape is asked -- at the flag
    (exit 2), at the supersede target (exit 4) and in the census (exit 10).
    The line rule is ``LINE_BREAKS``, which is ``str.splitlines`` read out as a
    set, so a value carrying one of the ten is two lines even when json holds it
    as one string.
    """
    return (isinstance(value, str) and bool(value.strip("".join(BLANKS)))
            and not any(char in value for char in LINE_BREAKS))


def why_problems(record: dict) -> list[str]:
    """What ``record``'s ``why`` gets wrong, as problem strings naming the field.

    The ledger's name for :func:`noni._why.why_problems`: the writer's flag, this
    census group's record pass, the ordering census's entry pass and the
    supersede-target read all ask one question of a rationale, so the wording is one
    sentence wherever a bad ``why`` is refused. See that module for the two rules and
    the bound's one owner.
    """
    return _why.why_problems(record)


def is_bounded_single_line(value: object, maximum: int) -> bool:
    """Whether ``value`` is one non-blank line of at most ``maximum`` code points.

    The ledger's name for :func:`noni._why.is_bounded_single_line`, which is what a
    writer's flag check asks when a free-text value carries a bound as well as a
    shape rule. :func:`is_single_line` keeps its one-argument signature: the bound is
    a separate check, so the two attribution name fields keep their current shape.
    """
    return _why.is_bounded_single_line(value, maximum)


def why_max() -> int:
    """The rationale bound, read from :data:`noni._why.WHY_MAX`, the one owner.

    Never spelled here nor anywhere else in the product: a second literal is how a
    writer and the census come to disagree about a value one of them wrote, and how a
    doc page comes to state a bound no code enforces.
    """
    return _why.why_max()


# The key a rationale is written under, read from the module that states the rule:
# the record's field, an order entry's field, and the name every refusal and every
# census row prints for it.
WHY_FIELD = _why.WHY_FIELD


def is_non_empty_string(value: object) -> bool:
    """Whether ``value`` is a string carrying at least one character.

    The type the census wants for ``id``, ``by``, ``asked_by``, ``scope`` and
    ``date``: ``bool`` fails it because Python calls ``True`` an ``int`` and json's
    ``true`` is neither a number nor a string.
    """
    return isinstance(value, str) and bool(value)


# --- the shape of one record, as the census and the writer check it ----------
#
# The problem list these helpers build is what census.py's ``ledger-record`` class
# reports, so the wording is part of the contract: one problem names one field and
# nothing else, and a rewording is a golden-fixture change at once.
# ``census_ledger_checks`` composes the rows; these helpers answer questions about
# fields and never append to anything.


def validate_source(record: dict) -> list[str]:
    """What ``record``'s tracker provenance gets wrong, as problem strings.

    ``source`` is the one optional field that is itself an object, so its keys are a
    closed set of their own: an extra key would ride into a report on a provenance
    nobody asked for. A JSON integer is a number with no fractional part and no
    exponent, which is what this checks with
    ``isinstance(int)`` plus not-``bool``, because Python calls ``True`` an ``int``
    and json's ``true`` is not a number the census accepts.

    Total on the record: no ``source`` key is no provenance and answers no problem,
    so a caller asks the question without first asking whether it may.
    """
    src = record.get("source")
    if src is None:
        return []
    if not isinstance(src, dict):
        return ["source must be null or an object with issue_number and comment_id"]
    problems: list[str] = []
    for key in ("issue_number", "comment_id"):
        value = src.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            problems.append(f"source.{key} must be an integer")
    extra = [k for k in src if k not in ("issue_number", "comment_id")]
    if extra:
        problems.append("source unknown field(s): " + ", ".join(sorted(extra)))
    return problems


# The calendar ranges, read out of the matched positions of a date the regex has
# already accepted: (first slice, last slice, low, high, the problem it reports).
# A leap second is the only 60 the census admits, and a 13th month is not a month,
# so a date that parses to a time the calendar has no name for is a malformed
# record and not a date the census will sort a chain by.
_DATE_RANGES: tuple[tuple[int, int, int, int, str], ...] = (
    (5, 7, 1, 12, "date month out of range"),
    (8, 10, 1, 31, "date day out of range"),
    (11, 13, 0, 23, "date hour out of range"),
    (14, 16, 0, 59, "date minute out of range"),
    (17, 19, 0, 60, "date second out of range"),
)


def validate_date(record: dict) -> list[str]:
    """What ``record``'s ``date`` gets wrong, as problem strings.

    The shape is ``DATE_RE``; the ranges are ``_DATE_RANGES``. An absent ``date``
    is no problem here -- a missing field is reported once, by the required-field
    check that names it.
    """
    date = record.get("date")
    if not isinstance(date, str):
        return [] if "date" not in record else ["date is not a string"]
    if not DATE_RE.match(date):
        return ["date is not a valid UTC ISO-8601 string"]
    return [problem for start, stop, low, high, problem in _DATE_RANGES
            if not low <= int(date[start:stop]) <= high]


def validate_questions(record: dict) -> list[str]:
    """What ``record``'s question list gets wrong, as problem strings.

    One option is a malformed multiple-choice question unless the record carries the
    writer's marker, so a one-option record cannot be told apart from a broken 2-4
    form by its content alone: the marker is the discriminator, exactly as the
    operator decision on issue #59 settled it. The marker relaxes the lower bound
    for every question of the record it is written on, which is what lets one record
    mix a one-option question with a 2-4-option one.

    The marker is per record; the bound it relaxes is per question, and the marker
    must be earned by one: with the marker present, at least one question of the
    record has to carry exactly one option. A marker over an all-2-4 record says
    something the record does not show, so it is reported rather than ignored.
    """
    if "questions" not in record:
        return []
    questions = record["questions"]
    if not isinstance(questions, list) or not 1 <= len(questions) <= 4:
        return ["questions must be an array of 1-4 entries"]
    marker = record.get(SINGLE_OPTION_MARKER) is True
    lower = OPTION_MIN_WITH_MARKER if marker else OPTION_MIN
    # Asked once for the record, not per question: the marker is a per-record
    # claim that the record holds a one-option question, so a record with two
    # questions, one asked with one option and one with two, satisfies it. A
    # question is counted only when its options are a list at all -- a malformed
    # options value already earns its own problem below.
    earns_marker = any(isinstance(question, dict)
                       and isinstance(question.get("options"), list)
                       and len(question["options"]) == 1
                       for question in questions)
    problems: list[str] = []
    for question in questions:
        if not isinstance(question, dict):
            problems.append("question entry is not an object")
            continue
        if not ({"id", "text", "options"} <= set(question)):
            problems.append("question missing id/text/options")
        options = question.get("options")
        if not isinstance(options, list) or not lower <= len(options) <= OPTION_MAX:
            problems.append(f"question options must be an array of {OPTION_MIN}-{OPTION_MAX} "
                            f"strings ({OPTION_MIN_WITH_MARKER}-{OPTION_MAX} "
                            f"with the {SINGLE_OPTION_MARKER} marker)")
        elif not all(isinstance(option, str) for option in options):
            problems.append("question options must be strings")
        answer = question.get("answer")
        if "answer" in question and answer is not None and not isinstance(answer, str):
            problems.append("question answer must be a string or null")
    if marker and not earns_marker:
        # The marker must be earned by at least one question of the record it is
        # written on: a record marked single-option while every question holds 2-4
        # options was not written by --single-option (the writer refuses that shape
        # at the flag), so it is reported rather than believed. Both facts it rests
        # on are read from the record itself: the marker as the true literal, and
        # the one-option count.
        problems.append(f"{SINGLE_OPTION_MARKER} is set but no question has exactly "
                        f"one option: a one-option question is what the marker means")
    return problems


# The record's ``status``, and the status a run writes. A question with no answer
# is an open chain-root record, and an unanswered question is exactly what a
# supersede must not leave behind, so the word is decided from the answers and is
# the one field of an existing record the writer is allowed to change.
STATUS_DECIDED = "decided"
STATUS_OPEN = "open"
STATUS_SUPERSEDED = "superseded"
STATUSES = (STATUS_DECIDED, STATUS_OPEN, STATUS_SUPERSEDED)


def status_for(unanswered: list[str]) -> str:
    """The ``status`` a record with these unanswered question ids carries."""
    return STATUS_OPEN if unanswered else STATUS_DECIDED


def render(record: dict, field_order: tuple[str, ...]) -> str:
    """The record's bytes: ``field_order``, two-space indent, one trailing newline.

    The order is the writer's, not this module's, because it is the order the census
    and the supersede canonical-form comparison read: a record whose fields arrive
    in another order is not in the form ``decide.py`` writes.

    A key outside ``field_order`` is refused rather than dropped. Silently dropping
    it would print a body missing a field the caller believes it wrote: the bytes
    would not match the dict, a supersede would compare its target against bytes it
    never rendered, and the census would read back a record with a field gone. One
    ``ValueError`` says so, and the callers already treat a refused render as their
    exit-4 event.

    The renderer refuses a number json cannot hold: ``allow_nan=False`` raises on
    ``NaN``, ``Infinity`` and an overflowed literal, and that ``ValueError`` is let
    go rather than worded here -- the callers catch it, and neither may be handed an
    empty string for a body.
    """
    unknown = [key for key in record if key not in field_order]
    if unknown:
        raise ValueError("the record carries field(s) outside the writer's field "
                         "order: " + ", ".join(sorted(unknown)))
    ordered = {key: record[key] for key in field_order if key in record}
    return json.dumps(ordered, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def build_questions(questions: list[tuple[str, str]], options: list[tuple[str, str]],
                    answers: list[tuple[str, str]], single_option: bool) -> list[dict] | str:
    """The record's question objects (id, text, options in given order, an answer
    that is a string or null, last ``--answer`` wins), or a refusal message.

    ``single_option`` is the writer's flag-level answer to "was a one-option form
    requested", and the writer's flag is the only thing that relaxes the bound. It
    relaxes per question rather than per record: a record written with the flag may
    still mix one-option and 2-4-option questions, and each question is judged on
    its own option count. The marker the census reads is written by the caller, so
    this rule never has to guess a record's intent from its option counts; the
    census checks the marker is earned by one of the record's questions.
    """
    lower = OPTION_MIN_WITH_MARKER if single_option else OPTION_MIN
    built: list[dict] = []
    for qid, text in questions:
        opts = [o for oid, o in options if oid == qid]
        if not lower <= len(opts) <= OPTION_MAX:
            return (f"question {qid} has {len(opts)} option(s); every question needs "
                    f"{lower}-{OPTION_MAX} options, given as --option {qid}=<option>"
                    + ("" if single_option else
                       f", or pass --{SINGLE_OPTION_MARKER.replace('_', '-')} to record "
                       "a decision the operator already made with one option"))
        asked = [a for aid, a in answers if aid == qid]
        built.append({"id": qid, "text": text, "options": opts,
                      "answer": asked[-1] if asked else None})
    return built


def parse_pairs(values: list[str], flag: str) -> tuple[list[tuple[str, str]], str | None]:
    """``ID=VALUE`` repeats as ordered pairs, or the message naming the malformed one.

    No '=' attaches a value to no question and an empty key or value writes a record
    the census rejects, so both are refused with the shape spelled out. Only the
    first '=' splits (a free-text answer may carry one) and order is kept: two
    ``--option q1=...`` flags are two options of q1.
    """
    out: list[tuple[str, str]] = []
    for value in values:
        key, sep, rest = value.partition("=")
        if not sep or not key.strip() or not rest:
            return [], (f"{flag} {value!r} is not an ID=VALUE pair "
                        f"(write it as {flag} q1=<value>, where q1 is the question's id)")
        out.append((key.strip(), rest))
    return out, None


def pair_refusal(flag: str, pairs: list[tuple[str, str]],
                 asked: set[str]) -> tuple[str, str] | None:
    """The (headline, hint) refusal for ``pairs`` naming a question ``asked`` does
    not hold, or None when every id matches.

    An option or an answer for an id nobody asked about would be dropped silently
    into a record the operator never wrote, so the id has to match one of the
    question ids and the refusal names the offending ones.
    """
    unknown = sorted({oid for oid, _v in pairs} - asked)
    if not unknown:
        return None
    return (f"{flag} names question(s) {', '.join(unknown)} that no --question asks",
            "the id must match one of the --question ids")


def unanswered_ids(questions: list[tuple[str, str]],
                   answers: list[tuple[str, str]]) -> list[str]:
    """The ids ``questions`` asks and ``answers`` never answers, in asked order.

    These are the questions written open (``"answer": null``), and the same list is
    what makes a run's status ``open`` and what makes a ``--supersedes`` run a
    refusal: an unanswered question would leave the chain with no live answer.
    """
    answered = {oid for oid, _value in answers}
    return [qid for qid, _text in questions if qid not in answered]


def source_provenance(issue: int | None,
                      comment: int | None) -> tuple[dict | None, tuple[str, str] | None]:
    """The record's ``source`` object (None for no provenance), and a (headline,
    hint) refusal pair when the two tracker flags do not agree.

    Half a provenance is refused because an object carrying one of its two integers
    would fail the census, and a tracker id is a positive number: zero or negative
    names no issue and no comment, so the record would carry provenance nothing can
    check. The caller words the refusal with its own printer and code.
    """
    if (issue is None) != (comment is None):
        return None, ("source provenance needs both --source-issue and --source-comment",
                      f"got issue={issue!r} comment={comment!r}; pass both, or neither")
    if issue is None:
        return None, None
    for flag, value in (("--source-issue", issue), ("--source-comment", comment)):
        if value is None or value < 1:
            return None, (f"{flag} {value!r} is not a positive integer",
                          f"name a real tracker id, e.g. {flag} 42")
    return {"issue_number": issue, "comment_id": comment}, None


def record_body(*, record_id: str, date_stamp: str,
                asked_by: str, questions: list[dict],
                by: str, scope: str, unanswered: list[str],
                supersedes: str | None, source: dict | None, decided_by: str | None,
                on_behalf_of: str | None, single_option: bool,
                why: str | None = None) -> dict:
    """The record as the writer renders it, in the order :func:`render` keeps.

    Each optional field is written only when its flag was given, so a run that
    passes none of them produces byte-for-byte the eight-field record. ``by`` is
    the commit author and is never overridden: the census reports ``by`` from git,
    so ``decided_by`` and ``on_behalf_of`` sit beside it as what the writer was
    told, not as a claim about the commit.

    The two date answers arrive apart because the writer's caller holds them apart:
    the day the id and the filename are built from never crosses into the record, and
    ``date_stamp`` is the instant the ``date`` field carries -- already a full
    ISO-8601 stamp, which the writer's own flag rules produced from one clock reading
    and nothing here restates. The record's ``date`` is never derived from its id, so a
    record whose filename names one day and whose field names another is the census's to
    report, not this function's to invent.
    """
    record: dict = {
        "id": record_id,
        "date": date_stamp,
        "asked_by": asked_by,
        "questions": questions,
        "by": by,
        "scope": scope,
        "status": status_for(unanswered),
        "supersedes": supersedes,
    }
    if source is not None:
        record["source"] = source
    if decided_by is not None:
        record["decided_by"] = decided_by
    if on_behalf_of is not None:
        record["on_behalf_of"] = on_behalf_of
    if single_option:
        record[SINGLE_OPTION_MARKER] = True
    if why is not None:
        record[WHY_FIELD] = why
    return record


def supersede_plan(supersedes: str | None, record_id: str, record_rel: str,
                   target_rel: str | None) -> tuple[list[str], str]:
    """The paths a run claims, and the commit subject that names the act.

    A supersede names both records it moves, so the log says what was replaced and
    not just what was added; a plain record names itself.
    """
    rels = [record_rel] if target_rel is None else [record_rel, target_rel]
    verb = f"supersede {supersedes} with {record_id}" if supersedes else record_id
    return rels, f"steering: {verb}"
