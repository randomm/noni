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
import subprocess
from pathlib import Path, PurePosixPath

import pytest
from _harness import _git_env_with_identity, _git_ok
from session_git_support import (
    _commit_files,
    _gone_upstream_clone,
    _pushable_clone,
    _repo,
    _seed_ahead,
)

from noni import _commit_cause, _session_git


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
    rel = _session_git.session_name("2026-10-01-aaaaaa")
    target = repo / rel
    target.parent.mkdir(parents=True)
    target.write_text("- status: active\n", encoding="utf-8")

    ok, why = _session_git.stage_and_commit(repo, rel, "register: 2026-10-01-aaaaaa")
    assert ok, why
    assert _commit_files(repo) == ["noni/sessions/2026-10-01-aaaaaa.md"]
    assert _git_ok(repo, "log", "-1", "--format=%s").stdout.strip() == \
        "register: 2026-10-01-aaaaaa"


def test_stage_and_commit_carries_only_its_own_path(tmp_path):
    """Two changed files, one commit: the other stays unstaged-or-staged and
    uncommitted, which is the whole point of the three-step primitive."""
    repo = _repo(tmp_path)
    mine_rel = _session_git.session_name("2026-10-01-bbbbbb")
    mine = repo / mine_rel
    mine.parent.mkdir(parents=True)
    mine.write_text("- status: active\n", encoding="utf-8")
    theirs = repo / "noni" / "decisions" / "theirs.json"
    theirs.parent.mkdir(parents=True)
    theirs.write_text('{"a": 1}\n', encoding="utf-8")
    # Someone else staged theirs before this writer ran; the writer must not
    # sweep it in and must not unstage it either.
    _git_ok(repo, "add", "noni/decisions/theirs.json")

    ok, why = _session_git.stage_and_commit(repo, mine_rel, "register: b")
    assert ok, why
    assert _commit_files(repo) == ["noni/sessions/2026-10-01-bbbbbb.md"]
    assert "A  noni/decisions/theirs.json" in _git_ok(repo, "status", "--porcelain").stdout


def test_stage_and_commit_rewrites_a_previously_committed_file(tmp_path):
    """The amend path of the same primitive: the second commit carries only the
    new bytes of the same path."""
    repo = _repo(tmp_path)
    rel = _session_git.session_name("2026-10-01-cccccc")
    target = repo / rel
    target.parent.mkdir(parents=True)
    target.write_text("- status: active\n", encoding="utf-8")
    assert _session_git.stage_and_commit(repo, rel, "first")[0]

    target.write_text("- status: closed\n", encoding="utf-8")
    ok, why = _session_git.stage_and_commit(repo, rel, "second")
    assert ok, why
    assert _commit_files(repo) == ["noni/sessions/2026-10-01-cccccc.md"]
    body = _git_ok(repo, "show", "HEAD:noni/sessions/2026-10-01-cccccc.md").stdout
    assert body == "- status: closed\n"


def test_stage_and_commit_reports_git_failure_without_an_exit_code(tmp_path):
    """The helper owns no exit code: every way it can fail comes back as
    ``(False, why)``, and a caller's single ``if not ok`` covers them all.

    Three fault classes, one shape: a name that is not one inside the state root
    (the helper's own words, and no ``ValueError`` escaping to the caller), a
    state root that is a symlink, and a git refusal (git's own words). None is an
    exit code, and none raises.
    """
    repo = _repo(tmp_path)

    ok, why = _session_git.stage_and_commit(repo, "../elsewhere.md", "nope")
    assert ok is False
    assert "inside the state root" in why, why

    # A git refusal names what git said, not the caller's commit message.
    missing = repo / "noni" / "sessions" / "absent.md"
    missing.parent.mkdir(parents=True)
    ok, why = _session_git.stage_and_commit(repo, "noni/sessions/absent.md", "nope")
    assert ok is False
    assert "nope" not in why, why
    assert "git" in why.lower(), why

    # A state root that is itself a symlink: the refusal the writers make before
    # they touch the tree is repeated here, in noni's words, so the primitive
    # cannot be driven around it by a caller that skipped its own check.
    link = tmp_path / "state-link"
    link.symlink_to(repo)
    ok, why = _session_git.stage_and_commit(link, "noni/sessions/absent.md", "nope")
    assert ok is False
    assert "symlink" in why, why
    assert str(repo.resolve()) in why, why


# --- the name the callers hand the primitive --------------------------------


