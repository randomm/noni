"""The git helper and the atomic writer ``decide.py`` builds a record with.

Mechanics, not the writer's contract: a git call that cannot hang, sign itself,
run a repository's own hooks or reach an external transport, and a write that
lands whole or not at all. The one test seam lives with the git helper, where
the call it stands in for is made; an unset seam variable is inert.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
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
    could name. None neutralises global config: ``by`` still comes from the tree's
    ``user.name``. A hang is ``GIT_TIMEOUT_RC``, never an answer; errors="replace"
    keeps a clobbered blob from raising inside subprocess.
    """
    cmd = ["git", "-C", str(repo), "-c", "commit.gpgsign=false",
           "-c", f"core.hooksPath={os.devnull}", "-c", "protocol.ext.allow=never", *args]
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


