"""Rebase rules for claim.py: a conflicted rebase aborts, an absent one is 6.

Extracted from the claim suite: the push-with-rebase path, asserted with git
plumbing only so the fixture never depends on a working-tree state."""

import re
import subprocess
from pathlib import Path

from _harness import (
    SRC,
    _claim_module,
    _git,
    _script_ast,
    _script_constant,
    advance_origin_with_claim,
    build_bare_origin,
    run_claim,
    run_register,
)
from claim_fixtures import (
    _git_blob,
    _git_text,
)
from claim_rebase_support import _stopped_rebase_git


def _rebase_state_paths(repo: Path) -> list[Path]:
    """The directories a stopped rebase can leave, resolved through git itself
    (plumbing only: rev-parse --git-path, never a hand-built .git).

    The names come from the module that owns the constant,
    ``_session_rebase_state.py``, read as a literal out of that file: the probe
    lives there, so the set this file asserts on and the set the probe examines
    are one list, and a backend directory added to the constant is probed and
    asserted rather than half of it. Read from the owner rather than from
    ``claim.py`` because that module only imports the name: a second literal
    beside the real one would be a copy this helper could read while the probe
    answered something else.
    """
    out = []
    tree = _script_ast(SRC / "noni" / "_session_rebase_state.py")
    for name in _script_constant(tree, "REBASE_STATE_DIRS",
                                 "_session_rebase_state.py"):
        raw = Path(_git_text(repo, "rev-parse", "--git-path", name))
        out.append(raw if raw.is_absolute() else repo / raw)
    return out


def _seed_ahead_of_tracking_ref(
    origin: Path, clone: Path, session_file: str, expected_row: str | None = None
) -> str:
    """Move ``origin`` ahead of ``clone`` without ``clone`` ever fetching.

    The distinction matters: claim.py rebases onto origin/<branch>, which git
    resolves against its own remote-tracking ref, not against the real tip.
    A clone that has already fetched the seed commit finds itself up to date,
    its rebase is a no-op, and the push goes through - so the fetch-rebase-push
    branch would never be entered and a conflict or refusal test would pass on
    nothing. Seeding through a throwaway clone leaves the caller's
    origin/<branch> stale: the push is then rejected on every attempt, and the
    rebase is what the test is actually about.

    Returns the seed commit's sha. With ``expected_row`` the seeded commit is
    read back through git and asserted to end with that row: a seeder that wrote
    nowhere near ``session_file`` would leave the caller's rebase a no-op, and
    the test would then fail on a return code instead of naming the broken
    fixture.
    """
    sha = advance_origin_with_claim(origin, clone.parent / "seeder", session_file, "#99")
    assert _git_text(clone, "rev-parse", "origin/main") != sha, (
        "precondition: the clone must not already hold the seed commit in "
        "origin/main, or its rebase is a no-op and the push never gets rejected"
    )
    if expected_row is not None:
        # Read the seeded file from origin's own copy of the commit: the clone
        # cannot have it (that is the point of the stale ref), so origin is the
        # right place to ask, and it is the copy every later push is judged
        # against. The seeder appends the row at file EOF, so it must be last.
        seeded = _git_blob(origin, sha, session_file)
        assert "- claims:" in seeded and seeded.rstrip().endswith(expected_row), (
            f"precondition: seed commit {sha[:7]} must carry the register at "
            f"{session_file} ending with {expected_row!r}; it reads "
            f"{seeded[-80:]!r}"
        )
    return sha


