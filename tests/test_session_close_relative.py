"""close.py against a relative ``--repo`` naming the nested state clone (issue #66).

``test_session_close.py`` drives every state-root case with an absolute
``str(repo)``, which is not the form a reader of docs/PRODUCT.md 7 types: the
private state root there is a clone nested inside the project and git-ignored by
it, named from the project directory as ``--repo .noni-state``. With that
spelling the pathspec used to keep the --repo component in it, so close exited 3
with its file written and uncommitted -- or, on a clone that already happened to
hold the doubled path, exited 0 having committed that decoy instead of the
session. Exit code alone cannot tell those apart, so every case here reads the
commit back out of git.

Split from ``test_session_close.py`` along that seam (the writer's own semantics
stay with the verb suite; the relative-repo route is one contract shared by all
four writers).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from _harness import CLOSE, _git_ok, run_from
from session_git_support import (
    _PATH,
    STATE_DIR,
    _assert_writer_left_nothing_behind,
    _committed_names,
    _nested_state,
    _strip_identity,
    _tracked_bytes,
)

from noni import close as close_mod

CLOSE_RELATIVE_SID = "2026-10-01-cccccc"
CLOSE_REL = f"noni/sessions/{CLOSE_RELATIVE_SID}.md"


def _close_relative_run(project: Path, sid: str,
                        refused: bool = False) -> subprocess.CompletedProcess[str]:
    """close.py from the project cwd, ``--repo`` naming the nested clone by name alone.

    ``refused`` strips the child's git identity so git itself refuses the commit,
    which is how the wording half of the contract is reached.
    """
    if refused:
        return run_from(project, CLOSE, "--repo", STATE_DIR, "--session-id", sid,
                        identity=False,
                        env={"GIT_CONFIG_GLOBAL": "/dev/null", "PATH": _PATH})
    return run_from(project, CLOSE, "--repo", STATE_DIR, "--session-id", sid)


def test_close_commits_the_session_with_a_relative_repo(tmp_path):
    """AC1/AC7: relative --repo exits 0 and the commit is exactly the one
    repo-relative session path, verifiable inside the state clone."""
    sid = CLOSE_RELATIVE_SID
    project, state, session = _nested_state(tmp_path, sid, name="close-relative")

    proc = _close_relative_run(project, sid)
    assert proc.returncode == close_mod.EXIT_OK, f"{proc.returncode}: {proc.stderr}"

    assert "- status: closed" in _git_ok(state, "show", f"HEAD:{CLOSE_REL}").stdout
    assert _git_ok(state, "log", "-1", "--format=%s").stdout.strip() == f"close: {sid}"
    assert _committed_names(state) == [CLOSE_REL], (
        "the commit moved paths other than the one session file"
    )
    assert _git_ok(state, "status", "--porcelain").stdout.splitlines() == []
    assert "- status: closed" in session.read_text(encoding="utf-8")


def test_close_with_a_relative_repo_leaves_nothing_behind_when_refused(tmp_path):
    """AC4/AC6/AC8: a refused relative-repo close names the repo-relative path in
    its headline and its hint, never a path beginning with the --repo component,
    and the commit it did not make left no bytes changed and only its own path
    staged."""
    sid = CLOSE_RELATIVE_SID
    project, state, session = _nested_state(tmp_path, sid, name="close-refused")
    _strip_identity(state)
    head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()
    tracked_before = _tracked_bytes(state)

    proc = _close_relative_run(project, sid, refused=True)

    assert proc.returncode == close_mod.EXIT_PUSH_FAILED, f"{proc.returncode}: {proc.stderr}"
    err = proc.stderr
    assert f"git could not commit {CLOSE_REL}" in err, err
    assert f"commit {CLOSE_REL} by hand" in err, err
    assert f"{STATE_DIR}/noni/sessions" not in err, (
        f"the wording names a path built by joining the relative --repo to the "
        f"state path: {err}"
    )
    assert "no upstream configured" not in err, (
        f"a refused commit was classified as a missing upstream: {err}"
    )
    # The change is on disk and nowhere else: no commit, and the staged set is
    # exactly the one path this run owns.
    assert "- status: closed" in session.read_text(encoding="utf-8")
    assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before
    _assert_writer_left_nothing_behind(state, tracked_before, [CLOSE_REL])
