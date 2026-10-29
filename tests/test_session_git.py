"""``_session_git``'s commit primitive and the paths it hands to git.

The primitive is the one commit three steps register.py, claim.py, close.py and
release.py build on, so the properties worth testing are the ones every writer
inherits: the steps run in the order that commits a never-before-seen path, only
the named path lands in the commit, nobody else's staged entry is touched, and a
failure comes back as ``(False, why)`` rather than an exit code or a raised
``ValueError``.

The path half is the guard the callers cannot get wrong: ``Path.resolve()``
resolves a not-yet-created file to the directory above the repository, so a
relative path handed to git unnormalised is read against the caller's working
directory — and ``-C`` carries an absolute path precisely so a relative
``--repo`` cannot be reinterpreted against wherever the process started.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from _harness import _git_env_with_identity, _git_ok
from session_git_support import _commit_files, _repo

from noni import _session_git


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
