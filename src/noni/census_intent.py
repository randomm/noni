"""The census's ``intent`` class: the standing intent file, read as the arbiter reads it.

Split from ``census.py`` the way the ordering group was: ``census.py`` owns the
CLI, the row shape and the group wiring, ``census_report.py`` owns the class
table, and this module owns the one class it reports over
``noni/direction/intent.md`` and the verdicts built from what the reads return.

One class, one read of the file, plus the history answer the run already holds:

- absent is not a finding. Standing intent is optional, so a project that has
  written none earns no row at all, exactly as a project that has never ordered
  anything earns no ordering rows.
- present and structurally wrong earns one row per problem, bucketed by subject:
  ``section-missing`` for a heading missing, repeated or out of order and for a
  ``Last-confirmed:`` line absent or repeated, ``over-cap`` for a file past the
  line cap. The rules are ``intentschema.problems``, the writer's own, so a file
  the writer produced is never a file this class calls broken.
- present and well-formed, but the last commit that touched the file does not
  carry the subject ``intent: <id>`` naming a record the ledger holds, earns one
  ``uncited`` row. That is one question, answered from the history view the run
  already built (``Git.commit_subject``) plus the ledger listing the run already
  took: no second ``git log``, no second readdir.
- a symlink, a directory, a device, an unreadable file or non-UTF-8 bytes earn
  one ``cannot-tell`` row and never a crash, never a clean. The same is true of
  the decision record the citation names: a cited record that is not an ordinary
  file is a ``cannot-tell``, never an ``uncited`` verdict built from bytes read
  through the link.

Nothing here prints or exits: every answer is appended to the caller's
``findings`` list through the ``row`` factory the census supplies.
"""

from __future__ import annotations

import errno
import re
from pathlib import Path
from typing import Callable

from . import intentschema

# A ledger record id is what decide.py writes: <YYYY-MM-DD>-<slug> of lowercase
# letters, digits and dashes. The census's own copy of the same shape the writer
# refuses a name outside of, kept here rather than imported from the writer's
# module: the census does not read through the order writer's helpers, and a name
# that could escape the ledger directory is refused before a path is built from it.
RECORD_ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*")

# The commit subject the writer produces, and the one word the uncited row looks
# for at its head.
INTENT_SUBJECT_PREFIX = "intent: "

# The ledger directory, relative to any state root: the intent file sits at
# <root>/noni/direction/intent.md, and the record its commit cites lives in the
# directory the run's ledger group reads (the --ledger override honoured, as for
# every other group). Named here so the pairing with the intent path is greppable.
INTENT_LEDGER_REL = "noni/decisions"

# The three status words a decision record may hold. An id whose record carries
# any other word answers nothing about the chain, so it is refused like an
# unreadable record: a hand-edited status must not decide an intent's citation.
RECORD_STATUSES = ("decided", "open", "superseded")
STATUS_SUPERSEDED = "superseded"

# The four subjects of this class. Like hygiene's `hygiene scan` / `deny-list`
# subjects they are the machine-readable discriminator: a consumer branches on
# `subject`, not on message prose.
SUBJECT_OVER_CAP = intentschema.SUBJECT_OVER_CAP
SUBJECT_SECTION_MISSING = intentschema.SUBJECT_SECTION_MISSING
SUBJECT_UNCITED = "uncited"
SUBJECT_CANNOT_TELL = "cannot-tell"
SUBJECTS: tuple[str, ...] = (SUBJECT_OVER_CAP, SUBJECT_SECTION_MISSING,
                             SUBJECT_UNCITED, SUBJECT_CANNOT_TELL)

# The one structural problem that is not a section problem: its sentence is the
# one ``intentschema`` writes with the over-cap subject in front of it, so the
# bucketing reads the prefix rather than re-deriving the rule. Fixed words from
# intentschema, so a comparison of two literals and no second copy of the rule.
_OVER_CAP_PREFIX = f"{intentschema.SUBJECT_OVER_CAP}:"


def subject_for(problem: str) -> str:
    """Which subject one structural problem of the file belongs to.

    The problem text arrives already prefixed by ``intentschema.problems``, so this
    is a read of the prefix rather than a guess at the sentence: a problem that
    carries neither prefix is a bug in the schema, and is filed under the section
    subject, which is the one that names the rule the file broke.
    """
    return SUBJECT_OVER_CAP if problem.startswith(_OVER_CAP_PREFIX) \
        else SUBJECT_SECTION_MISSING