def _precondition_rebase_stops(repo: Path, branch: str) -> None:
    """Prove the rebase actually ran and stopped in a conflict, from evidence.

    A run that never entered a rebase (a no-op seed, a push that was never
    rejected) reaches none of the classifier's branches, so the exit-5 and
    exit-6 tests would pass on nothing. git leaves a trail of exactly that in
    the reflog: a rebase that ran records a line naming the branch it was
    rebased onto. Must be called after the run whose behaviour is under test
    (the rebase is in this clone's reflog, and a probe run of our own would
    move HEAD and make the branch assertion below meaningless).
    """
    reflog = _git_text(repo, "reflog", "--format=%gs")
    assert re.search(r"rebase ", reflog), (
        "precondition: no rebase ran in this clone, so the classifier was never "
        f"exercised (reflog: {reflog!r})"
    )
    for state in _rebase_state_paths(repo):
        assert not state.exists(), f"{state} left behind: the clone is wedged mid-rebase"
    assert _git_text(repo, "rev-parse", "--abbrev-ref", "HEAD") == branch, (
        f"HEAD must be back on {branch!r} after the abort"
    )


def _registered_clone(tmp_path: Path) -> tuple[Path, Path, str, str]:
    """A clone of a bare origin holding one committed, pushed session register.

    Returns (origin, clone, session-id, session-file path relative to the
    clone). The session id is read out of register.py's own success line, so a
    change to that wording breaks one helper rather than every test that
    claims a task.
    """
    origin = tmp_path / "origin.git"
    clone = tmp_path / "clone"
    build_bare_origin(origin, [clone])

    # register.py commits its own file, and this fixture wants to make the
    # commit itself (the rebase tests compare this run's HEAD against a commit
    # it created by hand), so the writer is asked to leave the file in the work
    # tree: --no-commit is the documented form for a caller that commits.
    reg = run_register(clone, "developer", host="clone", worktree=str(clone),
                       **{"no-commit": None})
    assert reg.returncode == 0, reg.stderr
    registered = reg.stdout.strip()
    needle = "left uncommitted"
    assert needle in registered, (
        f"register.py no longer prints its documented success line ({needle!r}): "
        f"{registered!r}"
    )
    sid = _sid_of_uncommitted(registered)
    session_file = f"noni/sessions/{sid}.md"
    _git(clone, "add", "noni/sessions/")
    _git(clone, "commit", "-q", "-m", "register")
    _git(clone, "push", "-q", "origin", "main")
    return origin, clone, sid, session_file


def _sid_of_uncommitted(line: str) -> str:
    """The session id in a ``--no-commit`` line: ``.../<id>.md left uncommitted``.

    The two success lines name the same thing in different shapes (an id after
    ``registered session`` for the committing run, a path for the one that left
    the file in the work tree), and this fixture asks for the second.
    """
    tail = line.split(" -> ")[-1].rsplit(" left uncommitted", 1)[0]
    return tail.rsplit("/", 1)[-1].removesuffix(".md")


