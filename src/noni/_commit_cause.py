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

The wording is noni's own: an operator who runs a writer and gets exit 3 reads a
sentence, not git's status block, and each clause names the state that needs
fixing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from noni import _session_git

# subprocess.run(timeout=) reports a killed call with this code (the
# TimeoutExpired sentinel). A probe that came back with it answered nothing, and
# reading 'changed' is the honest fallback (see _index_matches_head).
GIT_TIMEOUT_RC = 124

# The four clauses. Each names a state an operator can act on, and the test
# suite reads these constants rather than copying them, so rewording a clause is
# a change the tests see.
NO_UPSTREAM = "this branch has no upstream configured"
UPSTREAM_GONE = "the upstream branch no longer exists on origin"
NOTHING_TO_COMMIT = ("the file already holds the bytes this run wrote, so git "
                     "found nothing to commit")
GIT_REFUSED = "git refused the commit"

_HEADS_PREFIX = "refs/heads/"
# The module the git calls go through, named once so the test that proves every
# probe is bounded reaches it the same way the writers reach their own git calls.
def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One bounded, hardened git call, through the writers' own helper.

    Resolved at call time rather than bound at import: this module and
    ``_session_git`` refer to each other (the commit primitive asks this one to
    name a failure, and a failure's cause is asked of git through that
    primitive), so a module-level binding would be taken while the other side
    is still running its own import.
    """
    return _session_git.git(repo, *args)


def commit_failure_cause(repo: Path,
                         result: subprocess.CompletedProcess[str]) -> str | None:
    """One noni-worded clause naming why this commit failed, or None when nothing answered.

    A cause is a claim about a failure that happened, so it is returned only for
    a call that reports one: ``result`` is the commit attempt this message
    accompanies, and an accepted commit has no cause to name (a caller that
    asked anyway gets None, which :func:`commit_failed` prints as git's words
    alone rather than as an invented fault).

    The order is the order of what an operator can act on: the state that stops
    a push is named before the state that merely made this run a no-op, so a
    tree that is both -- never pushed, and carrying no change -- is reported as
    the one that needs a fix:

    - the branch names no remote, a remote with no fetch refspec, or the
      literal ``.`` (this clone itself): there is no upstream to compare
      against, which is what a fresh state repository that was never pushed
      looks like;
    - the upstream's remote-tracking ref does not resolve, or git abbreviates it
      back to the literal ``HEAD``: that is git's "upstream is gone", the origin
      having deleted the branch;
    - the index matches HEAD: there was nothing to commit, which is what a
      release or close whose row or status already matches HEAD looks like;
    - anything else is git's own fault, and its words follow the clause.

    The branch is read from this tree (``symbolic-ref --short HEAD``), not from
    the literal ``HEAD``, which an inherited ``GIT_DIR`` would resolve
    elsewhere. A cause is returned only when a git call answered it; when a
    probe could not run this returns None and :func:`commit_failed` prints git's
    words alone, because guessing at the state and printing it as fact is worse
    than naming the fault and quoting what git said.
    """
    if result is None or result.returncode == 0:
        return None
    said = _said(result)
    branch = _git(repo, "symbolic-ref", "--short", "HEAD")
    name = branch.stdout.strip()
    if branch.returncode != 0 or not name or name == "HEAD":
        # Not even a branch name, so there is no upstream to classify: leave
        # this one to git's own words rather than call a broken tree a missing
        # upstream.
        return None
    upstream, missing = _upstream_ref(repo, name)
    if missing:
        return NO_UPSTREAM
    if not _resolves(repo, upstream) or _abbreviates_to_head(repo, upstream):
        return UPSTREAM_GONE
    if _index_matches_head(repo):
        return NOTHING_TO_COMMIT
    return GIT_REFUSED if said else None


def _upstream_ref(repo: Path, branch: str) -> tuple[str, bool]:
    """``(upstream ref, no upstream)`` for ``branch``; the second is True when none.

    Three states answer 'none': the branch names no remote; the remote it names
    is the literal ``.``, which is this clone itself, so no origin's branch
    could have gone; and the remote carries no fetch refspec, which leaves a ref
    the clone can never hold -- the state git's own wording cannot tell apart
    from a branch origin deleted.

    The branch's remote is read from its own config lines
    (``branch.<name>.remote`` and ``branch.<name>.merge``) rather than from
    ``<branch>@{upstream}``: a branch whose remote carries no such ref does not
    resolve, and that call answers with its own spelling and a non-zero exit,
    which reads as 'no upstream' whether or not that is the truth.
    """
    remote = _config_value(repo, f"branch.{branch}.remote")
    if not remote:
        named = _git(repo, "rev-parse", "--symbolic-full-name",
                     f"{branch}@{{upstream}}")
        ref = named.stdout.strip()
        if named.returncode != 0 or "/" not in ref:
            return "", True
        remote = ref.split("/", 1)[0]
    if not remote or remote == ".":
        return "", True
    merge = _config_value(repo, f"branch.{branch}.merge")
    if merge.startswith(_HEADS_PREFIX):
        return f"{remote}/{merge[len(_HEADS_PREFIX):]}", False
    configured = _git(repo, "config", "--get-regexp", r"^remote\..*\.fetch$")
    if configured.returncode != 0:
        return "", True
    wanted = f"remote.{remote}.fetch"
    for line in configured.stdout.splitlines():
        if line.split(maxsplit=1)[0] == wanted:
            return f"{remote}/{branch}", False
    return "", True


def _config_value(repo: Path, key: str) -> str:
    """One git config value, '' when unset or unreadable.

    Read without ``--global``: the writer's hardened environment already
    neutralises the host's config, and a tree's own config is the state that
    decides where this clone's commits go.
    """
    result = _git(repo, "config", "--get", key)
    return result.stdout.strip() if result.returncode == 0 else ""


def _resolves(repo: Path, ref: str) -> bool:
    """Whether ``ref`` names an object in this clone (``--verify --quiet``)."""
    return _git(repo, "rev-parse", "--verify", "--quiet", ref).returncode == 0


def _abbreviates_to_head(repo: Path, upstream: str) -> bool:
    """Whether git abbreviates ``upstream`` back to the literal ``HEAD``.

    That is how git marks an upstream whose remote-tracking ref is gone: the
    configured name still reads back as a string, but no object stands behind
    it, and a check on the name alone would read ``origin/main`` and call a
    deleted branch healthy. Asking for the unambiguous form is the question git
    itself answers.
    """
    if not upstream or upstream == "HEAD":
        return True
    return _git(repo, "rev-parse", "--no-abbrev", "--verify", "--quiet",
                f"{upstream}^{{commit}}").returncode != 0


def _index_matches_head(repo: Path) -> bool:
    """Whether the index carries no change against HEAD: git's 'nothing to commit'.

    Asked of the index as well as the work tree, so a file the writer wrote and
    staged (its reset and add steps ran) answers honestly: the bytes are in the
    index, and if they equal HEAD's there is nothing to commit. A probe killed
    by the timeout is not an answer, so it reports 'changed'.
    """
    staged = _git(repo, "diff", "--cached", "--quiet", "HEAD", "--")
    unstaged = _git(repo, "diff", "--quiet", "--")
    if staged.returncode == GIT_TIMEOUT_RC or unstaged.returncode == GIT_TIMEOUT_RC:
        return False
    return staged.returncode == 0 and unstaged.returncode == 0


def commit_failed(repo: Path, result: subprocess.CompletedProcess[str]) -> str:
    """The one line a commit failure reports: the cause in noni's words, then git's.

    The caller adds its own headline (which path it wrote and what to do about
    it), so this stays the cause half of the message. git's own output is
    sanitised, bounded (see :func:`noni._session_git.safe_text`) and flattened to
    one line, and it follows the cause instead of being the whole of it: that
    text is not this process's words -- it can carry remote-side and
    credential-helper output -- and printed on its own it reads as a raw
    ``git status`` dump.
    """
    cause = commit_failure_cause(repo, result)
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


def _safe(text: str) -> str:
    cleaned = _session_git.safe_text((text or "").strip())
    return "" if cleaned.strip() == "" else cleaned
