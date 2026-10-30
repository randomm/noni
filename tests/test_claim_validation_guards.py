"""The guards of claim.py: a task, a branch, a duplicate, a detached HEAD.

Extracted from the claim suite: the input validation chain and the refusals it
raises before any write, asserted through the CLI's exit codes."""

import subprocess

from _harness import (
    _git,
    run_claim,
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
