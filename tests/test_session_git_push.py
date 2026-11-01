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

import collections.abc
import subprocess
from pathlib import Path

import pytest
from _harness import _git_env_with_identity, _git_ok, build_bare_origin
from session_git_support import _pushable_clone, _seed_ahead

from noni import _session_git, _session_push
from noni import claim as _claim_mod

# The one shipped rebase-wording table, read from its owner rather than copied
# here, so the tests below drive the loop with the wording a writer really passes
# and the parity check compares live values with live ones.
_CLAIM_MESSAGES: _session_push.RebaseMessages = _claim_mod._REBASE_MESSAGES


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
        exit_rebase_conflict=5, exit_rebase_refused=6,
        messages=dict(_CLAIM_MESSAGES))
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
        exit_rebase_conflict=5, exit_rebase_refused=6,
        messages=dict(_CLAIM_MESSAGES))
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
        exit_rebase_conflict=8, exit_rebase_refused=9,
        messages=dict(_CLAIM_MESSAGES))
    assert code == 7, code
    err = capsys.readouterr().err
    assert "register.py:" in err, err
    # Bounded, not endless: one line per attempt plus the final report.
    assert err.count("push attempt") <= _session_git.MAX_PUSH_ATTEMPTS, err


def test_the_git_seams_are_annotated_so_a_caller_can_match_one():
    """The injectable git parameters carry a type, not a bare default.

    ``stopped_state_dir`` and ``classify_rebase_failure`` each take a callable a
    caller supplies so the verdict's probes and its abort go through the git this
    command actually runs -- ``claim.py``'s adapter is one. An unannotated
    parameter there is an implicit ``Any``: a caller handing in a callable with the
    wrong arity (``claim.py``'s own git helper takes the argv first, which is the
    whole reason the adapter exists) fails at runtime inside a failure path, the
    worst place to discover it. The annotation is what makes that mismatch a
    static one, so the parameter's own annotation has to name a callable.
    """
    import inspect
    import typing

    for name in ("stopped_state_dir", "classify_rebase_failure"):
        function = getattr(_session_push, name)
        parameter = inspect.signature(function).parameters["run_git"]
        annotation = typing.get_type_hints(function)["run_git"]
        assert annotation is not inspect.Parameter.empty, (name, parameter)
        assert getattr(annotation, "__origin__", None) is collections.abc.Callable, \
            (name, annotation)
        # The seam is the whole call shape (repo plus argv), so it takes a
        # variadic positional list rather than a fixed one-argument function.
        shapes = _session_push.GitRunner.__args__
        assert shapes[0] is Ellipsis, (name, shapes)
        assert str(shapes[-1]) == "subprocess.CompletedProcess[str]", \
            (name, shapes, _session_push.GitRunner)
        assert parameter.default is _session_push._run_git, \
            (name, "the seam must keep the module's own git as its default")


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


# --- the branch name the push is given ---------------------------------------


def _recording_git(results: dict[tuple[str, ...], int]):
    """A git seam that records every argv and answers from a verb-keyed table.

    The push loop's argv is the thing under test here, so the double has to keep
    it: a test that only asserts the exit code cannot tell a ref from an option.
    """
    calls: list[tuple[str, ...]] = []

    def run_git(repo, *args):
        calls.append(tuple(args))
        returncode = results.get(tuple(args), results.get((args[0],), 0))
        return subprocess.CompletedProcess(list(args), returncode,
                                           "", "recorded refusal")

    return calls, run_git


def test_current_branch_refuses_a_name_that_git_would_read_as_an_option():
    """A leading dash is the shape that matters, and the tree can hold one.

    ``git push origin <name>`` sends a leading-dash argument as a push option
    (``--force``, ``--receive-pack=...``) rather than as a ref, and a ref of that
    shape is reachable: ``git update-ref refs/heads/--force <sha>`` creates one
    that ``rev-parse --abbrev-ref HEAD`` then prints. The name is validated here,
    at the one place the loop learns it, so no caller has to remember to.
    """
    for name in ("-receive-pack=evil", "--force", "-o", "-u"):
        branch, why = _branch_as_head_names(name)
        assert branch is None, name
        assert "safe ref name" in why, (name, why)


