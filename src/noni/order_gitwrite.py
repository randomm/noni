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
from typing import NamedTuple

from . import gitenv
from .gitwrite import SHOW_NOT_IN_HEAD

GIT_TIMEOUT = 60
# What a killed git call reports. No caller may read a git answer from it.
GIT_TIMEOUT_RC = 124


class Committed(NamedTuple):
    """One answer of :func:`committed_bytes`, as a shape and not as a value.

    Three states, three shapes, so no caller can confuse them through a shared
    sentinel: ``data`` holds the committed blob verbatim and ``code`` is ``None``;
    ``code`` is set for a call that answered nothing, which is an environment fault
    and never "unchanged"; and when both are ``None`` git honestly reported that
    nothing is committed at that path (the state the first ``add`` writes into). No
    sentinel byte string and no magic return code travels between the probe and its
    caller, so a comparison cannot read one arm as another.
    """

    data: bytes | None
    code: int | None
    # git's own stderr, decoded for the fault arm only: the wording is what tells an
    # honest "not in that tree" apart from a corrupt object store.
    why: str


def _fault(returncode: int, why: str) -> Committed:
    """The arm for a call that answered nothing, naming its code and git's reason."""
    return Committed(data=None, code=returncode, why=why)


def committed_bytes(repo: Path, rel: str) -> Committed:
    """What HEAD holds at ``rel``, as one of three answers.

    The freshness read of the writer: before a run writes, it compares what HEAD
    holds at the artifact's path against the bytes it read at the start of the
    run, and refuses when they moved (issue #116). One :func:`git_bytes` call, so
    the probe carries the same hardening, the same bound and the same test seam as
    the commit itself, and no second git runner exists to drift from it.

    Absence is observed, never inferred from a missing answer -- the same rule
    ``orderstate.read_order`` follows by asking ``lstat`` before it believes a path
    is empty. The three answers are:

      the call succeeded
        -- ``Committed(data=<bytes>)``: the committed blob verbatim, however empty
           those bytes are. A committed zero-length blob IS a blob: it is compared
           like any other and a run that read a real file refuses against it. The
           read is binary, so there is no decode and no newline translation anywhere
           on the path and what is compared is the byte sequence this writer would
           itself have written.
      128 with git's own "not in that tree" wording
        -- ``Committed(data=None, code=None)``: nothing is committed at that path.
           The phrase set is ``gitwrite.SHOW_NOT_IN_HEAD``, the single owner of both
           wordings, and it covers the unborn-HEAD case as well as the absent path: a
           repository with no commit at all (the state of a freshly initialised
           private state repository, which is what the quickstart tells the operator
           to create) says "invalid object name 'HEAD'", and that reads as nothing
           committed rather than as a fault, or the first committed order of such a
           repository would never land. The wording is git's English, and the call
           runs under ``LC_ALL=C`` for that reason: a translated refusal would match
           no phrase and become a fault, which fails closed.
      anything else
        -- ``Committed(code=<n>)``: a call that answered nothing (``GIT_TIMEOUT_RC``
           for a hang, the call's own return code otherwise), with git's stderr in
           ``why``. A corrupt object store, a bad HEAD or a hung git is an
           environment fault and must never be read as "committed bytes, unchanged".
    """
    shown = git_bytes(repo, "show", f"HEAD:{rel}")
    if shown.returncode == 0:
        return Committed(data=shown.stdout, code=None, why="")
    why = _stderr(shown.stderr)
    if shown.returncode == GIT_TIMEOUT_RC:
        return _fault(GIT_TIMEOUT_RC, why)
    # Matched on what git said rather than on its code alone, and on an empty stdout
    # besides: a 128 that wrote nothing is not an answer this run may read as "there
    # is no committed order", which would let it commit over one HEAD actually holds.
    if (shown.returncode == 128 and not shown.stdout
            and any(phrase in why for phrase in SHOW_NOT_IN_HEAD)):
        return Committed(data=None, code=None, why="")
    return _fault(shown.returncode, why)


def _stderr(stderr: bytes | None) -> str:
    """``stderr`` as text, for matching git's own wording and nothing else.

    Lenient on purpose: this is git's explanation of a fault, decoded only to look
    for the two honest-negative phrases, so a byte the decoder cannot represent must
    not raise. No file content ever passes through here -- the blob goes to the
    caller as bytes, unread.
    """
    return "" if stderr is None else stderr.decode("utf-8", errors="replace")


def git_bytes(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """One bounded hardened git call in ``repo``, stdout handed over as raw bytes.

    The read half of this module's git helper, for the call that returns file
    contents rather than a verdict. A blob read through ``text=True`` with
    ``errors="replace"`` would decode and re-encode the artifact, so a committed
    blob whose bytes differ from what the run read could be reported as the same
    bytes once the difference fell on something the decoder could not represent.
    A freshness comparison has to be verbatim, and only a binary read makes "the
    same bytes" a claim about bytes.

    Same hardening, same bound, same environment as :func:`git`: the argv comes
    from one builder both halves call, so the two can never drift.
    """
    cmd = _git_command(repo, *args)
    try:
        return subprocess.run(cmd, capture_output=True, timeout=GIT_TIMEOUT,
                              env=_read_env())
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, returncode=GIT_TIMEOUT_RC, stdout=b"",
            stderr=(f"git {args[0] if args else '?'} timed out after "
                    f"{GIT_TIMEOUT}s").encode("utf-8"),
        )


def _read_env() -> dict[str, str]:
    """The environment of a read whose stderr the probe has to be able to read.

    ``gitenv.child_env()`` plus ``LC_ALL=C``: the honest negatives of ``show`` are
    recognised by git's own wording, and a translated refusal would match no phrase
    and be reported as a fault. C is the one locale whose wording is fixed, and it
    changes nothing else about the call.
    """
    env = gitenv.child_env()
    env["LC_ALL"] = "C"
    return env


def _git_command(repo: Path, *args: str) -> list[str]:
    """The argv of one hardened git call: the shape both halves of this module run.

    ``commit.gpgsign=false`` keeps a signing requirement from wedging the order;
    ``core.hooksPath=`` at the null device keeps the repository's own hooks off
    this commit; ``protocol.ext.allow=never`` refuses the external transports a
    remote could name; ``core.fsmonitor=false`` keeps the tree's file-system
    monitor helper off. Global config is NOT neutralised: the commit is made
    under the tree's configured identity, like every other noni writer.
    """
    return ["git", "-C", str(repo), "-c", "commit.gpgsign=false",
            "-c", f"core.hooksPath={os.devnull}", "-c", "protocol.ext.allow=never",
            "-c", "core.fsmonitor=false", *args]


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One bounded git call in ``repo``, hardened and never signing a commit.

    The write half of this module's git helper: ``add`` and ``commit``, whose stdout
    nobody reads. :func:`git_bytes` is its twin for a call whose stdout IS the answer,
    and both run the argv :func:`_git_command` builds.

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
    cmd = _git_command(repo, *args)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              timeout=GIT_TIMEOUT, env=gitenv.child_env())
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
