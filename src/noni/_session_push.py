"""The push loop the session writers share: fetch, rebase, push, at most 3 attempts.

:func:`fetch_rebase_push` is what ``--push`` runs after a writer has committed its
session file: the losing pusher ends rebased-and-pushed, so both writers' commits
land and the census is what flags the disagreement. The verdicts are not the same
bug and are not reported the same way: a rebase that started and stopped leaves
the clone mid-rebase (anything run next would commit on top of a half-finished
rebase), so it is aborted and reported as a conflict; a rebase git never started
left nothing to clean up, so the refusal's hint names committing or stashing.

The module is mechanics only. It owns no exit-code contract and no wording of its
own beyond the defaults below: the caller hands in its ``label`` and its four
codes, and may hand in ``messages``, ``probe`` and ``abort`` to keep its own
phrasing and drive its own git, so an operator hears the command they ran and the
git calls are the ones that command actually makes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
    directory carries positive evidence of being stopped (see
    :func:`stopped_state`). ``indeterminate`` says the question could not be
    answered: a probe could not run, or a state file could not be read.

    Probes go through ``git rev-parse --git-path``, which resolves the
    directories wherever the git dir lives (plain clone, worktree).
    """
    indeterminate = False
    for name in REBASE_STATE_DIRS:
        probe = git(repo, "rev-parse", "--git-path", name)
        if probe.returncode != 0:
            indeterminate = True
            break
        state, answer = stopped_state(repo, Path(probe.stdout.strip()))
        if answer == "stopped":
            return state, indeterminate
        if answer == "unreadable":
            indeterminate = True
    return None, indeterminate


# The default wording for each rebase verdict, in this helper's own voice. A
# caller hands its own ``messages`` mapping to keep its own phrasing (claim.py
# speaks of the claim, close.py of the close); the keys are the verdict names
# and each value is the tuple of lines that verdict prints, formatted from the
# slots the call fills in: {quoted}, {name}, {seconds}, {abort}.
_REBASE_MESSAGES: dict[str, tuple[str, ...]] = {
    "state_unreadable": (
        "rebase failed and its state cannot be read, so no abort was attempted: "
        "{quoted}",
        "run 'git status' and 'git rebase --abort' by hand in {name}, then "
        "re-run this command",
    ),
    "abort_failed": (
        "rebase conflict and git rebase --abort failed: {abort}",
        "git said: {quoted}",
        "the clone is still mid-rebase in {name}; run git rebase --abort by hand",
    ),
    "timeout_stopped": (
        "rebase timed out after {seconds}s and was stopped in a conflict, so it "
        "was aborted: {quoted}",
    ),
    "conflict": (
        "rebase conflict: someone else changed the same session file, so the "
        "rebase stopped: {quoted}",
        "fix: fetch origin, resolve the conflict in the session file, then "
        "re-run; the commit this run made is intact on {name}",
    ),
    "timeout": ("rebase timed out after {seconds}s: {quoted}",),
    "refused": (
        "rebase refused (it never started): {quoted}",
        "fix: commit or stash the uncommitted changes in this clone, then re-run; "
        "this run started no rebase, so the commit it made is intact",
    ),
}


def _classify_rebase_failure(
    repo: Path, rebase: subprocess.CompletedProcess[str], *, label: str,
    exit_push_failed: int, exit_rebase_conflict: int, exit_rebase_refused: int,
    timed_out: bool = False, messages: dict[str, tuple[str, ...]] | None = None,
    probe=None, abort=None,
) -> int:
    """Turn a failed ``git rebase origin/<branch>`` into the caller's exit code.

    The two cases are not the same bug. A rebase that started and stopped
    leaves the clone mid-rebase, so anything the caller runs next commits on
    top of a half-finished rebase: this helper aborts it and hands back the
    conflict code. A rebase git never started left nothing to clean up, so
    running an abort there would be noise: the refusal code's hint names
    committing or stashing.

    ``probe`` is the function that locates a stopped rebase
    (``(repo) -> (dir, indeterminate)``). The default is this module's own,
    which probes through the hardened helper; a caller that drives its own push
    loop hands the probe it uses, so its scripted or hardened git seam is the
    one the verdict asks, and the two cannot disagree about the clone's state.
    ``abort`` is handed the same reason: the abort is a git call too, and a
    caller that drives its own git must be the one that runs it, so what this
    reports is the outcome of the call the caller actually made.
    """
    quoted = " ".join((_safe(rebase.stderr) or _safe(rebase.stdout)
                       or "no reason given").splitlines()[:3])
    wording = messages or _REBASE_MESSAGES
    slots = {"quoted": quoted, "name": repo.name, "seconds": str(GIT_TIMEOUT)}
    state, indeterminate = (probe or _stopped_state_dir)(repo)
    if state is None and indeterminate:
        # The probe could not answer, so this run claims no knowledge of the
        # clone's state: an unrunnable probe must not become "not stopped",
        # because a real conflict would then be reported as a refusal whose
        # hint cannot resolve it.
        return _report_lines(label, exit_rebase_refused,
                             wording["state_unreadable"], slots)
    if state is not None:
        abort = (abort or _abort_rebase)(repo)
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


def _abort_rebase(repo: Path) -> subprocess.CompletedProcess[str]:
    """The default abort: one hardened 'git rebase --abort' in this clone."""
    return git(repo, "rebase", "--abort")


def _report_lines(label: str, code: int, lines: tuple[str, ...],
                  slots: dict[str, str]) -> int:
    """One verdict's report, its lines formatted from the caller's slots."""
    return _report(label, code, *[line.format(**slots) for line in lines])