def citation_from_subject(subject: str) -> str | None:
    """The record id a commit subject cites, or None when it cites none.

    ``intent: <id>`` is the shape the writer commits with. The id is what the
    ledger lookup then answers for, so a subject that carries the word and no
    nameable id is no citation: the row says so rather than matching a prefix
    alone.
    """
    text = (subject or "").strip()
    if not text.startswith(INTENT_SUBJECT_PREFIX):
        return None
    cited = text[len(INTENT_SUBJECT_PREFIX):].strip()
    return cited if RECORD_ID_RE.fullmatch(cited) else None


def check_intent(
    intent: Path, ledger: Path, root: Path, findings: list[dict], strict: bool, *,
    row: Callable[..., dict], rel_to_root: Callable[[Path, Path], str],
    file_kind: Callable[..., tuple[str, str | None]],
    fault_text: Callable[[BaseException], str],
    load_json_strict: Callable[[bytes], object],
    commit_subject: Callable[[str], str | None],
) -> None:
    """Check the standing intent file; append its findings to ``findings``.

    Two reads and one history answer: the file, the record its citation names,
    and the subject of the commit that wrote it. ``ledger`` is the directory the
    run's ledger group reads (the ``--ledger`` override honoured, exactly as every
    other group answers for it), which is what the cited record is read from.
    ``commit_subject`` is the run's history view answering "what was the subject
    of the last commit that touched this path"; it answers None for both 'no such
    commit' and 'git could not answer', which is why the row that read feeds is a
    ``cannot-tell`` and never an ``uncited``.

    The row factory, the root-relative identifier, the path classifier and the
    fault wording are the census's own and arrive as arguments rather than being
    imported, so the row shape, the machine-local-path rule and the bounded-text
    rule keep their single owner in ``census.py``.
    """
    def add(subject: str, message: str, *, whole_artifact: bool = False) -> None:
        findings.append(row("intent", strict, subject, rel, message, root,
                            severity="warn" if subject == SUBJECT_CANNOT_TELL
                            else None,
                            whole_artifact=whole_artifact))

    kind, problem = file_kind(intent)
    if kind == "absent":
        # Standing intent is optional: no file, no row. This is the whole of the
        # 'silent when absent' contract, and the reason no healthy-tree fixture
        # in this repository's suite changes its expected rows.
        return
    # The identifier is asked for before the verdict on the path: a path this run
    # could not read still has to be named by the row that says so, and the
    # classifier's answer must not decide whether that read happens.
    rel = rel_to_root(root, intent)
    if kind != "regular":
        add(SUBJECT_CANNOT_TELL,
            f"cannot-tell: {rel} is not a readable regular file ({problem}), so its "
            "sections and its citation were not checked", whole_artifact=True)
        return

    try:
        # ``read_bytes`` and not ``open``: pathlib's own read raises
        # ``RuntimeError`` (``OSError`` for an ``ELOOP`` it can classify), and this
        # row is the class's answer for a file it was told to read and could not.
        raw = intent.read_bytes()
    except (OSError, RuntimeError) as exc:
        add(SUBJECT_CANNOT_TELL,
            f"cannot-tell: {rel} could not be read ({fault_text(exc)}), so its "
            "sections and its citation were not checked", whole_artifact=True)
        return
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        # The bytes are foreign content and a row must not echo them: the class
        # and its own words are the finding, exactly as for a session register or
        # a decision record that is not UTF-8.
        add(SUBJECT_CANNOT_TELL,
            f"cannot-tell: {rel} is not valid UTF-8, so its sections and its "
            "citation were not checked", whole_artifact=True)
        return

    problems = intentschema.problems(text)
    if problems:
        # One row per problem, sorted by subject then text so both output modes
        # emit them in one stable order. The citation question is not asked of a
        # file that is not the file: a structure the writer refuses has no
        # committed shape that could have cited anything.
        for problem_text in sorted(problems, key=lambda p: (subject_for(p), p)):
            subject = subject_for(problem_text)
            add(subject, f"{subject}: {problem_text}")
        return

    headline = commit_subject(rel)
    if headline is None:
        add(SUBJECT_CANNOT_TELL,
            f"cannot-tell: no commit touching {rel} was found in this tree, so "
            "whether the intent cites a ledger record cannot be answered",
            whole_artifact=True)
        return

    cited = citation_from_subject(headline)
    if cited is None:
        add(SUBJECT_UNCITED,
            f"uncited: the last commit that touched {rel} does not name a decision "
            f"record, so the intent rests on nothing the ledger holds (expected a "
            f"commit subject '{INTENT_SUBJECT_PREFIX}<decision-id>')")
        return

    # The cited record is classified with the same classifier the intent file was
    # asked of, before any read, and the answer decides whether a read happens at
    # all: a path behind a link is opened only when it is an ordinary file, so
    # bytes outside the repo can never become a verdict on the intent.
    record = ledger / f"{cited}.json"
    record_kind, record_problem = file_kind(record)
    if record_kind not in ("absent", "regular"):
        # A symlink, a directory or a device at the cited path says nothing about
        # whether the direction stands. The row names the census's own
        # classification words and the cited id, never a target path or a byte.
        add(SUBJECT_CANNOT_TELL,
            f"cannot-tell: the record {cited} the intent cites is not a readable "
            f"regular file ({record_problem}), so whether it stands could not be "
            "answered", whole_artifact=True)
        return

    # One read of the cited record answers both halves of the question -- is it
    # there, and does it stand. Two faults are blindness and reported as
    # cannot-tell; the third is a verdict. A read that was stopped (ENOENT, or the
    # ledger itself is not a directory) says the record is not there, which is the
    # direction's fault and reads uncited; a read the file system refused for some
    # other reason is this run's blindness, and a permission problem on somebody
    # else's file must never be quoted as a finding against the intent.
    body, read_fault = _record_body(record)
    if read_fault is not None and not _absence(read_fault):
        add(SUBJECT_CANNOT_TELL,
            f"cannot-tell: the record {cited} the intent cites could not be read "
            f"({fault_text(read_fault)}), so whether it stands could not be "
            "answered", whole_artifact=True)
        return
    if read_fault is not None:
        add(SUBJECT_UNCITED,
            f"uncited: the intent's last commit cites decision {cited}, which no "
            f"file under {INTENT_LEDGER_REL}/ carries")
        return
    why = _record_problem(body, load_json_strict)
    if why is not None:
        add(SUBJECT_UNCITED,
            f"uncited: the intent's last commit cites decision {cited}, which "
            f"{why}")


