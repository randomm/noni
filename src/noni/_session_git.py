"""The git mechanics the four session writers build their commit with.

register.py, claim.py, close.py and release.py all write one file under
``noni/sessions/`` and commit exactly that file. The three steps they need are
here, once, so no writer keeps its own copy of a git call:

  atomic_write(path, text)              -- same-directory temp file, os.replace
  session_name(sid)                     -- the one repo-relative name a writer
                                       commits: ``noni/sessions/<sid>.md``
  stage_and_commit(repo, name, msg)     -- three steps, in this order:
      1. ``git -C <abspath(repo)> reset -q -- <name>``
                                      the writer's own index entry back to HEAD
                                       (a no-op for an untracked path)
      2. ``git -C <abspath(repo)> add -- <name>``
                                      gives an untracked or never-committed
                                       path its index entry
      3. ``git -C <abspath(repo)> commit -q -m <msg> --only -- <name>``
                                      commits exactly that path — a brand-new
                                      one included, because step 2 gave it an
                                      index entry
     Every other staged entry is never touched: it stays staged and
     uncommitted. A whole-tree commit is never used.

``<name>`` is a path *inside* the state root -- ``noni/sessions/<sid>.md``, not
a path the caller spells from wherever it happens to be standing. That is a
contract rather than a guess: the primitive never resolves a caller's path
against the process working directory, so no reading of a relative ``--repo``
can survive into the pathspec. :func:`session_name` builds the name, and
:func:`relative_name` is the one guard that refuses a name which does not
stand inside the root. The writers take the refusal before they write a byte.
The push loop is not here: it lives in :mod:`noni._session_push`, which imports
these primitives from here. A re-export would be a cycle, so the writers import
that module directly for their ``--push``.

The reason a commit failed is named in noni's own words rather than handed
through as git's. That half lives in :mod:`noni._commit_cause`, which
classifies the four states a writer can be left in (no upstream, the upstream
gone, nothing to commit, or some other git fault) and assembles the one line a
failure prints. :func:`stage_and_commit` asks it for that line only when a
commit is refused, importing it there rather than at module scope, so this
module holds no compile-time reference to the classifier and the classifier keeps
calling git through here.

The set of statuses that end a session lives here too, as
:data:`TERMINAL_STATUSES`, so the four writers agree on what "already closed"
means, and :func:`session_status` reads the field that set is decided from, so
no writer keeps its own copy of the '- status:' scan. A test asserts it equals
the census's own two inactive sets (``census_sessions._INACTIVE_STATUSES`` and
``census.INACTIVE_STATUSES``); the census sources are not changed and import
nothing from here.

Like the package's other git helpers, every call is bounded, never signs, runs
no repository hooks and refuses the external transports a remote could name.
This module is mechanics only: it owns no exit-code contract and prints the
caller's label on every message, so a fault reads in the voice of the command
the operator ran.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Literal

from . import gitenv

# What :func:`stopped_state` answers about one probed rebase state directory.
StoppedStateAnswer = Literal["stopped", "absent", "unreadable"]

# Statuses that end a session. A claim from a session in one of these states
# no longer counts toward the double-claim check, and close.py calls a session
# already in one of them terminal: it has nothing left to do. The status is
# stripped and lower-cased before it is compared. The census owns the same set
# twice over (its own two modules), and a test pins the two copies together;
# a status added on one side without the other is that test's failure.
TERMINAL_STATUSES: frozenset[str] = frozenset({"closed", "done", "superseded", "ended"})

# The two directories a stopped rebase can leave: the merge backend writes
# rebase-merge/, the am backend writes rebase-apply/, so the classifier probes
# both.
REBASE_STATE_DIRS: tuple[str, ...] = ("rebase-merge", "rebase-apply")

GIT_TIMEOUT = 60
# What a killed git call reports. No caller may read a git answer from it.
GIT_TIMEOUT_RC = 124
# Attempts the push loop makes before it reports failure.
MAX_PUSH_ATTEMPTS = 3

# How much of git's own output the push loop and the classifier echo. These
# streams are not this process's words (a fetch or push against an origin can
# forward remote-side and credential-helper text) and an agent pipes them
# straight into tool output, so they are sanitised and bounded rather than
# printed raw.
GIT_OUTPUT_LIMIT = 500

# A session id or a task reference is one token of a commit message, so it is
# validated before it reaches git: no whitespace, no path separator. Every
# writer here builds its message as a fixed prefix plus one such token, which
# is what keeps free text out of ``git commit -m``. fullmatch, not match: '$'
# also matches before a trailing newline.
TOKEN_RE = re.compile(r"^[^\s/\\]+$")


def safe_text(text: str, limit: int = GIT_OUTPUT_LIMIT) -> str:
    """Render git's own output for the terminal: bounded, no control bytes.

    Control characters other than newline and space are dropped, so an ANSI or
    OSC sequence cannot reach the terminal, and the tail past ``limit`` is
    dropped so one huge blob cannot crowd out everything else.
    """
    kept = []
    for ch in text:
        if ch == "\n" or ch == " " or unicodedata.category(ch)[0] != "C":
            kept.append(ch)
    cleaned = "".join(kept)
    if len(cleaned) > limit:
        return cleaned[:limit] + "... [truncated]"
    return cleaned


def git(repo: Path, *args: str, _run=subprocess.run) -> subprocess.CompletedProcess[str]:
    """One bounded git call in ``repo``, hardened, under the tree's identity.

    ``_run`` is the call this helper makes, and nothing else: a test that must
    hand this module scripted git answers replaces it and reaches every git call
    the session writers make through here. It is not a knob a caller turns — the
    writers never pass it.

    ``commit.gpgsign=false`` keeps a signing requirement from wedging the
    commit; ``core.hooksPath=`` at the null device keeps the repository's own
    hooks off it; ``protocol.ext.allow=never`` refuses the external transports
    a remote could name; ``core.fsmonitor=false`` keeps the tree's file-system
    monitor helper off every call. Global config is NOT neutralised: the
    commit is made under whoever's git config applies to the tree, like every
    other noni writer.

    The caller's working directory is removed from the picture, not consulted:
    ``repo`` and every ``args`` entry that names a path are made absolute where
    they are used, so a relative ``--repo`` resolves against the tree named on
    the command line rather than wherever the caller happened to start. That
    is not pedantry: a tree containing a ``noni/`` directory (the attached
    project's own state directory) turns a cwd-relative ``noni/sessions/x.md``
    into a path in a *different* repository, and a commit made there is a write
    nobody asked for.

    A hang is answered, not propagated: the call that cannot finish comes back
    as ``GIT_TIMEOUT_RC`` so every caller classifies it the same way instead of
    the run ending in a traceback.

    The environment is ``gitenv.child_env()``: every variable whose name begins
    with ``GIT_`` is removed except the identity, config and transport names on
    ``gitenv.CHILD_ENV_GIT_ALLOWLIST``, so an inherited one cannot send this
    commit to another repository, stage it through a stray index, write its
    objects to another object store or trace itself into a file the caller
    names. ``--repo`` alone decides the tree, which is the state-root contract.
    """
    cmd = ["git", "-C", os.path.abspath(str(repo)), "-c", "commit.gpgsign=false",
           "-c", f"core.hooksPath={os.devnull}", "-c", "protocol.ext.allow=never",
           "-c", "core.fsmonitor=false", *args]
    try:
        return _run(cmd, capture_output=True, text=True, errors="replace",
                    timeout=GIT_TIMEOUT, env=gitenv.child_env())
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, returncode=GIT_TIMEOUT_RC, stdout="",
            stderr=f"git {args[0] if args else '?'} timed out after {GIT_TIMEOUT}s",
        )


def in_git_worktree(repo: Path) -> bool:
    """True when git can commit in ``repo``: it resolves a git directory.

    The one question that decides whether a commit is possible at all, asked
    with a call whose answer is absolute (``--absolute-git-dir``, not
    ``--git-dir``: the latter prints a path relative to the *current* directory
    once you are inside the work tree, which is an answer to a different
    question). A tree with no git directory answers no, and the caller then
    behaves as --no-commit: the file is written, the run says so, and nothing
    is claimed as committed.
    """
    return git(repo, "rev-parse", "--absolute-git-dir").returncode == 0


def is_terminal_status(status: str) -> bool:
    """True when ``status`` names a session that has ended (see the set)."""
    return status.strip().lower() in TERMINAL_STATUSES


# The field a session's lifecycle reads. register.py writes it, close.py sets
# it, and the census parses it; the writers that need to read it read it here,
# so a file whose status lines disagree cannot answer 'active' to one writer
# and 'closed' to another.
STATUS_FIELD = "- status:"


def session_status(body: str) -> str | None:
    """The value of the last '- status:' line of ``body``, or None when it has none.

    Last occurrence wins, the way the census's own parser reads a repeated
    field: a writer needs the one answer a census run on the same bytes would
    act on, and the same bytes handed to two writers must give one verdict.
    """
    for line in reversed(body.splitlines()):
        stripped = line.strip()
        if stripped.startswith(STATUS_FIELD):
            value = stripped[len(STATUS_FIELD):].strip()
            if value:
                return value
    return None


def valid_token(token: str) -> bool:
    """True when ``token`` is safe to put in a commit message after a prefix."""
    return bool(token) and TOKEN_RE.fullmatch(token) is not None


def file_mode(path: Path) -> int:
    """The mode a file this writer creates should carry: ``path``'s own when it
    exists (replacing a file is no reason to change who can read it), else
    world-readable as the umask allows. mkstemp's 0600 is never written: a
    session file the census cannot read is a broken register."""
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        pass
    umask = os.umask(0o022)
    os.umask(umask)
    return 0o644 & ~umask


def atomic_write(path: Path, text: str) -> None:
    """Write ``text`` via a same-directory temp file and os.replace: a crash
    mid-write leaves the old bytes, never a truncated session file. The temp
    file's mode is set before the replace, so what lands is the mode the file
    should have, not mkstemp's owner-only default."""
    mode = file_mode(path)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.",
                                    suffix=".tmp")
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


