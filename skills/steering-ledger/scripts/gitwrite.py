"""The git helper and the atomic writer ``decide.py`` builds a record with.

Mechanics, not the writer's contract: a git call that cannot hang, sign itself,
run a repository's own hooks or reach an external transport; a write that lands
whole or not at all; and the probes that read a supersede target's committed
bytes, which answer only for themselves and take their refusal wording from the
writer. The one test seam lives with the git helper, where the call it stands in
for is made; an unset seam variable is inert.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

GIT_TIMEOUT = 60
# What run_git hands back for a call that never answered. No caller may read a
# git answer from it: every probe treats it as a refusal, never as rc 0.
GIT_TIMEOUT_RC = 124
# The seam the exit-5 test uses, and nothing else: the state it undoes (a
# committed record clobbered out of band) reaches this code no other way. Read
# at call time, so the value never needs a reload to take effect. The seam has
# exactly one value, ``1``, which fails the commit step and nothing else; any
# other value answers nothing, so a stray value in the environment cannot make
# one git call fail. Tests that need a specific call to fail patch subprocess.run
# in this module's namespace instead.
FAIL_COMMIT_ENV_VAR = "NONI_DECIDE_FAIL_COMMIT"

# The seam's stand-in reports a failure it did not return itself with this code:
# 128 is git's own general failure.
FAIL_COMMIT_RC = 128


def seam_answer(args: tuple[str, ...]) -> subprocess.CompletedProcess[str] | None:
    """The stand-in answer for a git call, or None to run it for real: the seam
    value ``1`` makes the commit fail (a state no input can produce) with
    ``FAIL_COMMIT_RC`` and no output. Any other value, and the unset variable of
    every real run, answers nothing.
    """
    if os.environ.get(FAIL_COMMIT_ENV_VAR) != "1":
        return None
    if not args or args[0] != "commit":
        return None
    return subprocess.CompletedProcess(["commit"], returncode=FAIL_COMMIT_RC,
                                       stdout="", stderr="forced failure (test seam)")


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One bounded git call in ``repo``, hardened and never signing a commit.
    ``commit.gpgsign=false`` keeps a signing requirement from wedging a record;
    ``core.hooksPath=`` at the null device keeps the repository's own hooks off this
    commit; ``protocol.ext.allow=never`` refuses the external transports a remote
    could name; ``core.fsmonitor=false`` keeps the tree's file-system monitor
    helper off every probe, since it is a program git execs to ask what changed.
    None neutralises global config: ``by`` still comes from the tree's
    ``user.name``. A hang is ``GIT_TIMEOUT_RC``, never an answer; errors="replace"
    keeps a clobbered blob from raising inside subprocess.
    """
    cmd = ["git", "-C", str(repo), "-c", "commit.gpgsign=false",
           "-c", f"core.hooksPath={os.devnull}", "-c", "protocol.ext.allow=never",
           "-c", "core.fsmonitor=false", *args]
    answered = seam_answer(args)
    if answered is not None:
        return answered
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, returncode=GIT_TIMEOUT_RC, stdout="",
            stderr=f"git {args[0] if args else '?'} timed out after {GIT_TIMEOUT}s",
        )


def file_mode(path: Path) -> int:
    """The mode a file this writer creates should carry: ``path``'s own when it
    exists (replacing a file is no reason to change who can read it), else
    world-readable as the umask allows. mkstemp's 0600 is never written: a record
    the census cannot read is a broken ledger."""
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        pass
    umask = os.umask(0o022)
    os.umask(umask)
    return 0o644 & ~umask


def write_atomic(path: Path, text: str) -> None:
    """Write ``text`` via a same-directory temp file and os.replace (claim.py's
    idiom): a crash mid-write leaves the old bytes, never a truncated record. The
    temp file's mode is set before the replace, so what lands is the mode the file
    should have, not mkstemp's owner-only default."""
    mode = file_mode(path)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def record_object(raw: bytes) -> dict | None:
    """The record object ``raw`` holds, or None when it is not one. Decoding
    happens here, not in json.loads' reader, so a non-UTF-8 record answers "not a
    record" instead of a traceback, and its bytes are never echoed.
    """
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def refuse_git_timeout(label: str,
                       *hung: tuple[str, subprocess.CompletedProcess[str]]) -> str | None:
    """A probe that timed out is a refusal (exit 3), never a clean answer: the
    message names the first hung call, and reading a timeout as 'tracked', 'clean' or
    'a work tree' would let a slow machine decide what enters the ledger. ``label``
    names the writer that is refusing, so the mechanic stays the writer's voice."""
    for command, result in hung:
        if result.returncode != GIT_TIMEOUT_RC:
            continue
        return f"git {command} timed out after {GIT_TIMEOUT}s, so {label} cannot " \
               "tell whether the tree is one it may write"