def test_relative_name_refuses_every_spelling_that_leaves_the_root():
    """The explicit-name contract: only a path inside the state root is a name.

    No ``--repo`` heuristic sits behind this: the primitive takes a name and
    never reads one against the process working directory, so the shapes that
    used to be *guessed* at are now simply refused. Absolute is refused because
    ``git add`` accepts an absolute pathspec from outside the ``-C`` tree,
    returns 0 and stages nothing -- a silent nothing-landed. ``..`` is refused
    because a pathspec that walks out of the root is git reading another tree.
    ``./`` and ``//`` normalise rather than being refused: the caller meant the
    same file, and a normalised name is the one string the writer prints, stages
    and probes.
    """
    assert _session_git.relative_name("noni/sessions/x.md") == "noni/sessions/x.md"
    assert _session_git.relative_name(PurePosixPath("noni/sessions/x.md")) == \
        "noni/sessions/x.md"
    assert _session_git.relative_name("./noni/sessions/x.md") == "noni/sessions/x.md"
    assert _session_git.relative_name("noni//sessions/x.md") == "noni/sessions/x.md"
    assert _session_git.relative_name("noni/sessions/../other.md") == \
        "noni/other.md"
    for bad in ("/tmp/x.md", "/noni/sessions/x.md", "//server/share/x.md",
                "../x.md", "noni/../../x.md", "..", ".", ""):
        assert _session_git.relative_name(bad) == "", bad
    # An absolute name is refused on its way in rather than left for git to
    # answer: whether git accepts one depends on where it points, so the one
    # verdict a writer may print about it is its own, and it must not depend on
    # the filesystem. (See the refusal test below for the primitive's half.)
    # A backslash inside a name is a separator, not a character: the Windows
    # spelling of the same file is the same name.
    assert _session_git.relative_name("noni\\sessions\\x.md") == "noni/sessions/x.md"


def test_session_name_is_the_one_spelling_the_writers_share():
    """One derivation for the four writers: the name they write, stage, print and
    probe is this function's answer and nothing else."""
    name = _session_git.session_name("2026-10-01-aaaaaa")
    assert name == "noni/sessions/2026-10-01-aaaaaa.md"
    assert name == f"{_session_git.SESSIONS_REL}/2026-10-01-aaaaaa.md"
    assert _session_git.relative_name(name) == name


def test_a_name_is_committed_against_the_repo_and_never_the_cwd(tmp_path):
    """The bug the name contract exists for, now that no path reaches the primitive.

    A name is joined to ``repo`` and nothing else, so a decoy tree beside the
    cwd -- the shape a project carrying its own ``noni/`` directory presents --
    is neither written nor committed, whatever the process is standing in. The
    old form of this test handed the primitive a relative *path* and asked it to
    guess where the path came from; the contract makes the guess impossible, so
    the same tree now pins that ``repo / name`` is where the bytes land.
    """
    repo = tmp_path / "repo"
    (repo / "noni" / "sessions").mkdir(parents=True)
    _git_ok(repo, "init", "-q", "-b", "main")
    _git_ok(repo, "config", "user.name", "Replay")
    _git_ok(repo, "config", "user.email", "replay@fixture.invalid")

    # The decoy tree beside the cwd, with a file at the very name this run owns.
    (tmp_path / "noni" / "sessions").mkdir(parents=True)
    decoy = tmp_path / "noni" / "sessions" / "x.md"
    decoy.write_text("decoy\n", encoding="utf-8")
    (repo / "noni" / "sessions" / "x.md").write_text("- status: active\n",
                                                     encoding="utf-8")

    cwd_before = os.getcwd()
    os.chdir(tmp_path)
    try:
        ok, why = _session_git.stage_and_commit(repo, "noni/sessions/x.md",
                                                "register: x")
        assert ok, why
    finally:
        os.chdir(cwd_before)

    # The file that landed is the repo's, and the decoy beside the cwd is
    # neither committed nor touched.
    committed = _git_ok(repo, "show", "HEAD:noni/sessions/x.md").stdout
    assert committed == "- status: active\n", committed
    assert decoy.read_text(encoding="utf-8") == "decoy\n"


