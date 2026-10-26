"""Record a steering decision: write one dated record under noni/decisions/
and commit it; with --supersedes, flip the target's status in the same commit.

The writer records what the operator decided and never chooses an answer:
every question's text, options and answer come from flags. Status is derived,
never supplied: all questions answered is ``decided``, any unanswered question
is ``open`` (written as ``"answer": null``), and the target of a supersede
becomes ``superseded``. There is no --status flag.

``id`` is ``<date>-<slug>``: the slug must match [a-z0-9-]+ (dashes, lowercase
letters, digits), so a record's filename stays a plain path segment, and
``--date`` (default: today, UTC) is the day that names it. A supersede carries
the date of the record it replaces, so the chain and the filename stay in
step, and the slug is what keeps the two files apart. A supersede target is
read from the working tree and must be tracked, committed and byte-identical to
``git show HEAD:<path>``; only its ``status`` field changes, and it is written
with the same atomic replace as the new record. Both paths are staged and
committed together with one ``--only`` commit, so a run never sweeps a file it
did not write into the commit.

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

Every refusal (exit 2, 3 or 4) leaves the ledger and the supersede target
untouched: the writes happen only after every check has passed, each file is
written to a temp file in its own directory and moved into place with
os.replace, and a commit failure rolls both paths back. The record's ``by``
comes from git config user.name and its ``date`` from --date or this run's UTC
clock; neither is guessed from anything else.
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

# The env var the exit-5 rollback test sets, and nothing else uses. No input
# flag reaches a failing commit (everything that could make git refuse is
# refused earlier), while the real state the rollback exists to undo — a
# committed record's bytes clobbered out of band — cannot be set up by a flag
# either. So the path is forced once, by a test, through this variable: it is
# read a single time at import into FAIL_COMMIT, which an in-process test can
# also set directly. Outside a test both stay inert.
FAIL_COMMIT_ENV_VAR = "NONI_DECIDE_FAIL_COMMIT"
FAIL_COMMIT: bool = os.environ.get(FAIL_COMMIT_ENV_VAR) == "1"

# Every return path in this module names one of these constants, and the
# docstring's 'Exit codes:' block above carries exactly this set of codes
# (asserted by tests/test_decide.py, which reads both).
EXIT_OK: int = 0
EXIT_USAGE: int = 2
EXIT_GIT: int = 3
EXIT_COLLISION: int = 4
EXIT_COMMIT_FAILED: int = 5

# The slug is the second half of the record id and of its filename, so it is
# held to what the census accepts as a plain path segment: census.sh rejects
# any *.json basename outside ^[A-Za-z0-9._-]+\.json$ as 10:bad-name, and one
# dot, slash or uppercase letter in a slug would poison the ledger for every
# later census run. Dashes are the only separator allowed, so the id stays
# <date>-<slug> and the date part stays unambiguous.
SLUG_RE = re.compile(r"[a-z0-9-]+")
DATE_FLAG_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}-[a-z0-9-]+")

# The derived-status words, and the one field of an existing record this
# writer is allowed to change.
STATUS_DECIDED = "decided"
STATUS_OPEN = "open"
STATUS_SUPERSEDED = "superseded"

# The record's field order is the order both censuses document; json.dump
# keeps it, so a record reads the way references/decisions.md shows it.
FIELD_ORDER = (
    "id",
    "date",
    "asked_by",
    "questions",
    "by",
    "scope",
    "status",
    "supersedes",
    "source",
)


def _prefix() -> str:
    """The name every refusal starts with: this script, as the others do."""
    return Path(__file__).name + ":"


def _fail(code: int, message: str, hint: str | None = None) -> int:
    """Print one refusal to stderr and hand back its exit code.

    A headline that names what was refused plus a fix line that says what to
    type, so no exit here is a bare number: an agent that cannot ask the
    operator still has the command that would resolve it.
    """
    print(f"{_prefix()} {message}", file=sys.stderr)
    if hint:
        print(f"{_prefix()} fix: {hint}", file=sys.stderr)
    return code


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one git call in ``repo`` with signing forced off.

    Only GPG signing is overridden: a signing requirement in a throwaway or CI
    tree must not wedge a record, and the identity stays whatever this tree's
    git config says (``by`` is read from that same config). Every call is
    bounded by GIT_TIMEOUT, so a hung git is a clean refusal, not a hang.
    """
    cmd = ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, returncode=124, stdout="",
            stderr="git " + (args[0] if args else "?") + " timed out after "
            + str(GIT_TIMEOUT) + "s",
        )


