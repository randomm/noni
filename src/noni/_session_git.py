"""The git mechanics the four session writers build their commit with.

register.py, claim.py, close.py and release.py all write one file under
``noni/sessions/`` and commit exactly that file. The three steps they need are
here, once, so no writer keeps its own copy of a git call:

  atomic_write(path, text)              -- same-directory temp file, os.replace
  stage_and_commit(repo, path, msg)     -- three steps, in this order:
      1. ``git reset -q -- <path>``   the writer's own index entry back to HEAD
                                       (a no-op for an untracked path)
      2. ``git add -- <path>``        gives an untracked or never-committed
                                       path its index entry
      3. ``git commit -q -m <msg> --only -- <path>``
                                      commits exactly that path — a brand-new
                                      one included, because step 2 gave it an
                                      index entry
     Every other staged entry is never touched: it stays staged and
     uncommitted. A whole-tree commit is never used.
  fetch_rebase_push(repo, branch)       -- push, and on rejection fetch, rebase
                                       onto origin/<branch> and push again, at
                                       most 3 attempts; a rebase that stopped
                                       is aborted (exit 5), a rebase git never
                                       started is not (exit 6)

The set of statuses that end a session lives here too, as
:data:`TERMINAL_STATUSES`, so the four writers agree on what "already closed"
means. A test asserts it equals the census's own two inactive sets
(``census_sessions._INACTIVE_STATUSES`` and ``census.INACTIVE_STATUSES``); the
census sources are not changed and import nothing from here.

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
import sys
import tempfile
import unicodedata
from pathlib import Path

from . import gitenv

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


def rel_of(repo: Path, path: Path) -> str:
    """``path`` as a repo-relative posix path, the form every git call here takes.

    A relative ``path`` names a file inside ``repo`` — that is what a caller
    holding ``--repo`` and a repo-relative name means — so it is joined to
    ``repo`` rather than resolved against the process's working directory.
    ``Path.resolve()`` is not usable for this: it resolves a path that does not
    exist yet by walking up to the nearest directory that does, so the file a
    writer is about to create resolves to the directory above the repository —
    and a path outside a repo has no repo-relative form at all.

    The comparison is made on absolute, normalised paths (``os.path.abspath``,
    which does not touch the filesystem), and a path the repository does not
    contain is refused with ``ValueError`` rather than quietly producing a
    relative path that git would read against some other tree.
    """
    root = os.path.abspath(str(repo))
    candidate = str(path)
    absolute = candidate if os.path.isabs(candidate) else os.path.join(root, candidate)
    absolute = os.path.abspath(absolute)
    prefix = root + os.sep
    if absolute != root and not absolute.startswith(prefix):
        raise ValueError(f"{path} is not inside {repo}")
    return os.path.relpath(absolute, root).replace(os.sep, "/")


def stage_and_commit(repo: Path, path: Path, message: str) -> tuple[bool, str]:
    """Commit exactly ``path`` under ``message``; ``(True, "")`` or ``(False, why)``.

    The three steps are the primitive (see the module docstring): reset the
    path's own index entry, add it, then ``commit --only`` that path. A file
    nobody had committed before is committed by these same three steps, and a
    path somebody else had staged is left staged and uncommitted.

    Any git refusal comes back as ``(False, git's own words)``: this helper
    owns no exit code, so the caller names the class of failure and prints the
    hint. A path outside the repository is answered the same way rather than as
    a raised ``ValueError``: the helper's promise is that it never hands back
    anything but a verdict, so the caller's one ``if not ok`` covers every way
    this can fail and no writer has to guard a git call with its own except.
    """
    try:
        rel = rel_of(repo, path)
    except ValueError as exc:
        return False, f"cannot commit {path}: {exc}"
    reset = git(repo, "reset", "-q", "--", rel)
    if reset.returncode != 0:
        return False, _detail(reset, f"git reset failed for {rel}")
    added = git(repo, "add", "--", rel)
    if added.returncode != 0:
        return False, _detail(added, f"git add failed for {rel}")
    committed = git(repo, "commit", "-q", "-m", message, "--only", "--", rel)
    if committed.returncode != 0:
        return False, _detail(committed, f"git commit failed for {rel}")
    return True, ""


def _detail(result: subprocess.CompletedProcess[str], headline: str) -> str:
    """One headline naming what git said about a failed call, sanitised."""
    said = _safe(result.stderr) or _safe(result.stdout) or "no reason given"
    return f"{headline}: {said}"


def _safe(text: str) -> str:
    cleaned = safe_text(text.strip())
    return "" if cleaned.strip() == "" else cleaned


def current_branch(repo: Path) -> tuple[str | None, str]:
    """The branch HEAD names: ``(branch, "")``, or ``(None, why)``.

    ``git rev-parse --abbrev-ref HEAD`` prints the literal string ``HEAD``
    when HEAD is detached, so that is the value refused here (a push to a
    branch literally named "HEAD" is not a push anyone asked for). A call that
    failed or printed nothing is refused the same way: the caller cannot push
    to a branch it cannot name.
    """
    result = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if result.returncode != 0:
        return None, _detail(result, "cannot resolve the current branch")
    branch = result.stdout.strip()
    if branch in ("", "HEAD"):
        return None, "cannot push from detached HEAD"
    return branch, ""


def fetch_rebase_push(repo: Path, branch: str, attempts: int = MAX_PUSH_ATTEMPTS,
                      *, label: str, exit_push_failed: int,
                      exit_rebase_conflict: int,
                      exit_rebase_refused: int) -> int:
    """Push ``branch`` to origin, retrying with fetch and rebase; return the caller's code.

    fetch-rebase-push, at most ``attempts`` attempts: the losing pusher ends
    rebased-and-pushed, so both writers' commits land and the census is what
    flags the disagreement. The exit codes are the caller's own constants,
    handed in with its ``label`` — this module is mechanics, and the operator
    hears the command they ran, not the helper that ran git for it.

    Returns ``exit_push_failed`` when the attempts run out, a fetch fails or a
    call is killed by the timeout; ``exit_rebase_conflict`` when a rebase
    entered and stopped, which this helper aborts; ``exit_rebase_refused`` when
    git never started the rebase or its state could not be read, which this
    helper leaves alone.
    """
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            fetch = git(repo, "fetch", "origin")
            if fetch.returncode != 0:
                return _report(label, exit_push_failed,
                               _detail(fetch, "git fetch failed"),
                               "check the remote and the network, then re-run with --push")
            rebase = git(repo, "rebase", f"origin/{branch}")
            if rebase.returncode != 0:
                return _classify_rebase_failure(
                    repo, rebase, label=label, exit_push_failed=exit_push_failed,
                    exit_rebase_conflict=exit_rebase_conflict,
                    exit_rebase_refused=exit_rebase_refused,
                    timed_out=rebase.returncode == GIT_TIMEOUT_RC,
                )
        push = git(repo, "push", "origin", branch)
        if push.returncode == 0:
            return 0
        if push.returncode == GIT_TIMEOUT_RC:
            _report(label, 0, _detail(push, f"push attempt {attempt}/{attempts} timed out"))
            continue
        _report(label, 0,
                f"push attempt {attempt}/{attempts} rejected: "
                + (_safe(push.stderr) or _safe(push.stdout) or "no reason given"))
    return _report(
        label, exit_push_failed,
        f"push still rejected after {attempts} attempts",
        f"run 'git -C {repo.name} fetch origin' and 'git -C {repo.name} rebase "
        f"origin/{branch}' by hand, then re-run with --push",
    )


def _report(label: str, code: int, *lines: str) -> int:
    """Print one report to stderr in the caller's voice and hand back its code."""
    for line in lines:
        if line:
            print(f"{label}: {line}", file=sys.stderr)
    return code


def _stopped_state_dir(repo: Path) -> tuple[Path | None, bool]:
    """Locate a rebase this clone is actually stopped in.

    Returns ``(dir, indeterminate)``. ``dir`` is set only when the state
    directory carries positive evidence of being stopped: both ``head-name``
    and ``onto`` read back non-empty, which is what a live stopped rebase
    always leaves and what a stray directory does not. ``indeterminate`` says
    the question could not be answered: a probe could not run, or a state file
    could not be read.

    Existence alone is not evidence: a directory whose files cannot be read is
    somebody else's leftover, and aborting it would reset the caller's worktree
    and index. Probes go through ``git rev-parse --git-path``, which resolves
    the directories wherever the git dir lives (plain clone, worktree).
    """
    indeterminate = False
    for name in REBASE_STATE_DIRS:
        probe = git(repo, "rev-parse", "--git-path", name)
        if probe.returncode != 0:
            indeterminate = True
            break
        state = Path(probe.stdout.strip())
        if not state.is_absolute():
            # --git-path prints a path relative to the working tree git
            # resolved for this call, which is the clone itself.
            state = repo / state
        try:
            head_name = (state / "head-name").read_text(encoding="utf-8", errors="replace")
            onto = (state / "onto").read_text(encoding="utf-8", errors="replace")
        except OSError:
            # Absent is an answer (nothing stopped here); unreadable is not.
            if state.is_dir():
                indeterminate = True
            continue
        if head_name.strip() and onto.strip():
            return state, indeterminate
    return None, indeterminate


def _classify_rebase_failure(
    repo: Path, rebase: subprocess.CompletedProcess[str], *, label: str,
    exit_push_failed: int, exit_rebase_conflict: int, exit_rebase_refused: int,
    timed_out: bool = False,
) -> int:
    """Turn a failed ``git rebase origin/<branch>`` into the caller's exit code.

    The two cases are not the same bug. A rebase that started and stopped
    leaves the clone mid-rebase, so anything the caller runs next commits on
    top of a half-finished rebase: this helper aborts it and hands back the
    conflict code. A rebase git never started left nothing to clean up, so
    running an abort there would be noise: the refusal code's hint names
    committing or stashing.
    """
    quoted = " ".join((_safe(rebase.stderr) or _safe(rebase.stdout)
                       or "no reason given").splitlines()[:3])
    state, indeterminate = _stopped_state_dir(repo)
    if state is None and indeterminate:
        # The probe could not answer, so this run claims no knowledge of the
        # clone's state: an unrunnable probe must not become "not stopped",
        # because a real conflict would then be reported as a refusal whose
        # hint cannot resolve it.
        return _report(
            label, exit_rebase_refused,
            f"rebase failed and its state cannot be read, so no abort was "
            f"attempted: {quoted}",
            f"run 'git status' and 'git rebase --abort' by hand in {repo.name}, "
            "then re-run this command",
        )
    if state is not None:
        abort = git(repo, "rebase", "--abort")
        if abort.returncode != 0:
            return _report(
                label, exit_rebase_conflict,
                f"rebase conflict and git rebase --abort failed: {_detail(abort, 'git said')}",
                f"the clone is still mid-rebase in {repo.name}; run git rebase --abort "
                "by hand",
            )
        if timed_out:
            return _report(
                label, exit_push_failed,
                f"rebase timed out after {GIT_TIMEOUT}s and was stopped in a "
                f"conflict, so it was aborted: {quoted}",
            )
        return _report(
            label, exit_rebase_conflict,
            f"rebase conflict: someone else changed the same session file, so the "
            f"rebase stopped: {quoted}",
            f"fix: fetch origin, resolve the conflict in the session file, then "
            f"re-run; the commit this run made is intact on {repo.name}",
        )
    if timed_out:
        return _report(
            label, exit_push_failed,
            f"rebase timed out after {GIT_TIMEOUT}s: {quoted}",
        )
    return _report(
        label, exit_rebase_refused,
        f"rebase refused (it never started): {quoted}",
        "fix: commit or stash the uncommitted changes in this clone, then re-run; "
        "this run started no rebase, so the commit it made is intact",
    )