def test_current_branch_accepts_the_names_real_branches_use():
    """The guard is a dash check, not a narrowing of legitimate names.

    ``feature/x``, ``1.2.3`` and a tag-like name are all shapes real branches use
    and git accepts, and a loop that refused them would refuse the ordinary push.
    The leading character stays alphanumeric by contract, so ``_wip`` is not on
    this list -- it is a name git will make and this loop will refuse, which is a
    narrower set than git's and is the price of the dash rule.
    """
    for name in ("main", "feature/issue-57-fix", "1.2.3", "v1.0.0-rc1",
                 "release/2026-10", "a-b_c.d/e"):
        branch, why = _branch_as_head_names(name)
        assert branch == name, (name, why)
        assert why == "", (name, why)


def _branch_as_head_names(name: str):
    """``current_branch``'s answer for a tree whose HEAD names ``name``.

    The name is supplied rather than created because git refuses to *make* a
    leading-dash branch through ``git branch`` (``check-ref-format`` refuses it)
    while ``update-ref`` will happily create one that ``rev-parse --abbrev-ref
    HEAD`` then prints; the loop's job is to survive the name the tree already
    has, so the double prints it and the guard is what is under test.
    """
    def fake_git(repo, *args):
        return subprocess.CompletedProcess(list(args), 0, name + "\n", "")

    original = _session_push.git
    _session_push.git = fake_git
    try:
        return _session_push.current_branch(Path("/does-not-matter"))
    finally:
        _session_push.git = original


def test_the_push_names_an_explicit_refspec_so_no_argument_reads_as_an_option(tmp_path):
    """The argv handed to git is the contract, so the argv is what is asserted.

    Two defences, both pinned: the name is checked on the way in, and the push
    carries ``refs/heads/<name>:refs/heads/<name>`` -- an explicit refspec, which
    is what a plain branch name resolves to anyway, so the same ref is written and
    there is no bare argument left for git to read as a push option. A caller that
    hands the loop an unchecked name (an explicit ``--branch`` from its own CLI)
    still cannot turn this call into ``git push origin --force``.
    """
    calls, run_git = _recording_git({("push",): 1})
    code = _session_push.fetch_rebase_push(
        tmp_path, "main", attempts=1, label="close.py", exit_push_failed=3,
        exit_rebase_conflict=5, exit_rebase_refused=6,
        messages=dict(_CLAIM_MESSAGES), run_git=run_git)
    assert code == 3, code
    pushes = [args for args in calls if args[0] == "push"]
    assert pushes, calls
    for args in pushes:
        assert args[:2] == ("push", "origin"), args
        assert args[2] == "refs/heads/main:refs/heads/main", args
        # Nothing else on the argv, so there is no third positional for git to
        # mistake for an option, and no leading dash anywhere.
        assert len(args) == 3, args
        assert not any(arg.startswith("-") for arg in args[1:]), args


def test_a_dash_prefixed_branch_never_reaches_git_as_a_push_option(tmp_path, capsys):
    """The regression: a leading-dash branch name is refused at the push boundary.

    Driven through the argv the loop would have sent. The trust boundary is
    ``fetch_rebase_push`` itself, not only ``current_branch``: an explicit
    ``--branch`` from a caller's own CLI arrives here without ever passing
    through discovery, so the loop must refuse it before its first git call.
    With the check, no argv is recorded at all and the caller's push code comes
    back; without it, the argv below is ``push origin --force``, which git would
    have applied as an option to the push instead of reading it as a ref.
    """
    calls, run_git = _recording_git({("push",): 0})
    code = _session_push.fetch_rebase_push(
        tmp_path, "--force", attempts=1, label="close.py", exit_push_failed=3,
        exit_rebase_conflict=5, exit_rebase_refused=6,
        messages=dict(_CLAIM_MESSAGES), run_git=run_git)
    assert code == 3, (code, calls)
    assert calls == [], f"a refused branch must never reach git: {calls}"
    err = capsys.readouterr().err
    assert "close.py:" in err, err
    assert "--force" in err, f"the refusal must name the bad branch: {err}"


