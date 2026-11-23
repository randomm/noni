"""The containment precondition every harness git runner asserts (issue #220).

Moved out of ``harness_git.py`` for the source-file size rule (AGENTS.md: every
tracked source file at or under 500 lines), along the seam the issue itself drew:
this module owns the one question -- *is this directory a repository of its own?*
-- and nothing else. The runners in ``harness_git`` and ``quickstart_topology`` ask
it; they do not answer it.

Why the question exists. ``git -C <dir> config ...`` on a directory that is not a
repository does not fail. Git walks up and writes into the nearest enclosing one,
so the leak needed only a plain directory under the checkout -- and a dev run keeps
its scratch there (AGENTS.md: one ignored folder per issue, ``tmp/issue-N/``). The
harness's ``-c user.name=...`` prefix hid it: the config call exited 0 and printed
nothing, whichever tree it answered for. Every commit made in the checkout and its
worktrees afterwards was authored by the fixture identity.

The companion half of the containment is environmental and lives in
:func:`harness_runners.subprocess_env`: ``GIT_CEILING_DIRECTORIES`` stops git
discovering a repository by walking up from the *current directory*, and does
nothing at all for ``git -C <path>``. Neither one is optional.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

# The variables a top-level probe must carry from the launcher's env: the git-location
# overrides that would make ``rev-parse --show-toplevel`` answer for some tree other
# than the target, and the config pins that decide whether git reads a host gitconfig
# while answering. Everything else (PATH, HOME, the identity) is irrelevant to the
# question, so the probe keeps the harness's own PATH and never inherits an operator's
# HOME by accident.
_TOPLEVEL_PROBE_ENV_VARS = frozenset(
    {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
     "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG",
     "GIT_CONFIG_NOSYSTEM", "GIT_CEILING_DIRECTORIES"})


def _looks_bare(path: Path) -> bool:
    """Whether git would call ``path`` a bare repository, read from the file.

    A probe run *without* being told the tree is bare cannot ask the question: git
    answers an empty ``init --bare`` directory with "not a git repository", because
    the only thing it will say there is "must be run in a work tree". So a caller that
    did not pass ``bare=`` gets the answer from the file ``git init --bare`` itself
    wrote, and the guard stops inventing failures for fixtures it created correctly.

    Read, not asked: by the time this matters the tree may hold nothing but its own
    config, which is precisely when an interrogating subprocess has nothing to say. The
    key is only ever true in the form ``git init --bare`` writes it, so scratch state
    cannot claim its way past the guard by holding a lookalike file.
    """
    for config in (path / "config", path / ".git" / "config"):
        try:
            body = config.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "bare = true" in body or "bare=true" in body:
            return True
    return False


def assert_own_repo_top(path: Path, env: Mapping[str, str] | None = None,
                        bare: bool | None = None,
                        sub_tree: bool = False) -> Path:
    """Refuse unless ``path`` is the top level of its *own* repository.

    The question is asked of git itself rather than answered from the tree -- a
    directory can look like a repository and belong to one above it -- and the answer
    is compared to the target resolved on both sides: pytest's ``tmp_path`` can be a
    symlinked path, and a byte-for-byte comparison would then refuse every legitimate
    repo instead of only the leaking one.

    ``env`` is the environment the runner is about to launch git with, so the probe
    sees the same config the call will: a runner whose child env replaces ``HOME`` (or
    pins ``GIT_CONFIG_*``) has its dubious-ownership refusal read here rather than
    three frames down, next to the git words that caused it.

    ``bare`` is for a repository with no working tree at all -- a fixture's bare
    origin. ``--show-toplevel`` refuses such a repository outright ("must be run in a
    work tree"), so the bare form is asked whether it is its own bare repository, which
    a fixture's origin answers and a plain directory inside somebody else's repository
    does not: the same containment, phrased for a tree with no working tree to be the
    top of.

    ``sub_tree`` is for a tree the harness clones into another repository -- the
    quickstart's private state clone inside the reader's project, the one fixture with
    a repository legitimately nested in a repository. The question then cannot be "is
    this the top level" (it is not, and cannot be) but "does this path own its own
    ``.git``", asked of the filesystem rather than of the parent's git.
    """
    if sub_tree:
        return _assert_own_git_dir(path)
    if bare is None:
        # Not told which shape to expect, so the tree is asked itself: a caller that
        # knows passes ``bare=`` and outranks this.
        bare = _looks_bare(path)
    resolved = path.resolve()
    shown = _toplevel_probe(path, env, bare)
    if shown.returncode != 0:
        raise RuntimeError(
            f"git {shown.stderr.strip()}: {path} is not a repository the harness "
            "may write into, so a git call on it would reach an enclosing "
            "repository (issue #220)"
        )
    answer = shown.stdout.strip()
    if bare:
        return _refuse_unless_bare(path, answer, resolved)
    return _refuse_enclosing_repository(path, answer, resolved)


def _toplevel_probe(path: Path, env: Mapping[str, str] | None,
                    bare: bool) -> subprocess.CompletedProcess[str]:
    """Ask git the containment question, under the launcher's own config pins.

    The probe runs with a filtered environment rather than the launcher's whole one:
    the git-location variables and the config pins are what could change the answer,
    and a probe that inherited an operator's ``HOME`` would be asking about a different
    user's repository than the call it guards.

    ``safe.directory`` is set to the target itself because the probe's env may carry no
    ``HOME`` at all, and git's ownership check reads the operator's safe-directory list
    out of the config it would otherwise find there. The target is the directory under
    test, so naming it is not a widening: it is the one path the call was going to act
    on anyway.
    """
    probe = {k: v for k, v in (env if env is not None else os.environ).items()
             if k in _TOPLEVEL_PROBE_ENV_VARS}
    # An explicit null config still runs git's ownership check, so an otherwise
    # environment-less probe cannot lose it by dropping HOME.
    probe.setdefault("GIT_CONFIG_NOSYSTEM", "1")
    probe.setdefault("GIT_CONFIG_GLOBAL", os.devnull)
    question = "--is-bare-repository" if bare else "--show-toplevel"
    return subprocess.run(
        ["git", "-c", "safe.directory=" + str(path), "-C", str(path),
         "rev-parse", question],
        capture_output=True, text=True, env=probe, timeout=60)


def _refuse_unless_bare(path: Path, answer: str, resolved: Path) -> Path:
    """The bare arm: a fixture's origin is only ever created by ``init --bare``.

    Anything git answers other than ``true`` means the tree is somebody else's
    repository (or none), and a config write into it is the leak.
    """
    if answer != "true":
        raise RuntimeError(
            f"git says {path} is not a bare repository (it answered {answer!r}); "
            "a fixture's origin is created by ``init --bare`` alone, so anything "
            "else means this tree is somebody else's repository (issue #220)"
        )
    return resolved


def _refuse_enclosing_repository(path: Path, answer: str, resolved: Path) -> Path:
    """The working-tree arm: git's answer for the target must be the target."""
    toplevel = Path(answer).resolve()
    if toplevel != resolved:
        raise RuntimeError(
            f"git target {path} resolves to the enclosing repository {toplevel}; "
            "the harness writes git state only into a throwaway repo of its own "
            "(issue #220)"
        )
    return resolved


def _assert_own_git_dir(path: Path) -> Path:
    """Refuse unless ``path`` is a directory that owns its own ``.git``.

    The check is a stat rather than a git call because the parent's git is exactly the
    answer that cannot be trusted here: it reports the parent's top level. A directory
    with no ``.git`` of its own is the leak, so the refusal says that plainly.
    """
    resolved = path.resolve()
    if not (resolved / ".git").exists():
        raise RuntimeError(
            f"{path} holds no .git of its own, so a git call on it would be answered "
            "by an enclosing repository (issue #220)"
        )
    return resolved


def require_own_repo_top(repo: Path, args: tuple[str, ...],
                         env: Mapping[str, str] | None = None,
                         bare: bool = False, *,
                         creating: bool | None = None) -> None:
    """The precondition for one runner's argument list, creation verbs excepted.

    One place decides the exceptions, so ``_git`` and ``_git_e2`` cannot drift on them.
    Three states make a call a creation rather than a write into something: the verb is
    ``init`` (a creation by name, which the initialiser asserts on afterwards); the
    target already holds a bare repository's config, which no working tree can be the
    top level of and which the work-tree probe can only answer "not a repository"
    about; or the caller said so, which is how a fixture that clones a destination
    passes -- the verdict on that one comes after the clone ran, and a clone that
    created nothing is refused then. Every other verb -- above all ``config``, the one
    that leaked -- is refused before git is asked. An argument list that starts with an
    option rather than a verb is checked anyway: failing closed is the cheaper mistake
    than letting a ``-c``-prefixed config call through.
    """
    if not args:
        return
    if creating is True or args[0] == "init" or _looks_bare(repo):
        # ``init`` is the exception by name -- the initialiser asserts the result
        # itself, including the bare form an empty origin is built by (see
        # :func:`_check_created` for why the after-the-fact probe needs to be told
        # which question to ask). ``creating`` is the same exemption for a runner that
        # was told by its caller that this call makes the target a repository, which
        # is how a fixture that clones a destination passes: the verdict on that one
        # comes after the clone ran, and a clone that created nothing is refused then.
        return
    assert_own_repo_top(repo, env, bare)