# The exit a probe that answered nothing yields, for a writer that installed no
# printer of its own (``probe_timeout_refusal``). ``decide.py`` assigns its own
# EXIT_GIT here when it loads this module, so the code the helper hands back is the
# writer's, never a copy that can drift.
EXIT_PROBE_TIMEOUT: int = 3


# What ``git show HEAD:<path>`` says with 128 and this stderr: the path is not in
# that tree. Both are honest negative answers, not a repository git could not
# read, and the writer turns each into its exit-4 refusal (missing target,
# untracked target). Matching them is what keeps a genuine "no such object" out
# of the exit-3 refusal below, which is reserved for a show that failed for a
# reason that told us nothing.
SHOW_NOT_IN_HEAD = ("does not exist in 'HEAD'", "but not in 'HEAD'")


def probe_unanswered(command: str, returncode: int, stderr: str = "") -> bool:
    """Whether ``command``'s ``returncode`` is not an answer it may be read for.

    ``ls-files --error-unmatch`` answers tracked with 0 and not-tracked with 1, so
    any other code ran no check; ``status --porcelain`` answers with its stdout,
    which only 0 fills honestly; ``show HEAD:<path>`` answers the committed bytes
    with 0 and any other non-zero code leaves stdout empty, which a reader would
    take for an empty record rather than a repository git could not read.

    ``show`` is the one verb with honest non-zero answers, and they are recognised
    by what git says rather than by the code alone: 128 with "does not exist in
    'HEAD'" or "but not in 'HEAD'" is a true report that the path is not in that
    tree, which the writer refuses as a missing or untracked target (exit 4), while
    the same 128 for any other reason (a corrupt object database, a bad HEAD, a
    broken work tree) answered nothing and is refused as a git problem (exit 3).
    Every other verb is only ever asked to not hang.
    A code outside the set is a refusal, exactly as a hang is: the call returned
    an empty stdout that a reader would otherwise take for 'not tracked', 'clean'
    or 'nothing committed', which is how a corrupt index could let a supersede
    rewrite a target nobody had inspected.
    """
    allowed = {"ls-files": (0, 1), "status": (0,), "show": (0,)}.get(command)
    if returncode == GIT_TIMEOUT_RC:
        return True
    if allowed is None or returncode in allowed:
        return False
    return not (command == "show"
                and any(phrase in stderr for phrase in SHOW_NOT_IN_HEAD))


def refuse_git_probe(label: str, command: str, returncode: int) -> str:
    """Why a probe that answered nothing is a refusal, in the writer's own voice.

    A hang and a failure are two different faults and are named as two different
    things: a slow machine is not a broken repository, and the operator's next
    step differs (re-run, versus find out why git cannot read the index).
    """
    fault = (f"timed out after {GIT_TIMEOUT}s" if returncode == GIT_TIMEOUT_RC
             else f"failed (exit {returncode})")
    return (f"git {command} {fault}, so {label} cannot tell whether the tree "
            "is one it may write")


def make_probe_refusal(fail: Callable[..., int], code: int, label: str) -> Callable[..., int]:
    """Build the printer a writer installs as its ``probe_timeout_refusal``.

    The wording and its exit code live here so the helper that raised the refusal
    is also what words it; ``fail`` is the writer's own headline-and-hint printer,
    ``code`` the exit it publishes for a git problem, and ``label`` the writer's
    name, so the refusal reads in the voice of the command that refused. The hint
    names the very call that died, because that is the one to get answering.
    """

    def _refuse(repo: Path, command: str, returncode: int) -> int:
        hint = f"re-run decide once git answers again (git -C {repo} {command})"
        return fail(code, refuse_git_probe(label, command, returncode), hint)

    return _refuse


