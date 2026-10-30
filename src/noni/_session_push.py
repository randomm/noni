"""The push loop the session writers share: fetch, rebase, push, at most 3 attempts.

:func:`fetch_rebase_push` is what ``--push`` runs after a writer has committed its
session file: the losing pusher ends rebased-and-pushed, so both writers' commits
land and the census is what flags the disagreement. The verdicts are not the same
bug and are not reported the same way: a rebase that started and stopped leaves
the clone mid-rebase (anything run next would commit on top of a half-finished
rebase), so it is aborted and reported as a conflict; a rebase git never started
left nothing to clean up, so the refusal's hint names committing or stashing.

The module owns the mechanics of the loop and the verdicts, and no wording: each
writer hands in its own ``label``, its four codes, its ``messages`` table for the
rebase verdicts, and (for the classifier) its own ``probe`` and ``abort``, so an
operator hears the command they ran and the git calls are the ones that command
actually makes. ``claim.py`` is the shipped holder of the rebase wording and
passes it to both entry points; a caller with no wording of its own gets a generic
line per verdict rather than a second table nobody keeps in step.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

from ._session_git import (
    GIT_TIMEOUT,
    GIT_TIMEOUT_RC,
    MAX_PUSH_ATTEMPTS,
    REBASE_STATE_DIRS,
    _detail,
    _safe,
    git,
    stopped_state,
)

# The shape every git seam in this module has: the repo first, then the git
# argv, and a bounded CompletedProcess back. The two injectable parameters below
# take a callable of this shape (``claim.py``'s adapter is one), so a caller that
# drives its own git hands in a callable and the type says what it must accept.
GitRunner = Callable[..., subprocess.CompletedProcess[str]]

# The shape of a branch name this loop will hand to git. A leading dash is what
# makes the check worth having: ``git push origin <name>`` reads a leading-dash
# argument as a push option (``--force``, ``--receive-pack=...``) rather than as
# a ref, so a name the loop did not choose for itself must never be passed bare.
# The rest of the pattern refuses the ref-name shapes git itself refuses (a
# component of only dots, a ``.lock`` suffix, a trailing slash), and
# ``git check-ref-format`` accepts every name this one does. fullmatch, not
# match: ``$`` also matches before a trailing newline, which would let ``main\n``
# reach the command line as a name plus an argument.
BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")

# The wording one writer's rebase reports carry, keyed by the verdict names in
# :data:`REBASE_VERDICTS`. The type names what :func:`classify_rebase_failure`
# reads out of it — a tuple of whole lines, never one string — so a writer that
# publishes a bare string is a mistake a reader can see rather than a report that
# prints one line where it meant three.
RebaseMessages = dict[str, tuple[str, ...]]


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """The one git seam the loop uses, so one injection covers every call it makes.

    A caller that drives its own git (a scripted test double, or claim.py's own
    call shape) hands a callable here and every call the verdict makes -- the
    state probes, the abort -- goes through it, so what the report says is the
    outcome of the calls that caller actually made.
    """
    return git(repo, *args)


def current_branch(repo: Path) -> tuple[str | None, str]:
    """The branch HEAD names: ``(branch, "")``, or ``(None, why)``.

    ``git rev-parse --abbrev-ref HEAD`` prints the literal string ``HEAD``
    when HEAD is detached, so that is the value refused here (a push to a
    branch literally named "HEAD" is not a push anyone asked for). A call that
    failed or printed nothing is refused the same way: the caller cannot push
    to a branch it cannot name.

    A name that is not a safe ref name is refused too, for the reason
    :data:`BRANCH_NAME_RE` states: this is the one place the loop learns the
    name, so it is the one place that name can be stopped from becoming an
    option of the push. A detached HEAD keeps its own message, which is the
    fact the operator needs (check out a branch), and is not reported as a
    malformed name.
    """
    result = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if result.returncode != 0:
        return None, _detail(result, "cannot resolve the current branch")
    branch = result.stdout.strip()
    if branch in ("", "HEAD"):
        return None, "cannot push from detached HEAD"
    if not BRANCH_NAME_RE.fullmatch(branch):
        # git can be coaxed into creating a ref this regex refuses (an
        # ``update-ref`` of ``--force``, for one) and the tree's own history can
        # arrive with one, so the loop must not be the place that name turns into
        # an argument of its own git call. This is the shape claim.py's --branch
        # check applies to its own argument, applied here to the name the tree
        # reported (looser by design: this name may carry a slash).
        return None, (f"the current branch {branch!r} is not a safe ref name "
                      "(expected a letter or digit, then letters, digits, ., _, "
                      "- or /)")
    return branch, ""


def fetch_rebase_push(repo: Path, branch: str, attempts: int = MAX_PUSH_ATTEMPTS,
                      *, label: str, exit_push_failed: int,
                      exit_rebase_conflict: int,
                      exit_rebase_refused: int,
                      messages: RebaseMessages,
                      run_git: GitRunner = _run_git) -> int:
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

    ``messages`` is the caller's wording for the rebase verdicts, passed straight
    to :func:`classify_rebase_failure` (see :data:`REBASE_VERDICTS` for the keys).
    There is no default here either: the hint that names the session file a
    writer owns is that writer's prose, and the loop has nothing of its own to
    say about it.

    Every git call the loop makes -- the fetch, the rebase, the push, and the
    verdict's probes and abort -- goes through ``run_git``, which defaults to this
    module's own bounded :func:`git`. A caller that drives its own git hands in one
    callable and keeps one seam, so the report can never disagree with the command
    about what git answered.
    """
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            fetch = run_git(repo, "fetch", "origin")
            if fetch.returncode != 0:
                return _report(label, exit_push_failed,
                               _detail(fetch, "git fetch failed"),
                               "check the remote and the network, then re-run with --push")
            rebase = run_git(repo, "rebase", f"origin/{branch}")
            if rebase.returncode != 0:
                return classify_rebase_failure(
                    repo, rebase, label=label, exit_push_failed=exit_push_failed,
                    exit_rebase_conflict=exit_rebase_conflict,
                    exit_rebase_refused=exit_rebase_refused,
                    timed_out=rebase.returncode == GIT_TIMEOUT_RC,
                    messages=messages, run_git=run_git,
                )
        # An explicit refspec, so the name is read as a ref and never as an
        # option: ``refs/heads/<name>`` is what a plain branch argument resolves
        # to, so the push is the same operation with the leading-dash reading
        # taken away. ``branch`` has already passed BRANCH_NAME_RE in
        # :func:`current_branch` (or the caller's own check for an explicit
        # ``--branch``).
        push = run_git(repo, "push", "origin",
                       f"refs/heads/{branch}:refs/heads/{branch}")
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


