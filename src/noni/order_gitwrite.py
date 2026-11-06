"""The git helper, the committed-bytes probe and the atomic writer of ``order.py``.

Mechanics, not the writer's contract: a git call that cannot hang, sign itself,
run a repository's own hooks or reach an external transport; a read of the bytes
HEAD holds for one path that refuses to guess when git could not answer; and a
write that lands whole or not at all. All three live here rather than beside the
verbs because none answers a question about the ordering -- they are the three
ways this writer could damage a tree, and each has exactly one implementation.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path

from . import gitenv

GIT_TIMEOUT = 60
# What a killed git call reports. No caller may read a git answer from it.
GIT_TIMEOUT_RC = 124

# What ``git show HEAD:<path>`` says, alongside code 128, when the path is simply
# not in that tree (and when HEAD itself does not exist yet). Both are honest
# negative answers rather than a repository git could not read, and matching them
# is what keeps a genuine "no such object" out of the environment fault
# ``committed_bytes`` reports for every other non-zero answer.
SHOW_NOT_IN_HEAD = ("does not exist in 'HEAD'", "but not in 'HEAD'")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One bounded git call in ``repo``, hardened and never signing a commit.

    ``commit.gpgsign=false`` keeps a signing requirement from wedging the order;
    ``core.hooksPath=`` at the null device keeps the repository's own hooks off
    this commit; ``protocol.ext.allow=never`` refuses the external transports a
    remote could name; ``core.fsmonitor=false`` keeps the tree's file-system
    monitor helper off. Global config is NOT neutralised: the commit is made
    under the tree's configured identity, like every other noni writer.

    A hang is answered, not propagated: the call that cannot finish is turned
    into ``GIT_TIMEOUT_RC`` so every caller classifies it the same way (exit 3,
    the file named, never claimed as committed) instead of the run ending in a
    traceback.

    The environment is ``gitenv.child_env()``: every variable whose name begins
    with ``GIT_`` is removed except the identity, config and transport names on
    ``gitenv.CHILD_ENV_GIT_ALLOWLIST``, so a caller's exported value cannot
    retarget this commit, make it stage through a stray index, write its objects
    to another object store or trace itself into a file the caller names.
    ``repo`` alone decides the repository.
    """
    cmd = ["git", "-C", str(repo), "-c", "commit.gpgsign=false",
           "-c", f"core.hooksPath={os.devnull}", "-c", "protocol.ext.allow=never",
           "-c", "core.fsmonitor=false", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              timeout=GIT_TIMEOUT, env=gitenv.child_env())
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, returncode=GIT_TIMEOUT_RC, stdout="",
            stderr=f"git {args[0] if args else '?'} timed out after {GIT_TIMEOUT}s",
        )


def committed_bytes(repo: Path, rel: str) -> bytes | None | int:
    """What HEAD holds at ``rel``, or ``None`` when nothing is committed there.

    The freshness read of the writer: before a run writes, it compares what HEAD
    holds at the artifact's path against the bytes it read at the start of the
    run, and refuses when they moved (issue #116). One ``git()`` call, so the
    probe carries the same hardening, the same bound and the same test seam as
    the commit itself, and no second git runner exists to drift from it.

    The three answers git can give are kept apart, because a run that read them
    alike would write on top of an order it never saw:

      0            -- the committed bytes, returned verbatim. No decode and no
                       newline translation: what is compared is the byte sequence
                       this writer would itself have written.
      128 + phrase -- an honest "that path is not in that tree" (git's own wording,
                       including the case where HEAD itself does not exist yet).
                       ``None``: there are no committed bytes, which is the state
                       the first ``add`` writes into, not a change.
      anything else -- a call that answered nothing, returned as
                       ``GIT_TIMEOUT_RC`` for a hang or the call's own return code.
                       A corrupt object store, a bad HEAD or a hung git is an
                       environment fault (the caller's exit 3) and must never be
                       read as "committed bytes, unchanged" or as "nothing there".
    """
    shown = git(repo, "show", f"HEAD:{rel}")
    if shown.returncode == 0:
        return shown.stdout.encode("utf-8")
    if shown.returncode == GIT_TIMEOUT_RC:
        return GIT_TIMEOUT_RC
    # git's two honest negative answers for this verb, matched on what git said
    # rather than on its code alone: 128 for any other reason answered nothing.
    if shown.returncode == 128 and any(phrase in (shown.stderr or "")
                                       for phrase in SHOW_NOT_IN_HEAD):
        return None
    return shown.returncode


def written(exc: OSError, what: str) -> str:
    """One 'could not be written' headline naming the OSError and its reason."""
    return f"{what} ({exc.__class__.__name__}: {exc.strerror or exc})"


def file_mode(path: Path) -> int:
    """The mode a file this writer creates should carry: ``path``'s own when it
    exists (replacing a file is no reason to change who can read it), else
    world-readable as the umask allows. mkstemp's 0600 is never written: an
    order the census cannot read is an order nobody can trust."""
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        pass
    umask = os.umask(0o022)
    os.umask(umask)
    return 0o644 & ~umask


def write_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` via a same-directory temp file and os.replace: a crash
    mid-write leaves the old bytes, never a truncated order. The temp file's
    mode is set before the replace, so what lands is the mode the file should
    have, not mkstemp's owner-only default. Bytes, not text: what the writer
    compares against the committed file is the same byte sequence it writes."""
    mode = file_mode(path)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.",
                                    suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
