"""The guards of claim.py: a task, a branch, a duplicate, a detached HEAD.

Extracted from the claim suite: the input validation chain and the refusals it
raises before any write, asserted through the CLI's exit codes. The guard on
``--session-id`` itself lives in ``test_claim_session_id_guard.py``, which is
about the derivation the four writers share rather than about claim's own
arguments.
"""

import subprocess
from pathlib import Path

from _harness import (
    CLAIM,
    _claim_module,
    _git,
    _git_env_with_identity,
    run_claim,
    run_from,
)
from claim_fixtures import (
    SESSION_ID,
    _claim_cwd,
    _claim_from,
    _claim_state_root_case,
    _decoy_tree,
    _git_text,
    _make_session,
    _session_path,
)
from session_git_support import (
    _PATH,
    STATE_DIR,
    _assert_writer_left_nothing_behind,
    _committed_names,
    _nested_state,
    _strip_identity,
    _tracked_bytes,
)

# The session and the one path every commit below must consist of. The fixture
# gives the clone a decoy at the doubled spelling of this path, so a claim that
# admitted that path shows up in the name set rather than passing quietly.
GUARD_SID = "2026-10-01-cccccc"
GUARD_REL = f"noni/sessions/{GUARD_SID}.md"


def test_task_with_whitespace_is_refused(tmp_path):
    """A --task with embedded whitespace corrupts the single-line claim row
    and is refused (exit 4), like the empty / whitespace-only task."""
    repo = _make_session(tmp_path)
    # "  #42" is rejected only as whitespace-only after strip; a token with
    # embedded whitespace ("#42 extra") is the shape the guard must refuse.
    for bad in ("#42 extra", "a b"):
        proc = run_claim(repo, SESSION_ID, bad)
        assert proc.returncode == 4, f"task {bad!r}: expected exit 4, got {proc.returncode}: {proc.stderr}"
        assert "task" in proc.stderr.lower()
    # The whitespace-only form is the pre-existing exit-4 path.
    proc = run_claim(repo, SESSION_ID, "   ")
    assert proc.returncode == 4, f"whitespace-only task: expected exit 4, got {proc.returncode}: {proc.stderr}"


def test_task_single_token_is_accepted(tmp_path):
    """A well-formed single-token task (the documented grammar) is
    accepted and appended."""
    repo = _make_session(tmp_path)
    proc = run_claim(repo, SESSION_ID, "#42")
    assert proc.returncode == 0, f"expected exit 0, got {proc.returncode}: {proc.stderr}"
    assert "- claim: #42" in _session_path(repo).read_text()


def test_claim_reads_and_writes_only_the_state_root_named_by_repo(tmp_path):
    """--repo is the state root, and the only one: a claim run from an unrelated
    directory lands in the state repository and touches nothing beside its cwd.

    The three trees are the whole point. The state root is a separate git
    repository holding the register; the decoy sits under the cwd and carries a
    register file of its own with a claim no run of this test makes; the cwd
    itself starts empty. So a tool that resolved ``noni/sessions/`` from the cwd
    or from its own location would either append to the decoy, create a
    ``noni/`` under the cwd, or fail to find the register at all — and each of
    the four assertions below names one of those.
    """
    root, decoy, cwd = _claim_state_root_case(tmp_path)
    decoy_bytes = (decoy / "noni" / "sessions" / f"{SESSION_ID}.md").read_bytes()

    proc = _claim_from(cwd, root, "#42")
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    # The claim landed in the state root, and was committed there.
    assert "- claim: #42" in _session_path(root).read_text(encoding="utf-8")
    assert "claim: #42" in _git_text(root, "log", "--format=%s"), \
        "the claim was not committed in the state repository"
    # Nothing was read from or written beside the cwd: the decoy is byte for
    # byte the fixture, and no ``noni/`` appeared under the cwd at all.
    assert (decoy / "noni" / "sessions" / f"{SESSION_ID}.md").read_bytes() == decoy_bytes, (
        "the run wrote the decoy register under the cwd, so state resolved "
        "from somewhere other than --repo"
    )
    assert not (cwd / "noni").exists(), "the run created noni/ under the cwd"