# Where the session files live, as a name inside the state root. The four
# writers and the census read this one directory; a writer's file is always
# ``<this>/<session-id>.md``, so :func:`session_name` is the only place the
# spelling is written.
SESSIONS_REL = "noni/sessions"


def session_name(session_id: str) -> str:
    """The name a session's own file carries inside the state root.

    One function because four writers must stage, print and probe the same
    string: the file write location (``repo / name``), the pathspec, the failure
    wording and the hint are all derived from this one call. A name is what the
    commit primitive takes -- never a path the caller spelled from its own cwd
    (see :func:`stage_and_commit`).
    """
    return f"{SESSIONS_REL}/{session_id}.md"


def relative_name(name: str | PurePosixPath) -> str:
    """``name`` normalised, or ``""`` when it does not name a path inside the root.

    The contract :func:`stage_and_commit` relies on, written down where a caller
    can check it before it writes anything: the name it hands the commit
    primitive is a path *inside* the state root, so it is never absolute and
    never walks out of the root with a ``..`` component. Normalisation is what
    makes ``noni/sessions/../other.md`` and ``./noni/sessions/x.md`` the same
    judgement as a bare ``..``: the name is normalised first, so a ``..`` that
    lands back inside the root is just the file it names, and one that walks out
    of it arrives at a path whose first component is ``..`` -- refused whatever
    the rest of it spells.

    Three shapes are refused: an absolute path (git accepts an absolute pathspec
    from outside the ``-C`` tree, returns 0 and stages nothing, so a silent
    nothing-landed is the exact fault the primitive must not be able to produce);
    a name that walks out of the root; and the empty name or the root itself,
    because a writer commits one file and not a tree.

    The backslash is a separator here and not a character in a name: ``a\\b`` is
    a path on Windows, and a pathspec that is really one bizarre POSIX filename
    would be committed rather than refused.

    Returns ``""`` rather than raising: the caller's one ``if not rel`` has to
    cover every way a path can be wrong, including the refusal this module makes
    on the caller's behalf for a state root it has not looked at yet.
    """
    text = str(name).replace("\\", "/")
    if text.startswith("/"):
        return ""
    # ``os.path.normpath`` is the collapse: it resolves every ``.`` and ``..``
    # component against the growing path, so a name that walks out of the root
    # arrives at one whose first component is ``..`` and is refused. (A
    # ``PurePosixPath`` does *not* do this -- it keeps ``..`` as a component --
    # and a pathspec that still carries one is a path git refuses as outside the
    # tree, which is a different fault with a different message.) The leading
    # ``/`` test above is not redundant with normpath, which preserves it.
    normalised = PurePosixPath(os.path.normpath(text))
    if not normalised.parts or normalised.parts[0] == "..":
        # '' and '.' both answer with no parts: neither names a file.
        return ""
    return normalised.as_posix()