def target_probes(label: str, repo: Path, path: Path) -> dict:
    """What the three git probes say about ``path``: ``rel`` for the messages,
    the ``tracked`` and ``dirty`` answers, the ``committed`` bytes (None when there
    are none) and ``from_head`` (whether git itself handed them over). When a probe
    never answered, ``probe_timeout_refusal`` is asked for the verdict and its exit
    code is handed back as ``timed_out``, and no other key is set: reading a
    timeout as 'tracked', 'clean' or 'committed' would let a slow machine decide
    what enters the ledger. A probe that reported a failure rather than hanging is
    refused the same way, because it too answered with nothing but an empty stdout.
    ``label`` names the writer, so the refusal reads in its voice.
    """
    rel = path.relative_to(repo).as_posix()
    tracked = run_git(repo, "ls-files", "--error-unmatch", "--", rel)
    status = run_git(repo, "status", "--porcelain", "--", rel)
    shown = run_git(repo, "show", f"HEAD:{rel}")
    probes = (("ls-files", tracked), ("status", status), ("show", shown))
    dead = next(((name, result) for name, result in probes
                 if probe_unanswered(name, result.returncode, result.stderr)), None)
    if dead is not None:
        # The helper writes no stderr of its own: whose file refused is the writer's
        # to say, so it prints the refusal and hands back its exit code.
        timed_out = probe_timeout_refusal(repo, dead[0], dead[1].returncode)
        return {"timed_out": EXIT_PROBE_TIMEOUT if timed_out is None else timed_out}
    committed = tracked.returncode == 0 and not status.stdout.strip()
    return {
        "timed_out": None,
        "rel": rel,
        "tracked": tracked.returncode == 0,
        "dirty": bool(status.stdout.strip()),
        "committed": (b"" if shown.returncode != 0
                      else shown.stdout.encode("utf-8")) if committed else None,
        "from_head": committed and shown.returncode == 0,
    }


def probe_timeout_refusal(repo: Path, command: str, returncode: int) -> int | None:
    """The refusal for a probe that answered nothing, whether it hung or died. The
    default answers None, and the caller reads that as 'trust no probe answer' and
    still exits ``EXIT_PROBE_TIMEOUT``; ``decide.py`` installs a printer of its own
    when it loads this module, so the wording names the writer that is refusing.
    """
    del repo, command, returncode
    return None


def refuse_target_fields(record: dict, target_id: str) -> tuple[str, str] | None:
    """Why ``record``'s own field types cannot be carried through a status flip, or
    None.

    A supersede copies the target and changes one value, so the helper that rewrites
    it must be able to describe every byte it moves. Two fields decide that:

    ``date`` is sliced to its first ten characters to compare against the run's
    --date, so a value that is not a string would either raise TypeError mid-run or
    slice a null to ``''`` and be reported as "dated another day" -- which tells the
    operator to pass a date the record does not carry in the form the census
    requires. ``questions`` is what the record answers, and a flip that copied
    anything other than a non-empty list of objects each with a string ``id`` and an
    ``answer`` that is a string or null would be repairing the ledger by accident.

    Both rules are census.py's own ("date is not a string", "questions must be an
    array of 1-4 entries", "question entry is not an object", "question answer must
    be a string or null"), so a ledger holding either was never clean.
    """
    if "date" in record and not isinstance(record["date"], str):
        return (f"supersede target {target_id} carries a {type(record['date']).__name__} "
                "in its date field where the census requires a string",
                "repair the record's date to the ISO form YYYY-MM-DDTHH:MM:SSZ and "
                "commit it, then re-run decide")
    questions = record.get("questions")
    if not isinstance(questions, list) or not questions:
        return (f"supersede target {target_id} carries no questions: "
                f"{type(questions).__name__} where a non-empty list is required",
                "name a record the census accepts (census.py: questions must be an "
                "array of 1-4 entries)")
    for entry in questions:
        if not isinstance(entry, dict):
            return (f"supersede target {target_id} has a {type(entry).__name__} among "
                    "its questions where an object is required",
                    "repair the record so every question is an object with id, text, "
                    "options and an answer, then re-run decide")
        if not isinstance(entry.get("id"), str):
            return (f"supersede target {target_id} has a question whose id is "
                    f"{type(entry.get('id')).__name__}, not a string",
                    "repair the record so every question names itself with a string id, "
                    "then re-run decide")
        if "answer" in entry and not isinstance(entry["answer"], (str, type(None))):
            return (f"supersede target {target_id} has a question whose answer is "
                    f"{type(entry['answer']).__name__}, not a string or null",
                    "repair the record so every answer is a string or null, then "
                    "re-run decide")
    return None


def refuse_live_record(record: dict, target_id: str, superseded: str) -> tuple[str, str] | None:
    """Why a committed record may not be flipped to ``superseded``, or None.

    Two facts make a target unsupersedable whatever its field types say: its status
    is already ``superseded``, which is terminal, so a second supersede would give
    one record two successors and the census would report a duplicate; and its own
    ``id`` differs from the name it was asked for by, which is two records in one
    file -- the censuses key the chain on the ``id`` field, so superseding by
    filename would mark a record the operator did not name.

    ``superseded`` arrives as a parameter because the status word is the writer's
    contract and this helper is the mechanic: a copy kept here could drift from the
    constant the writer flips to and quietly stop refusing what it should.
    """
    if record.get("status") == superseded:
        return (f"supersede target {target_id} is already {superseded}; "
                f"{superseded} is terminal", "supersede the record that replaced it "
                "(the census report shows it)")
    return None if record.get("id") == target_id else (
        f"supersede target {target_id} names itself {record.get('id')!r} in its own "
        "record", "pass the id the record carries, not the filename")


