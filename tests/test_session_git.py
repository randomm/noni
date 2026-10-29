"""_session_git: the git mechanic the four session writers share.

This module owns the one commit primitive register.py, claim.py, close.py and
release.py build on, so the properties worth testing are the ones every writer
inherits: the three steps run in the order that commits a never-before-seen
path, only the named path lands in the commit, nobody else's staged entry is
touched, the paths handed to git are absolute so the caller's working directory
cannot redirect a write into another repository, and the terminal-status set
still agrees with the census's own two copies.

The census sources are the ones pinned: this module holds a copy of the set, not
an import, and the equality asserted here is what stops the two drifting.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from _harness import _git_env_with_identity, _git_ok, build_bare_origin

from noni import _session_git, gitenv
from noni import census as census_mod
from noni import census_sessions as census_sessions_mod


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


# --- the commit primitive ----------------------------------------------------


def _repo(tmp_path: Path) -> Path:
    """A git repo with one commit, on main, under tmp_path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_ok(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("test repo\n", encoding="utf-8")
    _git_ok(repo, "add", "README.md")
    _git_ok(repo, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "initial commit")
    return repo


def _commit_files(repo: Path, rev: str = "HEAD") -> list[str]:
    return _git_ok(repo, "show", "--name-only", "--format=", rev).stdout.split()


def test_stage_and_commit_commits_a_file_never_seen_before(tmp_path):
    """The primitive's reason for being: reset, add, then ``commit --only``.

    A brand-new path has no index entry, so a plain ``commit --only <path>``
    refuses it ("did not match any file(s) known to git"). Step 2 is what makes
    step 3 able to carry the file, and a reordering breaks this test.
    """
    repo = _repo(tmp_path)
    target = repo / "noni" / "sessions" / "2026-10-01-aaaaaa.md"
    target.parent.mkdir(parents=True)
    target.write_text("- status: active\n", encoding="utf-8")

    ok, why = _session_git.stage_and_commit(repo, target, "register: 2026-10-01-aaaaaa")
    assert ok, why
    assert _commit_files(repo) == ["noni/sessions/2026-10-01-aaaaaa.md"]
    assert _git_ok(repo, "log", "-1", "--format=%s").stdout.strip() == \
        "register: 2026-10-01-aaaaaa"


def test_stage_and_commit_carries_only_its_own_path(tmp_path):
    """Two changed files, one commit: the other stays unstaged-or-staged and
    uncommitted, which is the whole point of the three-step primitive."""
    repo = _repo(tmp_path)
    mine = repo / "noni" / "sessions" / "2026-10-01-bbbbbb.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("- status: active\n", encoding="utf-8")
    theirs = repo / "noni" / "decisions" / "theirs.json"
    theirs.parent.mkdir(parents=True)
    theirs.write_text('{"a": 1}\n', encoding="utf-8")
    # Someone else staged theirs before this writer ran; the writer must not
    # sweep it in and must not unstage it either.
    _git_ok(repo, "add", "noni/decisions/theirs.json")

    ok, why = _session_git.stage_and_commit(repo, mine, "register: b")
    assert ok, why
    assert _commit_files(repo) == ["noni/sessions/2026-10-01-bbbbbb.md"]
    assert "A  noni/decisions/theirs.json" in _git_ok(repo, "status", "--porcelain").stdout


def test_stage_and_commit_rewrites_a_previously_committed_file(tmp_path):
    """The amend path of the same primitive: the second commit carries only the
    new bytes of the same path."""
    repo = _repo(tmp_path)
    target = repo / "noni" / "sessions" / "2026-10-01-cccccc.md"
    target.parent.mkdir(parents=True)
    target.write_text("- status: active\n", encoding="utf-8")
    assert _session_git.stage_and_commit(repo, target, "first")[0]

    target.write_text("- status: closed\n", encoding="utf-8")
    ok, why = _session_git.stage_and_commit(repo, target, "second")
    assert ok, why
    assert _commit_files(repo) == ["noni/sessions/2026-10-01-cccccc.md"]
    body = _git_ok(repo, "show", "HEAD:noni/sessions/2026-10-01-cccccc.md").stdout
    assert body == "- status: closed\n"


def test_stage_and_commit_reports_git_failure_without_an_exit_code(tmp_path):
    """The helper owns no exit code: every way it can fail comes back as
    ``(False, why)``, and a caller's single ``if not ok`` covers them all.

    Two fault classes, one shape: a path the repository does not contain (the
    helper's own words, and no ``ValueError`` escaping to the caller), and a git
    refusal (git's own words). Neither is an exit code, and neither raises.
    """
    repo = _repo(tmp_path)
    outside = tmp_path / "elsewhere.md"
    outside.write_text("x\n", encoding="utf-8")

    ok, why = _session_git.stage_and_commit(repo, outside, "nope")
    assert ok is False
    assert "not inside" in why, why

    # A git refusal names what git said, not the caller's commit message.
    missing = repo / "noni" / "sessions" / "absent.md"
    missing.parent.mkdir(parents=True)
    ok, why = _session_git.stage_and_commit(repo, missing, "nope")
    assert ok is False
    assert "nope" not in why, why
    assert "git" in why.lower(), why


# --- the path resolution the callers cannot get wrong ------------------------


def test_rel_of_refuses_a_path_outside_the_repo(tmp_path):
    """A path the repository does not contain has no repo-relative form; it is
    refused rather than quietly turned into ``../..`` something git would read
    against a different tree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ValueError):
        _session_git.rel_of(repo, tmp_path / "outside.md")
    # A sibling whose name merely starts with the repo's name is not inside it.
    with pytest.raises(ValueError):
        _session_git.rel_of(repo, tmp_path / "repo-evil" / "x.md")


def test_rel_of_resolves_a_relative_path_against_the_repo_not_the_cwd(tmp_path):
    """The bug this guard exists for.

    ``Path.resolve()`` resolves a path that does not exist yet by walking up to
    the nearest directory that does, so a file about to be created resolves to
    the directory above the repository — and a relative path handed to git
    without this normalisation is read against the caller's working directory.
    A tree containing a ``noni/`` directory then turns ``noni/sessions/x.md``
    into a write in some other repository.
    """
    repo = tmp_path / "repo"
    (repo / "noni" / "sessions").mkdir(parents=True)
    _git_ok(repo, "init", "-q", "-b", "main")

    cwd_before = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert _session_git.rel_of(repo, Path("noni/sessions/x.md")) == \
            "noni/sessions/x.md"
        # The bytes exist only inside the repo; a run that resolved the relative
        # name against the cwd would have looked beside it and found nothing.
        (tmp_path / "noni" / "sessions").mkdir(parents=True)
        (tmp_path / "noni" / "sessions" / "x.md").write_text("decoy\n",
                                                              encoding="utf-8")
        (repo / "noni" / "sessions" / "x.md").write_text("- status: active\n",
                                                         encoding="utf-8")
        ok, why = _session_git.stage_and_commit(repo, Path("noni/sessions/x.md"),
                                                "register: x")
        assert ok, why
    finally:
        os.chdir(cwd_before)

    # The file that landed is the repo's, and the decoy beside the cwd is
    # neither committed nor touched.
    committed = _git_ok(repo, "show", "HEAD:noni/sessions/x.md").stdout
    assert committed == "- status: active\n", committed
    assert (tmp_path / "noni" / "sessions" / "x.md").read_text(encoding="utf-8") == "decoy\n"


def test_git_always_talks_to_the_named_repo_whatever_the_cwd_says(tmp_path):
    """``-C`` carries an absolute path, so a relative ``--repo`` cannot be
    reinterpreted against wherever the process happened to start."""
    repo = _repo(tmp_path)
    cwd_before = os.getcwd()
    os.chdir(tmp_path)
    try:
        result = _session_git.git(Path("repo"), "rev-parse", "--absolute-git-dir")
    finally:
        os.chdir(cwd_before)
    assert result.returncode == 0
    assert result.stdout.strip() == str(repo / ".git")


# --- the hardened call -------------------------------------------------------


def test_the_git_helper_is_bounded_hardened_and_makes_no_signing_promise():
    """The four ``-c`` overrides and the timeout, tested where they live.

    A helper that silently dropped one would still pass every behavioural test,
    because an ordinary fixture repo has no hooks, no signing requirement and
    no fsmonitor helper to be bitten by."""
    seen: list[list[str]] = []
    bounds: list[dict] = []

    def spy(cmd, *args, **kwargs):
        seen.append(list(cmd))
        bounds.append(dict(kwargs))
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    proc = _session_git.git(Path("/nonexistent-repo"), "status", "--porcelain",
                            _run=spy)
    assert proc.returncode == 0
    assert len(seen) == 1, seen
    cmd = seen[0]
    assert cmd[:3] == ["git", "-C", "/nonexistent-repo"], cmd
    joined = " ".join(cmd)
    for hardening in ("-c commit.gpgsign=false", f"-c core.hooksPath={os.devnull}",
                      "-c protocol.ext.allow=never", "-c core.fsmonitor=false"):
        assert hardening in joined, f"{hardening} missing from {joined}"
    assert cmd[-2:] == ["status", "--porcelain"], cmd
    assert bounds[0].get("timeout") == _session_git.GIT_TIMEOUT, bounds[0]


def test_the_git_helper_hands_its_child_no_git_location_variables(monkeypatch):
    """The environment the helper passes, tested where the call is made.

    The behavioural proof is in ``tests/test_writer_git_env.py``; this pins the
    same property one level down, so a helper that dropped its ``env=`` fails
    here even before a writer is run. The location variables are the ones that
    relocate the child away from the ``-C`` path; the identity variables are not
    touched, because a commit made without them is a commit that fails.
    """
    seen: list[dict] = []

    def spy(cmd, *args, **kwargs):
        seen.append(dict(kwargs.get("env") or {}))
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    for name in gitenv.GIT_LOCATION_VARS:
        monkeypatch.setenv(name, "/hostile/" + name.lower())
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Replay")

    _session_git.git(Path("/nonexistent-repo"), "status", "--porcelain", _run=spy)

    assert len(seen) == 1, seen
    env = seen[0]
    for name in gitenv.GIT_LOCATION_VARS:
        assert name not in env, f"{name} reached the child: {env.get(name)!r}"
    assert env.get("GIT_AUTHOR_NAME") == "Replay", (
        "child_env removed a variable the commit needed: "
        "the identity must travel to the child"
    )


def test_a_hung_git_call_reports_the_timeout_code(tmp_path):
    """The helper converts its own timeout instead of raising, so every caller
    classifies a killed call the same way rather than ending in a traceback."""
    def hang(cmd, *args, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 60))

    proc = _session_git.git(tmp_path, "push", "origin", "main", _run=hang)
    assert proc.returncode == _session_git.GIT_TIMEOUT_RC != 0
    assert "timed out" in proc.stderr
    assert "push" in proc.stderr, "the message names which git call hung"


# --- atomic_write ------------------------------------------------------------


def test_atomic_write_leaves_the_old_bytes_when_the_write_fails(tmp_path, monkeypatch):
    """A crash mid-write leaves the previous file, never a truncated one, and no
    temp file is left beside it. This is why the writers do not call open()."""
    target = tmp_path / "s.md"
    target.write_text("original\n", encoding="utf-8")
    real_replace = os.replace

    def exploding_replace(src, dst, *args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", exploding_replace)
    with pytest.raises(OSError):
        _session_git.atomic_write(target, "replacement\n")
    monkeypatch.setattr(os, "replace", real_replace)

    assert target.read_text(encoding="utf-8") == "original\n"
    # No temp file is left beside it. Scoped to the temp names the helper uses,
    # because the suite's own isolation home also lives in tmp_path.
    assert [p.name for p in tmp_path.iterdir()
            if p.name.startswith(".s.md")] == [], list(tmp_path.iterdir())


def test_atomic_write_gives_a_new_file_the_mode_the_umask_allows(tmp_path):
    """mkstemp's 0600 must not survive: a session file the census cannot read is
    a broken register. An existing file keeps its own mode."""
    target = tmp_path / "new.md"
    _session_git.atomic_write(target, "text\n")
    assert _session_git.file_mode(target) == os.stat(target).st_mode & 0o777
    assert oct(os.stat(target).st_mode & 0o777) == oct(_session_git.file_mode(target))

    target.chmod(0o600)
    _session_git.atomic_write(target, "text again\n")
    assert oct(os.stat(target).st_mode & 0o777) == "0o600"


# --- the rebase classifier ---------------------------------------------------


def _pushable_clone(tmp_path):
    """A clone of a bare origin with one commit pushed, ready to diverge."""
    origin = tmp_path / "origin.git"
    clone = tmp_path / "clone"
    build_bare_origin(origin, [clone])
    return origin, clone


def _seed_ahead(origin: Path, tmp_path: Path, name: str,
                files: dict[str, str]) -> Path:
    """Clone ``origin``, commit ``files`` on main, push; return the working tree.

    The clone names ``main`` on the command line: the suite's sandboxed HOME
    carries no ``init.defaultbranch``, so a plain clone takes git's own default
    (master) and the push of ``main`` then has nothing to push.
    """
    seed = tmp_path / name
    seed.mkdir(parents=True)
    work = seed / "w"
    _git_ok(seed, "clone", "-q", "-b", "main", str(origin), str(work))
    for rel, content in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(content, encoding="utf-8")
        _git_ok(work, "add", rel)
    _git_ok(work, "-c", "user.name=Seeder", "-c", "user.email=seeder@fixture.invalid",
            "commit", "-q", "-m", f"seed: {name}")
    _git_ok(work, "push", "-q", "origin", "main")
    return work


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

    code = _session_git.fetch_rebase_push(
        clone, "main", attempts=2, label="close.py", exit_push_failed=3,
        exit_rebase_conflict=5, exit_rebase_refused=6)
    assert code == 5, (code, capsys.readouterr())
    err = capsys.readouterr().err
    assert "close.py:" in err, err
    assert "rebase conflict" in err, err
    # The clone is not left mid-rebase: the state directory is gone and HEAD
    # names the branch it was invoked on.
    assert _session_git._stopped_state_dir(clone) == (None, False)
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

    code = _session_git.fetch_rebase_push(
        clone, "main", attempts=2, label="release.py", exit_push_failed=3,
        exit_rebase_conflict=5, exit_rebase_refused=6)
    assert code in (5, 6), (code, capsys.readouterr().err)
    err = capsys.readouterr().err
    assert "release.py:" in err, err
    # Nothing was aborted behind the caller's back, and the branch is intact.
    assert _session_git._stopped_state_dir(clone)[0] is None
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
    assert _session_git._stopped_state_dir(repo) == (None, False)

    (git_dir / "rebase-merge").mkdir(parents=True)
    assert _session_git._stopped_state_dir(repo) == (None, True)

    # Positive evidence is both files reading back non-empty.
    (git_dir / "rebase-merge" / "head-name").write_text("refs/heads/main\n",
                                                        encoding="utf-8")
    (git_dir / "rebase-merge" / "onto").write_text("abc123\n", encoding="utf-8")
    state, indeterminate = _session_git._stopped_state_dir(tmp_path / "repo")
    assert state == git_dir / "rebase-merge", state
    assert indeterminate is False


# --- terminal statuses: the copy that must not drift -------------------------


def test_terminal_statuses_equal_the_census_inactive_sets():
    """This module holds a copy of the set, not an import (it must not depend on
    the census, and the census must not depend on it). The census owns the same
    answer twice over, and all three must agree: a status added on one side
    without the others is this test's failure, and the bug it catches is a
    closed session still counted in the double-claim check."""
    assert _session_git.TERMINAL_STATUSES == frozenset(
        census_sessions_mod._INACTIVE_STATUSES)
    assert _session_git.TERMINAL_STATUSES == frozenset(census_mod.INACTIVE_STATUSES)


def test_is_terminal_status_ignores_surrounding_space_and_case():
    """The field is read from a hand-editable file, so ' Closed ' and 'CLOSED'
    name the same ended session as 'closed'."""
    for spelling in ("closed", "  closed  ", "CLOSED", "Closed", "\tclosed\n"):
        assert _session_git.is_terminal_status(spelling), spelling
    for live in ("active", "", "   ", "open", "claimed"):
        assert not _session_git.is_terminal_status(live), live


# --- token validation --------------------------------------------------------


def test_valid_token_admits_one_clean_token_and_refuses_the_rest():
    """A token goes into a commit message and a file path, so whitespace and a
    separator are refused before either is reached. fullmatch, not match: a
    trailing newline must not sneak through ('$' matches before one)."""
    for good in ("developer", "reviewer", "#42", "2026-10-01-aaaaaa", "closed"):
        assert _session_git.valid_token(good), good
    for bad in ("", " ", "a b", "a/b", "a\\b", "a\n", "\nactive", "a b\n"):
        assert not _session_git.valid_token(bad), repr(bad)


# --- safe_text ---------------------------------------------------------------


def test_safe_text_strips_control_bytes_and_bounds_the_tail():
    """git's output can carry remote-side or credential-helper text, and an
    agent pipes it straight into tool output. Control bytes other than newline
    and space are dropped (no ANSI or OSC sequence reaches the terminal) and the
    tail past the limit is dropped with a marker."""
    noisy = "ok\x1b[2J\x07 done"
    cleaned = _session_git.safe_text(noisy)
    assert "\x1b" not in cleaned and "\x07" not in cleaned
    assert "ok" in cleaned and "done" in cleaned

    long = _session_git.safe_text("x" * (_session_git.GIT_OUTPUT_LIMIT + 50))
    assert long.endswith("... [truncated]")
    assert len(long) == _session_git.GIT_OUTPUT_LIMIT + len("... [truncated]")


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

    code = _session_git.fetch_rebase_push(
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
    assert _session_git.current_branch(clone) == ("main", "")

    _git_ok(clone, "checkout", "-q", "--detach")
    branch, why = _session_git.current_branch(clone)
    assert branch is None
    assert "detached HEAD" in why, why