def test_rebase_conflict_is_aborted_and_reported_as_exit_5(tmp_path: Path) -> None:
    """A fetch-rebase-push that hits a same-file conflict exits 5, leaves no
    rebase-merge/ or rebase-apply/ behind, keeps HEAD on the branch it was
    invoked on at the claim commit this run made with the claim intact, and
    prints git's own output plus a fix hint on stderr."""
    origin, clone, sid, session_file = _registered_clone(tmp_path)

    # A second writer lands a claim row at EOF of the same file while the
    # clone's origin/main stays stale (that is what _seed_ahead_of_tracking_ref
    # arranges): the push is rejected on every attempt, and the rebase onto the
    # stale ref has to replay the clone's own claim commit against the seed's
    # row in the same file, so it stops in a conflict.
    _seed_ahead_of_tracking_ref(origin, clone, session_file, "- claim: #99")
    assert _git_text(clone, "status", "--porcelain") == "", (
        "precondition: the clone works from a clean tree, so the only rebase "
        "failure this run can meet is the seeded conflict"
    )

    branch_before = _git_text(clone, "rev-parse", "--abbrev-ref", "HEAD")
    assert branch_before == "main", f"precondition: clone must sit on main, got {branch_before}"

    # claim.py commits the claim itself, so the sha the abort must return HEAD
    # to is the run's own claim commit: capture it from the commit the run
    # makes rather than assuming it equals the pre-run tip.
    before_run = _git_text(clone, "rev-parse", "HEAD")
    proc = run_claim(clone, sid, "#42", push=True)
    assert proc.returncode == 5, f"expected exit 5, got {proc.returncode}:\n{proc.stderr}"
    claim_commit = _git_text(clone, "rev-parse", "HEAD")
    assert claim_commit != before_run, "the run must have created a claim commit"
    assert "claim: #42" in _git_text(
        clone, "log", "-1", "--format=%B", claim_commit
    ), "the run's HEAD commit must be the claim commit"

    # Post-conditions, all via plumbing: nothing left mid-rebase, HEAD back on
    # the branch, and HEAD restored byte-identically to the claim commit this
    # run created.
    _precondition_rebase_stops(clone, branch_before)
    assert _git_text(clone, "rev-parse", "HEAD") == claim_commit, (
        "HEAD must be the pre-attempt tip (this run's claim commit), byte-identical"
    )
    assert "- claim: #42" in _git_text(clone, "show", f"HEAD:{session_file}"), (
        "the claim commit must survive the abort"
    )
    assert _git_text(clone, "status", "--porcelain") == "", (
        "the abort must leave no conflict markers behind"
    )

    # UX bar: git's own output plus a fix hint, and no traceback.
    low = proc.stderr.lower()
    assert "conflict" in low, f"stderr must name the conflict: {proc.stderr}"
    assert "fetch" in low and "re-run" in low, f"stderr must name the remedy: {proc.stderr}"
    assert "could not apply" in low, f"git's own rebase output must be echoed: {proc.stderr}"
    assert "Traceback" not in proc.stderr, f"unhandled exception: {proc.stderr}"