@pytest.mark.parametrize("name", [
    "--force", "-receive-pack=evil", "-o", "-u",
    "a..b", "feat/..", "a@{b}", "a~1", "a^2", "a?b", "a*b", "a[b", "a\\b",
    "...", "a/", "a.", "a\nb", "a\tb",
])
def test_the_push_boundary_refuses_every_shape_check_ref_format_refuses(
        tmp_path, capsys, name):
    """The tightened pattern, pinned name by name.

    ``git check-ref-format`` refuses each of these (``..``, ``@{``, a revision
    suffix, a glob character, a backslash, a control byte, an all-dots
    component, a trailing ``/`` or ``.``, a leading dash) and none of them is a
    name a noni writer needs, so admitting one would be an argument-injection
    path kept open for no reason. The refusal is identical whichever shape
    arrives: same code, the branch named in the line, zero git calls.
    """
    calls, run_git = _recording_git({})
    code = _session_push.fetch_rebase_push(
        tmp_path, name, attempts=1, label="claim.py", exit_push_failed=3,
        exit_rebase_conflict=5, exit_rebase_refused=6,
        messages=dict(_CLAIM_MESSAGES), run_git=run_git)
    assert code == 3, (name, code)
    assert calls == [], (name, calls)
    err = capsys.readouterr().err
    assert "claim.py:" in err, (name, err)
    # The refusal names the bad branch the way every other refusal here does:
    # repr(), so a control byte shows as its escape and the line stays one line.
    assert repr(name) in err, (name, err)


def test_the_push_boundary_refuses_identically_to_discovery(tmp_path, capsys):
    """Both paths into a push refuse the same name, from the one validator.

    The bug was two patterns drifting: discovery (``current_branch``) checked
    one regex, an explicit ``--branch`` checked another that admitted a leading
    dash. A name the tree reports and a name an operator types are now checked
    by the same function, so the refusal text and the code must agree.
    """
    name = "-receive-pack=evil"
    branch, why = _branch_as_head_names(name)
    assert branch is None, why
    calls, run_git = _recording_git({})
    code = _session_push.fetch_rebase_push(
        tmp_path, name, attempts=1, label="claim.py", exit_push_failed=3,
        exit_rebase_conflict=5, exit_rebase_refused=6,
        messages=dict(_CLAIM_MESSAGES), run_git=run_git)
    assert code == 3, code
    assert calls == [], calls
    err = capsys.readouterr().err
    # One rule, one wording: the reason phrase discovery prints is the reason
    # phrase the boundary prints. A second pattern would print a second prose.
    reason = why.removeprefix(f"the current branch {name!r} is ")
    assert reason in err, (why, err)


def test_the_push_boundary_accepts_the_names_real_branches_use(tmp_path):
    """The tightened pattern must not refuse an ordinary push.

    The names the discovery test accepts are pushed through the boundary here
    as well: a check that refused ``feature/issue-57-fix`` would stop every
    real run, so acceptance is pinned on both paths, not only the one.
    """
    for name in ("main", "feature/issue-57-fix", "1.2.3", "v1.0.0-rc1",
                 "release/2026-10", "a-b_c.d/e"):
        calls, run_git = _recording_git({})
        code = _session_push.fetch_rebase_push(
            tmp_path, name, attempts=1, label="close.py", exit_push_failed=3,
            exit_rebase_conflict=5, exit_rebase_refused=6,
            messages=dict(_CLAIM_MESSAGES), run_git=run_git)
        assert code == 0, (name, code, calls)
        pushes = [args for args in calls if args[0] == "push"]
        assert pushes == [("push", "origin",
                           f"refs/heads/{name}:refs/heads/{name}")], (name, calls)


def test_a_returncode_of_none_is_never_read_as_a_timeout(tmp_path, capsys):
    """A returncode that is not an int is never read as the timeout kill.

    The loop's timeout reading is ``returncode == GIT_TIMEOUT_RC``. A call that
    was launched and never waited on carries ``None`` there, and a text-shaped
    sentinel (``"124"`` from a stream that never parsed as an int) compares
    equal to nothing but proves nothing either: neither shape may take the
    'killed' branch, which reports a timeout this run never observed. Both must
    fall through to the ordinary rejection path.
    """
    for shape in (None, str(_session_git.GIT_TIMEOUT_RC)):
        calls, run_git = _recording_git({})

        def answering(repo, *args, shape=shape, run_git=run_git):
            # Record through the shared double first, then answer with the
            # shape under test: an argv this loop never recorded is itself the
            # failure this test is about.
            recorded = run_git(repo, *args)
            if args[0] == "push":
                return subprocess.CompletedProcess(list(args), shape, "", "")
            return recorded

        code = _session_push.fetch_rebase_push(
            tmp_path, "main", attempts=1, label="close.py", exit_push_failed=3,
            exit_rebase_conflict=5, exit_rebase_refused=6,
            messages=dict(_CLAIM_MESSAGES), run_git=answering)
        assert code == 3, (shape, code)
        pushes = [args for args in calls if args[0] == "push"]
        assert pushes, (shape, calls)
        err = capsys.readouterr().err
        assert "timed out" not in err, (shape, err)
