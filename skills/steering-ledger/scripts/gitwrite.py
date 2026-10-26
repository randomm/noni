"""The git runner and the atomic writer ``decide.py`` builds a record with.

Mechanics, not the writer's contract: a git call that cannot hang, sign itself,
run a repository's own hooks or reach an external transport, and a write that
lands whole or not at all. The one test seam lives with the runner, where the
call it stands in for is made; an unset seam variable is inert.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path

GIT_TIMEOUT = 60
# What run_git hands back for a call that never answered. No caller may read a
# git answer from it: every probe treats it as a refusal, never as rc 0.
GIT_TIMEOUT_RC = 124
# The seam the exit-5 and timeout tests use, and nothing else: the states they
# undo (a committed record clobbered out of band, a git call that never answers)
# reach this code no other way. Read at call time, so the value never needs a
# reload to take effect.
FAIL_COMMIT_ENV_VAR = "NONI_DECIDE_FAIL_COMMIT"

def seam_answer(args: tuple[str, ...]) -> subprocess.CompletedProcess[str] | None:
    """The stand-in answer for a git call, or None to run it for real: ``1`` makes
    the commit fail (a state no input can produce) and ``<rc>:<verb>`` answers the
    call for <verb> with that rc and no output, as a call that never answered
    would. Unset, as in every real run, answers nothing.
    """
    seam = os.environ.get(FAIL_COMMIT_ENV_VAR)
    if not seam:
        return None
    verb = args[0] if args else ""
    if seam == "1":
        seam = f"{FAIL_COMMIT_RC}:commit"
    head, sep, named = seam.partition(":")
    if not sep or named != verb or not head.lstrip("-").isdigit():
        return None
    detail = f"git {verb} timed out after {GIT_TIMEOUT}s" if head == str(GIT_TIMEOUT_RC) else \
        "forced failure (test seam)"
    return subprocess.CompletedProcess([verb], returncode=int(head), stdout="", stderr=detail)


# The seam's stand-in reports a failure it did not return itself with this code:
# 128 is git's own general failure.
FAIL_COMMIT_RC = 128


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