def test_claim_refuses_a_repo_that_is_not_a_directory(tmp_path):
    """A --repo naming no directory is a usage error (exit 4) with the argument
    named, and not a missing-session report (exit 1).

    The two refusals are different work for the caller — pass the right path
    versus register the session first — so the code and the wording both matter,
    and the guard must run before the register is looked for. Same message shape
    as register.py, close.py and release.py already use.
    """
    missing = tmp_path / "no-such-state-root"
    decoy = _decoy_tree(tmp_path)
    cwd = _claim_cwd(tmp_path)
    decoy_bytes = (decoy / "noni" / "sessions" / f"{SESSION_ID}.md").read_bytes()

    proc = _claim_from(cwd, missing, "#42")
    assert proc.returncode == 4, f"expected exit 4, got {proc.returncode}: {proc.stderr}"
    lowered = proc.stderr.lower()
    assert "--repo" in lowered, f"the refusal must name the argument: {proc.stderr}"
    assert "directory" in lowered, f"the refusal must name the state it found: {proc.stderr}"
    assert "register" not in lowered, (
        f"a missing state root is not a missing session: {proc.stderr}"
    )
    assert (decoy / "noni" / "sessions" / f"{SESSION_ID}.md").read_bytes() == decoy_bytes
    assert not (cwd / "noni").exists()


def test_claim_refuses_a_repo_that_is_a_file(tmp_path):
    """A --repo that exists but is not a directory is refused the same way,
    from a cwd that is not the state root."""
    root, decoy, cwd = _claim_state_root_case(tmp_path)
    not_a_dir = tmp_path / "claim-state-is-a-file"
    not_a_dir.write_text("i am a file, not a state root\n", encoding="utf-8")

    proc = _claim_from(cwd, not_a_dir, "#42")
    assert proc.returncode == 4, f"expected exit 4, got {proc.returncode}: {proc.stderr}"
    assert "--repo" in proc.stderr.lower()
    assert not (cwd / "noni").exists()
    assert _session_path(root).read_text(encoding="utf-8").count("- claim:") == 0, (
        "a refused run must not have claimed anything in the real state root"
    )


