"""Git fixture helpers for the test harness.

Moved out of ``_harness.py`` for the file-size ratchet (issue #52) and
re-exported from there, so every ``from _harness import`` keeps resolving.
A helper module: never named ``test_*``.

"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from harness_paths import CLAIM
from harness_sources import _script_ast, _script_constant


def _git_e2(
    repo: Path, *args: str, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run git in a repo with a deterministic identity and no GPG signing.

    ``env`` is for a call that must not inherit the ambient git identity. A
    supplied mapping *replaces* the process environment rather than augmenting
    it, so callers merge it into ``os.environ`` themselves (see
    ``advance_origin_with_claim``): a partial dict would drop PATH or HOME and
    fail as a confusing git-not-found or dubious-ownership error."""
    cmd = [
        "git", "-C", str(repo),
        "-c", "user.name=Replay",
        "-c", "user.email=replay@fixture.invalid",
        "-c", "commit.gpgsign=false",
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git with the deterministic harness identity (Replay), checking.

    The shared form the test modules' private ``_git`` helpers used:
    ``-c user.name/user.email/commit.gpgsign=false`` and ``check=True``.
    Returns the CompletedProcess so callers can read stdout (e.g. a
    ``git status --porcelain`` round-trip). ``_git_e2`` (no identity pin, no
    check) stays for the push-retry path, which drives its own git config."""
    cmd = [
        "git", "-C", str(repo),
        "-c", "user.name=Replay",
        "-c", "user.email=replay@fixture.invalid",
        "-c", "commit.gpgsign=false",
        *args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def _init_repo(path: Path) -> Path:
    """Create and initialise a throwaway git repo at ``path``."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "commit", "-q", "--allow-empty", "-m", "initial")
    return path




# --- The git-location decoys ---------------------------------------------------
#
# Every writer resolves its repository from ``--repo`` and passes that path to
# ``git -C``. Four variables in the caller's environment override that answer
# before the path is ever consulted: GIT_DIR and GIT_COMMON_DIR name a different
# repository directory, GIT_WORK_TREE a different working tree, and GIT_INDEX_FILE
# a different index to stage and commit through. A writer that hands its child the
# ambient environment therefore commits somewhere other than the state root while
# still reporting success for the tree it was pointed at.
#
# The two helpers below build those two states, and ``assert_writers_clear_git_env``
# is the one assertion every committing writer is run against: the record lands
# committed in the state root, the decoy repository and the decoy index keep the
# bytes they had before, and the state root reports a clean ``git status
# --porcelain`` (the commit is real, not merely written to the file).


def decoy_git_repo(tmp_path: Path, name: str = "decoy-git") -> tuple[Path, Path]:
    """A throwaway git repo to point ``GIT_DIR`` / ``GIT_WORK_TREE`` at.

    It carries one committed file of its own, so a writer that resolved the
    repository from the environment would have a real tree to commit into: a
    decoy git could not have worked in proves nothing about where the commit went.
    Returns ``(work_tree, git_dir)``.
    """
    repo = tmp_path / name
    _init_repo(repo)
    (repo / "decoy-tracked.txt").write_text("decoy content, never touched by a writer\n",
                                            encoding="utf-8")
    _git(repo, "add", "decoy-tracked.txt")
    _git(repo, "commit", "-q", "-m", "decoy tracked file")
    return repo, repo / ".git"


def decoy_git_index(repo: Path, tmp_path: Path,
                    name: str = "decoy-index") -> Path:
    """An index file for ``repo`` to point ``GIT_INDEX_FILE`` at, as a copy.

    The copy is of the repository's own committed index, so the decoy starts out
    agreeing with HEAD: a writer that staged and committed through it still
    reaches HEAD (git commits the index it was given), which is why this decoy
    needs the porcelain and before/after assertions rather than an exit code
    alone. Returns the decoy index path.
    """
    index = Path(_git_porcelain_git_dir(repo)) / "index"
    if not index.is_file():
        _git(repo, "update-index", "--refresh", "-q")
    decoy = tmp_path / name
    decoy.write_bytes(index.read_bytes())
    return decoy


def _git_porcelain_git_dir(repo: Path) -> str:
    """The git directory ``repo`` resolves to, as git itself answers it.

    ``--absolute-git-dir`` rather than a hand-built ``<repo>/.git``: a linked
    worktree keeps its index elsewhere, and the decoy has to copy the index the
    writer would have used.
    """
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"],
        capture_output=True, text=True, check=True).stdout.strip()


