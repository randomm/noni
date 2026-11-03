"""Why a session writer's commit failed, in noni's own words.

The four session writers (register, claim, close, release) each write one file
under ``noni/sessions/`` and commit exactly that file. When git refuses the
commit the run stops with its file already on disk, and what it prints at that
moment is the only explanation an operator gets. This module owns that
explanation: :func:`commit_failure_cause` names which of four states the tree is
in, and :func:`commit_failed` assembles the one line the writer prints.

The states are asked of git itself rather than read out of git's prose, because
the prose is translated, reworded between versions, and -- since it is echoed to
a terminal -- worth sanitising. Each probe is a plumbing call through
:func:`noni._session_git.git`, so it is bounded, never signs, runs no hooks and
refuses the external transports a remote could name.

The line leads with a sentence in noni's words and quotes git after it. The
clause is what an operator acts on; git's own output follows as the evidence,
sanitised and bounded, rather than standing in place of the sentence.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ._session_git import GIT_TIMEOUT_RC, git, safe_text

# The four clauses. Each names a state an operator can act on, and the tests
# read these constants rather than copying them. The operator-facing docs
# paraphrase them: references/register.md's "Committing a session file" is the
# one place the four states are spelled out, and nothing else restates them.
NO_UPSTREAM = "this branch has no upstream configured"
UPSTREAM_GONE = "the upstream branch no longer exists on origin"
NOTHING_TO_COMMIT = ("the file already holds the bytes this run wrote, so git "
                     "found nothing to commit")
GIT_REFUSED = "git refused the commit"

_HEADS_PREFIX = "refs/heads/"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One bounded, hardened git call, through the writers' own helper.

    This is the module's single git seam: every probe goes through it, and a test
    that must drive one class of call (a transport call that cannot finish, a verb
    that always refuses) replaces this one name. The indirection is not a cycle --
    :func:`noni._session_git.stage_and_commit` reaches the classifier at the other
    end of this edge only when a commit is refused, and it imports it there rather
    than at module scope, so the two modules never hold a compile-time reference to
    each other. Making this a direct call to :func:`git` would be behaviourally
    identical and would take the seam away from every probe test in the suite, so
    it stays.
    """
    return git(repo, *args)


def _answered(result: subprocess.CompletedProcess[str] | None) -> bool:
    """Whether a probe answered. A call killed by the timeout answered nothing.

    None is the shape a helper uses for 'this probe could not run'; it is the
    same non-answer as the timeout sentinel and reads the same way everywhere.

    Every probe in this module asks the question through this predicate, and no
    caller may read a returncode -- a non-zero one especially -- before it has
    asked: ``GIT_TIMEOUT_RC`` is a non-zero exit that reports a kill, not a
    verdict, and a probe that reads it as 'no', 'does not resolve' or 'differs'
    turns a hang into a state nobody measured. A result whose ``returncode`` is
    ``None`` answers nothing either: that is the shape of a call that was never
    waited on, and reading it as a verdict would be reading a comparison against
    ``None`` (``None != 0`` is true, so an unwaited call would otherwise be
    reported as a refusal git never made).
    """
    return (result is not None and result.returncode is not None
            and result.returncode != GIT_TIMEOUT_RC)


def commit_failure_cause(repo: Path,
                         result: subprocess.CompletedProcess[str],
                         rel: str | None = None) -> str | None:
    """One noni-worded clause naming why this commit failed, or None when nothing answered.

    Two invariants, both about not inventing facts. A cause is a claim about a
    failure that happened, so it is returned only for a call that reports one;
    and a cause is returned only when a git call answered it, because when a
    probe could not run -- including a call killed by the timeout, which is the
    same non-answer -- :func:`commit_failed` prints git's words alone rather
    than naming a state on a guess.

    The order is the order of what an operator can act on: the state that stops
    a push comes before the state that merely made this run a no-op. The branch
    is read from this tree (``symbolic-ref --short HEAD``), not from the literal
    ``HEAD``, which an inherited ``GIT_DIR`` would resolve elsewhere.
    """
    if result.returncode is None or result.returncode == 0:
        # No failure happened, or none was ever measured: a cause is a claim
        # about a refusal this run observed, so neither shape gets one.
        return None
    branch = _git(repo, "symbolic-ref", "--short", "HEAD")
    if not _answered(branch):
        return None
    name = branch.stdout.strip()
    if branch.returncode != 0 or not name or name == "HEAD":
        # Not even a branch name, so there is no upstream to classify: leave
        # this one to git's own words rather than call a broken tree a missing
        # upstream.
        return None
    no_upstream, verdict = _upstream_ref(repo, name)
    if verdict == "probe-failed":
        # A probe died, so this tree has not been measured: naming a state here
        # would be a guess.
        return None
    if verdict == "none":
        # Nothing to compare against -- no remote, this clone as the remote, or a
        # remote that fetches nothing. Every one of those answers with an empty
        # ref (see :func:`_no_upstream`), so there is no upstream to have gone
        # and no bytes to have changed. That one clause is worth printing
        # whatever git quoted, because it is a fact about the tree's own config
        # and not a reading of the refusal. Everything else needs something to
        # have been said: a quiet failure on a tree whose every other probe
        # answered healthy is left unclassified rather than given the generic
        # clause.
        return NO_UPSTREAM
    if not _said(result):
        return None
    resolves = _resolves(repo, no_upstream)
    if resolves is None:
        return None
    if resolves.returncode != 0:
        return UPSTREAM_GONE
    abbreviated = _abbreviates_to_head(repo, no_upstream)
    if abbreviated is None:
        return None
    if abbreviated:
        return UPSTREAM_GONE
    matches = _index_matches_head(repo, rel)
    if matches is None:
        return None
    if matches:
        return NOTHING_TO_COMMIT
    return GIT_REFUSED