def stage_and_commit(repo: Path, name: str | PurePosixPath, message: str) -> tuple[bool, str]:
    """Commit exactly ``name`` under ``message``; ``(True, "")`` or ``(False, why)``.

    ``name`` is a path inside the state root -- what :func:`session_name`
    returns -- and the three steps are the primitive (see the module docstring):
    reset the path's own index entry, add it, then ``commit --only`` that path.
    A file nobody had committed before is committed by these same three steps,
    and a path somebody else had staged is left staged and uncommitted.

    The caller's working directory is not consulted, on either side: the name is
    never resolved against it (which is why it is a name and not a path), and
    ``git -C`` carries an absolute path, so a relative ``--repo`` names the tree
    it named on the command line rather than wherever the process started. The
    two together are what make ``--repo`` the only thing that decides the target
    repository.

    Two refusals, both ``(False, one noni-worded line)`` rather than a raised
    ``ValueError``, so the caller's one ``if not ok`` covers every way this can
    fail and no writer guards a git call with its own except:

    * the name is not one inside the state root -- :func:`relative_name`'s
      verdict, said in noni's words. A writer asks the same question before it
      writes, so this half is the backstop rather than the usual path;
    * the state root is itself a symlink -- :func:`linked_state_root`'s.

    Any git refusal also comes back as ``(False, one noni-worded line)``: this
    helper owns no exit code, so the caller names the class of failure and prints
    the hint. The line leads with the cause in noni's own words and ends with what
    git said, sanitised and bounded (see
    :func:`noni._commit_cause.commit_failed`): a writer that stops here has
    already written its file, and the operator who aborts the run reads one
    sentence, not git's status block.
    """
    rel = relative_name(name)
    if not rel:
        return False, (f"cannot commit {name}: the session writers commit only a "
                       "path inside the state root (never an absolute path and "
                       "never one that leaves it)")
    linked, why = linked_state_root(repo)
    if linked is not None:
        return False, f"cannot commit {rel}: {why}"
    reset = git(repo, "reset", "-q", "--", rel)
    if reset.returncode != 0:
        return False, _detail(reset, f"git reset failed for {rel}")
    added = git(repo, "add", "--", rel)
    if added.returncode != 0:
        return False, _detail(added, f"git add failed for {rel}")
    committed = git(repo, "commit", "-q", "-m", message, "--only", "--", rel)
    if committed.returncode != 0:
        return False, _failure_line(repo, committed, rel)
    return True, ""


