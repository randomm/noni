"""decide.py's flag validation: the usage checks that run before git is consulted.

Every rule here is a usage rule, and all must be refused before the ledger is read or
written: a record built from a malformed flag set would land in the steering ledger as a
committed signal, and the census would report on a record its own schema does not accept.
Exit code and message stay decide.py's -- this module reads the flags and hands the
caller the pieces of a valid record or the code it already printed.

The rules: ``--date`` is a real calendar day; a ``--slug`` may not already begin with a
date (the writer prefixes the id, so a prefixed slug becomes a doubled-date record) --
one shape stated once as :data:`SLUG_DATE_PREFIX` and shared with
:func:`noni._writer.flag_refusals` so the two slug validators cannot disagree; 1-4
``--question`` flags, each ``ID=TEXT`` with distinct ids; ``--decided-by`` /
``--on-behalf-of`` are non-empty single-line strings, decided by the census's predicate
the caller hands in, and ``--on-behalf-of`` is refused without ``--decided-by``;
a supersede is refused while any question is unanswered. :func:`build_record_flags` is the
whole assembly in one call -- slug, date, questions, option/answer pairing against the ids
asked, the two name flags, the marker's one-option requirement and the rule a supersede
adds, in the order the refusals need. The record-shape rules it reads stay the schema's,
handed in as arguments, so a shape the census reports cannot be accepted here. The caller
keeps its printer, usage code, two patterns and schema calls; nothing imports decide.py.

The date arrives as the pair the record needs: the day the id is built from, and the
instant the ``date`` field carries. :func:`date_pair` reads the system clock once for a
run with no ``--date`` and cuts both halves from that one answer -- the clock is never
questioned and never read twice -- so a run cannot file a record whose name and field
fall on either side of midnight.

The module holds decide's path guards too, the other half of what must be refused before a
record is written. :mod:`noni._path_kind` owns the ``lstat`` question -- is every directory
from the state root down to the ledger one this writer may read or write through -- and
answers it for all three direction writers; :mod:`noni._writer` owns the mechanics that
create a ledger or land a record's bytes. What lives here is the seam between the two and
the printer: the call that asks one question, the print that answers it with ``decide``'s
exit code and ``decide``'s prefix.

Three seams, because this writer has three paths it may not use blindly:

- :func:`refuse_linked_state` asks the DIRECTORY question of every component of the
  writer's guarded list -- ``noni`` first, then ``noni/decisions`` -- before the git
  probes, the first read or the ``mkdir``. A link at ``noni`` is invisible to a question
  asked only of the leaf, because ``lstat`` resolves intermediate components; that is the
  fault that put a record outside the state repository.
- :func:`refuse_ledger_allocation` is the creation half: :func:`noni._writer.allocate_ledger`
  asks the same question before its ``mkdir``, because ``Path.is_dir`` follows a link and
  answered "already there" for a linked ledger, making the mkdir a no-op and the
  destination a tree outside the repository.
- :func:`refuse_taken_name` is the collision check ``Path.is_file`` cannot make:
  ``is_file()`` follows a link, so a name already spoken as a link reads as free and the
  atomic replace that follows writes through it.

Every seam prints through the caller's printer and takes its exit constant, so the
prefix is the command run and the number the docs state. Each is two statements at its
call site, which keeps them out of :mod:`noni.decide` -- a file at the size limit, where
a guard reaching for its own ``lstat`` would read one path twice, the failure
:mod:`noni._path_kind` exists to prevent.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from . import _path_kind, _writer
from .orderstate import now_iso

# A date flag is four-digit year, month, day; a real calendar day is checked against the
# calendar on top of the shape. Anchored, and used with fullmatch: '$' alone also matches
# before a trailing newline.
DATE_FLAG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# A slug may not begin with a date, because the record id is ``<date>-<slug>`` and the
# writer supplies the date: ``2026-11-08-topic`` would become
# ``<this run's date>-2026-11-08-topic``. Shape only, and its own pattern rather than
# ``DATE_FLAG_RE`` or ``parse_date``: that pair belongs to ``--date`` and asks the calendar,
# and a slug made of the wrong digits is a doubled id whatever the calendar says. Digits,
# not ``\\d``, so a Unicode digit cannot pose as one. Shared with
# :func:`noni._writer.flag_refusals`, the other slug validator, so the two entry points
# refuse the same prefix.
SLUG_DATE_PREFIX = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-")

# The refusal this module prints: decide.py's printer and its usage code, handed in by the
# caller so a refusal is worded and coded in one place. Nothing here imports decide.py --
# decide.py imports this one -- so both come in as arguments.
Fail = Callable[[int, str, str | None], int]

# The census's own test for the one-line shape, handed in as the printer is: the writer
# must refuse exactly what the census reports, and a copy here could drift.
LineFree = Callable[[object], bool]

# The same rule plus a length bound, for a flagged value that carries one (a record's
# ``why``). Handed in rather than imported for ``LineFree``'s reason: shape and number
# belong to the schema the census reads, and a copy is how a writer starts accepting
# what it reports.
BoundedLine = Callable[[object, int], bool]


class RecordFlags(Protocol):
    """The parsed flags :func:`build_record_flags` reads -- argparse's namespace, typed.

    A Protocol rather than ``argparse.Namespace`` because this module must not import the
    writer that owns the parser, and the seven attributes are the whole of what the assembly
    reads: an argument that grew a flag reads nothing until it is named here.
    """
    slug: str
    date: str | None
    question: list[str]
    option: list[str]
    answer: list[str]
    single_option: bool
    supersedes: str | None


# The seam a no-``--date`` run's stamp comes from: the one function this module reads
# the time from, and the only name it reads no argument for. No flag and no environment
# variable sits in front of it -- a variable a caller could set is a way to backdate a
# record, and a ledger dated by whoever ran the command is not a ledger. Tests move it
# by patching this function, never by setting something.
def run_instant() -> str:
    """This run's UTC instant as ``YYYY-MM-DDTHH:MM:SSZ``.

    Reads the wall clock through :func:`noni.orderstate.now_iso`, the parser the ordering
    writers' ``--now`` flag already goes through, so every timestamp noni writes has one
    owner for its shape: second resolution, no sub-second carry to make two stamps of one
    instant compare unequal. It takes no argument, reads no environment and has no failure
    to report: a system clock is not an input this writer can be handed a malformed one
    of, so there is no refusal here to design around and no fallback to invent. A run asks
    it at most once, from :func:`date_pair`, which cuts both halves of the record's date
    from that single answer.
    """
    return now_iso(None)[0]


def date_pair(date: str | None) -> tuple[str, str]:
    """The two date answers of one run: ``(day, stamp)``.

    The single place a no-``--date`` run reads the clock: :func:`run_instant` is called
    once here and both halves are cut from that one answer -- the day the id is built
    from is the stamp's first ten characters, so name and field cannot fall on either
    side of midnight. An explicit ``--date`` is a day the caller named and nothing more,
    so it is its own day and it stamps at midnight of that day.
    """
    if date is not None:
        # A caller that names a day has said what the record is dated, so the clock is
        # not read at all: the day stands and the stamp is midnight of that day.
        return date, f"{date}T00:00:00Z"
    instant = run_instant()
    return instant[:10], instant


def parse_date(date: str | None, *, fail: Fail,
               exit_usage: int) -> tuple[tuple[str, str] | None, int | None]:
    """The record's ``(day, stamp)`` pair, or the exit code of the refusal printed.

    The pair comes from :func:`date_pair`, which reads the clock once for it, so a run
    cannot file a record whose id names one day and whose field names another around
    midnight. ``None`` for the flag's absence means 'this run, UTC' and is not a refusal
    the flag can earn: the clock is not a flag, so nothing a caller passes can make this
    half refuse, and the refusals here are the two the flag's own shape has. The return
    shape (a value or the code the caller's printer already printed) is the same one
    every rule here keeps.
    """
    if date is None:
        # The flag's absence is not a refusal the flag can earn, and the calendar has no
        # opinion about a day nobody named: the pair is the run's own, one clock reading.
        return date_pair(None), None
    if not DATE_FLAG_RE.fullmatch(date):
        return None, fail(exit_usage, f"--date {date!r} is not YYYY-MM-DD",
                          "pass the record date as --date 2026-10-26")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return None, fail(exit_usage, f"--date {date!r} is not a real calendar date",
                          "pass a date that exists, e.g. --date 2026-10-26")
    return date_pair(date), None


def parse_questions(values: list[str], *, fail: Fail,
                    exit_usage: int) -> tuple[list[tuple[str, str]], int | None]:
    """``(id, text)`` per ``--question``, or the exit code of the refusal printed.

    One to four questions, each ``ID=TEXT``, each id used once: the record's schema
    carries the answers keyed by id, so a repeated id collapses two questions onto
    one answer.
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
                       build_questions: Callable[[list[tuple[str, str]], list[tuple[str,
                                                  str]], list[tuple[str, str]], bool],
                                                 object],
                       unanswered_ids: Callable[[list[tuple[str, str]], list[tuple[str,
                                                 str]]], list[str]],
                       ) -> tuple[str, str, object, list[str]] | int:
    """The record's four parts from the parsed flags, or the refusal's exit code.

    Returns ``(date_part, date_stamp, questions, unanswered)`` for a record this writer may
    write, or the int a caller returns straight away -- every refusal here is printed by the
    caller's printer on its own usage code, so one voice owns wording and number.
    ``date_part`` is the day the id and filename are built from, ``date_stamp`` the
    instant the ``date`` field carries: they travel apart on purpose, the name staying
    ``<day>-<slug>`` while the field keeps the time of day, and both come from the one
    reading :func:`date_pair` took of :func:`run_instant` -- so a ``--date`` run stamps
    midnight of the day it named, a run with no flag stamps the instant it ran.

    The order is the order the refusals need: slug first (it decides the filename, and so
    what the census accepts as a plain path segment), then date, then questions --
    ``--option`` and ``--answer`` are judged against the ids ``--question`` asked -- then
    the name flags and the marker, which read the options each question carries. The
    supersede rules come last because they read the answers: a declined steer is an open
    chain-root record, never a supersede. The rules stay the census's or the schema's
    wherever one exists; the one this function owns outright is the record-id shape,
    spelled by the caller's ``id_re`` for the same reason.
    """
    refusal = refuse_slug(args.slug, fail=fail, exit_usage=exit_usage,
                          slug_re=slug_re)
    if refusal is not None:
        return refusal
    date_pair_value, refused = parse_date(args.date, fail=fail, exit_usage=exit_usage)
    if refused is not None:
        return refused
    date_part, date_stamp_value = date_pair_value
    questions, refused = parse_questions(args.question, fail=fail,
                                        exit_usage=exit_usage)
    if refused is not None:
        return refused
    # The ids --question asked; --option and --answer are checked against them below.
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
    return date_part, date_stamp_value, built, unanswered