def test_rebase_refused_by_dirty_worktree_exits_6(tmp_path: Path) -> None:
    """When git refuses to start the rebase (an unstaged modification of a
    tracked file other than the session file) claim.py exits 6, runs no
    abort, and its hint names committing or stashing."""
    origin, clone, sid, session_file = _registered_clone(tmp_path)

    # Another writer advances origin while the clone's origin/main stays
    # stale, so every push is rejected and the rebase branch is entered; a
    # different task, so nothing else could conflict.
    _seed_ahead_of_tracking_ref(origin, clone, session_file)
    # The trigger: unstaged dirt in an unrelated tracked file (README.md is
    # what build_bare_origin commits, so it exists without extra setup).
    (clone / "README.md").write_text("unstaged local edit\n")

    # The run's own claim commit: what HEAD must still point at afterwards,
    # since a refusal runs no abort and moves nothing.
    proc = run_claim(clone, sid, "#42", push=True)
    assert proc.returncode == 6, f"expected exit 6, got {proc.returncode}:\n{proc.stderr}"
    claim_commit = _git_text(clone, "rev-parse", "HEAD")

    for state in _rebase_state_paths(clone):
        assert not state.exists(), f"{state} must never appear when the rebase never started"
    assert _git_text(clone, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert _git_text(clone, "status", "--porcelain") == "M README.md", (
        "a refusal touches nothing: the unstaged dirt is exactly where it was "
        "(porcelain XY, with the modification unstaged)"
    )
    # A refused rebase moved nothing, so the reflog says what really happened:
    # the claim commit is HEAD's own entry and no rebase line follows it.
    reflog = _git_text(clone, "reflog", "--format=%gs")
    assert not re.search(r"rebase ", reflog), (
        f"a refusal runs no rebase at all, so none may appear in the reflog: "
        f"{reflog!r}"
    )
    assert "claim: #42" in _git_text(clone, "log", "-1", "--format=%B", claim_commit), (
        "the run must have committed the claim before the push failed"
    )

    low = proc.stderr.lower()
    assert "stash" in low, f"the refusal hint must name stashing: {proc.stderr}"
    assert "commit" in low, f"the refusal hint must name committing: {proc.stderr}"
    assert "refus" in low, f"stderr must say the rebase was refused: {proc.stderr}"
    assert "Traceback" not in proc.stderr, f"unhandled exception: {proc.stderr}"


def _push_result(
    args: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """A canned result for the in-process push-loop fakes.

    A rejected push plus a successful fetch is what gets the loop into its
    fetch-rebase-push branch, so a fake that wants the classifier exercised has
    to answer the push with a rejection first; a fake that returns 1 for
    everything exits 3 on the fetch and tests nothing.
    """
    return subprocess.CompletedProcess(["git"] + args, returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def test_rebase_timeout_is_push_class_not_conflict(tmp_path: Path, monkeypatch) -> None:
    """A rebase that times out (GIT_TIMEOUT_RC, what claim.py's GIT_TIMEOUT
    produces) is the push class, not a conflict: with nothing stopped in the
    state directories there is nothing to abort, so the timeout returns exit 3
    rather than either of the rebase codes — and it does reach the probe, which
    is what proves no abort was attempted on a half-written state."""
    claim_mod = _claim_module()

    def timed_out(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["git"] + args, returncode=claim_mod.GIT_TIMEOUT_RC, stdout="",
            stderr=f"git {args[0]} timed out after {claim_mod.GIT_TIMEOUT}s",
        )

    calls: list[list[str]] = []

    # The probe asks git where the state dirs live; answering 0 with a path
    # under the empty scratch dir says "no rebase state here", which is the
    # state a killed rebase that never entered leaves behind. The push is
    # rejected and the fetch succeeds, so the loop reaches the rebase.
    def fake_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:2] == ["rev-parse", "--git-path"]:
            # A distinct path per probed name, none of which exists: the probe
            # answers "there is no rebase state here", which is what a killed
            # call that never entered a rebase leaves behind.
            return _push_result(args, 0, str(tmp_path / "absent" / args[2]) + "/")
        if args[0] == "fetch":
            return _push_result(args)
        if args[0] == "push":
            return _push_result(args, 1, "", "rejected: non-fast-forward")
        return timed_out(args, cwd)

    monkeypatch.setattr(claim_mod, "_git", fake_git)
    assert claim_mod._push_with_retry(
        Path("/does-not-matter"), "main", attempts=2
    ) == claim_mod.EXIT_PUSH_FAILED
    assert ["rebase", "origin/main"] in calls, f"the rebase was never attempted: {calls}"
    assert ["rebase", "--abort"] not in calls, (
        f"nothing was stopped, so no abort may run: {calls}"
    )


def test_rebase_timeout_that_stopped_in_conflict_is_aborted(tmp_path: Path, monkeypatch) -> None:
    """A timeout that lands *after* the rebase entered and stopped must not
    leave the clone wedged: the abort still runs (leaving the state dirs gone)
    and the code stays in the push class, because a killed call proves nothing
    about conflicts."""
    claim_mod = _claim_module()

    def fake_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["rev-parse", "--git-path"]:
            state = tmp_path / args[2]
            return _push_result(args, 0, str(state) + "/")
        if args[:2] == ["rebase", "--abort"]:
            for name in claim_mod.REBASE_STATE_DIRS:
                state = tmp_path / name
                for leaf in ("head-name", "onto"):
                    (state / leaf).unlink(missing_ok=True)
                if state.exists():
                    state.rmdir()
            return _push_result(args)
        if args[0] == "fetch":
            return _push_result(args)
        if args[0] == "push":
            return _push_result(args, 1, "", "rejected: non-fast-forward")
        if args[0] == "rebase":
            # The killed rebase had entered and stopped: a well-formed state dir
            # is left behind, which is exactly what the old early return on 124
            # used to walk away from.
            state = tmp_path / "rebase-merge"
            state.mkdir(exist_ok=True)
            (state / "head-name").write_text("refs/heads/main\n", encoding="utf-8")
            (state / "onto").write_text("0" * 40 + "\n", encoding="utf-8")
            return _push_result(
                args, claim_mod.GIT_TIMEOUT_RC, "",
                f"git {args[0]} timed out after {claim_mod.GIT_TIMEOUT}s",
            )
        return _push_result(args, 1)

    monkeypatch.setattr(claim_mod, "_git", fake_git)
    assert claim_mod._push_with_retry(tmp_path, "main", attempts=2) == claim_mod.EXIT_PUSH_FAILED
    for name in claim_mod.REBASE_STATE_DIRS:
        assert not (tmp_path / name).exists(), (
            f"{name} left behind: a timed-out rebase must not wedge the clone"
        )


def test_stale_rebase_state_dir_is_not_aborted(tmp_path: Path, monkeypatch) -> None:
    """A state directory an earlier crashed run left behind is not this run's
    rebase: claim.py must not abort it (an abort resets the worktree and the
    index), must report the refusal, and must name git's own reason."""
    claim_mod = _claim_module()
    stale = tmp_path / "rebase-merge"
    stale.mkdir()
    (stale / "leftover").write_text("from an earlier run\n", encoding="utf-8")

    aborts: list[list[str]] = []

    def fake_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["rev-parse", "--git-path"]:
            return _push_result(args, 0, str(tmp_path / args[2]) + "/")
        if args[:2] == ["rebase", "--abort"]:
            aborts.append(args)
            return _push_result(args)
        if args[0] == "fetch":
            return _push_result(args)
        if args[0] == "push":
            return _push_result(args, 1, "", "rejected: non-fast-forward")
        if args[0] == "rebase":
            return _push_result(
                args, 1, "",
                "error: cannot rebase: You have unstaged changes.\n"
                "error: Please commit or stash them.\n",
            )
        return _push_result(args, 1)

    monkeypatch.setattr(claim_mod, "_git", fake_git)
    assert claim_mod._push_with_retry(tmp_path, "main", attempts=2) == claim_mod.EXIT_REBASE_REFUSED
    assert not aborts, f"claim.py aborted a rebase it did not start: {aborts}"
    assert stale.is_dir(), "the caller's stray state directory must be left alone"


def test_unreadable_rebase_state_is_not_reported_as_a_clean_refusal(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """When the probe cannot run, "not stopped" is not a known answer: the run
    reports the refusal class without asserting that nothing is mid-rebase, and
    sends the caller to clean up by hand instead of to a hint that cannot work."""
    claim_mod = _claim_module()

    def fake_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["rev-parse", "--git-path"]:
            return _push_result(args, 128, "", "fatal: not a git repository\n")
        if args[0] == "fetch":
            return _push_result(args)
        if args[0] == "push":
            return _push_result(args, 1, "", "rejected: non-fast-forward")
        if args[0] == "rebase":
            return _push_result(args, 1, "", "error: cannot rebase\n")
        return _push_result(args, 1)

    monkeypatch.setattr(claim_mod, "_git", fake_git)
    assert claim_mod._push_with_retry(tmp_path, "main", attempts=2) == claim_mod.EXIT_REBASE_REFUSED
    err = capsys.readouterr().err
    assert "cannot be read" in err, f"stderr must admit it could not tell: {err}"
    assert "nothing is mid-rebase" not in err, f"stderr must not assert a clean clone: {err}"
    assert "rebase --abort" in err, f"stderr must name the manual remedy: {err}"


def test_failed_abort_names_the_wedged_clone(tmp_path: Path, monkeypatch, capsys) -> None:
    """When the abort itself fails, the caller must be able to tell a recovered
    clone from a wedged one: exit 5, git's own rebase output kept, and an
    explicit 'still mid-rebase, clean up by hand' line."""
    claim_mod = _claim_module()
    state = tmp_path / "rebase-merge"
    state.mkdir()
    (state / "head-name").write_text("refs/heads/main\n", encoding="utf-8")
    (state / "onto").write_text("0" * 40 + "\n", encoding="utf-8")

    def fake_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["rev-parse", "--git-path"]:
            return _push_result(args, 0, str(tmp_path / args[2]) + "/")
        if args[:2] == ["rebase", "--abort"]:
            return _push_result(args, 1, "", "error: unable to resolve 'REBASE_HEAD'\n")
        if args[0] == "fetch":
            return _push_result(args)
        if args[0] == "push":
            return _push_result(args, 1, "", "rejected: non-fast-forward")
        if args[0] == "rebase":
            return _push_result(
                args, 1, "", "error: could not apply abc1234... claim: #42\n",
            )
        return _push_result(args, 1)

    monkeypatch.setattr(claim_mod, "_git", fake_git)
    assert claim_mod._push_with_retry(tmp_path, "main", attempts=2) == claim_mod.EXIT_REBASE_CONFLICT
    err = capsys.readouterr().err
    assert "abort failed" in err, f"stderr must say the abort failed: {err}"
    assert "still mid-rebase" in err, f"stderr must name the wedged state: {err}"
    assert "could not apply" in err, f"git's own output must survive: {err}"
    assert state.is_dir(), "the fixture's state dir is what the failed abort left behind"


def test_git_output_is_sanitised_and_bounded() -> None:
    """git's output is echoed, and it can originate with the remote, so control
    bytes (ANSI/OSC sequences) and unbounded blobs must not reach the terminal
    the way they came."""
    claim_mod = _claim_module()
    hostile = "error: \x1b]0;takeover\x07 pushed\x00\x1b[31mred\x1b[0m\n"
    rendered = claim_mod._safe(hostile)
    for needle in ("\x1b", "\x00", "\x07"):
        assert needle not in rendered, f"{needle!r} survived the sanitizer: {rendered!r}"
    # The escape introducer is gone, so no downstream byte can start a sequence;
    # the printable tail of the stripped sequence is plain text once it is.
    assert "\x1b[" not in rendered and "\x1b]" not in rendered, rendered
    assert "pushed" in rendered and "red" in rendered, rendered
    assert "\n" in rendered, "newlines are content, not control noise"

    huge = "x" * (claim_mod.GIT_OUTPUT_LIMIT * 3)
    bounded = claim_mod._safe(huge)
    assert len(bounded) < len(huge), "git output must be bounded before the terminal"
    assert bounded.startswith("x" * 50) and "truncated" in bounded, bounded[-40:]
    assert claim_mod._safe("short") == "short"


def test_a_rebase_result_never_waited_on_is_not_the_timeout_class(
        tmp_path: Path, monkeypatch) -> None:
    """``returncode=None`` on the rebase is not a killed rebase.

    The loop reads the timeout verdict as ``returncode == GIT_TIMEOUT_RC``, and
    a ``CompletedProcess`` carries ``None`` for a call that was launched and
    never waited on. Read as a timeout the run prints 'rebase timed out' for a
    call nobody measured and exits 3 without classifying the clone's state;
    read as an ordinary refusal it takes the verdict's probes, which is the
    honest path -- and here it finds a stopped rebase, so the code is the
    conflict code and the abort really runs. A text-shaped sentinel (``'124'``
    from a stream that never parsed as an int) is the same non-answer.
    """
    claim_mod = _claim_module()

    for shape in (None, str(claim_mod.GIT_TIMEOUT_RC)):
        calls: list[list[str]] = []
        monkeypatch.setattr(claim_mod, "_git",
                            _stopped_rebase_git(tmp_path, shape, calls))
        code = claim_mod._push_with_retry(tmp_path, "main", attempts=2)
        assert code == claim_mod.EXIT_REBASE_CONFLICT, (shape, code, calls)
        assert ["rebase", "origin/main"] in calls, calls
        assert ["rebase", "--abort"] in calls, (
            f"a stopped clone is aborted whichever shape the rebase answered "
            f"with: {calls}")