def linked_state_root(repo: Path) -> tuple[Path | None, str]:
    """``(link, why)`` when ``repo`` is itself a symlink, else ``(None, "")``.

    The one place the rule is written, so the refusal a caller makes before it
    touches the tree and the one the commit primitive makes cannot drift apart.

    ``git`` works on the resolved path of the tree ``-C`` names, while a writer's
    own path arithmetic stays unresolved -- the writer joins the state root to a
    name inside it rather than resolving a file it has not created yet. A state
    root that is itself a link is where the two readings disagree, and the resolved path is what :mod:`noni._marker` would keep the
    working-copy marker at and what anyone auditing the commit later would have
    to match against a path nobody named on the command line. So the writer
    refuses and names ``resolved``, the one thing the operator can go and look
    at, rather than quietly following the link.

    A project directory *reached through* a link is not this state: only the
    ``--repo`` component itself is examined, never the cwd it is read against.
    """
    absolute = os.path.abspath(str(repo))
    if not (Path(absolute).is_symlink() or os.path.islink(str(repo))):
        return None, ""
    return Path(absolute), (f"--repo {repo} is a symlink to {os.path.realpath(absolute)}: "
                            "the session writers refuse a state root that is a symlink")


def _failure_line(repo: Path,
                  result: subprocess.CompletedProcess[str],
                  rel: str) -> str:
    """The default commit-failure namer: the classifier's line, imported when asked.

    Deferred to the call rather than bound at import: ``_commit_cause`` asks git
    through :func:`git` in this module, so a module-level reference between the
    two would be taken while one of them is still running its own import.
    """
    from . import _commit_cause
    return _commit_cause.commit_failed(repo, result, rel)