def assert_writers_clear_git_env(
    proc: subprocess.CompletedProcess[str], root: Path, rel: str,
    decoy_repo: Path | None, decoy_before: dict[str, bytes],
    decoy_index: Path | None, index_before: bytes | None,
    expect: str,
) -> None:
    """The four assertions every writer's decoy-git run has to satisfy.

    ``proc`` is the writer's completed run, ``root``/``rel`` the state root and
    the path its record must have been committed under, ``decoy_repo``/
    ``decoy_before`` the decoy tree and its file snapshot (``None``/``{}`` when
    the case set no ``GIT_DIR``), ``decoy_index``/``index_before`` the decoy
    index and its bytes (``None`` when the case set no ``GIT_INDEX_FILE``), and
    ``expect`` a fragment of the record's committed bytes that proves which
    writer ran.
    """
    assert proc.returncode == 0, f"writer failed under the decoy env: {proc.stderr}"
    shown = _git_show(root, f"HEAD:{rel}")
    assert shown.returncode == 0, (
        f"the record is not committed in the state root "
        f"(git status --porcelain: {_git_porcelain(root)!r}): {shown.stderr}"
    )
    assert expect in shown.stdout, f"the committed record is not this writer's: {shown.stdout!r}"
    assert _git_porcelain(root) == "", (
        "the run left the state root dirty, so its record was written and never "
        f"committed: {_git_porcelain(root)!r}"
    )
    if decoy_repo is not None:
        after = _tree_bytes(decoy_repo)
        assert after == decoy_before, (
            f"the run wrote the decoy repository named by GIT_DIR/GIT_WORK_TREE: "
            f"{sorted(set(after) ^ set(decoy_before)) or 'content changed'}"
        )
    if decoy_index is not None:
        assert decoy_index.read_bytes() == index_before, (
            "the run staged or committed through the decoy index named by "
            "GIT_INDEX_FILE, so the index it used was not the state root's own"
        )