def test_stage_and_commit_refuses_a_name_that_is_not_inside_the_root(tmp_path):
    """The backstop the writers do not rely on: a name that escapes the root never
    reaches git at all.

    Every writer asks the same question before it writes a byte, so this is the
    second line of defence -- and the one that matters for a caller that forgot
    to ask. An absolute pathspec is the dangerous shape: ``git add`` accepts one
    outside the ``-C`` tree, exits 0 and stages nothing, so a writer that admitted
    it would report a commit that carried no file.
    """
    repo = _repo(tmp_path)
    (repo / "noni" / "sessions").mkdir(parents=True)
    (repo / "noni" / "sessions" / "x.md").write_text("- status: active\n",
                                                      encoding="utf-8")
    head_before = _git_ok(repo, "rev-parse", "HEAD").stdout.strip()

    for bad in (str(repo / "noni" / "sessions" / "x.md"), "../outside.md",
                "noni/sessions/../../../outside.md", ".", ""):
        ok, why = _session_git.stage_and_commit(repo, bad, "nope")
        assert ok is False, bad
        assert "inside the state root" in why, why

    # Nothing reached git: HEAD unmoved, and the index holds no entry for a path
    # this run was refused.
    assert _git_ok(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert _git_ok(repo, "diff", "--cached", "--name-only").stdout.split() == []


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


# --- the cause of a failed commit -------------------------------------------
#
# The three-step primitive's failure half is the one an operator reads after a
# writer exited 3 with its file already written, so what it says is the
# contract: one noni-worded clause naming which of the four states the tree is
# in, git's own words after it rather than in place of them, and the path this
# run wrote named by the writer around it.


def _tracked_session(repo):
    """One committed session file under ``repo``, at a fixed path.

    Committed through the primitive itself, which is the point: the cause
    tests below ask what the primitive says about the state this helper built,
    so a baseline that did not land must fail here and not silently become a
    'nothing to commit' the tree never had.
    """
    rel = _session_git.session_name("2026-10-01-dddddd")
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("- status: active\n", encoding="utf-8")
    ok, why = _session_git.stage_and_commit(repo, rel, "register: d")
    if not ok:
        raise AssertionError(f"the fixture could not commit its baseline: {why}")
    shown = _git_ok(repo, "rev-list", "--count", "HEAD").stdout.strip()
    if shown == "0":
        raise AssertionError("the fixture's baseline commit is not on HEAD")
    return target


def test_a_commit_that_found_nothing_to_commit_names_that_cause(tmp_path):
    """The state release and close reach when the row or status already matches
    HEAD: the file was written, git found nothing to commit, and the run must
    say so instead of echoing a status block. The tree has a real upstream here
    (the gone-upstream case is the test below), so the cause can only be the
    empty diff, and the porcelain is checked as the fixture's precondition.

    A dirty path the writer does not own is planted alongside its own: the
    probes are scoped to the writer's path, so that unrelated dirt must not turn
    the answer into 'something changed' and lose the clause the operator needs.
    """
    origin, clone = _pushable_clone(tmp_path)
    _commit_files(clone)  # the fixture's own baseline commit exists
    target = _tracked_session(clone)
    target.write_text("- status: active\n", encoding="utf-8")
    unrelated = clone / "notes.md"
    unrelated.write_text("somebody else's dirty file\n", encoding="utf-8")
    assert _git_ok(clone, "status", "--porcelain", "--",
                   "noni/sessions/2026-10-01-dddddd.md").stdout == ""  # (no-op write)

    ok, why = _session_git.stage_and_commit(clone, _session_git.session_name("2026-10-01-dddddd"), "close: d")

    assert ok is False, why
    assert _commit_cause.NOTHING_TO_COMMIT in why, why
    # The commit did not happen: HEAD is still the register commit.
    assert _commit_files(clone) == ["noni/sessions/2026-10-01-dddddd.md"]
    assert origin.is_dir()


def test_a_diverged_clone_still_commits(tmp_path):
    """A clone whose origin moved ahead still commits: the divergence is the
    push's problem, not the commit's.

    The upstream resolves and the index carries a real change, so this is none
    of the four named states and nothing here should refuse the write. The tree
    is built by hand (a clone whose origin moved ahead) rather than by the
    gone-upstream fixture, because that fixture's whole point is a ref that does
    not resolve.
    """
    origin, clone = _pushable_clone(tmp_path)
    _seed_ahead(origin, tmp_path, "ahead", {"other.md": "moved\n"})
    target = _tracked_session(clone)
    target.write_text("- status: closed\n", encoding="utf-8")

    ok, why = _session_git.stage_and_commit(clone, _session_git.session_name("2026-10-01-dddddd"), "close: d")

    assert ok is True, why
    assert origin.is_dir()


def _git_commit(repo, message, rel):
    """Commit ``rel`` in ``repo`` under the harness identity, with the host's config.

    The writer's own helper neutralises the host's git config, which is what
    makes an unpushable tree look healthy here: with ``GIT_CONFIG_GLOBAL``
    pointing at ``/dev/null`` git cannot read the host's ``user.name``, so the
    commit git never gets to make has a cause named for it. A commit made
    through this helper is the control for that -- git ran with the caller's
    environment and its verdict is git's, not the harness's.
    """
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=Replay",
                           "-c", "user.email=replay@fixture.invalid",
                           "commit", "-q", "-m", message, "--only", "--", rel],
                          capture_output=True, text=True)


