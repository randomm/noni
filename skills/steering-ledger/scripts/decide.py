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
       malformed --date, --question, --option or --answer, a question with no
       options or more than four, or --supersedes with an unanswered question
    3  a git or identity problem: --repo is not a git repository, or
       git config user.name is not set (git config --global user.name <name>)
    4  a collision or a bad supersede target: the record file already exists,
       or the target is missing, already superseded, uncommitted, locally
       modified, or belongs to another chain
    5  the commit failed: both paths are rolled back (index reset, target
       restored, new record removed), so the tree is left as this run found it.
       The one input that reaches this code is a committed record clobbered out
       of band; the test seam FAIL_COMMIT_ENV_VAR forces it

Every refusal (2, 3 or 4) leaves the ledger and the target untouched: writes
happen only after every check passes, each file goes to a temp file in its own
directory and moves into place with os.replace, and a commit failure rolls both
paths back. ``by`` comes from git config user.name and ``date`` from --date or
this run's UTC clock; neither is guessed from anything else.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

GIT_TIMEOUT = 60
# The seam the exit-5 rollback test uses, and nothing else: the state it undoes
# (a committed record clobbered out of band) reaches this code no other way.
FAIL_COMMIT_ENV_VAR = "NONI_DECIDE_FAIL_COMMIT"
FAIL_COMMIT: bool = os.environ.get(FAIL_COMMIT_ENV_VAR) == "1"

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


def _written(exc: OSError, what: str) -> str:
    """One 'could not be written' headline naming the OSError and its reason."""
    return f"{what} ({exc.__class__.__name__}: {exc.strerror or exc})"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One bounded git call in ``repo`` with GPG signing forced off: a signing
    requirement must not wedge a record, identity stays what this tree's config
    says (``by`` comes from it) and GIT_TIMEOUT turns a hang into a refusal.
    """
    cmd = ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, returncode=124, stdout="",
            stderr=f"git {args[0] if args else '?'} timed out after {GIT_TIMEOUT}s",
        )


def _write_atomic(path: Path, text: str) -> None:
    """Write ``text`` via a same-directory temp file and os.replace (claim.py's
    idiom): a crash mid-write leaves the old bytes, never a truncated record.
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _render(record: dict) -> str:
    """The record's bytes: FIELD_ORDER, two-space indent, one trailing newline."""
    ordered = {key: record[key] for key in FIELD_ORDER if key in record}
    return json.dumps(ordered, indent=2, ensure_ascii=False) + "\n"


def _rollback(repo: Path, rels: list[str], target_rel: str | None, record_rel: str) -> str | None:
    """Undo this run's writes after a failed commit; None if the tree is clean.

    The index forgets both paths, the target is restored from HEAD and the new
    record is unlinked: ``git reset`` alone leaves it untracked on disk, where
    the censuses read it. A path that could not be restored is returned.
    """
    _git(repo, "reset", "-q", "--", *rels)
    if target_rel is not None:
        shown = _git(repo, "show", f"HEAD:{target_rel}")
        if shown.returncode != 0:
            return target_rel
        _write_atomic(repo / target_rel, shown.stdout)
    try:
        (repo / record_rel).unlink()
    except OSError:
        return record_rel
    return None


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


def _build_questions(
    questions: list[tuple[str, str]], options: list[tuple[str, str]], answers: list[tuple[str, str]]
) -> list[dict] | str:
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


