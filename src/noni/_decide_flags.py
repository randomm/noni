"""decide.py's flag validation: the usage checks that run before git is consulted.

Every rule here is a usage rule, and the reason it lives apart is that all of
them must be refused before the ledger is read or written: a record built from a
malformed flag set would land in the steering ledger as a committed signal, and
the census would then report on a record its own schema does not accept. The
exit code and the message stay decide.py's -- this module holds the reading of
the flags and hands the caller either the pieces of a valid record or the code
of the refusal it already printed.

The rules themselves: ``--date`` is a real calendar day; a ``--slug`` may not
already begin with a date (the writer prefixes the id with one itself, so a
prefixed slug becomes a doubled-date record), which is one shape stated once as
:data:`SLUG_DATE_PREFIX` and shared with :func:`noni._writer.flag_refusals` so the
two slug validators cannot disagree; one to four
``--question`` flags, each ``ID=TEXT`` with distinct ids; the ``--decided-by`` /
``--on-behalf-of`` names are non-empty single-line strings, decided by the
census's own predicate the caller hands in, and ``--on-behalf-of``
is refused without ``--decided-by``; and a supersede is refused while any question
is unanswered. :func:`build_record_flags` is the whole assembly in one call -- the
slug, the date, the questions, the option/answer pairing against the ids asked, the
two name flags, the marker's one-option requirement and the one rule a supersede adds
over any other record, in the order the refusals need. The record-shape rules it reads
stay the schema's,
handed in as arguments, so a shape the census reports cannot be accepted here.
The caller keeps its printer, its usage code, its two patterns and the schema calls
it resolves; nothing here imports from decide.py.

The module holds decide's path guards too, because they are the other half of what
must be refused before a record is written. :mod:`noni._path_kind` owns the
``lstat`` question -- is every directory from the state root down to the ledger one
this writer may read or write through -- and :func:`noni._path_kind.direction_refusal`
answers it for all three direction writers. :mod:`noni._writer` owns the mechanics
that create a ledger or land a record's bytes. What lives here is the seam between
the two and the printer: the call that asks one question, and the print that gives
its answer ``decide``'s exit code and ``decide``'s prefix.

Three seams, because this writer has three paths it may not use blindly:

- :func:`refuse_linked_state` asks the DIRECTORY question of every component of the
  writer's guarded list -- ``noni`` first, then ``noni/decisions`` -- before the git
  probes, the first read or the ``mkdir``. A link at ``noni`` is invisible to a
  question asked only of the leaf, because ``lstat`` resolves intermediate
  components, and that is the fault that put a record outside the state repository.
- :func:`refuse_ledger_allocation` is the creation half: :func:`noni._writer.allocate_ledger`
  asks the same directory question before its ``mkdir`` because ``Path.is_dir``
  follows a link and answered "already there" for a linked ledger, making the mkdir
  a no-op and the record's destination a tree outside the repository.
- :func:`refuse_taken_name` is the collision check ``Path.is_file`` cannot make:
  ``is_file()`` follows a link, so a record name already spoken as a link reads as
  free and the atomic replace that follows writes through it.

Every seam prints through the caller's own printer and takes the caller's own exit
constant, so the prefix a reader sees is the command they ran and the number is the
one docs/PRODUCT.md 7, ``skills/steering-ledger/SKILL.md`` and the writer's
docstring all state. Each is two statements at its call site, which is what keeps
them out of :mod:`noni.decide` -- a file at the size limit, where a guard that
reached for its own ``lstat`` would be a second reading of one path, the failure
:mod:`noni._path_kind` exists to prevent.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from . import _path_kind, _writer

# A date flag is four-digit year, month, day; a real calendar day is checked
# against the calendar on top of the shape. Anchored, and used with fullmatch:
# '$' alone also matches before a trailing newline.
DATE_FLAG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# A slug may not begin with a date, because the record id is ``<date>-<slug>`` and
# the writer supplies the date: ``2026-11-08-topic`` would become
# ``<this run's date>-2026-11-08-topic``. Shape only, and its own pattern rather
# than ``DATE_FLAG_RE`` or ``parse_date``: that pair belongs to ``--date`` and asks
# the calendar, and a slug made of the wrong digits is a doubled id whatever the
# calendar says. Digits, not ``\\d``, so a Unicode digit cannot pose as one. Shared
# with :func:`noni._writer.flag_refusals`, the other slug validator, so the two
# entry points refuse the same prefix.
SLUG_DATE_PREFIX = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-")

# The refusal this module prints: decide.py's own printer and its usage code,
# handed in by the caller so a refusal is worded and coded in one place. This
# module imports nothing from decide.py (decide.py imports this one), so the
# code and the format come in as arguments rather than being restated here.
Fail = Callable[[int, str, str | None], int]

# The census's own test for the one-line shape, handed in the same way the
# printer is: the writer must refuse exactly what the census reports, and a copy
# of that rule kept here could drift from it in silence.
LineFree = Callable[[object], bool]

# The same rule plus a length bound, for a flagged value that carries one (a
# record's ``why``). Handed in rather than imported for the reason ``LineFree`` is:
# the shape and the number both belong to the schema the census reads, and a copy of
# either here is how a writer comes to accept what the arbiter reports.
BoundedLine = Callable[[object, int], bool]


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
    record and never a supersede.

    The rules stay the census's or the schema's wherever one exists: ``build_questions``
    and ``unanswered_ids`` are the record schema's, handed in so a shape the census
    reports cannot be accepted here, and the one rule this function owns outright is
    the record-id shape, which is spelled by the caller's ``id_re`` for the same
    reason.
    """
    refusal = refuse_slug(args.slug, fail=fail, exit_usage=exit_usage,
                          slug_re=slug_re)
    if refusal is not None:
        return refusal
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