def stopped_state_dir(repo: Path, run_git: GitRunner = _run_git) -> tuple[Path | None, bool]:
    """Locate a rebase this clone is actually stopped in.

    Returns ``(dir, indeterminate)``. ``dir`` is set only when the state
    directory carries positive evidence of being stopped (see
    :func:`stopped_state`). ``indeterminate`` says the question could not be
    answered: a probe could not run, or a state file could not be read.

    Probes go through ``git rev-parse --git-path``, which resolves the
    directories wherever the git dir lives (plain clone, worktree). This is the
    one probe loop the session writers have: ``claim.py`` calls it too, passing
    its own git seam, so the two cannot disagree about the clone's state.
    """
    indeterminate = False
    for name in REBASE_STATE_DIRS:
        probe = run_git(repo, "rev-parse", "--git-path", name)
        if probe.returncode != 0:
            indeterminate = True
            break
        state, answer = stopped_state(repo, Path(probe.stdout.strip()))
        if answer == "stopped":
            return state, indeterminate
        if answer == "unreadable":
            indeterminate = True
    return None, indeterminate


# The verdict names :func:`classify_rebase_failure` distinguishes. This module
# holds no wording of its own: every writer hands its ``messages`` table to the
# verdict, because the operator hears the command they ran (see the module
# docstring) and a second table of wording here was a second copy to keep in
# step. The keys are these names and each value is the tuple of lines that
# verdict prints, formatted from the slots the call fills in: {quoted}, {name},
# {seconds}, {abort}. ``tests/test_session_writer_docs.py`` pins the shipped
# table's keys against this tuple, so a verdict added here without a key fails.
REBASE_VERDICTS: tuple[str, ...] = (
    "state_unreadable", "abort_failed", "timeout_stopped",
    "conflict", "timeout", "refused",
)