def refuse_slug(slug: str, *, fail: Fail, exit_usage: int,
                slug_re: re.Pattern[str]) -> int | None:
    """The exit code for a slug this writer may not build an id from, or None.

    The one statement of both slug rules, shared with :func:`noni._writer.flag_refusals` so
    the writer's second validator refuses what the first refuses: the character rule (the
    census accepts only this set in a plain path segment) and, on top of it, the date-prefix
    rule :data:`SLUG_DATE_PREFIX` spells. The character rule goes first, because a slug
    holding a slash or a space is not a slug whatever it starts with. The prefix refusal
    names the corrected slug -- its date and the following dash removed -- because that is
    the value the operator meant, and the hint says why the dated form is refused: the
    writer adds the date itself. A slug of only a date and its trailing dash has an empty
    remainder the first rule refuses as not a slug, so it is shown no corrected slug; a bare
    date carries no dash and stays accepted.
    """
    if not slug_re.fullmatch(slug):
        return fail(exit_usage, f"slug {slug!r} is not a slug",
                    "a slug is [a-z0-9-]+: lowercase letters, digits and dashes, no "
                    "dots, slashes, spaces or uppercase")
    prefixed = SLUG_DATE_PREFIX.match(slug)
    if prefixed:
        # The writer prefixes the id with the date itself (ledger_name), so a slug
        # that begins with a date becomes a record carrying two of them. Refused at the
        # flag, before the name is built, and shape only: a date the calendar refuses is
        # refused here too, because the doubled id is the fault either way.
        return fail(exit_usage,
                    f"slug {slug!r} already starts with a date: the record id would carry "
                    "two", "the writer adds the date itself, so pass the slug without it, "
                    f"as --slug {slug[prefixed.end():]}")
    return None


