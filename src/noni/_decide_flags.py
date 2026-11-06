"""decide.py's flag validation: the usage checks that run before git is consulted.

Every rule here is a usage rule, and the reason it lives apart is that all of
them must be refused before the ledger is read or written: a record built from a
malformed flag set would land in the steering ledger as a committed signal, and
the census would then report on a record its own schema does not accept. The
exit code and the message stay decide.py's -- this module holds the reading of
the flags and hands the caller either the pieces of a valid record or the code
of the refusal it already printed.

The rules themselves: ``--date`` is a real calendar day; one to four
``--question`` flags, each ``ID=TEXT`` with distinct ids; the ``--decided-by`` /
``--on-behalf-of`` names are non-empty single-line strings, decided by the
census's own predicate the caller hands in, and ``--on-behalf-of``
is refused without ``--decided-by``; and a supersede is refused while any question
is unanswered. :func:`build_record_flags` is the whole assembly in one call -- the
slug, the date, the questions, the option/answer pairing against the ids asked, the
two name flags, the marker's one-option requirement and the supersede rules, in the
order the refusals need -- and the record-shape rules it reads stay the schema's,
handed in as arguments, so a shape the census reports cannot be accepted here.
The caller keeps its printer, its usage code, its two patterns and the schema calls
it resolves; nothing here imports from decide.py.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Callable, Protocol

# A date flag is four-digit year, month, day; a real calendar day is checked
# against the calendar on top of the shape. Anchored, and used with fullmatch:
# '$' alone also matches before a trailing newline.
DATE_FLAG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# The refusal this module prints: decide.py's own printer and its usage code,
# handed in by the caller so a refusal is worded and coded in one place. This
# module imports nothing from decide.py (decide.py imports this one), so the
# code and the format come in as arguments rather than being restated here.
Fail = Callable[[int, str, str | None], int]

# The census's own test for the one-line shape, handed in the same way the
# printer is: the writer must refuse exactly what the census reports, and a copy
# of that rule kept here could drift from it in silence.
LineFree = Callable[[object], bool]


class RecordFlags(Protocol):
    """The parsed flags :func:`build_record_flags` reads -- argparse's namespace, typed.

    A Protocol rather than ``argparse.Namespace`` because this module must not
    import the writer that owns the parser, and the seven attributes are the whole
    of what the assembly reads: an argument that grew a flag reads nothing until it
    is named here.
    """

    slug: str
    date: str | None
    question: list[str]
    option: list[str]
    answer: list[str]
    single_option: bool
    supersedes: str | None


def parse_date(date: str | None, *, fail: Fail, exit_usage: int) -> tuple[str | None, int | None]:
    """The date part of the record id, or the exit code of the refusal printed.

    ``None`` for the flag's absence means 'today, UTC', which is what a run that
    names no date records under.
    """
    if date is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d"), None
    if not DATE_FLAG_RE.fullmatch(date):
        return None, fail(exit_usage, f"--date {date!r} is not YYYY-MM-DD",
                          "pass the record date as --date 2026-10-26")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return None, fail(exit_usage, f"--date {date!r} is not a real calendar date",
                          "pass a date that exists, e.g. --date 2026-10-26")
    return date, None


def parse_questions(values: list[str], *, fail: Fail,
                    exit_usage: int) -> tuple[list[tuple[str, str]], int | None]:
    """``(id, text)`` per ``--question``, or the exit code of the refusal printed.

    One to four questions, each ``ID=TEXT``, each id used once: the record's
    schema carries the answers keyed by id, so a repeated id would silently
    merge two questions into one answer.
    """
    if not 1 <= len(values) <= 4:
        return [], fail(
            exit_usage,
            f"{len(values)} --question flag(s); a record carries 1-4 questions",
            "ask between one and four questions, each as --question q1=<text>")
    questions: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value in values:
        qid, sep, text = value.partition("=")
        qid = qid.strip()
        if not sep or not qid or not text:
            return [], fail(
                exit_usage, f"--question {value!r} is not an ID=TEXT pair",
                "write it as --question q1=<the question as asked>")
        if qid in seen:
            return [], fail(exit_usage, f"--question id {qid!r} is used twice",
                            "give each question its own id")
        seen.add(qid)
        questions.append((qid, text))
    return questions, None


def build_record_flags(args: RecordFlags, *, fail: Fail, exit_usage: int,
                       slug_re: re.Pattern[str], id_re: re.Pattern[str],
                       parse_pairs: Callable[[list[str], str],
                                             tuple[list[tuple[str, str]], str | None]],
                       pair_refuse: Callable[[str, list[tuple[str, str]], set[str]],
                                             int | None],
                       name_refuse: Callable[[object, dict[str, list[str]]],
                                              int | None],
                       build_questions: Callable[[list[tuple[str, str]],
                                                  list[tuple[str, str]],
                                                  list[tuple[str, str]], bool],
                                                 object],
                       unanswered_ids: Callable[[list[tuple[str, str]],
                                                 list[tuple[str, str]]],
                                                 list[str]]) -> tuple[str, object, list[str]] | int:
    """The record's three parts from the parsed flags, or the refusal's exit code.

    Returns ``(date_part, questions, unanswered)`` for a record this writer may
    write, or the int a caller returns straight away -- every refusal here is
    printed by the caller's own printer on its own usage code, so one voice owns
    the wording and the number.

    The order is the order the refusals need: the slug first because it decides the
    filename (and so what the census can accept as a plain path segment), then the
    date, then the questions -- because ``--option`` and ``--answer`` are judged
    against the ids ``--question`` asked -- then the two name flags and the marker,
    which read the options each question will actually carry. The supersede rules
    come last because they read the answers: a declined steer is an open chain-root
    record and never a supersede, and a supersede without ``--date`` has no place in
    the chain it corrects.

    The rules stay the census's or the schema's wherever one exists: ``build_questions``
    and ``unanswered_ids`` are the record schema's, handed in so a shape the census
    reports cannot be accepted here, and the one rule this function owns outright is
    the record-id shape, which is spelled by the caller's ``id_re`` for the same
    reason.
    """
    if not slug_re.fullmatch(args.slug):
        return fail(exit_usage, f"slug {args.slug!r} is not a slug",
                    "a slug is [a-z0-9-]+: lowercase letters, digits and dashes, no "
                    "dots, slashes, spaces or uppercase")
    date_part, refused = parse_date(args.date, fail=fail, exit_usage=exit_usage)
    if refused is not None:
        return refused
    questions, refused = parse_questions(args.question, fail=fail,
                                        exit_usage=exit_usage)
    if refused is not None:
        return refused
    # The ids --question asked, kept here because --option and --answer are
    # checked against them just below.
    seen = {qid for qid, _text in questions}

    options, problem = parse_pairs(args.option, "--option")
    if problem is not None:
        return fail(exit_usage, problem,
                    "give every option 2-4 entries per question")
    answers, problem = parse_pairs(args.answer, "--answer")
    if problem is not None:
        return fail(exit_usage, problem,
                    "answer a question with --answer ID=<answer>")
    for flag, pairs in (("--option", options), ("--answer", answers)):
        unknown = pair_refuse(flag, pairs, seen)
        if unknown is not None:
            return unknown
    # The options each question holds, in the order given: the marker refusal reads
    # the same counts the record will carry, so the flag and the censuses answer one
    # question rather than two.
    options_by_question = {qid: [o for oid, o in options if oid == qid]
                           for qid, _text in questions}
    refused = name_refuse(args, options_by_question)
    if refused is not None:
        return refused
    built = build_questions(questions, options, answers, args.single_option)
    if isinstance(built, str):
        return fail(exit_usage, built,
                    "give every question 2-4 options, or --single-option to "
                    "allow exactly one")

    unanswered = unanswered_ids(questions, answers)
    if args.supersedes is not None:
        refused = check_supersede(args.supersedes, args.date, questions, answers,
                                  fail=fail, exit_usage=exit_usage)
        if refused is not None:
            return refused
        if not id_re.fullmatch(args.supersedes):
            return fail(exit_usage,
                        f"--supersedes {args.supersedes!r} is not a record id",
                        "a record id is YYYY-MM-DD-<slug>, e.g. 2026-10-01-steer-order")
    return date_part, built, unanswered


def refuse_name(flag: str, value: str | None, *, fail: Fail,
                exit_usage: int, line_free: LineFree) -> int | None:
    """The census's shape for one of the two name flags, or the code of the
    refusal printed. ``None`` (flag absent) is not a refusal: both names are
    optional and a record without them means the commit author decided.

    The rule is the census's own (`decided_by`/`on_behalf_of` must be non-empty
    single-line strings), stated once so the writer refuses at the flag what the
    census would otherwise report at exit 10 after the record was committed. The
    blank and the line rules are both carried by ``line_free``, the census's own
    predicate handed in by the caller: a name that is only whitespace names
    nobody, and a name carrying a break is not one name. Keeping both in the
    handed-in predicate is what stops the writer and the two censuses disagreeing
    on either.
    """
    if value is None:
        return None
    if not line_free(value):
        # One predicate, two refusals: the flag is empty when the census calls it
        # blank, and not a single line when it carries a break.
        if not value.strip():
            return fail(exit_usage, f"{flag} is empty",
                        f"name a login or pseudonym, e.g. {flag} operator-ann")
        return fail(exit_usage, f"{flag} is not a single line",
                    f"one name per {flag}: no line break in the value")
    return None


def check_supersede(supersedes: str | None, date: str | None,
                    questions: list[tuple[str, str]],
                    answers: list[tuple[str, str]], *, fail: Fail,
                    exit_usage: int) -> int | None:
    """The rule a supersede adds, or the exit code of the refusal printed.

    A declined steer is an open chain-root record, never a supersede: an
    unanswered question would leave the chain with no live answer (census exit
    20), so this is a usage error and not a ledger state.
    """
    answered_ids = {oid for oid, _value in answers}
    unanswered = [qid for qid, _text in questions if qid not in answered_ids]
    if unanswered:
        return fail(
            exit_usage,
            f"--supersedes {supersedes!r} with {len(unanswered)} unanswered "
            f"question(s) ({', '.join(unanswered)}) would leave the chain with no "
            "answer",
            "answer every question with --answer ID=<answer>, or record the "
            "decline as an open chain-root record without --supersedes",
        )
    if date is None:
        # A supersede carries the date of the record it replaces, so without
        # --date there is nothing to place it in the chain it corrects.
        return fail(exit_usage,
                    "--supersedes needs --date: a supersede carries the date of "
                    "the record it replaces",
                    "pass the target's date, e.g. --date 2026-10-26")
    return None
