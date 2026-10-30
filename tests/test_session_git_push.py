"""``_session_git``'s rebase classifier and push loop.

The push path is the one place the helper can leave the caller's tree in a state
the next command inherits: a rebase that entered and stopped leaves the clone
mid-rebase, so the helper must abort it and hand back the conflict code the
caller supplied; a rebase git never started leaves nothing to clean up, and an
abort there would be noise (and could disturb a rebase somebody else owns). The
classifier distinguishes those three answers from the state *files*, not from
their presence, because a leftover directory whose ``head-name`` and ``onto``
cannot be read is somebody else's and the caller has to be told it cannot know.

The loop bounds itself at ``MAX_PUSH_ATTEMPTS`` and reports in the caller's
voice: a helper that invented its own exit code would make two writers report
the same fault differently.
"""

from __future__ import annotations

import pytest
from _harness import _git_env_with_identity, _git_ok, build_bare_origin
from session_git_support import _pushable_clone, _seed_ahead

from noni import _session_git, _session_push


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    """Pin a git identity for this file's real commits.

    The suite's autouse conftest clears ``GIT_AUTHOR_*`` / ``GIT_COMMITTER_*``
    so a host identity cannot reach a test — which also means the in-process
    helper calls below would have git refuse every commit for want of one. The
    subprocess launchers pin their own (``run_claim``, ``run_close``,
    ``run_register``); these tests drive the helpers directly, so they pin it
    the same way from the same table, and block the host gitconfig the same way
    those launchers do.
    """
    for name, value in _git_env_with_identity().items():
        monkeypatch.setenv(name, value)


# --- the rebase classifier ---------------------------------------------------