def refuse_name(flag: str, value: str | None, *, fail: Fail,
                exit_usage: int, line_free: LineFree,
                bounded: BoundedLine | None = None,
                maximum: int | None = None) -> int | None:
    """The census's shape for one optional text flag, or the code of the refusal printed.

    ``None`` (flag absent) is not a refusal: the names are optional and a record without
    them means the commit author decided. The rule is the census's own (a name must be a
    non-empty single-line string), stated once so the writer refuses at the flag what the
    census would otherwise report at exit 10 after the commit. Blank and line rules are
    both carried by ``line_free``, the census's predicate handed in by the caller: a name
    of only whitespace names nobody, a name with a break is not one name. Keeping both
    there stops the two disagreeing.

    The bound is the second half of a pair, asked only when the caller hands it:
    ``bounded``/``maximum`` are how a flagged value with a length limit (a record's ``why``)
    is refused at the flag rather than reported by the census after the commit. Both arrive
    together or neither is asked -- a bound with no predicate cannot tell a blank from a long
    value -- and the pair comes from the schema the census reads, so the writer cannot accept
    a shape the arbiter reports. A name flag passes neither.
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
    if bounded is not None and maximum is not None and not bounded(value, maximum):
        return fail(exit_usage,
                    f"{flag} is {len(value)} characters, past the {maximum} limit",
                    f"shorten {flag} to at most {maximum} characters")
    return None


def check_supersede(supersedes: str | None, date: str | None,
                    questions: list[tuple[str, str]],
                    answers: list[tuple[str, str]], *, fail: Fail,
                    exit_usage: int) -> int | None:
    """The rule a supersede adds, or the exit code of the refusal printed.

    A declined steer is an open chain-root record, never a supersede: an unanswered
    question would leave the chain with no live answer (census exit 20), so this is a
    usage error, not a ledger state. The date is no rule here: a supersede carries the
    run's own ``--date``, as any other record does.
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
    return None