def _absence(fault: OSError) -> bool:
    """Whether ``fault`` says 'the record is not there' rather than 'unreadable'.

    ENOENT is the plain answer, and ENOTDIR is the same answer reached by a longer
    path: a ledger that is a file holds no record. Anything else (EACCES, EIO) is
    this run's blindness, reported as cannot-tell.
    """
    return fault.errno in (errno.ENOENT, errno.ENOTDIR)


def _record_body(record: Path) -> tuple[bytes | None, OSError | None]:
    """The bytes of the already-classified record, or the fault that stopped the read.

    Two answers, because "the record is wrong" and "this run could not read the
    record" are different findings and only the first is a verdict on the intent.
    The caller classifies ``record`` first: this opens a path only after the
    census's classifier called it an ordinary file, which is what keeps a link at
    the cited path from being read through.
    """
    try:
        return record.read_bytes(), None
    except OSError as exc:
        return None, exc


def _record_problem(raw: bytes,
                    load_json_strict: Callable[[bytes], object]) -> str | None:
    """Why the record bytes ``raw`` do not stand as a live decision, or None.

    The record must parse and carry a status of ``decided`` or ``open``: an intent
    whose citation the chain has moved past is standing direction nobody voted for
    any more, which is the rule ``order.py`` already applies before it writes a
    position. A record that will not parse is a verdict rather than a cannot-tell
    because the census read it in full and what it holds is not a record; only a
    read that faulted is blindness, and the caller keeps those apart. The wording
    is the census's own and quotes no field value out of the record.
    """
    try:
        value = load_json_strict(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return "the record is not readable JSON"
    if not isinstance(value, dict):
        return "the record is not a JSON object"
    status = value.get("status")
    if status == STATUS_SUPERSEDED:
        return "the record is superseded"
    if status not in RECORD_STATUSES:
        return f"its status is {type(status).__name__}, not decided or open"
    return None
