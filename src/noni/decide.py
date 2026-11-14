"""Record a steering decision: write one dated record under noni/decisions/ and
commit it; with --supersedes, flip the target's status in the same commit.

The writer records what the operator decided and never chooses an answer: every
question's text, options and answer come from flags. Status is derived, never
supplied: all questions answered is ``decided``, any unanswered question is
``open`` (written as ``"answer": null``), and the target of a supersede becomes
``superseded``. There is no --status flag.

``id`` is ``<date>-<slug>``, so a record's filename stays a plain path segment, and
``--date`` (default: today, UTC) is the day that names it. A supersede carries its own
``--date`` like any other record: the chain is what orders the ledger, so the day is
any valid date and the slug keeps the two files apart. A supersede target is read from
the working tree, must be
tracked and committed, and must be byte-identical to ``git show HEAD:<path>``; only
its ``status`` changes, and it is written with the same atomic replace as the new
record. Both paths go in one ``--only`` commit, so a run writes nothing else.

Usage:
    decide.py --repo REPO --slug SLUG --scope SCOPE --asked-by ROLE
              --question ID=TEXT [--option ID=OPTION]... [--answer ID=ANSWER]...
              [--date YYYY-MM-DD] [--source-issue N --source-comment N]
              [--decided-by WHO] [--on-behalf-of WHO] [--single-option]
              [--why REASON] [--supersedes ID] [--no-commit] [--init]

Exit codes:
    0  the record was written (and committed unless --no-commit)
    2  invalid input: an argparse failure, an empty or malformed slug, a slug
       already starting with a date (the writer adds it), a malformed --date,
       --question, --option or --answer, a source id that is not a positive integer, a
       question outside 1-4 or 2-4 options, an empty --decided-by or --on-behalf-of,
       --on-behalf-of without --decided-by, an empty, multi-line or over-long --why, a
       question with one option when --single-option was not given, --single-option when
       no question of the record has one option, or --supersedes with an unanswered
       question
    3  a git or identity problem: --repo is not a git work tree, git config user.name is
       not set (git config user.name <name>), a git probe timed out or failed for a reason
       that answered nothing, a --repo that is a directory holding no noni/ (pass the state
       clone, or --init for a new one), or a noni/ or noni/decisions directory -- every one
       from the state root down to the ledger -- that is no plain path this writer may read
       or write through (a symlink, a plain file, a socket or a device, each asked of lstat
       before the git probes, the first read or the mkdir; an absent ledger is admitted
       because the first record creates it)
    4  a collision or a bad supersede target: the record path already exists as anything
       (file, directory or symlink), or the target is missing, already superseded,
       untracked, locally modified, not a regular file at its path (symlink, directory or
       device), not readable at all, not in the writer's canonical form, or carries a field
       the census does not type as a string (including decided_by and on_behalf_of, which
       the census types as non-empty single-line strings, and why, which it types as one of
       those within the rationale bound), a status outside decided, open or superseded,
       questions that are not a non-empty list of objects each with a string id and a
       string-or-null answer, or a number JSON cannot hold (NaN, Infinity or an overflow).
       A show reporting no path in HEAD is this code, not 3: git answered
    5  the commit failed: both paths are rolled back (index reset, target
       restored, new record removed) and anything the undo could not do is named
       (a failed reset and the paths that may still be staged, or a path it could
       not be restored in), so the tree is never claimed as rolled back unless the
       rollback completed. The one input reaching this code is a committed record
       clobbered out of band; the seam FAIL_COMMIT_ENV_VAR ("1") forces it

Every refusal (2, 3 or 4) leaves the ledger and the target untouched: writes happen
only after every check passes, each file goes to a temp file in its own directory and
moves into place with os.replace, and a commit failure rolls both paths back. ``by``
is git config user.name; ``date`` is ``--date`` at UTC midnight, or this run's UTC
instant to the second with no ``--date``; either way the ``id`` carries that same day.

``--no-commit`` with ``--supersedes`` writes both files and prints one line naming
both paths and saying the target's status is now ``superseded``: a run that is then
aborted leaves an edited target, so restoring the chain means restoring that file and
deleting the new record, not just deleting the record.

Every path the success lines name (``wrote`` on either route) is the file's real
location from the caller's working directory: --repo joined to noni/decisions/
<id>.json, spelled the same with and without --no-commit.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from . import _decide_flags, _decide_state_root, _writer, gitwrite, labels, orderstate
from . import ledger_schema as _schema
from .ledger_schema import is_single_line

# The git helper and the atomic writer are an ordinary package import: inside an
# installed wheel there is no sibling file to load by path, and no directory of the
# package goes on ``sys.path``, so a lookalike earlier on some path cannot become this
# writer's mechanics. ``_git`` and ``_write_atomic`` are the two names the writer's
# tests replace to inject a fault no flag produces; the constants are re-exported
# because the writer's contract names them.
GIT_TIMEOUT = gitwrite.GIT_TIMEOUT
GIT_TIMEOUT_RC = gitwrite.GIT_TIMEOUT_RC
FAIL_COMMIT_ENV_VAR = gitwrite.FAIL_COMMIT_ENV_VAR
_git = gitwrite.run_git
_write_atomic = gitwrite.write_atomic

# Every return path names one of these; the 'Exit codes:' block above carries
# exactly this set (tests/test_decide_docs.py pins them together).
EXIT_OK: int = 0
EXIT_USAGE: int = 2
EXIT_GIT: int = 3
EXIT_COLLISION: int = 4
EXIT_COMMIT_FAILED: int = 5

# A slug is half the record id and half its filename, so it is held to what the
# census accepts as a plain path segment. Dashes only: the split is not ambiguous.
SLUG_RE = re.compile(r"[a-z0-9-]+")
ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9-]+")
# Status is derived from the answers; it is the one field of an existing record this
# writer may change. STATUSES, the census's set, goes to the target check.
STATUS_DECIDED = "decided"
STATUS_OPEN = "open"
STATUS_SUPERSEDED = "superseded"
STATUSES = (STATUS_DECIDED, STATUS_OPEN, STATUS_SUPERSEDED)

# ``noni`` first (a link there hides the ledger beneath it from ``lstat``), then the
# ledger; the walk and its declined-lstat rule live in :mod:`noni._decide_flags`.
_GUARDED_DIRS: tuple[str, ...] = ("noni", orderstate.DECISIONS_DIR)

# The field order the census documents; json.dump keeps it. The names after
# ``source`` are optional and appended last, so a record that carries none of them
# keeps the eight fields in the order the supersede canonical-form rule compares a
# target's committed bytes against. Their shapes are the census's, in
# ``ledger_schema``: the two names are non-empty single-line strings,
# ``single_option`` is the JSON true literal that lets a question hold one option, and
# ``why`` (_schema.WHY_FIELD) is one line within the rationale bound.
FIELD_ORDER = ("id", "date", "asked_by", "questions", "by",
               "scope", "status", "supersedes", "source",
               "decided_by", "on_behalf_of", "single_option", _schema.WHY_FIELD)


def _why_max() -> int:
    """The rationale bound this writer holds --why to, read from the schema.

    Never a number spelled in this file: :mod:`noni._why` owns the bound and a
    second literal is how a writer, the census and the help line come to state three
    different limits. Asked through a function so the help text and the refusal read
    one answer.
    """
    return _schema.why_max()


def _fail(code: int, message: str, hint: str | None = None) -> int:
    """Print a refusal to stderr as a headline plus a 'fix:' line naming the
    command that resolves it, and hand back the exit code.
    """
    label = f"{labels.DECIDE}:"
    print(label, message, file=sys.stderr)
    if hint:
        print(label, "fix:", hint, file=sys.stderr)
    return code


# The helper refuses its own target probes through this file, so a hung or failed git
# call is worded once and its empty answer is never read as a clean tree downstream.
gitwrite.probe_timeout_refusal = gitwrite.make_probe_refusal(_fail, EXIT_GIT, labels.DECIDE)
gitwrite.EXIT_PROBE_TIMEOUT = EXIT_GIT


def _render(record: dict) -> str:
    """The record's bytes in :data:`FIELD_ORDER`, via the census's own renderer."""
    return _schema.render(record, FIELD_ORDER)


def _source_provenance(issue: int | None, comment: int | None) -> dict | None | int:
    """The record's ``source`` object, ``None`` for none, or the refusal's exit code."""
    provenance, refusal = _schema.source_provenance(issue, comment)
    return _fail(EXIT_USAGE, *refusal) if refusal is not None else provenance


def _path_is_taken(path: Path) -> bool:
    """Whether anything sits at ``path``: ``lexists`` does not follow a link.

    The collision question ``Path.is_file`` cannot ask: a link reads as a free name
    there and the atomic replace that follows writes through it.
    """
    return os.path.lexists(path)


def _name_flags(args: argparse.Namespace,
                options_by_question: dict[str, list[str]]) -> int | None:
    """The single-flag usage refusals, worded in this writer's voice.

    :func:`noni._writer.flag_refusals` holds the rules; this seam hands it the
    writer's printer and usage code, the census's ``is_single_line`` predicate, the
    bounded predicate and its bound, and each question's options -- so a shape the
    census reports at exit 10 is refused at the flag instead.
    """
    return _writer.flag_refusals(_fail, EXIT_USAGE,
                                 _decide_flags.refuse_name,
                                 SLUG_RE, args.slug, args.scope, args.asked_by,
                                 args.decided_by, args.on_behalf_of,
                                 is_single_line,
                                 options_by_question=options_by_question,
                                 single_option=args.single_option,
                                 why=args.why,
                                 bounded=_schema.is_bounded_single_line,
                                 why_max=_why_max())


def _pair_flags_to_questions(flag: str, pairs: list[tuple[str, str]],
                             seen: set[str]) -> int | None:
    """The exit code printed when ``pairs`` names a question no ``--question`` asks.

    The rule is :func:`noni.ledger_schema.pair_refusal`, shared with the record schema
    so an orphan id is refused one way wherever it is found.
    """
    refusal = _schema.pair_refusal(flag, pairs, seen)
    return None if refusal is None else _fail(EXIT_USAGE, *refusal)


# The record's name and path spellings (``_record_name``), and what a clean flag check
# hands the run: the two date answers (day for the name, instant for the field), the
# questions and the ids left open.
RecordName = tuple[str, Path, str, list[str], list[str]]
_Checked = tuple[tuple[str, str], list[dict], list[str]] | int


def _record_name(repo: Path, ledger: Path, date_part: str, slug: str) -> RecordName:
    """The record's ``(id, path, rel, record_paths, target_paths)`` for one run.

    :func:`noni._writer.ledger_name` allocates the name from the day alone -- the instant
    the ``date`` field carries travels beside it, never inside it, so a record's name stays
    ``<day>-<slug>``. This seam adds the caller-cwd tokens (#77, AC2), which a supersede
    extends via :func:`noni._writer.target_paths_of`.
    """
    record_id, record_path, record_rel = _writer.ledger_name(repo, ledger, date_part,
                                                             slug)
    return (record_id, record_path, record_rel, [str(record_path)], [])


def _parse_pairs(values: list[str], flag: str) -> tuple[list[tuple[str, str]], str | None]:
    """``ID=VALUE`` repeats as pairs: :func:`ledger_schema.parse_pairs`."""
    return _schema.parse_pairs(values, flag)


def _open_ledger(repo: Path, ledger: Path) -> int | None:
    """The exit-5 refusal for a ledger directory that cannot be created, or None.

    The allocation and its directory question are :func:`noni._decide_flags`; this seam
    gives its refusal this writer's exit code and voice.
    """
    return _decide_flags.refuse_ledger_allocation(_fail, labels.DECIDE,
                                                  EXIT_COMMIT_FAILED, repo, ledger)


def _refuse_linked_state(repo: Path) -> int | None:
    """The exit-3 refusal for a ``noni/`` this writer may not read or write, or None.

    :func:`noni._decide_flags.refuse_linked_state` walks the components and words the
    two lines; this seam pins the call to :data:`EXIT_GIT`, the code docs/PRODUCT.md 7
    gives ``decide`` for a wrong path. It runs in ``main()`` BEFORE :func:`_identity`,
    so a linked tree is refused by noni and not read through by the git probes.
    """
    return _decide_flags.refuse_linked_state(_fail, EXIT_GIT, repo, _GUARDED_DIRS)


def _identity(repo: Path) -> str | int:
    """The tree's ``git config user.name``, or the printed refusal's exit code.

    The two git probes are :func:`noni._writer.identity`.
    """
    by, refusal = _writer.identity(labels.DECIDE, _git, repo)
    if refusal is not None:
        return _fail(EXIT_GIT, *refusal)
    return by


def _write_pair(repo: Path, record_path: Path, record: dict, target_rel: str | None,
                rels: list[str], record_rel: str, committed_bytes: bytes | None,
                target: tuple[Path, dict, bytes] | None,
                ledger: Path) -> str | int:
    """Land both paths, or the exit code of the refusal printed; '' is both landed.

    The renders, the writes and the target's status flip are
    :func:`noni._writer.write_record`; a render refusal is exit 4 and a filesystem
    fault rolls back here, where both claimed paths and the target's bytes are known.
    """
    try:
        refusal = _writer.write_record(_write_atomic, _render, record_path, record,
                                       target, STATUS_SUPERSEDED)
    except OSError as exc:
        return _refuse_unwritten(repo, rels, target_rel, record_rel, committed_bytes,
                                 ledger, exc)
    if refusal is not None:
        return _fail(EXIT_COLLISION, *refusal)
    return ""


def _commit(repo: Path, rels: list[str], target_rel: str | None, record_rel: str,
            committed_bytes: bytes | None, message: str) -> int | None:
    """Stage and commit exactly this run's paths, or the exit code of the refusal.

    The two git steps and their rollback are :func:`noni._writer.stage_and_commit`.
    """
    refusal = _writer.stage_and_commit(labels.DECIDE, repo, rels, message,
                                       target_rel, record_rel, committed_bytes)
    return None if refusal is None else _fail(EXIT_COMMIT_FAILED, *refusal)


def _load_target(repo: Path, ledger: Path,
                 target_id: str) -> tuple[Path, dict, bytes] | tuple[str, str] | int:
    """A target as ``(path, record, committed_bytes)``, a refusal pair, or the exit
    code a probe refusal printed; nothing is written on refusal.

    gitwrite holds the target's schema and the bytes compared against ``_render``.
    """
    path = ledger / f"{target_id}.json"
    found = gitwrite.load_committed_target(labels.DECIDE, repo, path, target_id,
                                           _render, STATUS_SUPERSEDED, STATUSES)
    return found if isinstance(found, int) or not isinstance(found[0], bytes) else (
        path, found[1], found[0])


def _build_record_flags(args: argparse.Namespace) -> _Checked:
    """The flags that assemble the record: :func:`noni._decide_flags.build_record_flags`.

    The rules, their order and their refusals are that module's; these seams hand it this
    writer's printer, codes, patterns and schema calls, so the census's rules stay the
    census's and one voice words every refusal. The date comes back as the pair the record
    needs: the day for the name, the instant for the field.
    """
    return _decide_flags.build_record_flags(args, fail=_fail, exit_usage=EXIT_USAGE,
                                            slug_re=SLUG_RE, id_re=ID_RE,
                                            parse_pairs=_parse_pairs,
                                            pair_refuse=_pair_flags_to_questions,
                                            name_refuse=_name_flags,
                                            build_questions=_schema.build_questions,
                                            unanswered_ids=_schema.unanswered_ids)


def _refuse_unwritten(repo: Path, rels: list[str], target_rel: str | None,
                      record_rel: str, committed_bytes: bytes | None,
                      ledger: Path, exc: OSError) -> int:
    """Roll the run's paths back after a write that did not land, and refuse.

    The undo and its wording are :func:`noni._writer.refuse_unwritten`; this seam hands
    it this writer's printer, code, label and ledger path.
    """
    return _writer.refuse_unwritten(labels.DECIDE, ledger, _fail, EXIT_COMMIT_FAILED,
                                    repo, rels, target_rel, record_rel, committed_bytes,
                                    exc)


def _refuse_taken_name(record_path: Path) -> int:
    """The exit-4 refusal for a record name that is already spoken.

    ``is_file()`` follows a link, so a link read as free and the replace wrote through
    it; the wording is :mod:`noni._decide_flags`' and the code is this writer's.
    """
    return _decide_flags.refuse_taken_name(_fail, EXIT_COLLISION, record_path)


def _validate_usage(args: argparse.Namespace) -> _Checked:
    """Flags-only checks, before git is consulted: :func:`_build_record_flags`.

    The order is the one the refusals need: the record's parts are parsed first
    because two of the flag rules read them, and the name and marker refusals come
    after the options are known.
    """
    return _build_record_flags(args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=labels.DECIDE,
        description="Record a steering decision",
    )
    # The tests read this parser from the AST, so the flag names are passed to
    # add_argument in main() itself: no helper may stand between the two.
    parser.add_argument("--repo", required=True,
                        help="the state root that holds (or will hold) noni/")
    parser.add_argument("--slug", required=True, help="id slug ([a-z0-9-]+)")
    parser.add_argument("--scope", required=True, help="the direction area the decision covers")
    parser.add_argument("--asked-by", required=True, help="the agent role or session that asked")
    parser.add_argument("--question", action="append", required=True, metavar="ID=TEXT",
                        help="a question, as ID=TEXT (repeatable, 1-4 questions)")
    parser.add_argument("--option", action="append", default=[], metavar="ID=OPTION",
                        help="an option for question ID (repeatable, 2-4 per question)")
    parser.add_argument("--answer", action="append", default=[], metavar="ID=ANSWER",
                        help="the operator's answer for question ID (repeatable; with no "
                        "--answer the question is written open as \"answer\": null)")
    parser.add_argument("--date", default=None, metavar="YYYY-MM-DD",
                        help="record date (default: today, UTC)")
    parser.add_argument("--decided-by", default=None, metavar="WHO",
                        help="who made the decision, when that is not the commit "
                        "author (a login or pseudonym, never an empty string)")
    parser.add_argument("--on-behalf-of", default=None, metavar="WHO",
                        help="the party the decision was made for (needs --decided-by)")
    parser.add_argument("--why", default=None, metavar="REASON",
                        help="the operator's one line of reason for the decision "
                        f"(a non-empty single line of at most {_why_max()} characters)")
    parser.add_argument("--single-option", action="store_true",
                        help="record a decision with exactly one option per question, "
                        "so nothing has to be invented (the multiple-choice form "
                        "without this flag still needs 2-4)")
    parser.add_argument("--source-issue", type=int, default=None,
                        help="tracker issue number (a positive integer)")
    parser.add_argument("--source-comment", type=int, default=None,
                        help="tracker comment id (a positive integer)")
    parser.add_argument("--supersedes", default=None, metavar="ID",
                        help="id of the record this one replaces (needs every answer)")
    parser.add_argument("--no-commit", action="store_true",
                        help="write the file(s) and leave them uncommitted for the caller")
    parser.add_argument("--init", action="store_true",
                        help="allow this run to create noni/ in a tree that holds none "
                        "(a new state root); without it such a --repo is refused")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    ledger = repo / "noni" / "decisions"
    # Before the identity probe and before anything is read or written.
    linked = _refuse_linked_state(repo)
    if linked is not None:
        return linked
    checked = _validate_usage(args)
    if isinstance(checked, int):
        return checked
    date_part, stamp, built, unanswered = checked

    source = _source_provenance(args.source_issue, args.source_comment)
    if isinstance(source, int):
        return source
    # --- git and identity: nothing is written until here and below ---------
    by = _identity(repo)
    if isinstance(by, int):
        return by
    # Asked after the git probes, so a tree that is no work tree keeps the refusal that
    # names that fault, and before the allocation, so a wrong --repo is refused without
    # gaining the directory this run would otherwise have created. The census-level
    # question is asked in the same call, also ahead of the allocation, so a run the
    # declaration refuses never leaves a ``noni/`` behind in a tree it may not write to.
    refused = _decide_state_root.refuse_run(_fail, EXIT_GIT, EXIT_USAGE,
                                            EXIT_COLLISION, repo, args.init)
    if refused is not None:
        return refused
    opened = _open_ledger(repo, ledger)
    if opened is not None:
        return opened

    record_id, record_path, record_rel, record_paths, target_paths = _record_name(
        repo, ledger, date_part, args.slug)
    if _path_is_taken(record_path):
        return _refuse_taken_name(record_path)

    target: tuple[Path, dict, bytes] | None = None
    target_rel: str | None = None
    if args.supersedes is not None:
        target, target_rel, refusal = _writer.supersede_target(
            _load_target, labels.DECIDE, repo, ledger, args.supersedes)
        if isinstance(refusal, int):
            return refusal  # a git probe on the target hung; the refusal is printed
        if refusal is not None:
            return _fail(EXIT_COLLISION, *refusal)
        # The caller-cwd form of every path this run prints (issue #77, AC2): the
        # record, and the target beside it for a supersede.
        record_paths, target_paths = _writer.target_paths_of(target, record_path)

    # --- the writes: every check above has passed --------------------------
    record = _schema.record_body(record_id=record_id,
                                 date_stamp=stamp,
                                 asked_by=args.asked_by, questions=built, by=by,
                                 scope=args.scope, unanswered=unanswered,
                                 supersedes=args.supersedes, source=source,
                                 decided_by=args.decided_by,
                                 on_behalf_of=args.on_behalf_of,
                                 single_option=args.single_option,
                                 why=args.why)
    rels, message = _schema.supersede_plan(args.supersedes, record_id, record_rel,
                                           target_rel)
    committed_bytes = None if target is None else target[2]
    written = _write_pair(repo, record_path, record, target_rel, rels, record_rel,
                          committed_bytes, target, ledger)
    if isinstance(written, int):
        return written

    def _report() -> int:
        print(_writer.success_line(labels.DECIDE, record_paths, target_paths,
                                   STATUS_SUPERSEDED, args.no_commit))
        return EXIT_OK

    if args.no_commit:
        # The census reads the working tree, so these files read as uncommitted (an
        # edited target is the census's exit 12): the line names both paths, says that
        # committing them is the caller's job, and says what the second path now
        # holds, so an operator who aborts the run knows to restore the target as
        # well as delete the new record.
        return _report()
    committed = _commit(repo, rels, target_rel, record_rel, committed_bytes, message)
    if committed is not None:
        return committed
    return _report()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