# The writer's failure printer: the code it wants back, the headline, the fix hint.
# Positional so a writer hands in its own ``_fail`` and keeps its prefix.
Printer = Callable[[int, str, str], int]

# The two lines the collision refusal prints, spelled once. The record id is unique
# across the ledger because the id IS the filename, built from --date and --slug, so
# the only repair the writer can offer is another slug, which is what the hint says:
# one refusal names both the rule and the way to satisfy it.
_TAKEN_HEADLINE = "{path} already exists; record ids are unique across the ledger"
_TAKEN_HINT = "choose a slug nobody has taken"


def refuse_linked_state(printer: Printer, code: int, repo: Path,
                        rels: tuple[str, ...]) -> int | None:
    """The exit code for a ``noni/`` this writer may not read or write, or None.

    The walk, its wording and its declined-``lstat`` rule are all
    :func:`noni._path_kind.direction_refusal`: every component of ``rels`` is asked of
    ``lstat``, from the state root down, and an absent one is the ordinary answer a first
    run creates. Nothing here reads, writes or creates and nothing raises: a declined
    answer is a refusal, never an absence. ``code`` and ``printer`` are the caller's, so
    page and run agree on one number and the prefix names the command that was run.
    """
    refused = _path_kind.direction_refusal(repo, rels)
    return None if refused is None else printer(code, *refused)