def _config_value(repo: Path, key: str) -> str | None:
    """One git config value: the value, ``""`` when unset, None when the probe died."""
    result = _git(repo, "config", "--get", key)
    if not _answered(result):
        return None
    return result.stdout.strip() if result.returncode == 0 else ""


def _configured_upstream(repo: Path, branch: str) -> tuple[str | None, str | None] | None:
    """The ``(remote, merge)`` a branch's own config lines name.

    ``(None, None)`` is git's own answer of 'this branch has no upstream'; None
    is a probe that could not run, which is not an answer either. Read from
    ``branch.<name>.remote`` and ``branch.<name>.merge`` rather than from
    ``<branch>@{upstream}`` for the states that can be read from config at all:
    a branch whose remote carries no such ref does not resolve, and that call
    answers with its own spelling and a non-zero exit, which reads as 'no
    upstream' whether or not that is the truth. The @{upstream} call is asked
    with ``--end-of-options`` so a branch named after one of git's option
    sentinels cannot turn this plumbing call into an argument-injection path.
    """
    remote = _config_value(repo, f"branch.{branch}.remote")
    if remote is None:
        return None
    if not remote:
        # No branch.remote line: the only upstream a branch can have then is one
        # git resolved itself, and the ref it resolved names the remote.
        named = _git(repo, "rev-parse", "--end-of-options",
                     f"{branch}@{{upstream}}")
        if not _answered(named):
            return None
        ref = named.stdout.strip()
        if named.returncode != 0 or "/" not in ref:
            # git's own 'no upstream configured', or a ref that names no remote.
            return None, None
        remote = ref.split("/", 1)[0]
    merge = _config_value(repo, f"branch.{branch}.merge")
    if merge is None:
        return None
    return remote, (merge if merge.startswith(_HEADS_PREFIX) else None)


def _no_upstream() -> tuple[str, str]:
    """The one answer for 'this branch has no upstream to compare against'.

    Every such state -- no remote named and none resolved, the remote being this
    clone itself, a remote that fetches nothing, or a fetch list that names no
    refspec for the remote -- leaves the same ``(ref, verdict)``: there is
    nothing here to compare HEAD against, and which of the four it is does not
    change what the operator does or what any later probe could measure. The
    docstring of :func:`_upstream_ref` lists them; this is the one place the
    answer itself is written.
    """
    return "", "none"


def _upstream_ref(repo: Path, branch: str) -> tuple[str, str]:
    """``(upstream ref, verdict)`` for ``branch``.

    The verdict is ``"none"`` for every state that leaves nothing to compare
    against, and ``"probe-failed"`` when a probe could not run: a config call
    that died is not evidence of a missing upstream. Each ``"none"`` exit is one
    of these, and each names something an operator can go and look at:

    - the branch names no remote at all, and git resolves no upstream ref for it
      either (a fresh state repository that was never pushed);
    - the remote it names is the literal ``.``, which is this clone itself, so
      no origin's branch could have gone;
    - the remote carries no fetch refspec, which leaves a ref the clone can
      never hold -- the state git's own wording cannot tell apart from a branch
      origin deleted.
    """
    configured = _configured_upstream(repo, branch)
    if configured is None:
        return "", "probe-failed"
    remote, merge = configured
    if remote is None:
        # No branch.remote line and no upstream ref to read one from: this is
        # git's own 'no upstream configured for branch' state, which is what a
        # fresh state repository that was never pushed looks like.
        return _no_upstream()
    if not remote or remote == ".":
        return _no_upstream()
    if merge is not None:
        return f"{remote}/{merge[len(_HEADS_PREFIX):]}", ""
    # No branch.merge line: the upstream is whatever origin's fetch refspec
    # could have fetched under the branch's own name.
    refspec_lines = _git(repo, "config", "--get-regexp", r"^remote\..*\.fetch$")
    if not _answered(refspec_lines):
        return "", "probe-failed"
    if refspec_lines.returncode != 0:
        return _no_upstream()
    wanted = f"remote.{remote}.fetch"
    for line in refspec_lines.stdout.splitlines():
        if line.split(maxsplit=1)[0] == wanted:
            return f"{remote}/{branch}", ""
    return _no_upstream()


