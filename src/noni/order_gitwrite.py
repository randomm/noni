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

GIT_TIMEOUT = 60
# What a killed git call reports. No caller may read a git answer from it.
GIT_TIMEOUT_RC = 124

# The git answer that means "this path is not in that tree". ``git cat-file -e``
# and ``git rev-parse --verify`` agree on it and on nothing else: 1 means the
# object is simply not there, which is an honest negative the writer reads as
# absence, while any other non-zero code answered nothing about the path and is a
# fault. The number is pinned here, at the one call that reads it, and
# ``tests/test_order_writer_probe.py`` pins the codes beside it.
NOT_IN_TREE_RC: int = 1

# The code ``git hash-object`` answers for input it will not name an object for. An
# empty stdin is the one case the writer meets, and it is not a fault: there is no
# blob, which the caller reads as "no such object" and never as "the object store is
# broken".
NO_BLOB_RC: int = 128


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
    run, and refuses when they moved (issue #116). Two bounded calls, both run by
    :func:`git_bytes`, so the probe carries the same hardening, the same bound and
    the same test seam as the commit itself, and no second git runner exists to
    drift from it.

    Absence is observed, never inferred from a missing answer -- the same rule
    ``orderstate.read_order`` follows by asking ``lstat`` before it believes a path
    is empty. It is also never read out of a sentence. An earlier shape of this
    function asked one ``git show`` and sorted its 128 into "absent" or "fault" by
    matching git's English wording against a phrase set, and that reading was wrong
    in a state the quickstart tells the operator to create: under an unborn HEAD,
    with the artifact already sitting in the working tree or the index, git does not
    say "does not exist in 'HEAD'" at all -- it says "path '<rel>' exists on disk,
    but not in 'HEAD'", no phrase the set carried. The first committed order of such
    a repository refused, and the wording of a refusal was load-bearing. So the
    question "is that path in that tree?" is now asked of :func:`tree_blob_id`,
    which answers it with a return code, and the blob is read only once git has said
    it is there. The three answers are:

      the blob is in HEAD's tree
        -- ``Committed(data=<bytes>)``: the committed blob verbatim, however empty
           those bytes are. A committed zero-length blob IS a blob: it is compared
           like any other and a run that read a real file refuses against it. The
           read is binary, so there is no decode and no newline translation anywhere
           on the path and what is compared is the byte sequence this writer would
           itself have written.
      HEAD has no such path
        -- ``Committed(data=None, code=None)``: nothing is committed at that path.
           This covers the unborn HEAD (a repository with no commit at all, which is
           what a freshly initialised private state repository is) and a path that
           no commit has ever held, and both read as nothing committed rather than as
           a fault, or the first committed order would never land.
      a call that answered nothing
        -- ``Committed(code=<n>)``: a hang (``GIT_TIMEOUT_RC``) or any non-zero code
           that is not the one honest negative above, with git's stderr in ``why``.
           A corrupt object store, a bad HEAD or a hung git is an environment fault
           and must never be read as "committed bytes, unchanged".
    """
    blob, why = tree_blob_id(repo, f"HEAD:{rel}")
    if blob is None and why:
        return _fault(NOT_IN_TREE_RC, why)
    if blob is None:
        return Committed(data=None, code=None, why="")
    shown = git_bytes(repo, "show", f"HEAD:{rel}")
    if shown.returncode == 0:
        return Committed(data=shown.stdout, code=None, why="")
    return _fault(shown.returncode, _stderr(shown.stderr))


def blob_id(repo: Path, data: bytes | None) -> tuple[str | None, str]:
    """The ``(blob id, fault)`` of bytes a run read, asked of git itself.

    The three reads of the guard are compared, and a comparison only means something
    when all three speak one currency. HEAD and the index answer in object ids; the
    artifact read answers in bytes. Comparing bytes to an id is not a comparison but a
    guaranteed difference, so this turns the bytes this run planned against into the
    same id the other two print, by way of ``git hash-object --stdin``, which hashes
    without storing: no ``-w``, so a probe leaves no loose object behind for a census
    or a gc to trip over.

    ``None`` -- what the artifact read hands back for a path that did not exist -- has
    no blob, and answers ``(None, "")`` rather than the id of an empty file. "No file"
    and "a file that holds nothing" are the two states a run must not confuse, and an
    empty file is a blob whose id git prints happily.
    """
    if data is None:
        return None, ""
    hashed = git_bytes(repo, "hash-object", "--stdin", input_text=data)
    if hashed.returncode == GIT_TIMEOUT_RC:
        return None, _stderr(hashed.stderr)
    if hashed.returncode != 0:
        if hashed.returncode == NO_BLOB_RC and not hashed.stdout.strip():
            return None, ""
        return None, _stderr(hashed.stderr) or f"exit {hashed.returncode}"
    return hashed.stdout.decode("ascii", errors="replace").strip(), ""


def tree_blob_id(repo: Path, rev: str) -> tuple[str | None, str]:
    """The ``(blob id, fault)`` of ``rev``, asked without reading a sentence.

    ``git rev-parse --verify --quiet <rev>`` prints the object id when the name
    resolves and nothing when it does not, and its exit code is the answer: 0 is the
    object, ``NOT_IN_TREE_RC`` is "no such object, and git knew exactly that", any
    other code (or a hang) is a call that answered nothing and comes back with its
    reason. Neither of the two honest answers depends on locale, on the version of
    git, or on whether a file of the same name happens to sit on disk.

    This is the question the freshness guard needs twice: does HEAD hold the
    artifact, and does the index hold the bytes HEAD holds. It deliberately does not
    distinguish "the tree has no such path" from "there is no tree" -- for a
    comparison against what this run read, both are "HEAD holds nothing here", and
    the guard has no use for the difference.
    """
    asked = git_bytes(repo, "rev-parse", "--verify", "--quiet", rev)
    if asked.returncode == GIT_TIMEOUT_RC:
        return None, _stderr(asked.stderr)
    if asked.returncode == 0:
        return asked.stdout.decode("ascii", errors="replace").strip(), ""
    if asked.returncode == NOT_IN_TREE_RC:
        return None, ""
    return None, _stderr(asked.stderr) or f"exit {asked.returncode}"


def index_blob_id(repo: Path, rel: str) -> tuple[str | None, str]:
    """The ``(blob id, fault)`` the INDEX holds at ``rel``, or ``(None, "")``.

    The third read of the guard, and the only one of the three that git's commit
    actually obeys: ``git commit --only -- <path>`` takes the path from the index,
    so whatever lands in HEAD is what the index held a moment before. ``git ls-files
    -s -- <rel>`` answers ``<mode> <blob> <stage>\t<rel>`` for a staged path and
    prints nothing with exit 0 for a path the index does not hold, which is the
    whole contract this function reads -- exit 0 with no line is "the index holds
    nothing at that path", not a fault.

    The two shapes that would NOT answer the question are pinned by the probe's
    tests: ``ls-files --error-unmatch`` exits 1 for an unstaged path (a code this
    module would read as "no such object", and which the guard cannot tell from a
    genuine fault) and ``diff --cached --quiet`` exits 1 for any staged change at
    all, including the one this writer itself is about to make.
    """
    listed = git_bytes(repo, "ls-files", "-s", "--", rel)
    if listed.returncode == GIT_TIMEOUT_RC:
        return None, _stderr(listed.stderr)
    if listed.returncode != 0:
        return None, _stderr(listed.stderr) or f"exit {listed.returncode}"
    line = listed.stdout.decode("utf-8", errors="replace").strip()
    if not line:
        return None, ""
    fields = line.split()
    if len(fields) < 2:
        return None, "git ls-files answered with no blob id"
    return fields[1], ""


def _stderr(stderr: bytes | None) -> str:
    """``stderr`` as text, for naming a git fault to the operator.

    Lenient on purpose: this is git's explanation of a fault, decoded only to be
    printed, so a byte the decoder cannot represent must not raise. No file content
    ever passes through here -- the blob goes to the caller as bytes, unread.
    """
    return "" if stderr is None else stderr.decode("utf-8", errors="replace")


def git_bytes(repo: Path, *args: str, input_text: bytes | None = None,
              ) -> subprocess.CompletedProcess[bytes]:
    """One bounded hardened git call in ``repo``, stdout handed over as raw bytes.

    The read half of this module's git helper, for the call that returns file
    contents rather than a verdict. A blob read through ``text=True`` with
    ``errors="replace"`` would decode and re-encode the artifact, so a committed
    blob whose bytes differ from what the run read could be reported as the same
    bytes once the difference fell on something the decoder could not represent.
    A freshness comparison has to be verbatim, and only a binary read makes "the
    same bytes" a claim about bytes.

    Same hardening, same bound, same environment as :func:`git` (see
    :func:`_read_env` for the one thing it adds), and the argv comes from one
    builder both halves call, so the two can never drift.
    """
    cmd = _git_command(repo, *args)
    try:
        return subprocess.run(cmd, capture_output=True, timeout=GIT_TIMEOUT,
                              input=input_text, env=_read_env())
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, returncode=GIT_TIMEOUT_RC, stdout=b"",
            stderr=(f"git {args[0] if args else '?'} timed out after "
                    f"{GIT_TIMEOUT}s").encode("utf-8"),
        )


def _read_env() -> dict[str, str]:
    """The environment of a read: ``gitenv.child_env()`` plus ``LC_ALL=C``.

    The first half is not decoration and is not the read's own invention: it is the
    package's single answer for the environment of a git child. A probe that built
    its environment from ``os.environ`` would keep every ``GIT_*`` name the caller
    exported, and four of them relocate a repository outright -- ``GIT_DIR`` and
    ``GIT_COMMON_DIR`` which repository directory to use, ``GIT_WORK_TREE`` which
    working tree it belongs to, ``GIT_INDEX_FILE`` which index to stage and commit
    through -- while ``GIT_OBJECT_DIRECTORY`` and
    ``GIT_ALTERNATE_OBJECT_DIRECTORIES`` move the object store underneath it. A
    guard that read its committed state through an inherited ``GIT_DIR`` would be
    told "nothing is committed here" by a different repository and commit over an
    order it never looked at. ``--repo`` alone decides the repository; see
    :mod:`noni.gitenv`.

    ``LC_ALL=C`` is the read's own addition. It no longer carries the honesty of the
    guard -- absence is asked as a return code, not matched in a sentence -- but the
    two fault arms still hand git's stderr to the operator, and C is the one locale
    whose wording is fixed, so a message the operator reads cannot come back
    translated into something this run wrote no phrase for.
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