def _write_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` through a temp file in the same directory.

    A crash mid-write leaves the old bytes in place rather than a truncated
    record, and a temp file that cannot be cleaned up is never left behind.
    Same-directory temp plus os.replace is the same idiom claim.py uses for the
    register file.
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
    """The record's bytes: two-space indent, ``source`` last, one trailing newline.

    Field order is fixed by FIELD_ORDER so a record reads the way the reference
    documents it, and the trailing newline keeps the committed blob diff-clean
    against a hand-checked file.
    """
    ordered = {key: record[key] for key in FIELD_ORDER if key in record}
    return json.dumps(ordered, indent=2, ensure_ascii=False) + "\n"


def _rollback(repo: Path, rels: list[str], target_rel: str | None, record_rel: str) -> str | None:
    """Undo this run's writes after a failed commit; name what could not be undone.

    Both paths go back the way they came: the index forgets them, the target is
    restored from ``git show HEAD:<path>`` (the bytes this run verified before
    editing it), and the record this run created is unlinked — ``git reset``
    alone leaves the file on disk as untracked, and an untracked record is a
    record the censuses read. Returns None when the tree is back where this run
    found it, or the path that could not be put back: that is the one thing the
    operator must be told, because the tree then no longer matches its commit.
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

    The pair is how an answer or an option names its question: a value with no
    '=' would silently attach to no question, and an empty key or value would
    write a record the census rejects, so both are refused here with the shape
    spelled out. A value may itself carry '=' (a free-text answer such as
    ``ship=friday``), so only the first one splits. Pairs are kept in order and
    not folded into a dict: two ``--option q1=...`` flags are two options of
    q1, and collapsing them would quietly lose one. The refusal is a message,
    so this helper stays out of the printing business and the caller decides
    the exit code.
    """
    out: list[tuple[str, str]] = []
    for value in values:
        key, sep, rest = value.partition("=")
        if not sep or not key.strip() or not rest:
            return [], (
                f"{flag} {value!r} is not an ID=VALUE pair "
                f"(write it as {flag} q1=<value>, where q1 is the question's id)"
            )
        out.append((key.strip(), rest))
    return out, None


def _build_questions(
    questions: list[tuple[str, str]], options: list[tuple[str, str]], answers: list[tuple[str, str]]
) -> list[dict] | str:
    """The record's question objects, or a refusal message.

    Each question carries its id, its text, its options and its answer (null
    when the operator left it open), which is the shape both censuses validate:
    1-4 questions, 2-4 options each, answer a string or null. Options keep the
    order they were given in; a question that was answered twice keeps its last
    answer (the flags are written by one caller, so a repeat is a correction,
    not a second answer).
    """
    built = []
    for qid, text in questions:
        opts = [o for oid, o in options if oid == qid]
        if not 2 <= len(opts) <= 4:
            return (
                f"question {qid} has {len(opts)} option(s); every question needs "
                "2-4 options, given as --option "
                + qid
                + "=<option>"
            )
        asked = [a for aid, a in answers if aid == qid]
        built.append(
            {
                "id": qid,
                "text": text,
                "options": opts,
                "answer": asked[-1] if asked else None,
            }
        )
    return built


def _load_target(
    repo: Path, ledger: Path, target_id: str
) -> tuple[Path, dict] | tuple[str, str]:
    """Read a supersede target, refusing every state it must not be in.

    Returns ``(path, record)`` or a ``(headline, hint)`` refusal pair. The
    target must be committed and byte-identical to HEAD: a locally modified or
    uncommitted target would have its uncommitted bytes folded into this
    commit, and a target that is already superseded, or whose chain already
    holds a live successor, would leave the chain broken (census exit 20).
    A refusal writes nothing.
    """
    path = ledger / f"{target_id}.json"
    if not path.is_file():
        return (
            f"supersede target {target_id} has no record file at {path}",
            "name the id of a committed record (see the census report's id column)",
        )
    rel = path.relative_to(repo).as_posix()
    tracked = _git(repo, "ls-files", "--error-unmatch", "--", rel)
    if tracked.returncode != 0:
        return (
            f"supersede target {target_id} is not tracked by git",
            "commit the record first: decide.py supersedes only committed records",
        )
    status = _git(repo, "status", "--porcelain", "--", rel)
    if status.stdout.strip():
        return (
            f"supersede target {target_id} is not byte-identical to its last commit",
            f"commit or discard the change to {rel} and re-run decide",
        )
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (
            f"supersede target {target_id} cannot be read as a record ({exc.__class__.__name__})",
            "repair the record or name a different target",
        )
    if not isinstance(record, dict):
        return (
            f"supersede target {target_id} is not a JSON object",
            "repair the record or name a different target",
        )
    if record.get("status") == STATUS_SUPERSEDED:
        return (
            f"supersede target {target_id} is already {STATUS_SUPERSEDED}; "
            "superseded is terminal",
            "supersede the record that replaced it (the census report shows the chain)",
        )
    if record.get("id") != target_id:
        return (
            f"supersede target {target_id} names itself {record.get('id')!r} in its own record",
            "pass the id the record carries, not the filename",
        )
    return path, record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record a steering decision")
    parser.add_argument("--repo", required=True, help="repository root")
    parser.add_argument("--slug", required=True, help="id slug ([a-z0-9-]+)")
    parser.add_argument("--scope", required=True, help="the direction area the decision covers")
    parser.add_argument("--asked-by", required=True, help="the agent role or session that asked")
    parser.add_argument(
        "--question", action="append", required=True, metavar="ID=TEXT",
        help="a question, as ID=TEXT (repeatable, 1-4 questions)",
    )
    parser.add_argument(
        "--option", action="append", default=[], metavar="ID=OPTION",
        help="an option for question ID (repeatable, 2-4 per question)",
    )
    parser.add_argument(
        "--answer", action="append", default=[], metavar="ID=ANSWER",
        help="the operator's answer for question ID (repeatable; a question with "
        "no --answer is written as open with \"answer\": null)",
    )
    parser.add_argument(
        "--date", default=None, metavar="YYYY-MM-DD",
        help="record date (default: today, UTC); --supersedes requires it",
    )
    parser.add_argument("--source-issue", type=int, default=None, help="tracker issue number")
    parser.add_argument("--source-comment", type=int, default=None, help="tracker comment id")
    parser.add_argument(
        "--supersedes", default=None, metavar="ID",
        help="id of the record this one replaces (requires every question answered)",
    )
    parser.add_argument(
        "--no-commit", action="store_true",
        help="write the file(s) and leave them uncommitted for the caller to commit",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    ledger = repo / "noni" / "decisions"

    # --- input shape: everything checkable without touching git -----------
    if not SLUG_RE.fullmatch(args.slug):
        return _fail(
            EXIT_USAGE,
            f"slug {args.slug!r} is not a slug",
            "a slug is one or more lowercase letters, digits and dashes ([a-z0-9-]+); "
            "no dots, no slashes, no spaces, no uppercase",
        )
    if not args.scope.strip():
        return _fail(EXIT_USAGE, "--scope is empty", "name the direction area, e.g. --scope 'release ordering'")
    if not args.asked_by.strip():
        return _fail(EXIT_USAGE, "--asked-by is empty", "name the agent role or session that asked")

    if args.date is None:
        date_part = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        if not DATE_FLAG_RE.fullmatch(args.date):
            return _fail(
                EXIT_USAGE,
                f"--date {args.date!r} is not YYYY-MM-DD",
                "pass the record date as --date 2026-10-26",
            )
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            return _fail(
                EXIT_USAGE,
                f"--date {args.date!r} is not a real calendar date",
                "pass a date that exists, e.g. --date 2026-10-26",
            )
        date_part = args.date

    if not 1 <= len(args.question) <= 4:
        return _fail(
            EXIT_USAGE,
            f"{len(args.question)} --question flag(s); a record carries 1-4 questions",
            "ask between one and four questions, each as --question q1=<text>",
        )
    questions: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value in args.question:
        qid, sep, text = value.partition("=")
        qid = qid.strip()
        if not sep or not qid or not text:
            return _fail(
                EXIT_USAGE,
                f"--question {value!r} is not an ID=TEXT pair",
                "write it as --question q1=<the question as asked>",
            )
        if qid in seen:
            return _fail(EXIT_USAGE, f"--question id {qid!r} is used twice", "give each question its own id")
        seen.add(qid)
        questions.append((qid, text))

    options, problem = _parse_pairs(args.option, "--option")
    if problem is not None:
        return _fail(EXIT_USAGE, problem, "give every option 2-4 entries per question")
    answers, problem = _parse_pairs(args.answer, "--answer")
    if problem is not None:
        return _fail(EXIT_USAGE, problem, "answer a question with --answer ID=<answer>")
    for label, pairs in (("--option", options), ("--answer", answers)):
        unknown = sorted({oid for oid, _v in pairs} - seen)
        if unknown:
            return _fail(
                EXIT_USAGE,
                f"{label} names question(s) {', '.join(unknown)} that no --question asks",
                "the id must match one of the --question ids",
            )

    built = _build_questions(questions, options, answers)
    if isinstance(built, str):
        return _fail(EXIT_USAGE, built, "give every question 2-4 options")

    # A declined steer is an open chain-root record, never a supersede: an
    # unanswered question in a supersede would leave the chain with no live
    # answer (census exit 20), so this is a usage error, not a ledger state.
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
        if not ID_RE.fullmatch(args.supersedes):
            return _fail(
                EXIT_USAGE,
                f"--supersedes {args.supersedes!r} is not a record id",
                "a record id is YYYY-MM-DD-<slug>, e.g. 2026-10-01-steer-order",
            )
        # The chain's date is the record it replaces carries, so a supersede
        # without --date cannot be placed in the chain it is correcting.
        if args.date is None:
            return _fail(
                EXIT_USAGE,
                "--supersedes needs --date: a supersede carries the date of the "
                "record it replaces",
                "pass the target's date, e.g. --date 2026-10-26",
            )

    source = None
    if args.source_issue is not None or args.source_comment is not None:
        if args.source_issue is None or args.source_comment is None:
            return _fail(
                EXIT_USAGE,
                "source provenance needs both --source-issue and --source-comment",
                f"got issue={args.source_issue!r} comment={args.source_comment!r}; "
                "pass both, or neither",
            )
        source = {"issue_number": args.source_issue, "comment_id": args.source_comment}

    # --- git and identity --------------------------------------------------
    inside = _git(repo, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0:
        return _fail(
            EXIT_GIT,
            f"{repo} is not a git work tree",
            "run decide from the attached project's repository root "
            "(git -C REPO rev-parse --is-inside-work-tree must succeed)",
        )
    named = _git(repo, "config", "user.name")
    by = named.stdout.strip()
    if named.returncode != 0 or not by:
        return _fail(
            EXIT_GIT,
            f"git config user.name is not set for {repo}, so the record cannot be attributed",
            "set an identity: git -C REPO config user.name <name> "
            "(or --global for every repository)",
        )

    record_id = f"{date_part}-{args.slug}"
    record_path = ledger / f"{record_id}.json"
    record_rel = record_path.relative_to(repo).as_posix()
    if record_path.is_file():
        # An existing file of the same name is a collision whether or not git
        # tracks it: writing over it would take somebody else's record (or
        # their uncommitted draft) out of the ledger.
        return _fail(
            EXIT_COLLISION,
            f"{record_path} already exists; record ids are unique across the ledger",
            "choose a slug nobody has taken (--slug <slug>); a supersede keeps the "
            "--date of the record it replaces and differs by its slug",
        )

    target: tuple[Path, dict] | None = None
    target_rel: str | None = None
    if args.supersedes is not None:
        found = _load_target(repo, ledger, args.supersedes)
        if isinstance(found[0], str):
            headline, hint = found
            return _fail(
                EXIT_COLLISION,
                headline,
                hint or "name a committed, live record of the chain being corrected",
            )
        target_path, target_record = found
        target_rel = target_path.relative_to(repo).as_posix()
        # A supersede carries the date of the record it replaces: the chain
        # position, the filename stem and the census's replay ordering all read
        # that date, so a new day would cut the new record out of the chain it
        # is correcting. The slug is what keeps the two files apart.
        if target_record.get("date", "")[:10] != date_part:
            return _fail(
                EXIT_COLLISION,
                f"--date {date_part} is not the date of the record being superseded "
                f"({target_record.get('date')!r})",
                "a supersede carries the date of the record it replaces: pass "
                f"--date {str(target_record.get('date', ''))[:10]}",
            )
        target = (target_path, target_record)

    # --- the writes: reached only after every check above passed -----------
    status = STATUS_DECIDED if not unanswered else STATUS_OPEN
    record: dict = {
        "id": record_id,
        "date": f"{date_part}T00:00:00Z",
        "asked_by": args.asked_by,
        "questions": built,
        "by": by,
        "scope": args.scope,
        "status": status,
        "supersedes": args.supersedes,
    }
    if source is not None:
        record["source"] = source

    if not ledger.is_dir():
        # The ledger directory is allocated on the first record: a fresh
        # project has no noni/ state yet, and creating the directory that
        # holds this run's record is the writer's own allocation.
        try:
            ledger.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _fail(
                EXIT_COMMIT_FAILED,
                f"the ledger directory {ledger} could not be created "
                f"({exc.__class__.__name__}: {exc.strerror or exc})",
                f"check that {repo} is writable, then re-run decide",
            )

    rels = [record_rel]
    try:
        _write_atomic(record_path, _render(record))
        if target is not None:
            target_path, target_record = target
            flipped = dict(target_record)
            flipped["status"] = STATUS_SUPERSEDED
            _write_atomic(target_path, _render(flipped))
            rels.append(target_rel)
    except OSError as exc:
        # The atomic replace never half-writes a record, so this is a ledger we
        # cannot write to at all: back both paths out the same way a failed
        # commit does, so the refusal leaves the tree as this run found it.
        _rollback(repo, rels, target_rel, record_rel)
        return _fail(
            EXIT_COMMIT_FAILED,
            f"the record could not be written ({exc.__class__.__name__}: {exc.strerror or exc})",
            f"check that {ledger} is writable, then re-run decide",
        )

    if args.no_commit:
        # Same validation chain and the same atomic writes as the committing
        # path, minus git add and git commit. The census reads the working
        # tree, so a run that reports on the ledger right now sees these files
        # as uncommitted (census.sh reports an edited target as exit 12): the
        # line names both paths and says committing them is the caller's job.
        print(
            f"{_prefix()} wrote {', '.join(rels)}; left uncommitted: commit these paths "
            "before running the census"
        )
        return EXIT_OK

    added = _git(repo, "add", "--", *rels)
    if added.returncode != 0:
        _rollback(repo, rels, target_rel, record_rel)
        return _fail(
            EXIT_COMMIT_FAILED,
            f"git add failed: {added.stderr.strip()}",
            f"the paths {', '.join(rels)} are rolled back; re-run decide",
        )
    message = (
        f"steering: supersede {args.supersedes} with {record_id}"
        if args.supersedes is not None
        else f"steering: {record_id}"
    )
    # --only with explicit paths: the commit carries exactly what this run
    # wrote, never a file somebody else had already staged.
    if FAIL_COMMIT:
        committed = subprocess.CompletedProcess(
            ["git", "commit"], returncode=128, stdout="", stderr="forced failure (test seam)"
        )
    else:
        committed = _git(repo, "commit", "-q", "-m", message, "--only", "--", *rels)
    if committed.returncode != 0:
        unredone = _rollback(repo, rels, target_rel, record_rel)
        detail = committed.stderr.strip() or committed.stdout.strip()
        if unredone is not None:
            return _fail(
                EXIT_COMMIT_FAILED,
                f"git commit failed and {unredone} could not be rolled back: {detail}",
                f"run 'git status --porcelain -- {unredone}' and restore that path "
                "by hand (git show HEAD:<path> writes the committed bytes back)",
            )
        return _fail(
            EXIT_COMMIT_FAILED,
            f"git commit failed: {detail}",
            f"{', '.join(rels)} are rolled back to their state before this run",
        )
    print(f"{_prefix()} wrote {record_path}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
