"""The git helper and the atomic writer ``order.py`` builds its commit with.

Mechanics, not the writer's contract: a git call that cannot hang, sign itself,
run a repository's own hooks or reach an external transport; and a write that
lands whole or not at all. Both live here rather than beside the verbs because
neither answers a question about the ordering -- they are the two ways this
writer could damage a tree, and each has exactly one implementation.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path

GIT_TIMEOUT = 60
# What a killed git call reports. No caller may read a git answer from it.
GIT_TIMEOUT_RC = 124


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
    """
    cmd = ["git", "-C", str(repo), "-c", "commit.gpgsign=false",
           "-c", f"core.hooksPath={os.devnull}", "-c", "protocol.ext.allow=never",
           "-c", "core.fsmonitor=false", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, returncode=GIT_TIMEOUT_RC, stdout="",
            stderr=f"git {args[0] if args else '?'} timed out after {GIT_TIMEOUT}s",
        )


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
