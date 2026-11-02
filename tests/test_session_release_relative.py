"""release.py against a relative ``--repo`` naming the nested state clone (issue #66).

``test_session_release.py`` drives every state-root case with an absolute
``str(repo)``. A reader of docs/PRODUCT.md 7 names the private state root
differently: a clone nested inside the project, git-ignored by it, passed from
the project directory as ``--repo .noni-state``. With that spelling the release
pathspec used to carry the --repo component, so the row came out of the working
copy and nothing was committed -- exit 3 with a hint naming a path the clone does
not hold -- or exit 0 with a decoy path in the commit. Every case here therefore
reads the commit back out of git rather than trusting the exit code.

Split from ``test_session_release.py`` along that seam: the verb's own row
semantics stay in the writer suite, the relative-repo route is one contract the
four writers share.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from _harness import RELEASE, _git_ok, run_from
from session_git_support import (
    STATE_DIR,
    _assert_writer_left_nothing_behind,
    _committed_names,
    _nested_state,
    _strip_identity,
    _tracked_bytes,
)

from noni import release as release_mod

# The environment a refused commit needs: no global config for git to read a
# committer out of (the launcher is asked not to add the identity pair).
_PATH = os.environ.get("PATH", "/usr/bin:/bin")

RELEASE_RELATIVE_SID = "2026-10-01-cccccc"
RELEASE_REL = f"noni/sessions/{RELEASE_RELATIVE_SID}.md"


def _release_relative_run(project: Path, sid: str, task: str,
                          refused: bool = False) -> subprocess.CompletedProcess[str]:
    """release.py from the project cwd, ``--repo`` naming the nested clone by name.

    ``refused`` strips the child's git identity so git itself refuses the commit.
    """
    if refused:
        return run_from(project, RELEASE, "--repo", STATE_DIR, "--session-id", sid,
                        "--task", task, identity=False,
                        env={"GIT_CONFIG_GLOBAL": "/dev/null", "PATH": _PATH})
    return run_from(project, RELEASE, "--repo", STATE_DIR, "--session-id", sid,
                    "--task", task)


def test_release_removes_the_row_with_a_relative_repo(tmp_path):
    """AC1/AC7: relative --repo exits 0, the row is gone in the clone, and the
    commit is exactly the one repo-relative session path."""
    sid = RELEASE_RELATIVE_SID
    project, state, session = _nested_state(tmp_path, sid, name="release-relative")

    proc = _release_relative_run(project, sid, "#1")
    assert proc.returncode == release_mod.EXIT_OK, f"{proc.returncode}: {proc.stderr}"

    assert "- claim: #1" not in session.read_text(encoding="utf-8")
    committed = _git_ok(state, "show", f"HEAD:{RELEASE_REL}").stdout
    assert "- claim: #1" not in committed, "the row is still in the commit"
    assert "- claim: #2" in committed, "the writer released a row nobody named"
    assert _git_ok(state, "log", "-1", "--format=%s").stdout.strip() == "release: #1"
    assert _committed_names(state) == [RELEASE_REL], (
        "the commit moved paths other than the one session file"
    )
    assert _git_ok(state, "status", "--porcelain").stdout.splitlines() == []


def test_release_with_a_relative_repo_leaves_nothing_behind_when_refused(tmp_path):
    """AC4/AC6/AC8: a refused relative-repo release names the repo-relative path
    in its headline and its hint, never a path beginning with the --repo
    component, and never blames a missing upstream for a commit git refused."""
    sid = RELEASE_RELATIVE_SID
    project, state, session = _nested_state(tmp_path, sid, name="release-refused")
    _strip_identity(state)
    head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()
    tracked_before = _tracked_bytes(state)

    proc = _release_relative_run(project, sid, "#1", refused=True)

    assert proc.returncode == release_mod.EXIT_PUSH_FAILED, f"{proc.returncode}: {proc.stderr}"
    err = proc.stderr
    assert f"git could not commit {RELEASE_REL}" in err, err
    assert f"commit {RELEASE_REL} by hand" in err, err
    assert f"{STATE_DIR}/noni/sessions" not in err, (
        f"the wording names a path built by joining the relative --repo to the "
        f"state path: {err}"
    )
    assert "no upstream configured" not in err, (
        f"a refused commit was classified as a missing upstream: {err}"
    )
    assert "- claim: #1" not in session.read_text(encoding="utf-8")
    assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before
    _assert_writer_left_nothing_behind(state, tracked_before, [RELEASE_REL])