def refuse_state_root(printer: Printer, code: int, repo: Path,
                      admits: Callable[[], bool], *, hint: str = "") -> int | None:
    """The exit code for a ``--repo`` that is no noni state root, or None.

    The question a run asks of its ``--repo`` before it writes anything: the tree holds state
    of somebody's or it holds none, and a tree holding none is a wrong ``--repo`` whatever
    the verb intends -- a code repository passed where the state clone was meant passes the
    git work-tree probe, so this is the seam that refuses it.

    ``admits`` is the run's creator exception, asked HERE, over the tree as it stands. The
    writer below is reached only once the state root is settled and its own
    :func:`noni._writer.allocate_ledger` runs ``mkdir parents=True``, so the question,
    deferred past that allocation, finds the ``noni/`` this very run made and calls it a
    state root -- how a wrong ``--repo`` used to answer its own question and gain a ledger
    and a record. A writer hands the answer as a thunk so the exception follows the tree's
    contents (:func:`noni._writer.ledger_is_first`) rather than the verb's say-so, and it
    is asked here, ahead of the guard that can decline to ask.

    The obstruction question is not asked here: :func:`refuse_linked_state` asks it of the
    same ``lstat`` ahead of this, so a linked ``noni/`` keeps the sentence that names it.
    ``code`` and ``printer`` are the caller's own, so the prefix is the command the operator
    ran and the number its documents state. ``hint`` is one sentence the caller adds to the
    shared fix line -- empty by default, so a writer with no flag of its own prints the two
    shared sentences.
    """
    refused = None if admits() else _path_kind.state_root_refusal(repo, hint=hint)
    return None if refused is None else printer(code, *refused)


def _allocation_refusal(repo: Path, ledger: Path) -> tuple[str, str] | None:
    """The ledger directory asked as a directory, for a caller that wants the pair.

    The question :func:`refuse_ledger_allocation` asks before its mkdir, exposed for a
    writer whose allocation lives behind its own seam: the guard's, never a second ``is_dir``
    beside the mkdir.
    """
    return _path_kind.direction_refusal(repo, (_relative(repo, ledger),))


def _relative(root: Path, path: Path) -> str:
    """``path`` spelled from ``root``, or as an off-tree path the guard cannot walk.

    The writers pass a ledger derived from the same ``--repo`` they hand in, so the normal
    case is a one-word ``relative_to``; a path off the root is spelled verbatim and the
    guard's own bounds reject it rather than inspect it -- a caller cannot aim the
    directory question above its state root.
    """
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def refuse_ledger_allocation(printer: Printer, label: str, code: int, repo: Path,
                             ledger: Path) -> int | None:
    """The exit code for a ledger directory this run may not create, or None.

    The two halves of one allocation, in the order they have to happen: the directory
    question first (the guard, not ``Path.is_dir``, which follows a link and answers
    "already there" for a ``noni/decisions`` linking outside the state repository), then
    :func:`noni._writer.allocate_ledger`, which creates the absent directory the first
    record needs. Absent is created, a real directory is accepted as it stands, a link or
    odd kind comes back as the guard's refusal rather than a mkdir through it. A caller
    asks only after the tree proved a work tree with an identity, so a run refused for
    another reason never creates the path it was refused at.
    """
    refused = _allocation_refusal(repo, ledger)
    if refused is not None:
        return printer(code, *refused)
    made = _writer.allocate_ledger(label, repo, ledger)
    return None if made is None else printer(code, *made)


def refuse_taken_name(printer: Printer, code: int, record_path: Path) -> int:
    """The exit code for a record name that is already spoken.

    The writer asks this after its guards cleared the directory, so anything standing at
    the record's path -- file, directory or link -- is a collision and not a name to
    reuse: the answer is always another slug.
    """
    return printer(code, _TAKEN_HEADLINE.format(path=record_path), _TAKEN_HINT)
