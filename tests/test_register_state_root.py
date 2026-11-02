"""register.py writes its state under --repo and nowhere else.

register.py is the writer that creates ``noni/sessions/`` in the first place, so
a run that resolved that directory from its cwd would seed a project nobody
pointed it at. Three trees per run: the state repository (a git repo holding no
``noni/`` yet), a decoy register beside the cwd, and an empty cwd a stray write
would show up in. Each assertion below names which of the three it measures.

Split out of ``test_register_defaults.py``, which keeps the writer's own
defaults, refusals and idempotency paths.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from _harness import REGISTER, _git_ok, run_from
from register_refusal_fixtures import _fields, _git_repo, _sid_of
from session_git_support import (
    STATE_DIR,
    _assert_writer_left_nothing_behind,
    _committed_names,
    _nested_state,
    _strip_identity,
    _tracked_bytes,
)

# The environment a refused commit needs: no global config for git to read a
# committer out of (the launcher is asked not to add the identity pair).
_PATH = os.environ.get("PATH", "/usr/bin:/bin")

REGISTER_STATE_DIR = "register-state-root"
REGISTER_CWD_DIR = "register-cwd"
REGISTER_DECOY_DIR = "register-decoy"
REGISTER_DECOY_SID = "2026-10-01-dddddd"


def _register_case(tmp_path: Path) -> tuple[Path, Path, Path]:
    """The three trees of one register state-root run: (root, decoy, cwd)."""
    root = _git_repo(tmp_path)
    root = root.rename(tmp_path / REGISTER_STATE_DIR)
    decoy = tmp_path / REGISTER_DECOY_DIR
    sessions = decoy / "noni" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / f"{REGISTER_DECOY_SID}.md").write_text(
        "# session decoy\n\n- identity: decoy\n- host/worktree: decoy (decoy)\n"
        "- started: 2026-10-01T10:00:00Z\n- status: active\n- claims:\n"
        "  - claim: #999\n",
        encoding="utf-8",
    )
    cwd = tmp_path / REGISTER_CWD_DIR
    cwd.mkdir(parents=True, exist_ok=True)
    return root, decoy, cwd


def _register_from(cwd: Path, repo: Path, identity: str = "developer"
                   ) -> subprocess.CompletedProcess[str]:
    """register.py launched from ``cwd``, with ``--repo`` naming the state root."""
    return run_from(cwd, REGISTER, "--repo", str(repo), "--identity", identity)


def test_register_creates_the_register_only_under_the_state_root(tmp_path):
    """A first registration creates ``noni/sessions/`` in the state repository
    and leaves the decoy and the cwd exactly as they were."""
    root, decoy, cwd = _register_case(tmp_path)
    decoy_bytes = (decoy / "noni" / "sessions" / f"{REGISTER_DECOY_SID}.md").read_bytes()
    assert not (root / "noni").exists(), "the state root must start with no noni/"

    proc = _register_from(cwd, root)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    files = list((root / "noni" / "sessions").glob("*.md"))
    assert len(files) == 1, f"one register file is one registration: {files}"
    body = files[0].read_text(encoding="utf-8")
    assert _fields(body)["identity"] == "developer"
    # The commit landed in the state repository, not wherever the run happened
    # to be launched from: HEAD's only path is the new register file.
    subject = _git_ok(root, "log", "-1", "--format=%s").stdout.strip()
    assert subject.startswith("register:"), subject
    assert (decoy / "noni" / "sessions" / f"{REGISTER_DECOY_SID}.md").read_bytes() \
        == decoy_bytes, (
        "the run touched the decoy register beside its cwd, so the sessions "
        "directory resolved from somewhere other than --repo"
    )
    assert not (cwd / "noni").exists(), "the run created noni/ under the cwd"


def test_register_reuses_the_state_roots_marker_not_the_cwds(tmp_path):
    """The working-copy marker is read from ``--repo`` too: a second run in the
    same state root continues the session instead of minting a new one, even
    though both runs launch from an unrelated directory."""
    root, _decoy, cwd = _register_case(tmp_path)
    first = _register_from(cwd, root)
    assert first.returncode == 0, first.stderr
    sid = _sid_of(first.stdout)

    second = _register_from(cwd, root)
    assert second.returncode == 0, second.stderr
    assert f"{sid}.md already registered" in second.stdout, second.stdout
    assert len(list((root / "noni" / "sessions").glob("*.md"))) == 1, (
        "a second run allocated a second session, so the marker was not the "
        "state root's"
    )


def test_register_refuses_a_repo_that_is_not_a_directory(tmp_path):
    """A --repo naming no directory is a usage error (exit 2) naming the
    argument, and it creates nothing beside the cwd."""
    _root, decoy, cwd = _register_case(tmp_path)
    decoy_bytes = (decoy / "noni" / "sessions" / f"{REGISTER_DECOY_SID}.md").read_bytes()

    proc = _register_from(cwd, tmp_path / "no-such-state-root")
    assert proc.returncode == 2, f"expected exit 2, got {proc.returncode}: {proc.stderr}"
    assert "--repo" in proc.stderr.lower(), proc.stderr
    assert "directory" in proc.stderr.lower(), proc.stderr
    assert (decoy / "noni" / "sessions" / f"{REGISTER_DECOY_SID}.md").read_bytes() \
        == decoy_bytes
    assert not (cwd / "noni").exists()


# --- the private-state route named as a reader names it (issue #66) -----------
#
# ``_register_from`` above passes an absolute ``str(repo)``, as every launcher in
# this suite does. The private state root of docs/PRODUCT.md 7 is named
# differently -- a clone nested in the project and git-ignored by it, passed from
# the project directory as ``--repo .noni-state``. register is the verb that
# computed its printed path separately from the path it staged, so the wording is
# as much a part of this contract as the exit code is.

def _register_relative_run(project: Path, refused: bool = False,
                           identity: str = "developer") -> subprocess.CompletedProcess[str]:
    """register.py from the project cwd, ``--repo`` naming the nested clone by name.

    ``refused`` strips the child's git identity so git itself refuses the commit.
    """
    if refused:
        return run_from(project, REGISTER, "--repo", STATE_DIR, "--identity", identity,
                        identity=False,
                        env={"GIT_CONFIG_GLOBAL": "/dev/null", "PATH": _PATH})
    return run_from(project, REGISTER, "--repo", STATE_DIR, "--identity", identity)


def test_register_commits_the_register_with_a_relative_repo(tmp_path):
    """AC1/AC7: relative --repo exits 0, the register lands in the clone, and the
    commit is exactly the one repo-relative path the run wrote."""
    project, state, _session = _nested_state(tmp_path, "2026-10-01-bbbbbb",
                                             name="register-relative")

    proc = _register_relative_run(project)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    sid = _sid_of(proc.stdout)
    rel = f"noni/sessions/{sid}.md"
    assert "- identity: developer" in _git_ok(state, "show", f"HEAD:{rel}").stdout
    assert _git_ok(state, "log", "-1", "--format=%s").stdout.strip() == f"register: {sid}"
    # Name-set equality, not exit code: a run that admitted the decoy at the
    # doubled path would exit 0 and fail here.
    assert _committed_names(state) == [rel], (
        "the commit moved paths other than the one register file"
    )
    assert _git_ok(state, "status", "--porcelain").stdout.splitlines() == []
    # The marker belongs to the state clone, not to the cwd the run started in.
    assert (state / ".git" / "noni-session").is_file()


def test_register_with_a_relative_repo_names_the_repo_relative_path_when_refused(tmp_path):
    """AC2/AC4/AC6/AC8: a refused relative-repo register names its own
    ``noni/sessions/<sid>.md`` in both the headline and the hint, never a path
    beginning with the --repo component, and never blames a missing upstream.

    The id is read out of the run's own words, so the assertion cannot drift from
    the run that produced it: register derived its message path separately from
    the path it staged, and this is the case an exit-code-only test cannot see.
    """
    project, state, _session = _nested_state(tmp_path, "2026-10-01-bbbbbb",
                                             name="register-refused")
    _strip_identity(state)
    head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()
    tracked_before = _tracked_bytes(state)

    proc = _register_relative_run(project, refused=True)

    assert proc.returncode == 3, f"{proc.returncode}: {proc.stderr}"
    err = proc.stderr
    sid = err.split("git could not commit noni/sessions/")[1].split(".md")[0]
    rel = f"noni/sessions/{sid}.md"
    assert f"git could not commit {rel} (the file is written)" in err, err
    assert f"commit {rel} by hand" in err, err
    assert f"{STATE_DIR}/noni/sessions" not in err, (
        f"the wording names a path built by joining the relative --repo to the "
        f"state path: {err}"
    )
    assert "no upstream configured" not in err, (
        f"a refused commit was classified as a missing upstream: {err}"
    )
    # The file is on disk and the clone holds no commit this run made.
    assert (state / rel).is_file()
    assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before
    _assert_writer_left_nothing_behind(state, tracked_before, [rel])