def refuse_slug(slug: str, *, fail: Fail, exit_usage: int,
                slug_re: re.Pattern[str]) -> int | None:
    """The exit code for a slug this writer may not build an id from, or None.

    The one statement of both slug rules, shared with :func:`noni._writer.flag_refusals`
    so the writer's second validator refuses what the first refuses: the character
    rule (the census accepts only this set in a plain path segment) and, on top of
    it, the date-prefix rule :data:`SLUG_DATE_PREFIX` spells. The character rule goes
    first, because a slug holding a slash or a space is not a slug whatever it starts
    with. The prefix refusal names the corrected slug -- the value with its date and
    the following dash removed -- because that is the value the operator meant, and
    the hint says why the writer will not take the dated form: it adds the date
    itself. A slug that is only a date and its trailing dash has an empty remainder,
    which the first rule refuses as not a slug, so that shape is shown no corrected
    slug: there is nothing left to show. A bare date carries no trailing dash
    and stays accepted.
    """
    if not slug_re.fullmatch(slug):
        return fail(exit_usage, f"slug {slug!r} is not a slug",
                    "a slug is [a-z0-9-]+: lowercase letters, digits and dashes, no "
                    "dots, slashes, spaces or uppercase")
    prefixed = SLUG_DATE_PREFIX.match(slug)
    if prefixed:
        # The writer prefixes the id with the date itself (ledger_name), so a slug
        # that begins with a date becomes a record carrying two of them. Refused at
        # the flag, before the name is built. Shape only: a date the calendar refuses
        # is refused here too, because the doubled id is the fault either way. The
        # hint shows the corrected slug, the value with its date prefix removed.
        return fail(exit_usage,
                    f"slug {slug!r} already starts with a date: the record id would "
                    f"carry two",
                    "the writer adds the date itself, so pass the slug without it, "
                    f"as --slug {slug[prefixed.end():]}")
    return None