def test_a_commit_git_accepted_reports_no_cause(tmp_path):
    """The cause half speaks only about a call that failed.

    A tree with no upstream at all is the state most likely to be guessed at
    (a fresh private state repository never pushed), so it is the one to check
    an accepted commit against: git took the commit, and the classifier says
    nothing, because a run that succeeded and was told to fix its upstream is a
    run sent to fix something that was never wrong. The commit itself is proved
    by the same ``git`` the writer shells out to, not by the writer's verdict.
    """
    repo = _repo(tmp_path)  # no remote at all: nothing was ever pushed
    assert _git_ok(repo, "rev-parse", "--verify", "--quiet", "HEAD").returncode == 0
    target = _tracked_session(repo)
    rel = "noni/sessions/2026-10-01-dddddd.md"
    target.write_text("- status: active\n- note: second run\n", encoding="utf-8")
    assert _git_ok(repo, "status", "--porcelain").stdout.strip() != ""
    assert _git_commit(repo, "control", rel).returncode == 0  # the state is committable
    target.write_text("- status: active\n- note: third run\n", encoding="utf-8")

    ok, why = _session_git.stage_and_commit(repo, _session_git.session_name("2026-10-01-dddddd"), "close: d")

    assert ok is True, why
    assert why == ""
    assert _git_ok(repo, "log", "-1", "--format=%s").stdout.strip() == "close: d"
    # The same tree with a real upstream, and a writer that owns a path of its
    # own to ask about: a failed call there is answered by the probes, and an
    # accepted call has no cause to name at all.
    origin, clone = _pushable_clone(tmp_path, name="cause-check")
    _tracked_session(clone)
    assert _commit_cause.commit_failure_cause(
        clone, subprocess.CompletedProcess([], 1, "", "")) is None
    assert _commit_cause.commit_failure_cause(
        repo, subprocess.CompletedProcess([], 0, "", "")) is None
    assert origin.is_dir()


def test_a_commit_whose_upstream_origin_deleted_names_that_cause(tmp_path):
    """The upstream is gone: origin's branch was deleted and the clone's
    remote-tracking ref pruned with it. The cause is read from git's own
    answers, so it holds whatever wording git prints for the state."""
    origin, clone = _gone_upstream_clone(tmp_path)
    target = _tracked_session(clone)
    target.write_text("- status: active\n", encoding="utf-8")

    ok, why = _session_git.stage_and_commit(clone, _session_git.session_name("2026-10-01-dddddd"), "close: d")

    assert ok is False, why
    assert _commit_cause.UPSTREAM_GONE in why, why
    assert origin.is_dir()


def test_the_failure_line_names_the_cause_and_keeps_git_sown_words(tmp_path):
    """One line: noni's clause first, git's own sanitised words after it.

    Both halves matter. The clause is what an operator acts on; git's words are
    the evidence, bounded and stripped of control bytes and newlines on the way
    out. The message carries no raw status block on its own and no commit
    subject.
    """
    repo = _repo(tmp_path)
    target = _tracked_session(repo)
    target.write_text("- status: active\n", encoding="utf-8")

    ok, why = _session_git.stage_and_commit(repo, _session_git.session_name("2026-10-01-dddddd"), "register: secret-subject")

    assert ok is False
    assert why.count("\n") == 0, why  # one line, whatever git printed
    assert why.startswith("git could not commit -- "), why
    assert "register: secret-subject" not in why, why


def test_a_failure_git_explained_nothing_reports_no_invented_cause(tmp_path):
    """When no probe answered, the line quotes git and asserts nothing.

    A cause is a claim about the tree. ``commit_failure_cause`` returns None
    rather than guess, and the message falls back to git's words so an operator
    is not sent to fix an upstream that was there all along. The tree here has
    a real, resolving upstream, so the None is the probes' answer and not the
    absence of anything to ask about.
    """
    origin, clone = _pushable_clone(tmp_path, name="silent-cause")
    _tracked_session(clone)
    silent = subprocess.CompletedProcess([], 1, "", "")
    assert _commit_cause.commit_failure_cause(clone, silent) is None
    line = _commit_cause.commit_failed(clone, subprocess.CompletedProcess(
        [], 1, "", "fatal: some git fault"))
    assert "fatal: some git fault" in line, line
    assert origin.is_dir()


def test_session_status_reads_the_field_the_census_would_act_on():
    """One field reader for the three writers that read it.

    Last occurrence wins and surrounding space is dropped, which is what the
    census's parser does: a file whose two status lines disagree must not be
    'active' to claim.py and 'closed' to close.py.
    """
    assert _session_git.session_status("- status: active\n") == "active"
    assert _session_git.session_status(
        "  - status: active\n- status: closed\n") == "closed"
    assert _session_git.session_status("- identity: dev\n") is None
    assert _session_git.session_status("- status:\n") is None
    assert _session_git.is_terminal_status(" Superseded ")
    assert not _session_git.is_terminal_status("active")
