"""decide.py's flag validation: the usage checks that run before git is consulted.

Every rule here is a usage rule, and the reason it lives apart is that all of
them must be refused before the ledger is read or written: a record built from a
malformed flag set would land in the steering ledger as a committed signal, and
the census would then report on a record its own schema does not accept. The
exit code and the message stay decide.py's -- this module holds the reading of
the flags and hands the caller either the pieces of a valid record or the code
of the refusal it already printed.

The rules themselves: ``--date`` is a real calendar day; one to four
``--question`` flags, each ``ID=TEXT`` with distinct ids; and a supersede is
refused while any question is unanswered. ``--option`` / ``--answer`` pairing, the
slug and the 2-4-options-per-question rule stay in decide.py next to the record
renderer they feed.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone

from . import labels

# A date flag is four-digit year, month, day; a real calendar day is checked
# against the calendar on top of the shape.
DATE_FLAG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# decide.py's usage code, restated here so this module imports nothing from
# decide.py (decide.py imports this one).
_EXIT_USAGE = 2  # decide.EXIT_USAGE: a malformed flag set is a usage fault


def _fail(message: str, hint: str | None = None) -> int:
    """Print one decide.py usage refusal in decide.py's words and give back its code."""
    print(f"{labels.DECIDE}: {message}", file=sys.stderr)
    if hint:
        print(f"{labels.DECIDE}: fix: {hint}", file=sys.stderr)
    return _EXIT_USAGE


def parse_date(date: str | None) -> tuple[str | None, int | None]:
    """The date part of the record id, or the exit code of the refusal printed.

    ``None`` for the flag's absence means 'today, UTC', which is what a run that
    names no date records under.
    """
    if date is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d"), None
    if not DATE_FLAG_RE.fullmatch(date):
        return None, _fail(f"--date {date!r} is not YYYY-MM-DD",
                           "pass the record date as --date 2026-10-26")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return None, _fail(f"--date {date!r} is not a real calendar date",
                           "pass a date that exists, e.g. --date 2026-10-26")
    return date, None


def parse_questions(values: list[str]) -> tuple[list[tuple[str, str]], int | None]:
    """``(id, text)`` per ``--question``, or the exit code of the refusal printed.

    One to four questions, each ``ID=TEXT``, each id used once: the record's
    schema carries the answers keyed by id, so a repeated id would silently
    merge two questions into one answer.
    """
    if not 1 <= len(values) <= 4:
        return [], _fail(
            f"{len(values)} --question flag(s); a record carries 1-4 questions",
            "ask between one and four questions, each as --question q1=<text>")
    questions: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value in values:
        qid, sep, text = value.partition("=")
        qid = qid.strip()
        if not sep or not qid or not text:
            return [], _fail(f"--question {value!r} is not an ID=TEXT pair",
                             "write it as --question q1=<the question as asked>")
        if qid in seen:
            return [], _fail(f"--question id {qid!r} is used twice",
                             "give each question its own id")
        seen.add(qid)
        questions.append((qid, text))
    return questions, None


def check_supersede(args: argparse.Namespace, questions: list[tuple[str, str]],
                    answers: list[tuple[str, str]]) -> int | None:
    """The rule a supersede adds, or the exit code of the refusal printed.

    A declined steer is an open chain-root record, never a supersede: an
    unanswered question would leave the chain with no live answer (census exit
    20), so this is a usage error and not a ledger state.
    """
    answered_ids = {oid for oid, _value in answers}
    unanswered = [qid for qid, _text in questions if qid not in answered_ids]
    if unanswered:
        return _fail(
            f"--supersedes {args.supersedes!r} with {len(unanswered)} unanswered "
            f"question(s) ({', '.join(unanswered)}) would leave the chain with no "
            "answer",
            "answer every question with --answer ID=<answer>, or record the "
            "decline as an open chain-root record without --supersedes",
        )
    if args.date is None:
        # A supersede carries the date of the record it replaces, so without
        # --date there is nothing to place it in the chain it corrects.
        return _fail("--supersedes needs --date: a supersede carries the date of "
                     "the record it replaces",
                     "pass the target's date, e.g. --date 2026-10-26")
    return None