def refuse_name(flag: str, value: str | None, *, fail: Fail,
                exit_usage: int, line_free: LineFree,
                bounded: BoundedLine | None = None,
                maximum: int | None = None) -> int | None:
    """The census's shape for one optional text flag, or the code of the
    refusal printed. ``None`` (flag absent) is not a refusal: the optional names are
    optional and a record without them means the commit author decided.

    The rule is the census's own (a name must be a non-empty single-line string),
    stated once so the writer refuses at the flag what the census would otherwise
    report at exit 10 after the record was committed. The blank and the line rules are
    both carried by ``line_free``, the census's own predicate handed in by the caller:
    a name that is only whitespace names nobody, and a name carrying a break is not one
    name. Keeping both in the handed-in predicate is what stops the writer and the
    census disagreeing on either.

    The bound is the second half of the pair, asked only when the caller hands it:
    ``bounded``/``maximum`` are how a flagged value that also has a length limit (a
    record's ``why``) is refused at the flag rather than reported by the census after
    the commit. Both arrive together or neither is asked: a bound with no predicate
    could not tell a blank from a long value, and the pair comes from the same schema
    the census reads, so the writer cannot accept a shape the arbiter reports. A name
    flag passes neither and keeps its two refusals.
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

    A declined steer is an open chain-root record, never a supersede: an
    unanswered question would leave the chain with no live answer (census exit
    20), so this is a usage error and not a ledger state. The date is no rule
    here: a supersede carries the run's own ``--date``, exactly as any other
    record does.
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
# across the ledger because the id IS the filename, and the id is built from --date
# and --slug, so the only repair the writer can offer is another slug -- which is
# what the hint says, so one refusal names both the rule and the way to satisfy it.
_TAKEN_HEADLINE = "{path} already exists; record ids are unique across the ledger"
_TAKEN_HINT = "choose a slug nobody has taken"


def refuse_linked_state(printer: Printer, code: int, repo: Path,
                        rels: tuple[str, ...]) -> int | None:
    """The exit code for a ``noni/`` this writer may not read or write, or None.

    The walk, its wording and its declined-``lstat`` rule are all
    :func:`noni._path_kind.direction_refusal`: every component of ``rels`` is asked
    of ``lstat``, from the state root down, and an absent one is the ordinary answer
    a first run creates. Nothing here reads, writes or creates, and nothing raises:
    a declined answer is a refusal, never an absence.

    ``code`` is the caller's own constant so the page and the run agree on one
    number, and the printer is the caller's so the prefix stays the command the
    operator invoked.
    """
    refused = _path_kind.direction_refusal(repo, rels)
    return None if refused is None else printer(code, *refused)


def refuse_state_root(printer: Printer, code: int, repo: Path,
                      admits: Callable[[], bool], *,
                      hint: str = "") -> int | None:
    """The exit code for a ``--repo`` that is no noni state root, or None.

    The question a run asks of its ``--repo`` before it writes anything: the tree holds
    state of somebody's or it holds none, and a tree holding none is a wrong ``--repo``
    whatever the verb intends -- a committed code repository passed where the state clone
    was meant passes the git work-tree probe, so this is the seam that refuses it.

    ``admits`` is the run's creator exception, asked HERE, over the tree as it stands:
    the writer below is reached only once the state root has been settled, and its own
    :func:`noni._writer.allocate_ledger` runs ``mkdir parents=True`` -- so a question about
    the tree deferred past that allocation finds the ``noni/`` this very run made and calls
    it a state root, which is how a wrong ``--repo`` used to answer its own question and
    gain a ledger and a committed record of its own. A writer hands the answer over as a
    thunk so the exception follows the tree's contents (:func:`noni._writer.ledger_is_first`)
    rather than the verb's say-so, and is asked here -- before the guard that can decline to
    ask anything at all.

    The obstruction question is not asked here: :func:`refuse_linked_state` asks it of the
    same ``lstat`` ahead of this, so a linked ``noni/`` keeps the sentence that names it.
    ``code`` is the caller's own constant and ``printer`` its own, so the prefix is the
    command the operator ran and the number is the one its documents state. ``hint`` is
    one sentence the caller adds to the end of the shared fix line -- empty by default,
    so a writer that has no flag of its own prints exactly the two shared sentences.
    """
    refused = None if admits() else _path_kind.state_root_refusal(repo, hint=hint)
    return None if refused is None else printer(code, *refused)

def _allocation_refusal(repo: Path, ledger: Path) -> tuple[str, str] | None:
    """The ledger directory asked as a directory, for a caller that wants the pair.

    The question :func:`refuse_ledger_allocation` asks before its mkdir, exposed for
    a writer whose allocation lives behind its own seam: it is the guard's and never
    a second ``is_dir()`` beside the mkdir.
    """
    return _path_kind.direction_refusal(repo, (_relative(repo, ledger),))


def _relative(root: Path, path: Path) -> str:
    """``path`` spelled from ``root``, or as an off-tree path the guard cannot walk.

    The writers pass a ledger derived from the same ``--repo`` they hand in, so the
    normal case is a one-word ``relative_to``; a path that does not live under the
    root is spelled verbatim, which the guard's own bounds reject rather than
    inspecting -- a caller cannot aim the directory question above its state root.
    """
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def refuse_ledger_allocation(printer: Printer, label: str, code: int, repo: Path,
                             ledger: Path) -> int | None:
    """The exit code for a ledger directory this run may not create, or None.

    The two halves of one allocation, in the order they have to happen: the
    directory question first (the guard, not ``Path.is_dir``, which follows a link
    and answers "already there" for a ``noni/decisions`` that links to a tree
    outside the state repository), then :func:`noni._writer.allocate_ledger`, which
    creates the absent directory the first record needs. Absent is created, a real
    directory is accepted as it stands, and a link or an odd kind comes back as the
    guard's refusal rather than a mkdir through it. A caller asks only after the tree
    has proved itself a work tree with an identity, so a run refused for another
    reason never creates the path it was refused at.
    """
    refused = _allocation_refusal(repo, ledger)
    if refused is not None:
        return printer(code, *refused)
    made = _writer.allocate_ledger(label, repo, ledger)
    return None if made is None else printer(code, *made)


def refuse_taken_name(printer: Printer, code: int, record_path: Path) -> int:
    """The exit code for a record name that is already spoken.

    The writer asks this after its guards have cleared the directory, so anything
    standing at the record's path -- a file, a directory or a link -- is a collision
    and not a name to reuse: the answer is always another slug.
    """
    return printer(code, _TAKEN_HEADLINE.format(path=record_path), _TAKEN_HINT)
