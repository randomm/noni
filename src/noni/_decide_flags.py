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
is unanswered. ``--option`` / ``--answer`` pairing, the slug, the
2-4-options-per-question rule and the marker's one-option requirement stay in
decide.py next to the record renderer they
feed.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Callable

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
    handed-in predicate is what stops the writer and the census disagreeing
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
