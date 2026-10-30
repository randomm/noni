"""release.py: remove exactly one claim row, commit exactly one file.

A claim is a committed signal, so the two things this writer must never do are
remove the wrong row and sweep someone else's staged work into its commit. The
row grammar (``- claim: <task>``, see references/claim.md) is not changed here,
which is why an indented row under ``- claims:`` and a bare one at EOF (where
claim.py appends) are both released and neither shape is privileged.

Exit codes are read from the module's own constants, so a renumbering is this
file's failure rather than a silently passing assertion.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from _harness import (
    RELEASE,
    _git_ok,
    build_bare_origin,
    run_claim,
    run_from,
    run_register,
    run_release,
)

from noni import release as release_mod

BODY = """# session {sid}

- identity: dev
- host/worktree: host (repo)
- started: 2026-10-01T10:00:00Z
- status: active
- claims:
  - claim: #1
  - claim: #2
"""


_PATH = os.environ.get("PATH", "/usr/bin:/bin")
# The environment a refused commit needs: no global config for git to read a
# committer from, and no GIT_AUTHOR_* / GIT_COMMITTER_* (the launcher is asked
# not to add them). See the refused-commit test for what that state proves.


def _repo_with_session(tmp_path, body=None, sid="2026-10-01-aaaaaa", name="clone"):
    """A git repo holding one committed session file, by default claiming #1 and #2."""
    origin = tmp_path / f"{name}.origin.git"
    clone = tmp_path / name
    build_bare_origin(origin, [clone])
    session = clone / "noni" / "sessions" / f"{sid}.md"
    session.parent.mkdir(parents=True, exist_ok=True)
    session.write_text(body if body is not None else BODY.format(sid=sid),
                       encoding="utf-8")
    _git_ok(clone, "add", f"noni/sessions/{sid}.md")
    _git_ok(clone, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", f"register: {sid}")
    _git_ok(clone, "push", "-q", "origin", "main")
    return clone, session


def _origin_tip(origin: Path, branch: str = "main") -> str:
    """The subject of ``branch``'s tip in a bare origin (its HEAD names a branch
    no clone ever advances, so HEAD is not the thing to read)."""
    return _git_ok(origin, "log", "-1", "--format=%s", branch).stdout.strip()


def test_release_removes_the_named_row_and_keeps_the_other(tmp_path):
    """One row out, the rest byte-identical: the row is matched on the stripped
    line, so the indented row under the marker is the one that goes."""
    clone, session = _repo_with_session(tmp_path)
    before = session.read_text(encoding="utf-8").splitlines()

    proc = run_release(clone, "2026-10-01-aaaaaa", "#1")
    assert proc.returncode == release_mod.EXIT_OK, f"{proc.returncode}: {proc.stderr}"
    assert "released #1" in proc.stdout, proc.stdout

    after = session.read_text(encoding="utf-8").splitlines()
    assert "  - claim: #1" not in after, after
    assert "  - claim: #2" in after, after
    assert len(after) == len(before) - 1, (before, after)
    # Only the one line disappeared; nothing else moved.
    assert [line for line in before if line.strip() != "- claim: #1"] == after


def test_release_matches_a_bare_row_at_eof_the_same_way(tmp_path):
    """claim.py appends its row at EOF unindented; the census reads it and so
    does this writer, matched on the stripped line."""
    body = BODY.format(sid="2026-10-01-aaaaaa").rstrip("\n") + "\n- claim: #7\n"
    clone, session = _repo_with_session(tmp_path, body=body)

    proc = run_release(clone, "2026-10-01-aaaaaa", "#7")
    assert proc.returncode == release_mod.EXIT_OK, proc.stderr
    assert "- claim: #7" not in session.read_text(encoding="utf-8")
    assert "  - claim: #2" in session.read_text(encoding="utf-8")


def test_release_commits_only_the_sessions_own_file(tmp_path):
    clone, session = _repo_with_session(tmp_path)
    other = clone / "noni" / "decisions" / "other.json"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("{}\n", encoding="utf-8")
    _git_ok(clone, "add", "noni/decisions/other.json")

    proc = run_release(clone, "2026-10-01-aaaaaa", "#2")
    assert proc.returncode == release_mod.EXIT_OK, proc.stderr

    files = _git_ok(clone, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert files == ["noni/sessions/2026-10-01-aaaaaa.md"], files
    assert "A  noni/decisions/other.json" in _git_ok(clone, "status", "--porcelain").stdout
    assert _git_ok(clone, "log", "-1", "--format=%s").stdout.strip() == "release: #2"


def test_release_of_a_task_the_session_does_not_hold_exits_two(tmp_path):
    """The message names both the task and the session, so the operator can see
    which of the two was wrong."""
    clone, session = _repo_with_session(tmp_path)
    before = session.read_text(encoding="utf-8")

    proc = run_release(clone, "2026-10-01-aaaaaa", "#99")
    assert proc.returncode == release_mod.EXIT_NOT_HELD, proc.returncode
    assert "#99" in proc.stderr, proc.stderr
    assert "2026-10-01-aaaaaa" in proc.stderr, proc.stderr
    assert session.read_text(encoding="utf-8") == before


def test_release_of_a_missing_session_exits_one(tmp_path):
    clone, _ = _repo_with_session(tmp_path)
    proc = run_release(clone, "2026-10-01-nope00", "#1")
    assert proc.returncode == release_mod.EXIT_SESSION_MISSING, proc.returncode
    assert "register file not found" in proc.stderr, proc.stderr


def test_a_file_with_no_claims_marker_is_malformed_exit_two(tmp_path):
    """Without the marker the writer cannot tell a claim row from a field line,
    so it refuses rather than guessing which lines are rows."""
    clone, session = _repo_with_session(
        tmp_path, body="- identity: dev\n- status: active\n- claim: #1\n")
    proc = run_release(clone, "2026-10-01-aaaaaa", "#1")
    assert proc.returncode == release_mod.EXIT_NOT_HELD, proc.returncode
    assert "no '- claims:' marker" in proc.stderr, proc.stderr
    assert session.read_text(encoding="utf-8") == "- identity: dev\n- status: active\n- claim: #1\n"


def test_two_identical_rows_are_refused_not_guessed(tmp_path):
    """claim.py refuses a duplicate, so two identical rows mean the file was
    edited outside the writers; removing one silently reports a release the
    census does not agree with."""
    body = (BODY.format(sid="2026-10-01-aaaaaa").rstrip("\n")
            + "\n- claim: #5\n- claim: #5\n")
    clone, session = _repo_with_session(tmp_path, body=body)
    before = session.read_text(encoding="utf-8")

    proc = run_release(clone, "2026-10-01-aaaaaa", "#5")
    assert proc.returncode == release_mod.EXIT_NOT_HELD, proc.returncode
    assert "holds 2 '- claim: #5' rows" in proc.stderr, proc.stderr
    assert session.read_text(encoding="utf-8") == before


def test_unreadable_bytes_exit_two_and_never_a_traceback(tmp_path):
    """A UnicodeDecodeError carries no strerror; naming it would crash here."""
    clone, session = _repo_with_session(tmp_path)
    session.write_bytes(b"\xff\xfe\x00 not utf-8")
    proc = run_release(clone, "2026-10-01-aaaaaa", "#1")
    assert proc.returncode == release_mod.EXIT_NOT_HELD, proc.returncode
    assert "Traceback" not in proc.stderr, proc.stderr
    assert "UnicodeDecodeError" in proc.stderr, proc.stderr


def test_no_commit_removes_the_row_and_runs_no_git(tmp_path):
    clone, session = _repo_with_session(tmp_path)
    head_before = _git_ok(clone, "rev-parse", "HEAD").stdout.strip()

    proc = run_release(clone, "2026-10-01-aaaaaa", "#1", **{"no-commit": None})
    assert proc.returncode == release_mod.EXIT_OK, proc.stderr
    assert "left uncommitted" in proc.stdout, proc.stdout
    assert "- claim: #1" not in session.read_text(encoding="utf-8")
    assert _git_ok(clone, "rev-parse", "HEAD").stdout.strip() == head_before


def test_push_after_release_lands_the_commit_on_origin(tmp_path):
    origin = tmp_path / "origin.git"
    clone = tmp_path / "clone"
    build_bare_origin(origin, [clone])
    reg = run_register(clone, "dev", host="h")
    assert reg.returncode == 0, reg.stderr
    sid = reg.stdout.strip().split("registered session ")[1].split(" ->")[0].strip()

    claim = run_claim(clone, sid, "#3", push=True)
    assert claim.returncode == 0, claim.stderr

    proc = run_release(clone, sid, "#3", push=True)
    assert proc.returncode == release_mod.EXIT_OK, proc.stderr
    assert _origin_tip(origin) == "release: #3"
    # What origin holds is the released state: no row for #3.
    tip_body = _git_ok(clone, "show", f"origin/main:noni/sessions/{sid}.md").stdout
    assert "- claim: #3" not in tip_body, tip_body


def test_detached_head_with_push_is_refused(tmp_path):
    clone, _ = _repo_with_session(tmp_path)
    head = _git_ok(clone, "rev-parse", "HEAD").stdout.strip()
    _git_ok(clone, "checkout", "-q", "--detach", head)

    proc = run_release(clone, "2026-10-01-aaaaaa", "#1", push=True)
    assert proc.returncode == release_mod.EXIT_PUSH_FAILED, proc.returncode
    assert "push refused" in proc.stderr, proc.stderr


def _pushable(tmp_path, name="clone"):
    """A clone with an origin and a committed session claiming #1 and #2, ready
    for --push."""
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


def _advance_origin(tmp_path, origin, lines, name):
    """Replace the session file on origin/main with ``lines`` via a scratch clone."""
    seed = tmp_path / name
    work = seed / "w"
    seed.mkdir(parents=True)
    _git_ok(seed, "clone", "-q", "-b", "main", str(origin), str(work))
    (work / "noni" / "sessions").mkdir(parents=True, exist_ok=True)
    (work / "noni" / "sessions" / "2026-10-01-aaaaaa.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    _git_ok(work, "add", "noni/sessions/2026-10-01-aaaaaa.md")
    _git_ok(work, "-c", "user.name=Seeder", "-c", "user.email=seeder@fixture.invalid",
            "commit", "-q", "-m", f"seed: {name}")
    _git_ok(work, "push", "-q", "origin", "main")


def _release_push_rejected(tmp_path, name):
    """A clone whose release --push cannot land: origin rewrote the same rows.

    The clone's rebase cannot merge the two sides, so the run answers with one
    of the two rebase verdicts (the helper's own classification decides which);
    both are rebase codes, neither is exit 3.
    """
    origin, clone = _pushable(tmp_path, name=name)
    _advance_origin(tmp_path, origin,
                    ["- claim: #1", "- claim: #9", "- claim: #2"],
                    f"{name}.seed-other")
    return clone


def test_push_rebase_conflict_is_a_rebase_code_not_three(tmp_path):
    """A session-file conflict on --push is the conflict code, not "push
    failed": an agent scripting on these codes must be able to tell 'resolve
    the session file' from 'retry the push' (claim.py's split, #22)."""
    clone = _release_push_rejected(tmp_path, "conflict")
    proc = run_release(clone, "2026-10-01-aaaaaa", "#1", push=True)
    assert proc.returncode in (release_mod.EXIT_REBASE_CONFLICT,
                               release_mod.EXIT_REBASE_REFUSED), (
        proc.returncode, proc.stderr)
    # The clone is not left mid-rebase: an aborted (or never-started) rebase
    # leaves the branch it was invoked on.
    assert _git_ok(clone, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"


def test_rebase_verdicts_carry_their_hint_keywords_and_no_traceback(tmp_path):
    """Whichever rebase verdict the fixture produces, that verdict's own hint
    keyword is on stderr with no traceback: exit 5 names the conflict, exit 6
    names committing or stashing."""
    clone = _release_push_rejected(tmp_path, "hints")
    proc = run_release(clone, "2026-10-01-aaaaaa", "#1", push=True)
    err = proc.stderr
    assert "Traceback" not in err, err
    assert "fix" in err, err
    if proc.returncode == release_mod.EXIT_REBASE_CONFLICT:
        assert "conflict" in err, err
    elif proc.returncode == release_mod.EXIT_REBASE_REFUSED:
        assert "stash" in err, err
    else:
        raise AssertionError(f"unexpected verdict {proc.returncode}: {err}")


def test_a_commit_that_was_refused_names_the_cause_in_noni_words(tmp_path):
    """AC2 for release: a refused commit says so in one noni sentence, not a dump.

    Reached the way an operator reaches it (a state repository whose committer
    was never configured), and asserted in both directions: the message names
    the cause, names the path, admits the row is already removed in the working
    copy, and carries none of the ``XY path`` rows a raw ``git status
    --porcelain`` block is made of. The row really is gone from the file and
    really is still in HEAD, which is the half-applied state the message has to
    describe truthfully.
    """
    clone, session = _repo_with_session(tmp_path, name="clone-refused")
    head_before = _git_ok(clone, "rev-parse", "HEAD").stdout.strip()

    proc = run_from(clone, RELEASE, "--repo", str(clone),
                    "--session-id", "2026-10-01-aaaaaa", "--task", "#1",
                    identity=False,
                    env={"GIT_CONFIG_GLOBAL": "/dev/null", "PATH": _PATH})

    assert proc.returncode == release_mod.EXIT_PUSH_FAILED, f"{proc.returncode}: {proc.stderr}"
    err = proc.stderr
    assert "git could not commit" in err, err
    assert "the change is written" in err, err
    assert "noni/sessions/2026-10-01-aaaaaa.md" in err, err
    assert "by hand" in err, err
    assert " M noni/" not in err and "A  noni/" not in err, err
    assert "- claim: #1" not in session.read_text(encoding="utf-8")
    assert "- claim: #1" in _git_ok(clone, "show", "HEAD:noni/sessions/"
                                    "2026-10-01-aaaaaa.md").stdout
    assert _git_ok(clone, "rev-parse", "HEAD").stdout.strip() == head_before


def test_failure_hints_name_their_code_and_carry_no_traceback(tmp_path):
    """Each failure exit release.py raises from a plain working copy prints its
    code's hint keyword on stderr and no traceback: exit 1 names register, exit
    2 names the task it does not hold and calls the file malformed, exit 4
    names the usage fault it refuses."""
    clone, session = _repo_with_session(tmp_path)

    missing = run_release(clone, "2026-10-01-nope00", "#1")
    assert missing.returncode == release_mod.EXIT_SESSION_MISSING, missing.stderr
    assert "register" in missing.stderr, missing.stderr
    assert "Traceback" not in missing.stderr, missing.stderr

    not_held = run_release(clone, "2026-10-01-aaaaaa", "#77")
    assert not_held.returncode == release_mod.EXIT_NOT_HELD, not_held.stderr
    assert "not held" in not_held.stderr, not_held.stderr
    assert "#77" in not_held.stderr, not_held.stderr
    assert "2026-10-01-aaaaaa" in not_held.stderr, not_held.stderr
    assert "Traceback" not in not_held.stderr, not_held.stderr

    session.write_text("# session\n\n- identity: dev\n", encoding="utf-8")
    malformed = run_release(clone, "2026-10-01-aaaaaa", "#1")
    assert malformed.returncode == release_mod.EXIT_NOT_HELD, malformed.stderr
    assert "malformed" in malformed.stderr, malformed.stderr
    assert "Traceback" not in malformed.stderr, malformed.stderr

    usage = run_release(clone, "2026-10-01-aaaaaa", "a b")
    assert usage.returncode == release_mod.EXIT_USAGE, usage.stderr
    assert "not a single token" in usage.stderr, usage.stderr
    assert "Traceback" not in usage.stderr, usage.stderr


def test_non_token_arguments_exit_four(tmp_path):
    clone, _ = _repo_with_session(tmp_path)
    for bad in ("a b", "a/b", ""):
        proc = run_release(clone, bad, "#1")
        assert proc.returncode == release_mod.EXIT_USAGE, (bad, proc.returncode)
        assert "not a single token" in proc.stderr, proc.stderr

        proc = run_release(clone, "2026-10-01-aaaaaa", bad)
        assert proc.returncode == release_mod.EXIT_USAGE, (bad, proc.returncode)
        assert "not a single token" in proc.stderr, proc.stderr


def test_no_commit_with_push_exits_four(tmp_path):
    clone, _ = _repo_with_session(tmp_path)
    proc = run_release(clone, "2026-10-01-aaaaaa", "#1", **{"no-commit": None},
                       push=True)
    assert proc.returncode == release_mod.EXIT_USAGE, proc.returncode
    assert "cannot be combined with --push" in proc.stderr, proc.stderr


def test_a_tree_with_no_git_directory_behaves_as_no_commit(tmp_path):
    plain = tmp_path / "plain"
    sid = "2026-10-01-plain1"
    (plain / "noni" / "sessions").mkdir(parents=True)
    (plain / "noni" / "sessions" / f"{sid}.md").write_text(
        BODY.format(sid=sid), encoding="utf-8")

    proc = run_release(plain, sid, "#1")
    assert proc.returncode == release_mod.EXIT_OK, proc.stderr
    assert "left uncommitted" in proc.stdout, proc.stdout
    assert "- claim: #1" not in (plain / "noni" / "sessions" / f"{sid}.md").read_text()


def test_release_never_deletes_the_session_file(tmp_path):
    """Releasing the last claim leaves the register file in place: it is the
    session's record, and the census reads history for the deleted-file check."""
    body = (BODY.format(sid="2026-10-01-aaaaaa").replace("  - claim: #1\n", "")
            .replace("  - claim: #2\n", ""))
    clone, session = _repo_with_session(tmp_path, body=body + "- claim: #9\n")

    proc = run_release(clone, "2026-10-01-aaaaaa", "#9")
    assert proc.returncode == release_mod.EXIT_OK, proc.stderr
    assert session.is_file()
    assert "- claims:" in session.read_text(encoding="utf-8")


# --- State root: --repo names it, the cwd does not ----------------------------
#
# release.py removes one claim row from one file, so the pair of assertions is
# the whole contract: the row is gone from the state root's register, and the
# decoy register beside the cwd still carries both of its rows.

RELEASE_STATE_DIR = "release-state-root"
RELEASE_CWD_DIR = "release-cwd"
RELEASE_DECOY_DIR = "release-decoy"


def _release_state_root(tmp_path, sid="2026-10-01-aaaaaa"):
    """The state repository: a git repo whose only state is one session holding
    the two claim rows release.py chooses between."""
    origin = tmp_path / f"{RELEASE_STATE_DIR}.origin.git"
    root = tmp_path / RELEASE_STATE_DIR
    build_bare_origin(origin, [root])
    session = root / "noni" / "sessions" / f"{sid}.md"
    session.parent.mkdir(parents=True, exist_ok=True)
    session.write_text(BODY.format(sid=sid), encoding="utf-8")
    _git_ok(root, "add", f"noni/sessions/{sid}.md")
    _git_ok(root, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", f"register: {sid}")
    _git_ok(root, "push", "-q", "origin", "main")
    return root, session


def _release_case(tmp_path, sid="2026-10-01-aaaaaa"):
    """The three trees of one release state-root run: (root, session, decoy, cwd)."""
    root, session = _release_state_root(tmp_path, sid)
    decoy = tmp_path / RELEASE_DECOY_DIR
    decoy_session = decoy / "noni" / "sessions" / f"{sid}.md"
    decoy_session.parent.mkdir(parents=True, exist_ok=True)
    decoy_session.write_text(BODY.format(sid=sid), encoding="utf-8")
    cwd = tmp_path / RELEASE_CWD_DIR
    cwd.mkdir(parents=True, exist_ok=True)
    return root, session, decoy_session, cwd


def _release_from(cwd: Path, repo: Path, sid: str, task: str
                  ) -> subprocess.CompletedProcess[str]:
    """release.py launched from ``cwd``, with ``--repo`` naming the state root."""
    return run_from(cwd, RELEASE, "--repo", str(repo), "--session-id", sid,
                    "--task", task)


def test_release_removes_the_row_in_the_state_root_only(tmp_path):
    """The row disappears from the state root's register and the decoy register
    beside the cwd keeps both of its rows."""
    sid = "2026-10-01-aaaaaa"
    root, session, decoy_session, cwd = _release_case(tmp_path, sid)
    decoy_bytes = decoy_session.read_bytes()

    proc = _release_from(cwd, root, sid, "#1")
    assert proc.returncode == release_mod.EXIT_OK, f"{proc.returncode}: {proc.stderr}"

    body = session.read_text(encoding="utf-8")
    assert "- claim: #1" not in body, "the state root's row was not released"
    assert "- claim: #2" in body, "the writer released a row nobody named"
    assert _git_ok(root, "log", "-1", "--format=%s").stdout.strip().startswith("release:"), \
        "the release was not committed in the state repository"
    assert decoy_session.read_bytes() == decoy_bytes, (
        "the run edited the decoy register beside its cwd, so the register path "
        "resolved from somewhere other than --repo"
    )
    assert not (cwd / "noni").exists(), "the run created noni/ under the cwd"


def test_release_refuses_a_repo_that_is_not_a_directory(tmp_path):
    """A --repo naming no directory is refused (exit 4) naming the argument, and
    the decoy register beside the cwd keeps both of its rows."""
    sid = "2026-10-01-aaaaaa"
    _root, _session, decoy_session, cwd = _release_case(tmp_path, sid)
    decoy_bytes = decoy_session.read_bytes()

    proc = _release_from(cwd, tmp_path / "no-such-state-root", sid, "#1")
    assert proc.returncode == release_mod.EXIT_USAGE, proc.returncode
    assert "--repo" in proc.stderr.lower(), proc.stderr
    assert "is not a directory" in proc.stderr, proc.stderr
    assert decoy_session.read_bytes() == decoy_bytes, (
        "a refused run edited the decoy register beside its cwd"
    )
    assert not (cwd / "noni").exists()