def load_committed_target(
    label: str, repo: Path, path: Path, target_id: str,
    shape_refusal: Callable[[Path, str], tuple[str, str] | None],
    canonical: Callable[[dict], str],
    superseded: str,
) -> tuple[bytes, dict] | tuple[str, str] | int:
    """The ``(committed_bytes, record)`` of a supersede target this run may
    rewrite, the ``(headline, hint)`` pair naming why it may not, or the exit code
    of the timeout refusal ``target_probes`` already had printed.

    The git mechanics live here: the three probes and the verdicts read from them
    (untracked, locally modified, no committed bytes, no file at the path), the
    committed bytes read from HEAD, and the target's own bytes read from disk (a
    directory reads from HEAD, so the flip still derives from committed bytes and
    changes only the status). ``canonical`` is the writer's renderer, so the
    canonical-form rule compares against what the writer would itself have written.
    The whole target schema is asked here and not of the caller --
    ``refuse_target_fields`` for the census's field types and ``refuse_live_record``
    for the chain position -- so no caller can reach a write by checking only part
    of it: a target whose ``date`` is not a string, whose ``questions`` are malformed
    or whose status or ``id`` do not fit is refused before any path is opened.
    """
    state = target_probes(label, repo, path)
    if state["timed_out"] is not None:
        return state["timed_out"]
    if not state["tracked"]:
        return (f"supersede target {target_id} is not tracked by git",
                "commit the record first: decide.py supersedes only committed records")
    if state["dirty"]:
        return (f"supersede target {target_id} is not byte-identical to its last commit",
                f"commit or discard the change to {state['rel']} and re-run decide")
    refusal = shape_refusal(path, target_id) if not path.is_file() else None
    if refusal is not None:
        return refusal
    committed = state["committed"]
    if committed is None:  # the probes answered no committed bytes: read nothing
        return (f"supersede target {target_id} has no committed bytes to rewrite",
                "commit the record first: decide.py supersedes only committed records")
    record = record_object(path.read_bytes() if path.is_file() else committed)
    if record is None:
        return (f"supersede target {target_id} is not a readable JSON object",
                "repair the record or name a different target")
    # The field types are refused before the canonical comparison and before any
    # write: a record whose date is not a string or whose questions are malformed
    # could never have come from a writer, and rewriting one moves bytes at random.
    malformed = refuse_target_fields(record, target_id)
    if malformed is not None:
        return malformed
    stale = refuse_live_record(record, target_id, superseded)
    if stale is not None:
        return stale
    # A target whose committed bytes git would not hand over is refused too: with
    # nothing to compare against, the writer cannot know it would move only status.
    if not state["from_head"] or canonical(record).encode("utf-8") != committed:
        return (f"supersede target {target_id} is not in the canonical form this writer "
                "writes (its fields, their order or its indent), so rewriting it would "
                "move bytes beyond its status",
                "have the target written by decide.py, or repair and commit it in "
                "that form, then re-run decide")
    return committed, record


def rollback(repo: Path, rels: list[str], target_rel: str | None, record_rel: str,
             target_committed: bytes | None = None) -> str | None:
    """Undo this run's writes; None if the tree is clean, else what the undo could
    not do, as a message the exit-5 refusal prints verbatim.

    The record goes first (an unlink works whatever holds the target's path), the
    index forgets both paths, the target gets the bytes read at check time. Any
    non-zero answer from the reset is a failed undo, not only a timeout: the
    index may still hold this run's paths staged, so the message names the reset
    failure and those paths instead of reporting a clean tree. A silent wrong
    path is a ledger nobody will fix.
    """
    leftover: str | None = None
    try:
        (repo / record_rel).unlink()
    except OSError:
        leftover = f"{record_rel} could not be removed"
    reset = run_git(repo, "reset", "-q", "--", *rels)
    if reset.returncode != 0:
        # Any non-zero answer is a failed undo, not only a timeout: the index may
        # still hold this run's paths staged, so they are named rather than the
        # tree being called clean.
        detail = reset.stderr.strip() or reset.stdout.strip() or "no reason given"
        return (f"git reset failed (exit {reset.returncode}): {detail}; "
                f"{', '.join(rels)} may still be staged")
    if target_rel is not None:
        if target_committed is None:
            return f"{target_rel} could not be restored: its committed bytes were not read"
        try:
            write_atomic(repo / target_rel, target_committed.decode("utf-8"))
        except OSError:
            return f"{target_rel} could not be written back"
    return leftover


