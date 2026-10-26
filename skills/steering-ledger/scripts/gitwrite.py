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


def probe_unanswered(command: str, returncode: int) -> bool:
    """Whether ``command``'s ``returncode`` is not an answer it may be read for.

    ``ls-files --error-unmatch`` answers tracked with 0 and not-tracked with 1, so
    any other code ran no check; ``status --porcelain`` answers with its stdout,
    which only 0 fills honestly. Every other verb is only ever asked to not hang.
    A code outside the set is a refusal, exactly as a hang is: the call returned
    an empty stdout that a reader would otherwise take for 'not tracked', 'clean'
    or 'nothing committed', which is how a corrupt index could let a supersede
    rewrite a target nobody had inspected.
    """
    allowed = {"ls-files": (0, 1), "status": (0,)}.get(command)
    return returncode == GIT_TIMEOUT_RC or (
        allowed is not None and returncode not in allowed)


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
                 if probe_unanswered(name, result.returncode)), None)
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


def load_committed_target(
    label: str, repo: Path, path: Path, target_id: str,
    shape_refusal: Callable[[Path, str], tuple[str, str] | None],
    canonical: Callable[[dict], str],
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