def _detail(result: subprocess.CompletedProcess[str], headline: str) -> str:
    """One headline naming what git said about a failed call, sanitised."""
    return f"{headline}: {_said(result) or 'no reason given'}"


def _said(result: subprocess.CompletedProcess[str]) -> str:
    """What git said about a failed call, sanitised, bounded, on one line.

    The same flattening :mod:`noni._commit_cause` applies to a commit failure's
    quotation: these bytes are the tail of one report line, and a multi-line
    echo reads as a raw status dump rather than as a quotation in a sentence.
    """
    said = _safe(result.stderr) or _safe(result.stdout) or ""
    return " ".join(said.split())


def _safe(text: str) -> str:
    cleaned = safe_text((text or "").strip())
    return "" if cleaned.strip() == "" else cleaned


def stopped_state(repo: Path, probed: Path) -> tuple[Path | None, StoppedStateAnswer]:
    """One probed rebase state directory: ``(dir, answer)``, answer in three kinds.

    ``"stopped"`` when the directory carries positive evidence of a live
    stopped rebase -- both ``head-name`` and ``onto`` read back non-empty,
    which is what a stopped rebase always leaves and what a stray directory
    does not; ``"absent"`` when there is nothing stopped here; ``"unreadable"``
    when the question could not be answered because a state file could not be
    read. Existence alone is not evidence: a directory whose files cannot be
    read is somebody else's leftover, and aborting it would reset the caller's
    worktree and index -- which is why unreadable is its own answer and not
    folded into either of the others.

    ``probed`` is what ``git rev-parse --git-path`` printed, which is relative
    to the working tree that call resolved (the clone itself), so a relative
    answer is joined to ``repo`` here rather than by each caller.
    """
    state = probed if probed.is_absolute() else repo / probed
    try:
        head_name = (state / "head-name").read_text(encoding="utf-8", errors="replace")
        onto = (state / "onto").read_text(encoding="utf-8", errors="replace")
    except OSError:
        # Absent is an answer (nothing stopped here); unreadable is not.
        return None, "unreadable" if state.is_dir() else "absent"
    if head_name.strip() and onto.strip():
        return state, "stopped"
    return None, "absent"


# The push loop lives in :mod:`noni._session_push`, which imports these
# primitives from here. A re-export here would be a cycle, so the writers import
# that module directly.

