"""The private-state route as a reader names it: a relative ``--repo`` (issue #66).

docs/PRODUCT.md 7 sells a second state root -- a separate repository carrying the
same ``noni/`` layout, selected by passing its path as ``--repo``. The shape a
reader copies is a clone *nested inside* the project and git-ignored by it, named
on the command line by name alone: ``--repo .noni-state``, launched from the
project directory.

Every launcher the four writer suites had built its ``--repo`` from an absolute
``tmp_path``, so no test ever sent the relative form and the bug was invisible:
the old derivation joined the caller-relative ``--repo`` to the state path and
left the ``--repo`` component in the answer, so ``git -C <state> add --
st/noni/sessions/x.md`` named a path the state clone does not hold. Each of the
four writers exited 3 with its file written and uncommitted. No such helper
exists any more -- the writers build the name once with
:func:`noni._session_git.writer_name` -- which is why these tests hold: they pin
the fault the removed helper used to produce.

One module holds all four verbs rather than one test in each suite, because the
property is the shared primitive's and every launcher in it is the same
``run_from(cwd, script, ...)``. The per-verb assertions differ only in what the
writer prints, which is the point of AC6: a fix that corrected the pathspec but
not the message (register derives its message path separately from the path it
stages) fails here and passes an exit-code-only test.

Each run plants a committed decoy at the doubled path, so admitting that path
into the commit is a name-set failure rather than a silent success.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from _harness import CLAIM, CLOSE, REGISTER, RELEASE, _git_ok, run_from
from session_git_support import (
    _PATH,
    STATE_DIR,
    _committed_names,
    _nested_state,
    _strip_identity,
)

# One session id per verb's fixture; no writer in this file reuses another's tree.
SID = "2026-10-01-cccccc"

# The single path every commit in here must consist of, and the doubled spelling
# that must never appear in it or in any message.
REL = f"noni/sessions/{SID}.md"
DOUBLED = f"{STATE_DIR}/noni/sessions/{SID}.md"


def _refused_run(cwd: Path, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One writer from ``cwd`` with no committer identity, so git refuses the commit.

    The refusal the writer suites already use: it leaves the run's own path
    handling as the only variable being measured, and it is the honest state (a
    state repository prepared on a machine that never configured a committer).
    """
    return run_from(cwd, script, *args, identity=False,
                    env={"GIT_CONFIG_GLOBAL": "/dev/null", "PATH": _PATH})


def _assert_names_the_repo_relative_path(err: str) -> None:
    """The wording half of AC2/AC6: ``noni/sessions/<sid>.md`` and nothing else.

    ``DOUBLED`` is the string a path built by joining the caller-cwd-relative
    ``--repo`` to the state path produces, so its absence is what distinguishes a
    corrected derivation from a corrected pathspec with the message left behind.
    """
    assert DOUBLED not in err, (
        f"a path built by joining the relative --repo to the state path reached "
        f"the wording: {err}"
    )
    assert "no upstream configured" not in err, (
        f"a path whose commit was refused was classified as a missing upstream: {err}"
    )


def _assert_clone_clean(state: Path) -> None:
    """AC4: a writer that finished left no dirty or staged path behind."""
    assert _git_ok(state, "status", "--porcelain").stdout.splitlines() == [], (
        "a completed run left the state clone dirty"
    )


# --- register ---------------------------------------------------------------


def test_register_commits_the_session_with_a_relative_repo(tmp_path):
    """AC1/AC7: relative --repo from the project cwd exits 0, the register lands
    in the clone, and the commit is exactly the one repo-relative path."""
    project, state, _session = _nested_state(tmp_path, SID, name="register-relative")

    proc = run_from(project, REGISTER, "--repo", STATE_DIR, "--identity", "developer")
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    sid = proc.stdout.split("registered session ")[1].split(" ->")[0].strip()
    committed = _git_ok(state, "show", f"HEAD:noni/sessions/{sid}.md").stdout
    assert "- identity: developer" in committed, committed
    assert _git_ok(state, "log", "-1", "--format=%s").stdout.strip() == f"register: {sid}"
    # Exactly one path, and it carries no --repo component: the decoy the fixture
    # committed at the doubled path stayed out of this commit.
    assert _committed_names(state) == [f"noni/sessions/{sid}.md"], (
        "the commit moved paths other than the one register file"
    )
    _assert_clone_clean(state)
    # The marker belongs to the state clone, not to the cwd the run started in.
    assert (state / ".git" / "noni-session").is_file()