def _tree_bytes(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` as relative path -> bytes (the snapshot form)."""
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _git_show(repo: Path, rev: str) -> subprocess.CompletedProcess[str]:
    """Read a committed path back without the harness identity pin.

    ``rev`` is a ``<revision>:<path>`` pair. ``cat-file`` rather than ``show``:
    show runs the tree's clean/smudge filters over the blob it prints and can
    hand back an empty string for a file that is plainly there, which would make
    "not committed" indistinguishable from "filtered to nothing". The process is
    handed back so the caller decides whether a non-zero exit (no such path at
    that revision) is the finding; the harness's own ``_git`` checks instead.
    """
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-p", rev],
                          capture_output=True, text=True, check=False)


def _git_porcelain(repo: Path) -> str:
    """The state root's own ``git status --porcelain``, as one string."""
    return subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                          capture_output=True, text=True, check=True).stdout


def _commit_file(repo: Path, rel: str, content: str) -> None:
    """Write ``content`` to ``repo/rel`` and commit it under the harness
    identity (creating parent dirs as needed)."""
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "--allow-empty", "-m", f"add {rel}")


def _git_ok(
    repo: Path, *args: str, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    proc = _git_e2(repo, *args, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"git {args} failed: {proc.stderr.strip()}")
    return proc


def _git_env_with_identity() -> dict[str, str]:
    """An env that pins a deterministic git identity for subprocesses.

    claim.py commits under the caller's configured identity (it no longer
    hardcodes one), so the test harness pins one here: GIT_CONFIG_GLOBAL
    points at /dev/null so the host's ~/.gitconfig cannot leak in, and the
    GIT_AUTHOR_*/GIT_COMMITTER_* env vars supply the identity (signing is
    handled by the scripts' own commit.gpgsign=false)."""
    return {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_AUTHOR_NAME": "Replay",
        "GIT_AUTHOR_EMAIL": "replay@fixture.invalid",
        "GIT_COMMITTER_NAME": "Replay",
        "GIT_COMMITTER_EMAIL": "replay@fixture.invalid",
    }


def git_pin_date(repo: Path, iso_utc: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command with identity and commit dates pinned.

    ``iso_utc`` is the fixed timestamp; GIT_CONFIG_GLOBAL/SYSTEM point at
    /dev/null to block host gitconfig."""
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    env = dict(os.environ)
    env.update(_git_env_with_identity())
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    env["GIT_AUTHOR_DATE"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    env["GIT_COMMITTER_DATE"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    # core.hooksPath at the null device, like every writer's own git call: a
    # fixture that commits (or amends) must not run the repository's hooks any
    # more than the product does, and this helper runs a bare 'git' where the
    # writers run their hardened one.
    proc = subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false",
         "-c", "core.hooksPath=" + os.devnull, *args],
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git (pinned {iso_utc}) {args} failed: {proc.stderr.strip()}"
        )
    return proc


def build_bare_origin(origin: Path, worktrees: list[Path]) -> None:
    """Build a bare origin plus one or more clones all on branch 'main'.

    Every worktree is cloned from the bare origin (so the origin is actually
    shared — not one clone of another) and starts with one committed file so
    it has a commit to push. The caller then drives register.py / claim.py /
    push-retry against the clones.

    Every clone takes ``main`` from the clone command itself, not from its own
    ``init.defaultbranch``: the suite's sandboxed HOME carries no gitconfig, so
    a plain clone falls back to git's own default (master) and lands on a
    branch origin never had. That is invisible while the fixture alone commits,
    because the manual ``checkout -b main`` moves the uncommitted files over —
    but a writer that commits by itself (register.py) puts its commit on
    master, and the push of ``main`` then has nothing to push.
    """
    origin.mkdir(parents=True, exist_ok=True)
    _git_ok(origin, "init", "-q", "--bare")
    first = worktrees[0]
    first.mkdir(parents=True, exist_ok=True)
    _git_ok(first, "init", "-q", "-b", "main")
    (first / "README.md").write_text("test repo\n")
    _git_ok(first, "add", "README.md")
    _git_ok(first, "commit", "-q", "-m", "initial commit")
    _git_ok(first, "remote", "add", "origin", str(origin))
    _git_ok(first, "push", "-q", "-u", "origin", "main")
    for wt in worktrees[1:]:
        wt.mkdir(parents=True, exist_ok=True)
        _git_ok(wt.parent, "clone", "-q", "-b", "main", str(origin), str(wt))


def advance_origin_with_claim(
    origin: Path, seeder: Path, session_file: str, task: str, branch: str = "main"
) -> str:
    """Deterministically advance ``origin`` with a conflicting claim row.

    Clones ``origin`` into ``seeder``, appends one ``- claim: <task>`` row at
    EOF of ``session_file`` (the repo-relative path a claim.py run will also
    append to), commits and pushes it, then removes the seed clone. Because
    both writers append at EOF of the same file, the caller's next
    fetch-rebase-push stops in a real conflict rather than merging cleanly,
    which is what makes the exit-5 path testable without a race. Returns the
    pushed sha.

    ``build_bare_origin`` builds every clone from the same bare origin, so
    the committed baseline of ``session_file`` is identical here and in the
    caller's clone: that is what makes the EOF append conflict deterministic.

    The row is written with claim.py's own ``CLAIM_PREFIX``, so the seeded
    claimant writes exactly what a real one would (see ``_script_constant``).
    """
    for label, value in (("session_file", session_file), ("task", task), ("branch", branch)):
        if not isinstance(value, str) or not value:
            raise TypeError(
                f"advance_origin_with_claim needs a non-empty str {label}, got {value!r}"
            )
    prefix = _script_constant(_script_ast(CLAIM), "CLAIM_PREFIX", CLAIM.name)
    if seeder.exists():
        shutil.rmtree(seeder)
    seeder.parent.mkdir(parents=True, exist_ok=True)
    # The clone is pinned to the branch it is seeding. Two host inputs would
    # otherwise decide that for it: a ~/.gitconfig carrying
    # init.defaultbranch, and the pytest HOME sandbox that carries no
    # gitconfig at all. Under the sandbox git falls back to its own default
    # (master), origin has no master, and the clone checks out an empty
    # worktree on a branch that does not exist - which is how a seed clone
    # silently stops being a seed. So the branch is named in the clone
    # command and confirmed against HEAD before anything is appended.
    env = {**os.environ, **_git_env_with_identity()}
    try:
        # ``-b`` names the branch outright, so it does not matter that the
        # sandboxed HOME carries no init.defaultbranch, nor what origin's own
        # HEAD points at (a bare init repo defaults to master even when the
        # only branch ever pushed is main): an explicit checkout of a branch
        # that exists on origin is what makes the worktree non-empty.
        _git_ok(
            seeder.parent, "clone", "-q", "-b", branch, str(origin), str(seeder),
            env=env,
        )
    except RuntimeError as exc:
        # A bare 'clone has no <file>' would hide why: surface git's own
        # words (dubious ownership, empty remote, no such ref) with them.
        raise RuntimeError(f"seed clone of {origin} failed: {exc}") from None
    landed = _git_ok(seeder, "rev-parse", "--abbrev-ref", "HEAD", env=env).stdout.strip()
    if landed != branch:
        raise RuntimeError(
            f"seed clone checked out {landed!r}, not {branch!r}: the conflict "
            "fixture would seed the wrong branch"
        )
    target = seeder / session_file
    if not target.is_file():
        listing = " ".join(_git_ok(seeder, "ls-files", env=env).stdout.split()) or "<no files>"
        raise RuntimeError(
            f"seed clone has no {session_file} to append to; it checked out: {listing}"
        )
    body = target.read_text(encoding="utf-8")
    if not body.endswith("\n"):
        body += "\n"
    target.write_text(body + prefix + task + "\n", encoding="utf-8")
    _git_ok(seeder, "add", session_file, env=env)
    _git_ok(seeder, "commit", "-q", "-m", f"claim: {task}", env=env)
    _git_ok(seeder, "push", "-q", "origin", branch, env=env)
    sha = _git_ok(seeder, "rev-parse", "HEAD", env=env).stdout.strip()
    shutil.rmtree(seeder)
    return sha


class PushProtocolDrift(AssertionError):
    """Raised by :func:`push_with_retry` when the rebase step fails.

    The harness copy of the push protocol cannot mirror claim.py's exit-code
    contract (it is a fixture, not the product), so it names the two cases the
    product distinguishes and says plainly that it aborts nothing. A scenario
    that needs the real 5/6 semantics drives ``run_claim(..., push=True)``
    instead of this helper.
    """


def push_with_retry(repo: Path, branch: str, attempts: int = 3) -> None:
    """fetch-rebase-push with at most `attempts` attempts.

    The losing pusher ends rebased-and-pushed (both claims land); the census
    then flags the double-claim. This is the push protocol documented in the
    skill (fetch-rebase-push, at most 3 attempts).

    A failing rebase is not classified the way claim.py classifies it: this
    helper runs no abort and raises PushProtocolDrift, which says so. Callers
    that need the product's behaviour drive claim.py --push itself.
    """
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            _git_ok(repo, "fetch", "origin")
            rebase = _git_e2(repo, "rebase", f"origin/{branch}")
            if rebase.returncode != 0:
                raise PushProtocolDrift(
                    "git rebase origin/" + branch + " failed in the harness push "
                    "helper: " + rebase.stderr.strip()
                    + "; this fixture aborts nothing and does not tell conflict "
                    "from refusal — drive claim.py --push (exit 5/6) for that"
                )
        proc = _git_e2(repo, "push", "origin", branch)
        if proc.returncode == 0:
            return
        if attempt == attempts:
            raise RuntimeError(f"push failed after {attempts} attempts: {proc.stderr.strip()}")
