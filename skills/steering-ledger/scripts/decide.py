"""Record a steering decision: write one dated record under noni/decisions/ and
commit it; with --supersedes, flip the target's status in the same commit.

The writer records what the operator decided and never chooses an answer: every
question's text, options and answer come from flags. Status is derived, never
supplied: all questions answered is ``decided``, any unanswered question is
``open`` (written as ``"answer": null``), and the target of a supersede becomes
``superseded``. There is no --status flag.

``id`` is ``<date>-<slug>``, so a record's filename stays a plain path segment,
and ``--date`` (default: today, UTC) is the day that names it. A supersede
carries the date of the record it replaces, so chain and filename stay in step,
and the slug keeps the two files apart. A supersede target is read from the
working tree and must be tracked, committed and byte-identical to
``git show HEAD:<path>``; only its ``status`` changes, and it is written with
the same atomic replace as the new record. Both paths are staged and committed
with one ``--only`` commit, so a run never sweeps in a file it did not write.

Usage:
    decide.py --repo REPO --slug SLUG --scope SCOPE --asked-by ROLE
              --question ID=TEXT [--option ID=OPTION]... [--answer ID=ANSWER]...
              [--date YYYY-MM-DD] [--source-issue N --source-comment N]
              [--supersedes ID] [--no-commit]

Exit codes:
    0  the record was written (and committed unless --no-commit)
    2  invalid input: an argparse failure, an empty or malformed slug, a
       malformed --date, --question, --option or --answer, a source id that is
       not a positive integer, a question outside 1-4 or 2-4 options, or
       --supersedes with an unanswered question
    3  a git or identity problem: --repo is not a git work tree, git config
       user.name is not set (git config user.name <name>), or a git probe timed
       out or failed for a reason that answered nothing
    4  a collision or a bad supersede target: the record path already exists as
       anything (file, directory or symlink), or the target is missing, already
       superseded, untracked, locally modified, not a regular file at its path
       (symlink, directory or device), not readable at all, not in the writer's
       canonical form, dated another day than --date, or carries a field the census
       does not type as a string, questions that are not a non-empty list of objects
       each with a string id and a string-or-null answer, or a number JSON cannot
       hold (NaN, Infinity or an overflow). A show reporting no path in HEAD is this
       code, not 3: git answered
    5  the commit failed: both paths are rolled back (index reset, target
       restored, new record removed) and anything the undo could not do is named
       (a failed reset and the paths that may still be staged, or a path it could
       not be restored in), so the tree is never claimed as rolled back unless the
       rollback completed. The one input reaching this code is a committed record
       clobbered out of band; the seam FAIL_COMMIT_ENV_VAR ("1") forces it

Every refusal (2, 3 or 4) leaves the ledger and the target untouched: writes happen
only after every check passes, each file goes to a temp file in its own directory and
moves into place with os.replace, and a commit failure rolls both paths back. ``by``
is git config user.name; ``date`` is --date or this run's UTC clock.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# The git helper and the atomic writer live beside this file, loaded by path from
# this file's own directory: a sys.path entry would put a directory ahead of the
# standard library, where any gitwrite.py earlier on that path could be trusted as
# this writer's mechanics. The name is ours, so no caller shadows it; the constants
# below are re-exported because the writer's contract names them.
_GITWRITE_NAME = "noni_gitwrite"
_spec = importlib.util.spec_from_file_location(
    _GITWRITE_NAME, Path(__file__).resolve().parent / "gitwrite.py")
if _spec is None or _spec.loader is None:  # pragma: no cover - path is fixed
    raise RuntimeError("cannot load the git helper beside decide.py")
sys.modules[_GITWRITE_NAME] = gitwrite = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gitwrite)
del _spec

GIT_TIMEOUT = gitwrite.GIT_TIMEOUT
GIT_TIMEOUT_RC = gitwrite.GIT_TIMEOUT_RC
FAIL_COMMIT_ENV_VAR = gitwrite.FAIL_COMMIT_ENV_VAR
_git = gitwrite.run_git
_write_atomic = gitwrite.write_atomic
_load_committed_target = gitwrite.load_committed_target
_rollback = gitwrite.rollback
_undone = gitwrite.undo_wording

# Every return path names one of these; the 'Exit codes:' block above carries
# exactly this set (tests/test_decide.py reads both and pins them together).
EXIT_OK: int = 0
EXIT_USAGE: int = 2
EXIT_GIT: int = 3
EXIT_COLLISION: int = 4
EXIT_COMMIT_FAILED: int = 5

# A slug is half the record id and half its filename, so it is held to what the
# census accepts as a plain path segment (census.sh reports a basename outside
# ^[A-Za-z0-9._-]+\.json$ as 10:bad-name). Dashes only, so <date>-<slug> stays
# unambiguous.
SLUG_RE = re.compile(r"[a-z0-9-]+")
DATE_FLAG_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9-]+")

# Status is derived from the answers; it is the one field of an existing record
# this writer may change.
STATUS_DECIDED = "decided"
STATUS_OPEN = "open"
STATUS_SUPERSEDED = "superseded"

# The field order both censuses document; json.dump keeps it, source last.
FIELD_ORDER = ("id", "date", "asked_by", "questions", "by",
               "scope", "status", "supersedes", "source")


def _fail(code: int, message: str, hint: str | None = None) -> int:
    """Print a refusal to stderr as a headline plus a 'fix:' line naming the
    command that resolves it, and hand back the exit code.
    """
    label = f"{Path(__file__).name}:"
    print(label, message, file=sys.stderr)
    if hint:
        print(label, "fix:", hint, file=sys.stderr)
    return code


def _timeout(repo: Path, *probes: tuple[str, subprocess.CompletedProcess[str]]) -> int | None:
    """The exit-3 refusal for git probes meant to answer (gitwrite words the hung
    call, this writer prints it); None when they all answered.
    """
    message = gitwrite.refuse_git_timeout(Path(__file__).name, *probes)
    if message is None:
        return None
    cmd = next(name for name, result in probes if result.returncode == GIT_TIMEOUT_RC)
    return _fail(EXIT_GIT, message,
                 f"re-run decide once git answers again (git -C {repo} {cmd})")


# The helper refuses its own target probes through this file, so a hung or failed git
# call is worded once and its empty answer is never read as a clean tree downstream.
gitwrite.probe_timeout_refusal = gitwrite.make_probe_refusal(_fail, EXIT_GIT, Path(__file__).name)
gitwrite.EXIT_PROBE_TIMEOUT = EXIT_GIT


def _render(record: dict) -> str:
    """The record's bytes: FIELD_ORDER, two-space indent, one trailing newline.

    ``allow_nan=False`` is the whole refusal of a non-finite number, and json's
    ``ValueError`` is let go rather than worded here: the callers catch it, and
    neither may be handed an empty string for a body.
    """
    ordered = {key: record[key] for key in FIELD_ORDER if key in record}
    return json.dumps(ordered, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def _written(exc: OSError, what: str) -> str:
    """One 'could not be written' headline naming the OSError and its reason."""
    return f"{what} ({exc.__class__.__name__}: {exc.strerror or exc})"


def _path_is_taken(path: Path) -> bool:
    """Whether anything already sits at ``path``, whatever kind of path it is.

    ``lexists`` does not follow a link, so a symlink counts as taken where
    ``is_file()`` reports the name free; a directory or device counts too.
    """
    return os.path.lexists(path)


def _parse_pairs(values: list[str], flag: str) -> tuple[list[tuple[str, str]], str | None]:
    """Parse ``ID=VALUE`` repeats into ordered pairs, or name the malformed one.

    No '=' attaches a value to no question and an empty key or value writes a
    record the census rejects, so both are refused with the shape spelled out.
    Only the first '=' splits (a free-text answer may carry one) and order is
    kept: two ``--option q1=...`` flags are two options of q1.
    """
    out: list[tuple[str, str]] = []
    for value in values:
        key, sep, rest = value.partition("=")
        if not sep or not key.strip() or not rest:
            return [], (f"{flag} {value!r} is not an ID=VALUE pair "
                        f"(write it as {flag} q1=<value>, where q1 is the question's id)")
        out.append((key.strip(), rest))
    return out, None


def _build_questions(questions: list[tuple[str, str]], options: list[tuple[str, str]],
                     answers: list[tuple[str, str]]) -> list[dict] | str:
    """The record's question objects (id, text, 2-4 options in given order, an
    answer that is a string or null, last --answer wins), or a refusal message.
    """
    built = []
    for qid, text in questions:
        opts = [o for oid, o in options if oid == qid]
        if not 2 <= len(opts) <= 4:
            return (f"question {qid} has {len(opts)} option(s); every question needs "
                    "2-4 options, given as --option " + qid + "=<option>")
        asked = [a for aid, a in answers if aid == qid]
        built.append({"id": qid, "text": text, "options": opts,
                      "answer": asked[-1] if asked else None})
    return built


def _load_target(repo: Path, ledger: Path,
                 target_id: str) -> tuple[Path, dict, bytes] | tuple[str, str] | int:
    """A target as ``(path, record, committed_bytes)``, a ``(headline, hint)`` refusal
    pair, or the exit code a probe refusal printed; nothing is written on refusal.
    gitwrite probes the tree and holds the target's whole schema (the live-record
    rules, every field type the census names, and the committed bytes compared
    against ``_render``), so a value the renderer cannot name is a refusal.
    """
    path = ledger / f"{target_id}.json"
    found = _load_committed_target(Path(__file__).name, repo, path, target_id,
                                   _render, STATUS_SUPERSEDED)
    return found if isinstance(found, int) or not isinstance(found[0], bytes) else (
        path, found[1], found[0])


def _validate_usage(args: argparse.Namespace) -> tuple[str, list[dict], list[str]] | int:
    """Flags-only checks, before git is consulted: returns
    ``(date_part, questions, unanswered)`` for flags that can produce a valid
    record, or the exit code of the refusal already printed.
    """
    if not SLUG_RE.fullmatch(args.slug):
        return _fail(EXIT_USAGE, f"slug {args.slug!r} is not a slug",
                     "a slug is [a-z0-9-]+: lowercase letters, digits and dashes, no dots, "
                     "slashes, spaces or uppercase")
    if not args.scope.strip():
        return _fail(EXIT_USAGE, "--scope is empty", "name the direction area, e.g. --scope 'release ordering'")
    if not args.asked_by.strip():
        return _fail(EXIT_USAGE, "--asked-by is empty", "name the agent role or session that asked")

    if args.date is None:
        date_part = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    elif not DATE_FLAG_RE.fullmatch(args.date):
        return _fail(EXIT_USAGE, f"--date {args.date!r} is not YYYY-MM-DD",
                     "pass the record date as --date 2026-10-26")
    else:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            return _fail(EXIT_USAGE, f"--date {args.date!r} is not a real calendar date",
                         "pass a date that exists, e.g. --date 2026-10-26")
        date_part = args.date

    if not 1 <= len(args.question) <= 4:
        return _fail(EXIT_USAGE,
                     f"{len(args.question)} --question flag(s); a record carries 1-4 questions",
                     "ask between one and four questions, each as --question q1=<text>")
    questions: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value in args.question:
        qid, sep, text = value.partition("=")
        qid = qid.strip()
        if not sep or not qid or not text:
            return _fail(EXIT_USAGE, f"--question {value!r} is not an ID=TEXT pair",
                         "write it as --question q1=<the question as asked>")
        if qid in seen:
            return _fail(EXIT_USAGE, f"--question id {qid!r} is used twice", "give each question its own id")
        seen.add(qid)
        questions.append((qid, text))

    answers: list[tuple[str, str]] = []
    options, problem = _parse_pairs(args.option, "--option")
    if problem is not None:
        return _fail(EXIT_USAGE, problem, "give every option 2-4 entries per question")
    answers, problem = _parse_pairs(args.answer, "--answer")
    if problem is not None:
        return _fail(EXIT_USAGE, problem, "answer a question with --answer ID=<answer>")
    for flag, pairs in (("--option", options), ("--answer", answers)):
        unknown = sorted({oid for oid, _v in pairs} - seen)
        if unknown:
            return _fail(EXIT_USAGE,
                         f"{flag} names question(s) {', '.join(unknown)} that no --question asks",
                         "the id must match one of the --question ids")
    built = _build_questions(questions, options, answers)
    if isinstance(built, str):
        return _fail(EXIT_USAGE, built, "give every question 2-4 options")

    # A declined steer is an open chain-root record, never a supersede: an
    # unanswered question would leave the chain with no live answer (census
    # exit 20), so this is a usage error and not a ledger state.
    answered_ids = {oid for oid, _value in answers}
    unanswered = [qid for qid, _text in questions if qid not in answered_ids]
    if args.supersedes is not None:
        if unanswered:
            return _fail(
                EXIT_USAGE,
                f"--supersedes {args.supersedes!r} with {len(unanswered)} unanswered question(s) "
                f"({', '.join(unanswered)}) would leave the chain with no answer",
                "answer every question with --answer ID=<answer>, or record the "
                "decline as an open chain-root record without --supersedes",
            )
        if args.date is None:
            # A supersede carries the date of the record it replaces, so without
            # --date there is nothing to place it in the chain it corrects.
            return _fail(EXIT_USAGE,
                         "--supersedes needs --date: a supersede carries the date of "
                         "the record it replaces",
                         "pass the target's date, e.g. --date 2026-10-26")
        if not ID_RE.fullmatch(args.supersedes):
            return _fail(EXIT_USAGE, f"--supersedes {args.supersedes!r} is not a record id",
                         "a record id is YYYY-MM-DD-<slug>, e.g. 2026-10-01-steer-order")
    return date_part, built, unanswered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record a steering decision")
    # The tests read this parser from the AST, so the flag names are passed to
    # add_argument in main() itself: no helper may stand between the two.
    parser.add_argument("--repo", required=True, help="repository root")
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
                        help="record date (default: today, UTC); --supersedes requires it")
    parser.add_argument("--source-issue", type=int, default=None,
                        help="tracker issue number (a positive integer)")
    parser.add_argument("--source-comment", type=int, default=None,
                        help="tracker comment id (a positive integer)")
    parser.add_argument("--supersedes", default=None, metavar="ID",
                        help="id of the record this one replaces (needs every answer)")
    parser.add_argument("--no-commit", action="store_true",
                        help="write the file(s) and leave them uncommitted for the caller")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    ledger = repo / "noni" / "decisions"
    checked = _validate_usage(args)
    if isinstance(checked, int):
        return checked
    date_part, built, unanswered = checked

    source = None
    if (args.source_issue is None) != (args.source_comment is None):
        return _fail(EXIT_USAGE,
                     "source provenance needs both --source-issue and --source-comment",
                     f"got issue={args.source_issue!r} comment={args.source_comment!r}; "
                     "pass both, or neither")
    if args.source_issue is not None:
        # A tracker id is a positive number: zero or negative names no issue and
        # no comment, so the record would carry provenance nothing can check.
        for flag, value in (("--source-issue", args.source_issue),
                            ("--source-comment", args.source_comment)):
            if value is None or value < 1:
                return _fail(EXIT_USAGE, f"{flag} {value!r} is not a positive integer",
                             f"name a real tracker id, e.g. {flag} 42")
        source = {"issue_number": args.source_issue, "comment_id": args.source_comment}
    # --- git and identity: nothing is written until here and below ---------
    work_tree = _git(repo, "rev-parse", "--is-inside-work-tree")
    named = _git(repo, "config", "user.name")
    timed_out = _timeout(repo, ("rev-parse", work_tree), ("config", named))
    if timed_out is not None:
        return timed_out
    if work_tree.returncode != 0:
        return _fail(EXIT_GIT, f"{repo} is not a git work tree",
                     "run decide from the attached project's repo root (git -C REPO "
                     "rev-parse --is-inside-work-tree must succeed)")
    by = named.stdout.strip()
    if named.returncode != 0 or not by:
        return _fail(EXIT_GIT,
                     f"git config user.name is not set for {repo}, so the record cannot be "
                     "attributed",
                     "git config user.name is not set: give the tree an identity with "
                     f"git -C {repo} config user.name <name> (or --global)")

    record_id = f"{date_part}-{args.slug}"
    record_path = ledger / f"{record_id}.json"
    record_rel = record_path.relative_to(repo).as_posix()
    if _path_is_taken(record_path):
        # Tracked or not, and whatever kind of path it is, this name is taken:
        # is_file() follows a link, so a symlink would have read as free and
        # os.replace would have put a record where somebody's link stood.
        return _fail(
            EXIT_COLLISION,
            f"{record_path} already exists; record ids are unique across the ledger",
            "choose a slug nobody has taken; a supersede keeps the --date of the "
            "record it replaces and differs by its slug",
        )

    target: tuple[Path, dict, bytes] | None = None
    target_rel: str | None = None
    if args.supersedes is not None:
        found = _load_target(repo, ledger, args.supersedes)
        if isinstance(found, int):
            return found  # a git probe on the target hung; the refusal is printed
        if isinstance(found[0], str):
            return _fail(EXIT_COLLISION, found[0],
                         found[1] or "name a committed, live record of the chain being corrected")
        target_path, target_record, target_committed = found
        target_rel = target_path.relative_to(repo).as_posix()
        # Chain position, filename stem and census replay order all read this date,
        # so another day cuts the record out of the chain it corrects. A value that
        # is not a string was refused by _load_target; this slice is total here.
        if target_record.get("date", "")[:10] != date_part:
            want = str(target_record.get("date", ""))[:10]
            return _fail(
                EXIT_COLLISION,
                f"--date {date_part} is not the date of the record being superseded "
                f"({target_record.get('date')!r})",
                f"a supersede carries the date of the record it replaces: pass --date {want}")
        target = (target_path, target_record, target_committed)

    # --- the writes: every check above has passed --------------------------
    record: dict = {
        "id": record_id,
        "date": f"{date_part}T00:00:00Z",
        "asked_by": args.asked_by,
        "questions": built,
        "by": by,
        "scope": args.scope,
        "status": STATUS_OPEN if unanswered else STATUS_DECIDED,
        "supersedes": args.supersedes,
    }
    if source is not None:
        record["source"] = source
    if not ledger.is_dir():
        # A fresh project has no noni/ state; the writer allocates the directory
        # that holds its own record.
        try:
            ledger.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _fail(EXIT_COMMIT_FAILED,
                         _written(exc, f"the ledger directory {ledger} could not be created"),
                         f"check that {repo} is writable, then re-run decide")
    rels = [record_rel] if target is None else [record_rel, target_rel]
    committed_bytes = None if target is None else target[2]
    try:
        # The render is inside the try: a ValueError here refuses exit 4, not crash
        # at 1 after a write has already landed.
        _write_atomic(record_path, _render(record))
        if target is not None:
            flipped = dict(target[1])
            flipped["status"] = STATUS_SUPERSEDED
            _write_atomic(target[0], _render(flipped))
    except ValueError:
        # Not bytes this writer can produce: roll both paths back as a write failure
        # does. The render cannot name what json read, so the tree is left untouched.
        unredone = _rollback(repo, rels, target_rel, record_rel, committed_bytes)
        detail = (f"the record {record_id} carries a number this writer cannot name: "
                  "it is not in the canonical form decide.py writes")
        if unredone is not None:
            return _fail(EXIT_COMMIT_FAILED,
                         *_undone(detail, str(unredone), "", rels))
        return _fail(EXIT_COLLISION, detail,
                     "name a record decide.py wrote, or repair it and re-run decide")
    except OSError as exc:
        # os.replace never half-writes, so a path failed to land: roll both paths as
        # a failed commit does, and name the one that stayed.
        unredone = _rollback(repo, rels, target_rel, record_rel, committed_bytes)
        detail = _written(exc, "the record could not be written")
        if unredone is not None:
            return _fail(EXIT_COMMIT_FAILED,
                         *_undone(detail, str(unredone), str(exc), rels))
        return _fail(EXIT_COMMIT_FAILED, detail,
                     f"check that {ledger} is writable, then re-run decide")
    if args.no_commit:
        # The census reads the working tree, so these files read as uncommitted (an
        # edited target is census.sh exit 12): name both paths, and say that
        # committing them is the caller's job.
        print(f"{Path(__file__).name}: wrote {', '.join(rels)}; left uncommitted: commit "
              "these paths before running the census")
        return EXIT_OK
    added = _git(repo, "add", "--", *rels)
    if added.returncode != 0:
        unredone = _rollback(repo, rels, target_rel, record_rel, committed_bytes)
        detail = added.stderr.strip() or added.stdout.strip()
        if unredone is not None:
            return _fail(EXIT_COMMIT_FAILED,
                         *_undone("git add failed", str(unredone), detail, rels))
        return _fail(EXIT_COMMIT_FAILED, f"git add failed: {detail}",
                     f"the paths {', '.join(rels)} are rolled back; re-run decide")
    # --only with explicit paths: the commit carries exactly what this run wrote,
    # never a file somebody else had staged.
    verb = f"supersede {args.supersedes} with {record_id}" if args.supersedes else record_id
    committed = _git(repo, "commit", "-q", "-m", f"steering: {verb}", "--only", "--", *rels)
    if committed.returncode != 0:
        unredone = _rollback(repo, rels, target_rel, record_rel, committed_bytes)
        detail = committed.stderr.strip() or committed.stdout.strip()
        if unredone is not None:
            return _fail(EXIT_COMMIT_FAILED,
                         *_undone("git commit failed", str(unredone), detail, rels))
        return _fail(EXIT_COMMIT_FAILED, f"git commit failed: {detail}",
                     f"{', '.join(rels)} are rolled back to their state before this run")
    print(f"{Path(__file__).name}: wrote {record_path}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