def test_register_with_a_relative_repo_names_the_repo_relative_path_when_refused(tmp_path):
    """AC2/AC6/AC8: a refused relative-repo register names ``noni/sessions/<sid>.md``
    in its headline *and* its hint, never the doubled path.

    register.py is the verb that computed its message path separately from the
    path it staged, so this is the case an exit-code-only test cannot see.
    """
    project, state, _session = _nested_state(tmp_path, SID, name="register-refused")
    _strip_identity(state)
    head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()

    proc = _refused_run(project, REGISTER, "--repo", STATE_DIR, "--identity", "developer")

    assert proc.returncode == 3, f"{proc.returncode}: {proc.stderr}"
    err = proc.stderr
    # The id this run allocated, read out of the wording so the assertion cannot
    # drift from the run that produced it.
    sid = err.split("git could not commit noni/sessions/")[1].split(".md")[0]
    assert f"git could not commit noni/sessions/{sid}.md (the file is written)" in err, err
    assert f"commit noni/sessions/{sid}.md by hand" in err, err
    assert DOUBLED not in err, err
    assert "no upstream configured" not in err, err
    # AC4: the file is on disk, and the clone holds no commit this run made.
    assert (state / "noni" / "sessions" / f"{sid}.md").is_file()
    assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before


# --- claim ------------------------------------------------------------------


def test_claim_commits_the_row_with_a_relative_repo(tmp_path):
    """AC1/AC7: relative --repo from the project cwd exits 0, the row lands in
    the clone, and the commit is exactly the one repo-relative path."""
    project, state, session = _nested_state(tmp_path, SID, name="claim-relative")

    proc = run_from(project, CLAIM, "--repo", STATE_DIR, "--session-id", SID,
                    "--task", "#42")
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    assert "- claim: #42" in session.read_text(encoding="utf-8"), "the row is not on disk"
    committed = _git_ok(state, "show", f"HEAD:{REL}").stdout
    assert "- claim: #42" in committed, "the row is not in the commit"
    assert _git_ok(state, "log", "-1", "--format=%s").stdout.strip() == "claim: #42"
    assert _committed_names(state) == [REL], (
        "the commit moved paths other than the one session file"
    )
    _assert_clone_clean(state)


def test_claim_with_a_relative_repo_names_the_repo_relative_path_when_refused(tmp_path):
    """AC2/AC6/AC8: a refused relative-repo claim names ``noni/sessions/<sid>.md``
    in the wording it owes, ``( <rel>, which this run staged)``, never the doubled
    path, and does not call a refused commit a missing upstream."""
    project, state, session = _nested_state(tmp_path, SID, name="claim-refused")
    _strip_identity(state)
    head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()

    proc = _refused_run(project, CLAIM, "--repo", STATE_DIR, "--session-id", SID,
                        "--task", "#42")

    assert proc.returncode == 3, f"{proc.returncode}: {proc.stderr}"
    err = proc.stderr
    assert f"(noni/sessions/{SID}.md, which this run staged)" in err, err
    _assert_names_the_repo_relative_path(err)
    # AC4: the row is on disk, and the clone holds no commit this run made.
    assert "- claim: #42" in session.read_text(encoding="utf-8")
    assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before


# --- close ------------------------------------------------------------------


