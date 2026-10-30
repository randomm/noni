"""Fixtures the two register test modules share: a repo, a refusal, a field view.

Both modules drive register.py through its real CLI and need the same three
things: a throwaway repo with one commit to work in, a run whose commit git will
not take, and a way to read a session file's fields back. They live here so the
refusal environment is defined once -- the empty-gitconfig trick in
``_no_committer_env`` is the load-bearing part of every exit-3 test in the pair.

The product is the noni package; _harness puts src/ on sys.path, so the register
helpers are reachable from tests as ``from noni import register``. No skill
scripts/ dir goes on the path: the wrapper there is a shim, and a lookalike
earlier on sys.path must not be trusted as the writer's own code.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from _harness import REGISTER, _git_ok, run_from


def _git_repo(tmp_path: Path) -> Path:
    """A throwaway git repo with one commit, in tmp_path.

    The marker lives under the tree's own ``.git``, and the committing path
    needs a branch to commit on, so the idempotency tests need a real repo and
    not a bare directory.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_ok(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("test repo\n", encoding="utf-8")
    _git_ok(repo, "add", "README.md")
    _git_ok(repo, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "initial commit")
    return repo


def _head(repo: Path) -> str:
    """The commit HEAD names, for the assertion that a reuse adds none."""
    return _git_ok(repo, "rev-parse", "HEAD").stdout.strip()


def _sid_of(stdout: str) -> str:
    """The session id from register.py's committing success line."""
    return stdout.strip().split("registered session ")[1].split(" ->")[0].strip()


def _sid_of_any(repo: Path) -> str:
    """The session id of the one register file this run left in ``repo``.

    The id is minted from the clock, so a test that needs to name the path reads
    it back from the tree rather than guessing at the date.
    """
    files = list((repo / "noni" / "sessions").glob("*.md"))
    assert len(files) == 1, files
    return files[0].name


def _mark_status(path: Path, status: str) -> None:
    """Rewrite a session file's own ``- status:`` field to ``status``.

    The fixture reaches a terminal state without close.py, so the marker tests
    exercise register's reading of the field and nothing else.
    """
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("- status:"):
            lines.append(f"- status: {status}")
        else:
            lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fields(body: str) -> dict:
    """The '- key: value' fields of a register file, as a dict."""
    fields = {}
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("- "):
            key, sep, value = line[2:].partition(":")
            if sep:
                fields[key.strip()] = value.strip()
    return fields


def _hostworktree_value(body: str) -> str:
    """Return the value part of the '- host/worktree:' field line."""
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("- host/worktree:"):
            return line[len("- host/worktree:"):].strip()
    raise AssertionError(f"no host/worktree field in session file:\n{body}")


def _no_committer_env(tmp_path: Path) -> dict[str, str]:
    """The environment a commit refusal needs: a gitconfig that names no committer.

    An empty file, not ``/dev/null``, because the writer's git helper keeps
    ``GIT_CONFIG_GLOBAL`` in its environment (a caller's identity is meant to
    survive the filter), and a device reads as no config file at all -- which
    would let the *host's* config decide the committer and make the commit
    succeed. An empty regular file says 'this machine configured nothing', which
    is the state these tests want: the operator who runs a writer on a box where
    no committer was ever set. ``GIT_AUTHOR_*`` / ``GIT_COMMITTER_*`` stay
    unset (the suite's autouse fixture clears them and the launcher is asked not
    to add them), so git has no committer from either source.
    """
    empty = tmp_path / "_empty_gitconfig"
    empty.write_text("", encoding="utf-8")
    return {"GIT_CONFIG_GLOBAL": str(empty),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin")}


def _register_refusing_commit(repo: Path, scratch: Path, identity: str = "dev"
                              ) -> subprocess.CompletedProcess[str]:
    """One registering run in ``repo`` whose commit git will not take.

    ``scratch`` is where that run's empty gitconfig lives; the run is otherwise
    an ordinary one, so the only difference an operator can see is the refusal.
    """
    return run_from(repo, REGISTER, "--repo", str(repo), "--identity", identity,
                    identity=False, env=_no_committer_env(scratch))


def _refused_register(tmp_path, name, identity="dev"):
    """A committing register run whose git commit is refused; the tree is returned.

    ``_git_repo`` builds ``<dir>/repo``, so the tree comes back from it rather
    than being assumed to be ``tmp_path / name``.
    """
    parent = tmp_path / name
    parent.mkdir(parents=True, exist_ok=True)
    repo = _git_repo(parent)
    return repo, _register_refusing_commit(repo, tmp_path, identity)