def _claim_git_argv(tmp_path: Path, branch: str,
                    monkeypatch) -> list[list[str]]:
    """Every git argv a --push claim run makes, recorded at claim.py's own seam.

    The push loop is driven through ``claim_mod._git``, so replacing it records
    the exact argv the run would have handed git without touching a remote: the
    guard's promise is about argv ('no argument a leading dash'), and an
    assertion on an exit code alone cannot tell a ref from an option. The tree
    is real (``_make_session``), so the commit path runs for real up to the
    point the loop would push. The identity is pinned the way the subprocess
    launchers pin it: the suite's conftest clears the author and committer
    variables, so an in-process run that did not pin one would observe git's
    identity refusal instead of the push under test.
    """
    claim_mod = _claim_module()
    repo = _make_session(tmp_path)
    for name, value in _git_env_with_identity().items():
        monkeypatch.setenv(name, value)
    calls: list[list[str]] = []

    def recording(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        # The commit plumbing runs for real; only this loop's own verbs are
        # scripted. A push that succeeds keeps the run out of the retry path.
        if args and args[0] in ("push", "fetch", "rebase"):
            return subprocess.CompletedProcess(["git"] + list(args), 0, "", "")
        return original(list(args), cwd)

    original = claim_mod._git
    claim_mod._git = recording
    try:
        # In-process: the argv lives on this module's git seam, so the driver
        # is this module's main() too (run_claim spawns a subprocess, whose
        # git this recorder cannot see).
        code = claim_mod.main([
            "--repo", str(repo), "--session-id", SESSION_ID, "--task", "#42",
            "--branch", branch, "--push",
        ])
    finally:
        claim_mod._git = original
    assert code == 0, (code, calls)
    assert any(args and args[0] == "push" for args in calls), (
        f"the run never reached the push, so the argv proves nothing: {calls}")
    return calls


def test_branch_with_slash_or_dots_is_refused(tmp_path):
    """A --branch that is not a safe ref name (slash, dots, empty) is
    refused (exit 4) before git sees it."""
    repo = _make_session(tmp_path)
    # "..main" is a legal git ref name (the guard is a single-segment check,
    # not a git-ref-spec validator): slashes and embedded whitespace are the
    # shapes refused here. (A leading-dash value is refused even earlier,
    # by argparse, which is itself a refusal — not a push.)
    for bad in ("feature/x", "a b"):
        proc = run_claim(repo, SESSION_ID, "#42", branch=bad)
        assert proc.returncode == 4, f"branch {bad!r}: expected exit 4, got {proc.returncode}: {proc.stderr}"
    # A safe ref name is accepted by the guard (the push itself is not run
    # here; the guard is what this test pins).
    proc = run_claim(repo, SESSION_ID, "#43", branch="main")
    assert proc.returncode == 0, f"safe branch: expected exit 0, got {proc.returncode}: {proc.stderr}"


def test_a_leading_dash_branch_is_refused_before_git_sees_it(tmp_path):
    """The regression, on argv and on the CLI: a leading dash never reaches git.

    ``git push origin <name>`` reads a leading-dash argument as a push option
    (``--force``, ``--receive-pack=...``). claim.py's own old regex admitted
    it (``^[A-Za-z0-9._-]+$`` places no anchor against a leading dash), so a
    name that got in reached the shared loop unchecked.

    Two routes are pinned. Driven through ``main()`` the value arrives as a
    real argv element (argparse's own ``--branch=<value>`` form hands it over
    verbatim -- the separate-token form argparse refuses before any guard of
    ours runs), the module's git seam records every argv, and the assertion is
    "no git call at all was made", which an exit code alone cannot say. Driven
    through the CLI the same value is refused with the usage code, naming the
    argument and the value, and nothing is claimed on disk.
    """
    for value in ("--force", "-receive-pack=evil"):
        repo = _make_session(tmp_path / f"dash-{value.strip('-')}")
        claim_mod = _claim_module()
        calls: list[list[str]] = []

        def recording(args: list[str], cwd: Path,
                      calls: list[list[str]] = calls) -> subprocess.CompletedProcess[str]:
            calls.append(list(args))
            return subprocess.CompletedProcess(["git"] + list(args), 0, "", "")

        original = claim_mod._git
        claim_mod._git = recording
        try:
            code = claim_mod.main([
                "--repo", str(repo), "--session-id", SESSION_ID, "--task", "#42",
                f"--branch={value}", "--push",
            ])
        finally:
            claim_mod._git = original
        assert code == 4, f"--branch {value!r}: expected exit 4, got {code}: {calls}"
        assert calls == [], f"a refused --branch must never reach git: {calls}"
        # The CLI route: same value, same usage refusal, and the refusal names
        # both the argument and the value the operator typed.
        proc = run_claim(repo, SESSION_ID, "#42", **{"branch": f"={value}"})
        assert proc.returncode == 4, (
            f"--branch {value!r}: expected the exit-4 usage refusal, got "
            f"{proc.returncode}: {proc.stderr}")
        assert "branch" in proc.stderr.lower(), proc.stderr
        assert value in proc.stderr, (
            f"the refusal must name the bad value: {proc.stderr}")
        # Nothing was claimed: a usage refusal lands before any write.
        body = _session_path(repo).read_text(encoding="utf-8")
        assert "- claim:" not in body, f"{value!r}: {body}"


def test_a_validated_branch_reaches_git_only_as_an_explicit_refspec(tmp_path,
                                                                    monkeypatch):
    """The live path stays live: a good --branch is pushed, as a refspec only.

    Paired with the refusal test above: a guard that refused everything would
    pass it and fail this one. The recorded push argv is exactly
    ``push origin refs/heads/main:refs/heads/main`` -- no bare name, so nothing
    for git to read as an option, and no leading dash anywhere on the argv.
    """
    calls = _claim_git_argv(tmp_path, "main", monkeypatch)
    pushes = [args for args in calls if args and args[0] == "push"]
    assert pushes, calls
    for args in pushes:
        assert args == ["push", "origin",
                        "refs/heads/main:refs/heads/main"], args


def test_a_refusing_push_loop_names_the_branch_and_never_calls_git(tmp_path):
    """The boundary inside the loop: a refused branch means zero git calls.

    The two CLI refusals above never reach the loop, so they cannot show what
    the loop itself does. Entered directly with a name both paths would have
    rejected, the loop reports the bad branch in claim.py's own voice with
    claim.py's push code and makes no git call at all -- no fetch, no rebase,
    no push, so no option and no state change behind the operator's back.
    """
    claim_mod = _claim_module()
    calls: list[list[str]] = []

    def recording(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        return subprocess.CompletedProcess(["git"] + list(args), 0, "", "")

    original = claim_mod._git
    claim_mod._git = recording
    try:
        code = claim_mod._push_with_retry(Path("/does-not-matter"), "--force",
                                          attempts=2)
    finally:
        claim_mod._git = original
    assert code == claim_mod.EXIT_PUSH_FAILED, code
    assert calls == [], f"a refused branch must never reach git: {calls}"


def test_same_task_claim_twice_is_refused(tmp_path):
    """A session cannot append the same task claim twice: the second claim
    is refused (exit 2) and the register keeps one claim row."""
    repo = _make_session(tmp_path)
    first = run_claim(repo, SESSION_ID, "#42")
    assert first.returncode == 0, first.stderr
    second = run_claim(repo, SESSION_ID, "#42")
    assert second.returncode == 2, f"second claim: expected exit 2, got {second.returncode}: {second.stderr}"
    body = _session_path(repo).read_text()
    assert body.count("- claim: #42") == 1, "the duplicate claim row must not be appended"
    # A different task still appends.
    third = run_claim(repo, SESSION_ID, "#43")
    assert third.returncode == 0, third.stderr


def test_invalid_utf8_session_is_refused_without_traceback(tmp_path):
    """A session file with invalid UTF-8 bytes is refused (exit 2, like the
    malformed-file path) with a clean stderr message and no traceback."""
    repo = _make_session(tmp_path)
    _session_path(repo).write_bytes(b"- identity: dev\n- claims:\n  - claim: \xff\xfe#42\n")
    proc = run_claim(repo, SESSION_ID, "#42")
    assert proc.returncode == 2, f"expected exit 2, got {proc.returncode}: {proc.stderr}"
    assert "Traceback" not in proc.stderr, f"unhandled exception: {proc.stderr}"


def test_a_terminal_session_claims_nothing(tmp_path):
    """AC4: a session whose status has ended claims nothing further (exit 2).

    ``close`` is final, and the census ignores a terminal session's claims, so a
    row appended here would be invisible work: the run refuses before writing
    anything rather than leaving a claim nobody counts. Every status the census
    treats as ended is driven, not just 'closed', because the refusal is one set
    (``_session_git.TERMINAL_STATUSES``) and a set a test only samples can lose
    a member silently. Each case asserts the bytes are unchanged and uncommitted
    -- a refusal that wrote and committed a row would be the half-applied state
    this issue is about, with a nicer message on it.
    """
    for settled in ("closed", "done", "superseded", "ended"):
        repo = _make_session(tmp_path / settled)
        body = _session_path(repo).read_text(encoding="utf-8")
        body = body.replace("- status: active", f"- status: {settled}")
        _session_path(repo).write_text(body, encoding="utf-8")
        _git(repo, "commit", "-q", "-am", f"settle {settled}")

        proc = run_claim(repo, SESSION_ID, "#42")

        assert proc.returncode == 2, f"{settled}: expected exit 2, got {proc.returncode}: {proc.stderr}"
        assert settled in proc.stderr.lower(), f"{settled}: {proc.stderr}"
        assert "terminal" in proc.stderr.lower(), f"{settled}: {proc.stderr}"
        # Nothing was written: the file still holds exactly the committed bytes.
        assert _session_path(repo).read_text(encoding="utf-8") == body
        assert _git_text(repo, "status", "--porcelain") == "", f"{settled}: left dirty"


def test_a_terminal_refusal_precedes_the_duplicate_check(tmp_path):
    """Which refusal a terminal session gets when its task is also a duplicate.

    Both guards answer exit 2, but only one of them names the state the operator
    has to act on, and the order is what makes the message true: a run that
    reported 'already claims #42' for a closed session would be describing a
    live session. The duplicate row is planted before the status is settled, so
    the duplicate is genuinely there and the message that comes back is the
    terminal one.
    """
    repo = _make_session(tmp_path, claims=["#42"])
    body = _session_path(repo).read_text(encoding="utf-8")
    _session_path(repo).write_text(
        body.replace("- status: active", "- status: closed"), encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "close it")

    proc = run_claim(repo, SESSION_ID, "#42")

    assert proc.returncode == 2, proc.stderr
    assert "closed" in proc.stderr.lower(), proc.stderr


def test_a_session_with_no_status_field_still_claims(tmp_path):
    """The refusal is a status check, not a shape check. A register file with no
    '- status:' line at all is not terminal (the census has its own way of
    reading a file like that), and refusing it here would turn a file claim.py
    has always accepted into one the writer will not touch."""
    repo = _make_session(tmp_path)
    body = _session_path(repo).read_text(encoding="utf-8")
    _session_path(repo).write_text(
        "".join(line + "\n" for line in body.splitlines() if "- status:" not in line),
        encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "drop the status line")

    proc = run_claim(repo, SESSION_ID, "#42")

    assert proc.returncode == 0, proc.stderr
    assert "- claim: #42" in _session_path(repo).read_text(encoding="utf-8")


def test_detached_head_push_is_refused(tmp_path):
    """The detached-HEAD guard fires on the literal string git actually
    prints (rev-parse --abbrev-ref HEAD prints "HEAD" when detached, not
    "(detached HEAD)"): a push from detached HEAD is refused (exit 3)
    rather than attempting to push a branch named "HEAD"."""
    repo = _make_session(tmp_path)
    run_claim(repo, SESSION_ID, "#42")
    _git(repo, "checkout", "-q", "--detach")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True,
    )
    assert head.stdout.strip() == "HEAD", "precondition: git must print HEAD when detached"
    proc = run_claim(repo, SESSION_ID, "#43", push=True)
    assert proc.returncode == 3, f"expected exit 3 for detached-HEAD push, got {proc.returncode}: {proc.stderr}"
    assert "detached" in proc.stderr.lower()


# --- the private-state route named as a reader names it (issue #66) -----------
#
# ``_claim_from`` above passes an absolute ``str(root)``, the form every launcher
# in this suite builds. A reader of docs/PRODUCT.md 7 names the private state root
# as a clone nested in the project and git-ignored by it, from the project
# directory: ``--repo .noni-state``. With that spelling claim's pathspec used to
# keep the --repo component, so the row was appended and the commit was refused
# for a path the clone does not hold, and the wording named that doubled path.

def _claim_relative_run(project: Path, sid: str, task: str,
                        refused: bool = False) -> subprocess.CompletedProcess[str]:
    """claim.py from the project cwd, ``--repo`` naming the nested clone by name.

    ``refused`` strips the child's git identity so git itself refuses the commit.
    """
    if refused:
        return run_from(project, CLAIM, "--repo", STATE_DIR, "--session-id", sid,
                        "--task", task, identity=False,
                        env={"GIT_CONFIG_GLOBAL": "/dev/null", "PATH": _PATH})
    return run_from(project, CLAIM, "--repo", STATE_DIR, "--session-id", sid,
                    "--task", task)


def test_claim_appends_the_row_with_a_relative_repo(tmp_path):
    """AC1/AC7: relative --repo exits 0, the row lands in the clone, and the
    commit is exactly the one repo-relative session path."""
    project, state, session = _nested_state(tmp_path, GUARD_SID, name="claim-relative")

    proc = _claim_relative_run(project, GUARD_SID, "#42")
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    assert "- claim: #42" in session.read_text(encoding="utf-8"), "row not on disk"
    assert "- claim: #42" in _git_text(state, "show", f"HEAD:{GUARD_REL}"), (
        "the row is not in the commit"
    )
    assert _git_text(state, "log", "-1", "--format=%s").strip() == "claim: #42"
    assert _committed_names(state) == [GUARD_REL], (
        "the commit moved paths other than the one session file"
    )
    assert _git_text(state, "status", "--porcelain") == ""


def test_claim_with_a_relative_repo_names_the_repo_relative_path_when_refused(tmp_path):
    """AC2/AC4/AC6/AC8: a refused relative-repo claim names ``noni/sessions/
    <sid>.md`` in the wording it owes -- ``( <rel>, which this run staged)`` --
    never a path beginning with the --repo component, and never blames a missing
    upstream for a commit git refused."""
    project, state, session = _nested_state(tmp_path, GUARD_SID, name="claim-refused")
    _strip_identity(state)
    head_before = _git_text(state, "rev-parse", "HEAD").strip()
    tracked_before = _tracked_bytes(state)

    proc = _claim_relative_run(project, GUARD_SID, "#42", refused=True)

    assert proc.returncode == 3, f"{proc.returncode}: {proc.stderr}"
    err = proc.stderr
    assert f"({GUARD_REL}, which this run staged)" in err, err
    assert f"{STATE_DIR}/noni/sessions" not in err, (
        f"the wording names a path built by joining the relative --repo to the "
        f"state path: {err}"
    )
    assert "no upstream configured" not in err, (
        f"a refused commit was classified as a missing upstream: {err}"
    )
    # The row is on disk, and the clone holds no commit this run made and stages
    # nothing but the one path it owns.
    assert "- claim: #42" in session.read_text(encoding="utf-8")
    assert _git_text(state, "rev-parse", "HEAD").strip() == head_before
    _assert_writer_left_nothing_behind(state, tracked_before, [GUARD_REL])