def _read_json_object(path: Path) -> dict | None:
    """The object in ``path``, or None when it will not read as one."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def _refuse_unless_committed(repo: Path, path: Path, rel: str, target_id: str) -> tuple[str, str] | None:
    """Why this target may not be folded into this commit, or None: an untracked
    target brings unvalidated bytes, a locally modified one an unreviewed edit.
    """
    if not path.is_file():
        return (f"supersede target {target_id} has no record file at {path}",
                "name the id of a committed record (see the census report's id column)")
    if _git(repo, "ls-files", "--error-unmatch", "--", rel).returncode != 0:
        return (f"supersede target {target_id} is not tracked by git",
                "commit the record first: decide.py supersedes only committed records")
    if _git(repo, "status", "--porcelain", "--", rel).stdout.strip():
        return (f"supersede target {target_id} is not byte-identical to its last commit",
                f"commit or discard the change to {rel} and re-run decide")
    return None


def _load_target(repo: Path, ledger: Path, target_id: str) -> tuple[Path, dict] | tuple[str, str]:
    """Read a supersede target: ``(path, record)``, or a ``(headline, hint)``
    pair. Nothing is written on refusal. Past the committed-and-clean checks the
    target must read as a record object, not already superseded, with the ``id``
    it was asked for by: the censuses key the chain on that field.
    """
    path = ledger / f"{target_id}.json"
    refused = _refuse_unless_committed(repo, path, path.relative_to(repo).as_posix(), target_id)
    if refused is not None:
        return refused
    repair = "repair the record or name a different target"
    record = _read_json_object(path)
    if record is None:
        return (f"supersede target {target_id} is not a readable JSON object", repair)
    if record.get("status") == STATUS_SUPERSEDED:
        return (f"supersede target {target_id} is already {STATUS_SUPERSEDED}; "
                "superseded is terminal",
                "supersede the record that replaced it (the census report shows it)")
    if record.get("id") != target_id:
        return (f"supersede target {target_id} names itself {record.get('id')!r} in its own record",
                "pass the id the record carries, not the filename")
    return path, record


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
    parser.add_argument("--source-issue", type=int, default=None, help="tracker issue number")
    parser.add_argument("--source-comment", type=int, default=None, help="tracker comment id")
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
        source = {"issue_number": args.source_issue, "comment_id": args.source_comment}

    # --- git and identity: nothing is written until here and below ---------
    if _git(repo, "rev-parse", "--is-inside-work-tree").returncode != 0:
        return _fail(EXIT_GIT, f"{repo} is not a git work tree",
                     "run decide from the attached project's repo root (git -C REPO "
                     "rev-parse --is-inside-work-tree must succeed)")
    named = _git(repo, "config", "user.name")
    by = named.stdout.strip()
    if named.returncode != 0 or not by:
        return _fail(EXIT_GIT,
                     f"git config user.name is not set for {repo}, so the record cannot be "
                     "attributed",
                     "set an identity: git -C REPO config user.name <name> (or --global)")

    record_id = f"{date_part}-{args.slug}"
    record_path = ledger / f"{record_id}.json"
    record_rel = record_path.relative_to(repo).as_posix()
    if record_path.is_file():
        # Tracked or not, this name is taken: overwriting it takes somebody
        # else's record, or their draft, out of the ledger.
        return _fail(
            EXIT_COLLISION,
            f"{record_path} already exists; record ids are unique across the ledger",
            "choose a slug nobody has taken; a supersede keeps the --date of the "
            "record it replaces and differs by its slug",
        )

    target: tuple[Path, dict] | None = None
    target_rel: str | None = None
    if args.supersedes is not None:
        found = _load_target(repo, ledger, args.supersedes)
        if isinstance(found[0], str):
            return _fail(EXIT_COLLISION, found[0],
                         found[1] or "name a committed, live record of the chain being corrected")
        target_path, target_record = found
        target_rel = target_path.relative_to(repo).as_posix()
        # Chain position, filename stem and census replay order all read this
        # date, so another day cuts the record out of the chain it corrects.
        if target_record.get("date", "")[:10] != date_part:
            want = str(target_record.get("date", ""))[:10]
            return _fail(
                EXIT_COLLISION,
                f"--date {date_part} is not the date of the record being superseded "
                f"({target_record.get('date')!r})",
                f"a supersede carries the date of the record it replaces: pass --date {want}")
        target = (target_path, target_record)

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
    rels = [record_rel]
    try:
        _write_atomic(record_path, _render(record))
        if target is not None:
            flipped = dict(target[1])
            flipped["status"] = STATUS_SUPERSEDED
            _write_atomic(target[0], _render(flipped))
            rels.append(target_rel)
    except OSError as exc:
        # os.replace never half-writes, so the ledger is unwritable: back both
        # paths out the way a failed commit does.
        _rollback(repo, rels, target_rel, record_rel)
        return _fail(EXIT_COMMIT_FAILED, _written(exc, "the record could not be written"),
                     f"check that {ledger} is writable, then re-run decide")
    if args.no_commit:
        # The census reads the working tree, so these files now read as
        # uncommitted (an edited target is census.sh exit 12): the line names
        # both paths and says committing them is the caller's job.
        print(f"{Path(__file__).name}: wrote {', '.join(rels)}; left uncommitted: commit "
              "these paths before running the census")
        return EXIT_OK
    added = _git(repo, "add", "--", *rels)
    if added.returncode != 0:
        _rollback(repo, rels, target_rel, record_rel)
        return _fail(EXIT_COMMIT_FAILED, f"git add failed: {added.stderr.strip()}",
                     f"the paths {', '.join(rels)} are rolled back; re-run decide")
    # --only with explicit paths: the commit carries exactly what this run
    # wrote, never a file somebody else had already staged. FAIL_COMMIT is the
    # only way a run reaches a failing commit through a flag.
    if FAIL_COMMIT:
        committed = subprocess.CompletedProcess(["git", "commit"], returncode=128, stdout="",
                                               stderr="forced failure (test seam)")
    else:
        verb = f"supersede {args.supersedes} with {record_id}" if args.supersedes else record_id
        committed = _git(repo, "commit", "-q", "-m", f"steering: {verb}", "--only", "--", *rels)
    if committed.returncode != 0:
        unredone = _rollback(repo, rels, target_rel, record_rel)
        detail = committed.stderr.strip() or committed.stdout.strip()
        if unredone is not None:
            return _fail(EXIT_COMMIT_FAILED,
                         f"git commit failed and {unredone} could not be rolled back: {detail}",
                         f"run 'git status --porcelain -- {unredone}' and restore that path "
                         "by hand (git show HEAD:<path> writes the committed bytes back)")
        return _fail(EXIT_COMMIT_FAILED, f"git commit failed: {detail}",
                     f"{', '.join(rels)} are rolled back to their state before this run")
    print(f"{Path(__file__).name}: wrote {record_path}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