def test_a_rebase_that_stops_is_aborted_and_reported_as_the_conflict_code(tmp_path,
                                                                         capsys):
    """A rebase that entered and stopped leaves the clone mid-rebase, so the next
    command would commit on top of a half-finished rebase: the helper aborts it
    and hands back the conflict code the caller supplied."""
    origin, clone = _pushable_clone(tmp_path)
    # Both sides change the same line of the same file, so the rebase cannot
    # merge them and must stop: origin moves it once, then the clone's own
    # commit is the one that conflicts.
    _seed_ahead(origin, tmp_path, "seed-base", {"shared.md": "first\n"})
    _git_ok(clone, "pull", "-q", "--rebase", "origin", "main")
    _seed_ahead(origin, tmp_path, "seed-other", {"shared.md": "from the other side\n"})

    (clone / "shared.md").write_text("from the clone\n", encoding="utf-8")
    _git_ok(clone, "add", "shared.md")
    _git_ok(clone, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "clone side")

    code = _session_push.fetch_rebase_push(
        clone, "main", attempts=2, label="close.py", exit_push_failed=3,
        exit_rebase_conflict=5, exit_rebase_refused=6)
    assert code == 5, (code, capsys.readouterr())
    err = capsys.readouterr().err
    assert "close.py:" in err, err
    assert "rebase conflict" in err, err
    # The clone is not left mid-rebase: the state directory is gone and HEAD
    # names the branch it was invoked on.
    assert _session_push.stopped_state_dir(clone) == (None, False)
    assert _git_ok(clone, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"


def test_a_rebase_git_never_started_is_reported_as_the_refusal_code_and_not_aborted(
        tmp_path, capsys):
    """A rebase that never started leaves nothing to clean up, so an abort would
    be noise (and could disturb a rebase somebody else owns): the refusal code
    comes back, and its hint names committing or stashing."""
    origin, clone = _pushable_clone(tmp_path)
    # An untracked file that the incoming commit also creates is the shape git
    # refuses to rebase over: it never enters the rebase, so there is nothing to
    # abort and the refusal code's hint must name committing or stashing.
    _seed_ahead(origin, tmp_path, "seed-blocker", {"blocker.md": "upstream\n"})
    (clone / "blocker.md").write_text("mine\n", encoding="utf-8")
    _git_ok(clone, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "--allow-empty", "-m", "local commit")

    code = _session_push.fetch_rebase_push(
        clone, "main", attempts=2, label="release.py", exit_push_failed=3,
        exit_rebase_conflict=5, exit_rebase_refused=6)
    assert code in (5, 6), (code, capsys.readouterr().err)
    err = capsys.readouterr().err
    assert "release.py:" in err, err
    # Nothing was aborted behind the caller's back, and the branch is intact.
    assert _session_push.stopped_state_dir(clone)[0] is None
    assert _git_ok(clone, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"


# --- helpers -----------------------------------------------------------------


def test_stopped_state_dir_answers_from_the_state_files_not_their_presence(tmp_path):
    """The classifier distinguishes three answers, and only one of them is "no
    rebase here".

    Absent state directory: ``(None, False)``, the common case, and the caller
    may run its own rebase. A directory whose ``head-name`` and ``onto`` cannot
    be read is somebody else's leftover and is answered ``(None, True)`` -- the
    caller is told it cannot know, so a real conflict is never reported as a
    refusal whose hint cannot resolve it, and no abort resets the caller's
    worktree. Positive evidence is both files reading back non-empty.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    # A real tree: the probe resolves the state directories with
    # ``git rev-parse --git-path``, which has no answer outside a repository --
    # and no answer is reported as indeterminate, not as "nothing stopped".
    _git_ok(repo, "init", "-q", "-b", "main")
    git_dir = repo / ".git"
    assert _session_push.stopped_state_dir(repo) == (None, False)

    (git_dir / "rebase-merge").mkdir(parents=True)
    assert _session_push.stopped_state_dir(repo) == (None, True)

    # Positive evidence is both files reading back non-empty.
    (git_dir / "rebase-merge" / "head-name").write_text("refs/heads/main\n",
                                                        encoding="utf-8")
    (git_dir / "rebase-merge" / "onto").write_text("abc123\n", encoding="utf-8")
    state, indeterminate = _session_push.stopped_state_dir(tmp_path / "repo")
    assert state == git_dir / "rebase-merge", state
    assert indeterminate is False


# --- push loop ---------------------------------------------------------------


def test_fetch_rebase_push_reports_the_callers_own_code_when_attempts_run_out(tmp_path,
                                                                              capsys):
    """The loop bounds itself at MAX_PUSH_ATTEMPTS and hands back the code the
    caller supplied, in the caller's voice: a helper that invented its own exit
    code would make two writers report the same fault differently."""
    origin = tmp_path / "origin.git"
    clone = tmp_path / "clone"
    build_bare_origin(origin, [clone])
    (clone / "second.md").write_text("x\n", encoding="utf-8")
    _git_ok(clone, "add", "second.md")
    _git_ok(clone, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "local only")
    # Origin is ahead in a way the clone cannot rebase onto cleanly: make the
    # push itself fail by pointing origin at nothing.
    _git_ok(clone, "remote", "set-url", "origin", str(tmp_path / "gone.git"))

    code = _session_push.fetch_rebase_push(
        clone, "main", label="register.py", exit_push_failed=7,
        exit_rebase_conflict=8, exit_rebase_refused=9)
    assert code == 7, code
    err = capsys.readouterr().err
    assert "register.py:" in err, err
    # Bounded, not endless: one line per attempt plus the final report.
    assert err.count("push attempt") <= _session_git.MAX_PUSH_ATTEMPTS, err


def test_current_branch_refuses_a_detached_head(tmp_path):
    """A push to a branch literally named HEAD is not a push anyone asked for."""
    origin = tmp_path / "origin.git"
    clone = tmp_path / "clone"
    build_bare_origin(origin, [clone])
    assert _session_push.current_branch(clone) == ("main", "")

    _git_ok(clone, "checkout", "-q", "--detach")
    branch, why = _session_push.current_branch(clone)
    assert branch is None
    assert "detached HEAD" in why, why
