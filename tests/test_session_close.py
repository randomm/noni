"""close.py: the session-lifecycle verb that sets one field and commits one file.

Closing is the only way a session stops counting toward the census's
double-claim check, so the contract under test is narrow and load-bearing: the
run moves exactly the ``- status:`` line, commits exactly the session's own
file, is idempotent on a session that has already ended, and never deletes the
register file. The exit codes are the writer's own constants, read from the
module rather than copied.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from _harness import (
    CLOSE,
    _git_ok,
    build_bare_origin,
    run_close,
    run_from,
    run_register,
)

from noni import close as close_mod

BODY = """# session {sid}

- identity: dev
- host/worktree: host (repo)
- started: 2026-10-01T10:00:00Z
- status: active
- claims:
  - claim: #1
  - claim: #2
"""


def _origin_tip(origin: Path, branch: str = "main") -> str:
    """The subject of ``branch``'s tip commit in a bare origin.

    Read from the branch by name, not from HEAD: ``init --bare`` gives the
    repository a HEAD for git's own default branch (master), which no clone
    ever advances, so ``log -1`` on such an origin answers "no commits yet"
    while main is three commits deep.
    """
    return _git_ok(origin, "log", "-1", "--format=%s", branch).stdout.strip()


def _repo_with_session(tmp_path, sid="2026-10-01-aaaaaa", status="active", name="clone"):
    """A git repo holding one committed session file at ``status``.

    ``name`` lets one test build several trees under one ``tmp_path`` (the
    terminal-status sweep needs one per status, and a shared path would have
    the second iteration commit into the first one's repo).
    """
    origin = tmp_path / f"{name}.origin.git"
    clone = tmp_path / name
    build_bare_origin(origin, [clone])
    session = clone / "noni" / "sessions" / f"{sid}.md"
    session.parent.mkdir(parents=True, exist_ok=True)
    session.write_text(BODY.format(sid=sid).replace("- status: active",
                                                    f"- status: {status}"),
                       encoding="utf-8")
    _git_ok(clone, "add", f"noni/sessions/{sid}.md")
    _git_ok(clone, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", f"register: {sid}")
    _git_ok(clone, "push", "-q", "origin", "main")
    return clone, session


def test_close_sets_the_status_line_and_leaves_every_other_byte_alone(tmp_path):
    """The whole promise of the writer in one assertion: one line moves."""
    clone, session = _repo_with_session(tmp_path)
    before = session.read_text(encoding="utf-8")

    proc = run_close(clone, "2026-10-01-aaaaaa")
    assert proc.returncode == close_mod.EXIT_OK, f"{proc.returncode}: {proc.stderr}"

    after = session.read_text(encoding="utf-8")
    before_lines, after_lines = before.splitlines(), after.splitlines()
    assert len(before_lines) == len(after_lines)
    changed = [(b, a) for b, a in zip(before_lines, after_lines, strict=True) if b != a]
    assert changed == [("- status: active", "- status: closed")], changed


def test_close_commits_only_the_sessions_own_file(tmp_path):
    """The commit carries one path and sweeps in nobody else's staged work."""
    clone, session = _repo_with_session(tmp_path)
    # Someone else's staged change, which must survive the commit untouched and
    # uncommitted: the writer's --only is what protects it.
    other = clone / "noni" / "decisions" / "other.json"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("{}\n", encoding="utf-8")
    _git_ok(clone, "add", "noni/decisions/other.json")

    proc = run_close(clone, "2026-10-01-aaaaaa")
    assert proc.returncode == close_mod.EXIT_OK, proc.stderr

    files = _git_ok(clone, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert files == ["noni/sessions/2026-10-01-aaaaaa.md"], files
    # The other staged entry is still staged, still uncommitted.
    status = _git_ok(clone, "status", "--porcelain").stdout
    assert "noni/decisions/other.json" in status.split("\n")[0] or \
        "A  noni/decisions/other.json" in status, status
    head_subject = _git_ok(clone, "log", "-1", "--format=%s").stdout.strip()
    assert head_subject == "close: 2026-10-01-aaaaaa"


def test_closing_an_already_terminal_session_is_a_noop(tmp_path):
    """Idempotence: a session that has ended needs no commit, so a second close
    exits 0, moves no HEAD, and says it was already closed. Every terminal
    status answers the same way."""
    for status in sorted(close_mod._session_git.TERMINAL_STATUSES):
        sid = f"2026-10-01-t{status[:4]}"
        clone, session = _repo_with_session(tmp_path, sid=sid, status=status,
                                            name=f"clone-{status}")
        head_before = _git_ok(clone, "rev-parse", "HEAD").stdout.strip()
        before = session.read_text(encoding="utf-8")

        proc = run_close(clone, sid)
        tag = f"[{status}] "
        assert proc.returncode == close_mod.EXIT_OK, tag + proc.stderr
        assert "already closed" in proc.stdout, tag + proc.stdout
        assert f"status={status}" in proc.stdout, tag + proc.stdout
        assert session.read_text(encoding="utf-8") == before, tag
        assert _git_ok(clone, "rev-parse", "HEAD").stdout.strip() == head_before, tag


def test_close_of_a_missing_session_exits_one(tmp_path):
    clone, _ = _repo_with_session(tmp_path)
    proc = run_close(clone, "2026-10-01-nope00")
    assert proc.returncode == close_mod.EXIT_SESSION_MISSING, proc.returncode
    assert "register file not found" in proc.stderr, proc.stderr
    assert "fix:" in proc.stderr, proc.stderr


def test_close_of_a_file_with_no_status_line_exits_two(tmp_path):
    """Nothing to set is a malformed register, not a silent success."""
    clone, session = _repo_with_session(tmp_path)
    session.write_text("- identity: dev\n- claims:\n", encoding="utf-8")
    proc = run_close(clone, "2026-10-01-aaaaaa")
    assert proc.returncode == close_mod.EXIT_SESSION_MALFORMED, proc.returncode
    assert "malformed" in proc.stderr and "no '- status:'" in proc.stderr, proc.stderr
    # The fix hint spells the line the operator is told to add, once: the field
    # name already carries its colon, so a hint that added a second one would
    # tell them to write a line no parser reads.
    assert "add the '- status: active' line" in proc.stderr, proc.stderr
    assert "::" not in proc.stderr, proc.stderr


def test_close_of_unreadable_bytes_exits_two_and_not_with_a_traceback(tmp_path):
    """A UnicodeDecodeError carries no strerror; naming it would crash here."""
    clone, session = _repo_with_session(tmp_path)
    session.write_bytes(b"\xff\xfe\x00 not utf-8")
    proc = run_close(clone, "2026-10-01-aaaaaa")
    assert proc.returncode == close_mod.EXIT_SESSION_MALFORMED, proc.returncode
    assert "Traceback" not in proc.stderr, proc.stderr
    assert "UnicodeDecodeError" in proc.stderr, proc.stderr


def test_no_commit_writes_the_change_and_runs_no_git(tmp_path):
    clone, session = _repo_with_session(tmp_path)
    head_before = _git_ok(clone, "rev-parse", "HEAD").stdout.strip()

    proc = run_close(clone, "2026-10-01-aaaaaa", **{"no-commit": None})
    assert proc.returncode == close_mod.EXIT_OK, proc.stderr
    assert "left uncommitted" in proc.stdout, proc.stdout
    assert "- status: closed" in session.read_text(encoding="utf-8")
    assert _git_ok(clone, "rev-parse", "HEAD").stdout.strip() == head_before


def test_push_after_close_lands_the_commit_on_origin(tmp_path):
    origin = tmp_path / "origin.git"
    clone = tmp_path / "clone"
    build_bare_origin(origin, [clone])
    reg = run_register(clone, "dev", host="h")
    assert reg.returncode == 0, reg.stderr
    sid = reg.stdout.strip().split("registered session ")[1].split(" ->")[0].strip()

    proc = run_close(clone, sid, push=True)
    assert proc.returncode == close_mod.EXIT_OK, proc.stderr
    # origin holds the close commit: read it from the bare repo, not the clone.
    assert _origin_tip(origin) == f"close: {sid}"


def test_detached_head_with_push_is_refused_not_pushed_to_head(tmp_path):
    """No --branch flag means a detached HEAD must be refused (exit 3), not
    pushed to a branch literally named HEAD."""
    clone, session = _repo_with_session(tmp_path)
    head = _git_ok(clone, "rev-parse", "HEAD").stdout.strip()
    _git_ok(clone, "checkout", "-q", "--detach", head)

    proc = run_close(clone, "2026-10-01-aaaaaa", push=True)
    assert proc.returncode == close_mod.EXIT_PUSH_FAILED, proc.returncode
    assert "push refused" in proc.stderr, proc.stderr
    assert "no --branch flag" in proc.stderr, proc.stderr


def _pushable(tmp_path, name="clone"):
    """A clone with an origin and a committed active session, ready for --push."""
    origin = tmp_path / f"{name}.origin.git"
    clone = tmp_path / name
    build_bare_origin(origin, [clone])
    session = clone / "noni" / "sessions" / "2026-10-01-aaaaaa.md"
    session.parent.mkdir(parents=True, exist_ok=True)
    session.write_text(BODY.format(sid="2026-10-01-aaaaaa"), encoding="utf-8")
    _git_ok(clone, "add", "noni/sessions/2026-10-01-aaaaaa.md")
    _git_ok(clone, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", "register: 2026-10-01-aaaaaa")
    _git_ok(clone, "push", "-q", "origin", "main")
    return origin, clone


def _advance_origin(tmp_path, origin, content, name):
    """Commit ``content`` to the session file on origin/main via a scratch clone."""
    seed = tmp_path / name
    work = seed / "w"
    seed.mkdir(parents=True)
    _git_ok(seed, "clone", "-q", "-b", "main", str(origin), str(work))
    (work / "noni" / "sessions").mkdir(parents=True, exist_ok=True)
    (work / "noni" / "sessions" / "2026-10-01-aaaaaa.md").write_text(content,
                                                                     encoding="utf-8")
    _git_ok(work, "add", "noni/sessions/2026-10-01-aaaaaa.md")
    _git_ok(work, "-c", "user.name=Seeder", "-c", "user.email=seeder@fixture.invalid",
            "commit", "-q", "-m", f"seed: {name}")
    _git_ok(work, "push", "-q", "origin", "main")


def _close_push_rejected(tmp_path, name):
    """A clone whose close --push cannot land: origin moved the same line.

    The clone's rebase cannot merge the two sides, so the run answers with one
    of the two rebase verdicts (the helper's own classification decides which);
    both are the rebase codes, neither is exit 3.
    """
    origin, clone = _pushable(tmp_path, name=name)
    _advance_origin(tmp_path, origin, "from the other side\n", f"{name}.seed-other")
    return clone


def test_push_rebase_conflict_is_a_rebase_code_not_three(tmp_path):
    """A session-file conflict on --push is the conflict code, not "push
    failed": an agent scripting on these codes must be able to tell 'resolve
    the session file' from 'retry the push' (claim.py's split, #22)."""
    clone = _close_push_rejected(tmp_path, "conflict")
    proc = run_close(clone, "2026-10-01-aaaaaa", push=True)
    assert proc.returncode in (close_mod.EXIT_REBASE_CONFLICT,
                               close_mod.EXIT_REBASE_REFUSED), (proc.returncode, proc.stderr)
    # The clone is not left mid-rebase: an aborted (or never-started) rebase
    # leaves the branch it was invoked on.
    assert _git_ok(clone, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"


def test_rebase_verdicts_carry_their_hint_keywords_and_no_traceback(tmp_path):
    """Whichever rebase verdict the fixture produces, that verdict's own hint
    keyword is on stderr with no traceback: exit 5 names the conflict, exit 6
    names committing or stashing."""
    clone = _close_push_rejected(tmp_path, "hints")
    proc = run_close(clone, "2026-10-01-aaaaaa", push=True)
    err = proc.stderr
    assert "Traceback" not in err, err
    assert "fix" in err, err
    if proc.returncode == close_mod.EXIT_REBASE_CONFLICT:
        assert "conflict" in err, err
    elif proc.returncode == close_mod.EXIT_REBASE_REFUSED:
        assert "stash" in err, err
    else:
        raise AssertionError(f"unexpected verdict {proc.returncode}: {err}")


def test_failure_hints_name_their_code_and_carry_no_traceback(tmp_path):
    """Each failure exit close.py raises from a plain working copy prints its
    code's hint keyword on stderr and no traceback: exit 1 names register, exit
    2 names malformed, exit 4 names the usage fault it refuses."""
    clone, session = _repo_with_session(tmp_path)

    missing = run_close(clone, "2026-10-01-nope00")
    assert missing.returncode == close_mod.EXIT_SESSION_MISSING, missing.stderr
    assert "register" in missing.stderr, missing.stderr
    assert "Traceback" not in missing.stderr, missing.stderr

    session.write_text("# session\n\n- identity: dev\n", encoding="utf-8")
    malformed = run_close(clone, "2026-10-01-aaaaaa")
    assert malformed.returncode == close_mod.EXIT_SESSION_MALFORMED, malformed.stderr
    assert "malformed" in malformed.stderr, malformed.stderr
    assert "Traceback" not in malformed.stderr, malformed.stderr

    usage = run_close(clone, "a b")
    assert usage.returncode == close_mod.EXIT_USAGE, usage.stderr
    assert "not a single token" in usage.stderr, usage.stderr
    assert "Traceback" not in usage.stderr, usage.stderr


def test_non_token_session_id_exits_four(tmp_path):
    clone, _ = _repo_with_session(tmp_path)
    proc = run_close(clone, "a b")
    assert proc.returncode == close_mod.EXIT_USAGE, proc.returncode
    assert "not a single token" in proc.stderr, proc.stderr


def test_no_commit_with_push_exits_four(tmp_path):
    clone, _ = _repo_with_session(tmp_path)
    proc = run_close(clone, "2026-10-01-aaaaaa", **{"no-commit": None}, push=True)
    assert proc.returncode == close_mod.EXIT_USAGE, proc.returncode
    assert "cannot be combined with --push" in proc.stderr, proc.stderr


def test_repo_that_is_not_a_directory_exits_four(tmp_path):
    proc = run_close(tmp_path / "nowhere", "2026-10-01-aaaaaa")
    assert proc.returncode == close_mod.EXIT_USAGE, proc.returncode
    assert "is not a directory" in proc.stderr, proc.stderr


def test_a_tree_with_no_git_directory_behaves_as_no_commit(tmp_path):
    """Nothing to commit into is answered with the --no-commit line rather than
    a claimed commit or a git error."""
    plain = tmp_path / "plain"
    sid = "2026-10-01-plain1"
    (plain / "noni" / "sessions").mkdir(parents=True)
    (plain / "noni" / "sessions" / f"{sid}.md").write_text(
        BODY.format(sid=sid), encoding="utf-8")

    proc = run_close(plain, sid)
    assert proc.returncode == close_mod.EXIT_OK, proc.stderr
    assert "left uncommitted" in proc.stdout, proc.stdout
    assert "- status: closed" in (plain / "noni" / "sessions" / f"{sid}.md").read_text()


def test_close_never_deletes_the_register_file(tmp_path):
    """The file is the session's record and the census reads its history."""
    clone, session = _repo_with_session(tmp_path)
    proc = run_close(clone, "2026-10-01-aaaaaa")
    assert proc.returncode == close_mod.EXIT_OK, proc.stderr
    assert session.is_file()


# --- State root: --repo names it, the cwd does not ----------------------------
#
# close.py moves one line of one file, so the contract is narrow: the file it
# moves that line in is the one under the state root --repo named. Three trees:
# the state repository holding the session, a decoy session beside the cwd with
# the same id and an active status (so a cwd-driven run would have had a status
# line to move), and an empty cwd a stray write would show up in.

CLOSE_STATE_DIR = "close-state-root"
CLOSE_CWD_DIR = "close-cwd"
CLOSE_DECOY_DIR = "close-decoy"


def _close_state_root(tmp_path, sid="2026-10-01-aaaaaa"):
    """The state repository: a git repo whose only state is one active session."""
    origin = tmp_path / f"{CLOSE_STATE_DIR}.origin.git"
    root = tmp_path / CLOSE_STATE_DIR
    build_bare_origin(origin, [root])
    session = root / "noni" / "sessions" / f"{sid}.md"
    session.parent.mkdir(parents=True, exist_ok=True)
    session.write_text(BODY.format(sid=sid), encoding="utf-8")
    _git_ok(root, "add", f"noni/sessions/{sid}.md")
    _git_ok(root, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", f"register: {sid}")
    _git_ok(root, "push", "-q", "origin", "main")
    return root, session


def _close_case(tmp_path, sid="2026-10-01-aaaaaa"):
    """The three trees of one close state-root run: (state root, decoy, cwd)."""
    root, session = _close_state_root(tmp_path, sid)
    decoy = tmp_path / CLOSE_DECOY_DIR
    decoy_session = decoy / "noni" / "sessions" / f"{sid}.md"
    decoy_session.parent.mkdir(parents=True, exist_ok=True)
    decoy_session.write_text(BODY.format(sid=sid), encoding="utf-8")
    cwd = tmp_path / CLOSE_CWD_DIR
    cwd.mkdir(parents=True, exist_ok=True)
    return root, session, decoy_session, cwd


def _close_from(cwd: Path, repo: Path, sid: str) -> subprocess.CompletedProcess[str]:
    """close.py launched from ``cwd``, with ``--repo`` naming the state root."""
    return run_from(cwd, CLOSE, "--repo", str(repo), "--session-id", sid)


def test_close_writes_the_state_root_and_nothing_beside_the_cwd(tmp_path):
    """The status line moves in the state repository and the decoy session
    beside the cwd stays active, byte for byte."""
    sid = "2026-10-01-aaaaaa"
    root, session, decoy_session, cwd = _close_case(tmp_path, sid)
    decoy_bytes = decoy_session.read_bytes()

    proc = _close_from(cwd, root, sid)
    assert proc.returncode == close_mod.EXIT_OK, f"{proc.returncode}: {proc.stderr}"

    assert "- status: closed" in session.read_text(encoding="utf-8"), (
        "the state root's session was not closed"
    )
    assert _git_ok(root, "log", "-1", "--format=%s").stdout.strip().startswith("close:"), \
        "the close was not committed in the state repository"
    assert decoy_session.read_bytes() == decoy_bytes, (
        "the run closed the decoy session beside its cwd, so the register path "
        "resolved from somewhere other than --repo"
    )
    assert not (cwd / "noni").exists(), "the run created noni/ under the cwd"


def test_close_refuses_a_repo_that_is_not_a_directory(tmp_path):
    """A --repo naming no directory is refused (exit 4) naming the argument, and
    the decoy session beside the cwd stays active."""
    sid = "2026-10-01-aaaaaa"
    _root, _session, decoy_session, cwd = _close_case(tmp_path, sid)
    decoy_bytes = decoy_session.read_bytes()

    proc = _close_from(cwd, tmp_path / "no-such-state-root", sid)
    assert proc.returncode == close_mod.EXIT_USAGE, proc.returncode
    assert "--repo" in proc.stderr.lower(), proc.stderr
    assert "is not a directory" in proc.stderr, proc.stderr
    assert decoy_session.read_bytes() == decoy_bytes, (
        "a refused run wrote the decoy session beside its cwd"
    )
    assert not (cwd / "noni").exists()