def classify_rebase_failure(
    repo: Path, rebase: subprocess.CompletedProcess[str], *, label: str,
    exit_push_failed: int, exit_rebase_conflict: int, exit_rebase_refused: int,
    timed_out: bool = False, run_git: GitRunner = _run_git,
    messages: RebaseMessages,
) -> int:
    """Turn a failed ``git rebase origin/<branch>`` into the caller's exit code.

    The two cases are not the same bug. A rebase that started and stopped
    leaves the clone mid-rebase, so anything the caller runs next commits on
    top of a half-finished rebase: this helper aborts it and hands back the
    conflict code. A rebase git never started left nothing to clean up, so
    running an abort there would be noise: the refusal code's hint names
    committing or stashing.

    ``messages`` is required and has no default: it is the caller's own wording,
    keyed by the six names in :data:`REBASE_VERDICTS`. A verdict the table does
    not carry prints a generic line naming that verdict rather than raising, so
    an incomplete table cannot silence the report this function exists to make.

    ``run_git`` is the git seam every call this verdict makes goes through --
    the rebase-state probes and the abort alike. One seam, not two: a caller
    that drives its own git hands in one callable and the verdict cannot then
    disagree with it about the clone's state, and the abort the report quotes is
    the call that caller actually made.
    """
    quoted = _quote(rebase)
    wording = _DefensiveMessages(messages, quoted)
    slots = {"quoted": quoted, "name": repo.name, "seconds": str(GIT_TIMEOUT)}
    state, indeterminate = stopped_state_dir(repo, run_git)
    if state is None and indeterminate:
        # The probe could not answer, so this run claims no knowledge of the
        # clone's state: an unrunnable probe must not become "not stopped",
        # because a real conflict would then be reported as a refusal whose
        # hint cannot resolve it.
        return _report_lines(label, exit_rebase_refused,
                             wording["state_unreadable"], slots)
    if state is not None:
        abort = run_git(repo, "rebase", "--abort")
        if abort.returncode != 0:
            aborted = dict(slots)
            aborted["abort"] = _detail(abort, "git said")
            return _report_lines(label, exit_rebase_conflict,
                                 wording["abort_failed"], aborted)
        if timed_out:
            return _report_lines(label, exit_push_failed,
                                 wording["timeout_stopped"], slots)
        return _report_lines(label, exit_rebase_conflict, wording["conflict"], slots)
    if timed_out:
        return _report_lines(label, exit_push_failed, wording["timeout"], slots)
    return _report_lines(label, exit_rebase_refused, wording["refused"], slots)


class _DefensiveMessages:
    """A caller's ``messages`` table that cannot raise on a missing verdict.

    Indexing a plain dict is a ``KeyError`` on the failure path: the rebase has
    already failed and the abort has already run, so an exception there ends the
    run before the operator learns the clone's state. A missing (or empty) key
    answers one generic line that names the verdict and quotes git, which is
    honest about having no wording for it. The exit code is unaffected: it is the
    caller's contract, not its prose.
    """

    def __init__(self, messages: RebaseMessages,
                 quoted: str) -> None:
        self._messages = messages
        self._quoted = quoted

    def __getitem__(self, verdict: str) -> tuple[str, ...]:
        lines = self._messages.get(verdict)
        if lines:
            return lines
        return (f"rebase failed ({verdict}): {self._quoted}",)


def _quote(result: subprocess.CompletedProcess[str]) -> str:
    """git's own words for a failed call, sanitised, bounded, on up to three lines.

    Kept as its own slot value rather than interpolated into a template: these
    bytes can originate with the remote or a credential helper, so braces in
    them are literal text and must never be read as format placeholders.
    """
    return " ".join((_safe(result.stderr) or _safe(result.stdout)
                     or "no reason given").splitlines()[:3])


def _report_lines(label: str, code: int, lines: tuple[str, ...],
                  slots: dict[str, str]) -> int:
    """One verdict's report, its lines formatted from the caller's slots.

    The slots are filled by plain substitution, not ``str.format``: ``quoted``
    carries git's own text, which can come from the remote or a credential
    helper, and a payload reading as ``{0!r}`` or ``{quoted}`` would otherwise
    raise out of the push loop instead of printing the refusal. Only the three
    known slot names are ever looked up, and a line that names no slot prints
    verbatim.
    """
    return _report(label, code, *[_fill(line, slots) for line in lines])


def _fill(line: str, slots: dict[str, str]) -> str:
    """Substitute the known ``{name}`` slots in ``line``, leaving anything else alone."""
    for key, value in slots.items():
        line = line.replace("{" + key + "}", value)
    return line