def test_close_commits_the_session_with_a_relative_repo(tmp_path):
    """AC1/AC7: relative --repo from the project cwd exits 0, the status line
    moves in the clone, and the commit is exactly the one repo-relative path."""
    project, state, session = _nested_state(tmp_path, SID, name="close-relative")

    proc = run_from(project, CLOSE, "--repo", STATE_DIR, "--session-id", SID)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    assert _git_ok(state, "log", "-1", "--format=%s").stdout.strip() == f"close: {SID}"
    committed = _git_ok(state, "show", f"HEAD:{REL}").stdout
    assert "- status: closed" in committed, committed
    assert "- status: closed" in session.read_text(encoding="utf-8")
    assert _committed_names(state) == [REL], (
        "the commit moved paths other than the one session file"
    )
    # The decoy at the doubled path is still the fixture's own commit, unmoved.
    assert _git_ok(state, "show", f"HEAD:{DOUBLED}").stdout == \
        "decoy at the doubled path\n"
    _assert_clone_clean(state)


def test_close_with_a_relative_repo_names_the_repo_relative_path_when_refused(tmp_path):
    """AC2/AC6/AC8: a refused relative-repo close names ``noni/sessions/<sid>.md``
    in both its headline and its hint, never the doubled path, and the cause is
    not an unrelated upstream clause."""
    project, state, session = _nested_state(tmp_path, SID, name="close-refused")
    _strip_identity(state)
    head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()

    proc = _refused_run(project, CLOSE, "--repo", STATE_DIR, "--session-id", SID)

    assert proc.returncode == 3, f"{proc.returncode}: {proc.stderr}"
    err = proc.stderr
    assert f"git could not commit noni/sessions/{SID}.md" in err, err
    assert f"commit noni/sessions/{SID}.md by hand" in err, err
    _assert_names_the_repo_relative_path(err)
    # AC4 (the #57 writer-honesty contract): the file is written and exactly one
    # path is staged, so a later `git add -A` cannot sweep anything else in.
    assert "- status: closed" in session.read_text(encoding="utf-8")
    assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before
    assert [row for row in _git_ok(state, "status", "--porcelain").stdout.splitlines()
            if "noni/" in row] == [f"M  {REL}"]


# --- release ----------------------------------------------------------------


def test_release_removes_the_row_with_a_relative_repo(tmp_path):
    """AC1/AC7: relative --repo from the project cwd exits 0, the row is gone in
    the clone, and the commit is exactly the one repo-relative path."""
    project, state, session = _nested_state(tmp_path, SID, name="release-relative")

    proc = run_from(project, RELEASE, "--repo", STATE_DIR, "--session-id", SID,
                    "--task", "#1")
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    assert "- claim: #1" not in session.read_text(encoding="utf-8"), "row still on disk"
    committed = _git_ok(state, "show", f"HEAD:{REL}").stdout
    assert "- claim: #1" not in committed, "the row is still in the commit"
    assert "- claim: #2" in committed, "the writer released a row nobody named"
    assert _git_ok(state, "log", "-1", "--format=%s").stdout.strip() == "release: #1"
    assert _committed_names(state) == [REL], (
        "the commit moved paths other than the one session file"
    )
    _assert_clone_clean(state)


def test_release_with_a_relative_repo_names_the_repo_relative_path_when_refused(tmp_path):
    """AC2/AC6/AC8: a refused relative-repo release names ``noni/sessions/<sid>.md``
    in its headline and its hint, never the doubled path, and does not blame a
    missing upstream for a commit git refused."""
    project, state, session = _nested_state(tmp_path, SID, name="release-refused")
    _strip_identity(state)
    head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()

    proc = _refused_run(project, RELEASE, "--repo", STATE_DIR, "--session-id", SID,
                        "--task", "#1")

    assert proc.returncode == 3, f"{proc.returncode}: {proc.stderr}"
    err = proc.stderr
    assert f"git could not commit noni/sessions/{SID}.md" in err, err
    assert f"commit noni/sessions/{SID}.md by hand" in err, err
    _assert_names_the_repo_relative_path(err)
    # AC4: the row is removed on disk, and nothing landed in the clone.
    assert "- claim: #1" not in session.read_text(encoding="utf-8")
    assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before