def _resolves(repo: Path, ref: str) -> subprocess.CompletedProcess[str] | None:
    """The ``--verify --quiet`` verdict for ``ref``, or None when the probe died."""
    result = _git(repo, "rev-parse", "--verify", "--quiet", ref)
    return result if _answered(result) else None


def _abbreviates_to_head(repo: Path, upstream: str) -> bool | None:
    """Whether git abbreviates ``upstream`` back to the literal ``HEAD``; None if unasked.

    That is how git marks an upstream whose remote-tracking ref is gone: the
    configured name still reads back as a string, but no object stands behind
    it, and a check on the name alone would read ``origin/main`` and call a
    deleted branch healthy. Asking for the unambiguous form is the question git
    itself answers.
    """
    if not upstream or upstream == "HEAD":
        return True
    result = _git(repo, "rev-parse", "--no-abbrev", "--verify", "--quiet",
                  f"{upstream}^{{commit}}")
    if not _answered(result):
        return None
    return result.returncode != 0


def _index_matches_head(repo: Path, rel: str | None) -> bool | None:
    """Whether the index carries no change against HEAD; None when a probe died.

    Asked of the index as well as the work tree, so a file the writer wrote and
    staged (its reset and add steps ran) answers honestly: the bytes are in the
    index, and if they equal HEAD's there is nothing to commit.

    Both probes carry the one pathspec this writer owns (``rel``, the name
    :func:`noni._session_git.writer_name` produces), as every other step of
    ``stage_and_commit`` does: the question is whether *this* file's bytes
    changed, and a whole-tree probe would re-stat the entire work tree to answer
    a question about one path -- and would report somebody else's dirty file as
    a reason this run's own write had something to commit. ``rel=None`` is the
    whole-tree question, for a caller that named no path. The staged probe is
    against the commit ``--only`` will be judged against -- ``HEAD``, which is
    the commit git itself refuses against, and not against the remote-tracking
    ref: on the common path the writer's own register commit sits between
    ``HEAD`` and ``origin/<branch>", and a diff against origin would report
    that committed change as work still to be committed.
    """
    pathspec = rel if rel else "."
    staged = _git(repo, "diff", "--cached", "--quiet", "HEAD", "--", pathspec)
    unstaged = _git(repo, "diff", "--quiet", "--", pathspec)
    if not _answered(staged) or not _answered(unstaged):
        return None
    if staged.returncode != 0 or unstaged.returncode != 0:
        return False
    # Untracked files are no reason to call this run's own write a change: the
    # writer commits one path and untracked siblings are not part of it.
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard",
                     "--", pathspec)
    if not _answered(untracked):
        return None
    return untracked.stdout.strip() == ""


def commit_failed(repo: Path, result: subprocess.CompletedProcess[str],
                  rel: str | None = None) -> str:
    """The one line a commit failure reports: the cause in noni's words, then git's.

    The caller adds its own headline (which path it wrote and what to do about
    it), so this stays the cause half of the message. git's own output is
    sanitised, bounded (see :func:`noni._session_git.safe_text`) and flattened to
    one line, and it follows the cause instead of being the whole of it: that
    text is not this process's words -- it can carry remote-side and
    credential-helper output -- and printed on its own it reads as a raw
    ``git status`` dump.
    """
    cause = commit_failure_cause(repo, result, rel)
    said = _said(result)
    if cause is None:
        return f"git could not commit: {said or 'no reason given'}"
    return f"git could not commit -- {cause}" + (f"; git said: {said}" if said else "")


def _said(result: subprocess.CompletedProcess[str]) -> str:
    """What git said about a failed call, sanitised, bounded, on one line.

    Flattened deliberately: these bytes are the tail of one report line the
    writer prints, and a multi-line echo reads as a raw status dump rather than
    as a quotation inside a sentence.
    """
    said = _safe(result.stderr) or _safe(result.stdout) or ""
    return " ".join(said.split())


def _safe(text: str | None) -> str:
    cleaned = safe_text((text or "").strip())
    return "" if cleaned.strip() == "" else cleaned
