"""Validation tests for claim.py's documented grammar, guards and exit table.

Covers the E1-E5 hardening follow-ups and the agent-safety follow-up:
- --task must be a non-empty token (no embedded whitespace) - exit 4.
- --branch must be a safe ref name - exit 4.
- a session cannot append the same task claim twice - exit 2.
- the detached-HEAD guard fires when git rev-parse --abbrev-ref HEAD prints
  the literal string "HEAD" (what git actually prints when detached) rather
  than the parenthesised form, - exit 3.
- --no-commit appends through the same validation chain and runs no git.
- a rebase that starts and conflicts is aborted and reported as exit 5; a
  rebase git never started is exit 6 - both asserted with plumbing only.
- the docstring's Exit codes block and Usage block agree with the code.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

from _harness import (
    REPO,
    _claim_module,
    _git,
    _git_e2,
    _harness_source,
    _init_repo,
    _script_ast,
    _script_constant,
    advance_origin_with_claim,
    build_bare_origin,
    run_claim,
    run_register,
)

CLAIM = REPO / "skills" / "sessions-claims" / "scripts" / "claim.py"
SESSION_ID = "2026-10-01-aaaaaa"

# claim.py loaded as a module for the tests that drive its internals in-process
# (see _harness._claim_module: loaded by path under a name of our own, so no
# sys.path mutation and no collision with any other module named "claim").
claim_mod = _claim_module()


def _session_body(identity: str, claims: list[str] | None = None) -> str:
    lines = [f"- identity: {identity}", "- host/worktree: ws",
             "- started: 2026-10-01T10:00:00Z", "- status: active", "- claims:"]
    for c in claims or []:
        # Indented under the marker, the shape register.py writes and the
        # census parses; claim.py appends its own row at file EOF.
        lines.append(f"  - claim: {c}")
    return "\n".join(lines) + "\n"


def _appended(body: str, tasks: list[str]) -> str:
    """``body`` plus one claim row per task, appended where claim.py puts
    them: at file EOF, unindented."""
    for task in tasks:
        body += f"- claim: {task}\n"
    return body


def _make_session(tmp_path: Path, session_id: str = SESSION_ID,
                  claims: list[str] | None = None) -> Path:
    repo = _init_repo(tmp_path / "repo")
    sessions = repo / "noni" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f"{session_id}.md").write_text(_session_body("dev", claims))
    _git(repo, "add", f"noni/sessions/{session_id}.md")
    _git(repo, "commit", "-q", "-m", "session")
    return repo


def _session_path(repo: Path, session_id: str = SESSION_ID) -> Path:
    return repo / "noni" / "sessions" / f"{session_id}.md"


def _git_blob(repo: Path, revision: str, rel_path: str) -> str:
    """The exact bytes of ``rel_path`` at ``revision`` (plumbing, no filters).

    ``git cat-file`` rather than ``git show``: show runs the working-tree's
    textconv / clean-smudge filters over the blob it prints and can hand back an
    empty string for a file that is plainly there, which would make a fixture
    precondition fail on a file that is fine. cat-file is the plumbing path and
    prints the stored blob; a revision without that path exits non-zero, and the
    caller decides whether absence is an answer or a failure.
    """
    proc = _git_e2(repo, "cat-file", "-p", f"{revision}:{rel_path}")
    assert proc.returncode == 0, (
        f"git has no {rel_path} at {str(revision)[:12]}: {proc.stderr.strip()}"
    )
    return proc.stdout


def _git_text(repo: Path, *args: str) -> str:
    """Stdout of a plumbing git call (no identity needed, so nothing is written)."""
    return _git_e2(repo, *args).stdout.strip()


def _claim_tree() -> ast.Module:
    """Parse claim.py once so the parity readers below share one tree and one
    read of the file instead of each paying for both."""
    return _script_ast(CLAIM)


def _claim_docstring(tree: ast.Module) -> str:
    """The module docstring, typed before use: ast.get_docstring returns
    Optional[str] and every reader below splits it unconditionally."""
    doc = ast.get_docstring(tree)
    assert isinstance(doc, str), "claim.py has no module docstring"
    return doc


def _markdown_exit_codes(text: str, origin: str, only: set[int] | None = None) -> set[int]:
    """The codes in a markdown exit table: the rows are ``| `n` | meaning |``.

    The markdown copies of the claim exit table are the operator-facing
    contract; parsing them against the same constant set is what keeps them
    from renumbering quietly while the docstring parity test stays green.

    ``only`` restricts the parse to the codes the claim protocol owns: SKILL.md
    also carries the sessions-census table (30/31/32), which belongs to
    census-sessions.py and is not this script's contract.
    """
    rows = re.findall(r"^\|\s*`(\d+)`\s*\|", text, re.MULTILINE)
    assert rows, f"{origin} carries no '| `n` |' exit-code rows"
    codes = {int(m) for m in rows}
    if only is not None:
        claimed = codes & only
        assert claimed == only, (
            f"{origin} omits claim exit code(s) {sorted(only - claimed)} from its "
            f"table (it lists {sorted(codes)})"
        )
        codes = claimed
    assert codes, f"{origin} lists none of the claim codes {sorted(only or [])}"
    return codes


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


# --- --no-commit --------------------------------------------------------------


def test_no_commit_appends_without_touching_git(tmp_path):
    """--no-commit writes the row through the same chain and runs neither
    git add nor git commit: HEAD does not move and the row stays dirty."""
    repo = _make_session(tmp_path)
    head_before = _git_text(repo, "rev-parse", "HEAD")
    proc = run_claim(repo, SESSION_ID, "#42", **{"no-commit": None})
    assert proc.returncode == 0, f"expected exit 0, got {proc.returncode}: {proc.stderr}"
    # One line naming the file and saying the change is uncommitted (the
    # documented needle, not a paraphrase of it).
    assert f"appended #42 to {SESSION_ID}.md" in proc.stdout
    assert "left uncommitted" in proc.stdout
    assert "- claim: #42" in _session_path(repo).read_text(), "row must remain in the worktree"
    assert _git_text(repo, "rev-parse", "HEAD") == head_before, "no git commit may run"
    assert _git_text(repo, "status", "--porcelain") == f"M noni/sessions/{SESSION_ID}.md", (
        "the row must be left unstaged for the caller to commit"
    )


def test_no_commit_refuses_duplicate_row_written_by_earlier_no_commit(tmp_path):
    """The duplicate check reads the worktree file, so a row appended by a
    --no-commit run that was never committed still refuses the second run
    with exit 2."""
    repo = _make_session(tmp_path)
    first = run_claim(repo, SESSION_ID, "#42", **{"no-commit": None})
    assert first.returncode == 0, first.stderr
    second = run_claim(repo, SESSION_ID, "#42", **{"no-commit": None})
    assert second.returncode == 2, f"second no-commit: expected exit 2, got {second.returncode}: {second.stderr}"
    assert "Traceback" not in second.stderr
    assert _session_path(repo).read_text().count("- claim: #42") == 1


def test_no_commit_refuses_missing_register_file_without_writing(tmp_path):
    """The missing-register-file check (exit 1) runs on the --no-commit path
    too, and refuses before any write: no file is created."""
    repo = _init_repo(tmp_path / "repo")
    proc = run_claim(repo, "2026-10-01-bbbbbb", "#42", **{"no-commit": None})
    assert proc.returncode == 1, f"expected exit 1, got {proc.returncode}: {proc.stderr}"
    assert "register" in proc.stderr.lower()
    assert not _session_path(repo, "2026-10-01-bbbbbb").exists(), (
        "the refused run must not create a register file"
    )
    assert _git_text(repo, "status", "--porcelain") == ""


def test_no_commit_refuses_malformed_session(tmp_path):
    """The '- claims:' marker check also runs on the --no-commit path: a
    session file without the marker is refused with exit 2 and untouched."""
    repo = _init_repo(tmp_path / "repo")
    sessions = repo / "noni" / "sessions"
    sessions.mkdir(parents=True)
    target = sessions / f"{SESSION_ID}.md"
    body = "- identity: dev\n- host/worktree: ws\n- started: 2026-10-01T10:00:00Z\n- status: active\n"
    target.write_text(body)
    _git(repo, "add", f"noni/sessions/{SESSION_ID}.md")
    _git(repo, "commit", "-q", "-m", "session")
    proc = run_claim(repo, SESSION_ID, "#42", **{"no-commit": None})
    assert proc.returncode == 2, f"expected exit 2, got {proc.returncode}: {proc.stderr}"
    assert "Traceback" not in proc.stderr
    assert target.read_text() == body, "the malformed file must be left as it was"


def test_no_commit_with_push_is_refused_before_any_write(tmp_path):
    """--no-commit together with --push is a usage error (exit 4, not 2):
    exit 2 covers only malformation and duplicate claims. The refusal comes
    before the append, so nothing is written."""
    repo = _make_session(tmp_path)
    body_before = _session_path(repo).read_text()
    proc = run_claim(repo, SESSION_ID, "#42", push=True, **{"no-commit": None})
    assert proc.returncode == 4, f"expected exit 4, got {proc.returncode}: {proc.stderr}"
    assert "commit" in proc.stderr.lower() and "push" in proc.stderr.lower()
    assert "Traceback" not in proc.stderr
    assert _session_path(repo).read_text() == body_before, (
        "the refusal must happen before the row is appended"
    )
    assert _git_text(repo, "status", "--porcelain") == ""


def test_no_commit_validates_branch_then_ignores_it(tmp_path):
    """Under --no-commit the --branch guard still runs (a bad value is exit
    4), but a valid value changes nothing: same row, no push, no commit."""
    repo = _make_session(tmp_path)
    head_before = _git_text(repo, "rev-parse", "HEAD")
    for bad in ("feature/x", "a b"):
        proc = run_claim(repo, SESSION_ID, "#42", branch=bad, **{"no-commit": None})
        assert proc.returncode == 4, f"branch {bad!r}: expected exit 4, got {proc.returncode}: {proc.stderr}"
        assert "branch" in proc.stderr.lower()
    assert _session_path(repo).read_text() == _session_body("dev"), (
        "a refused --branch must not leave a row behind"
    )
    proc = run_claim(repo, SESSION_ID, "#42", branch="main", **{"no-commit": None})
    assert proc.returncode == 0, f"expected exit 0, got {proc.returncode}: {proc.stderr}"
    assert _session_path(repo).read_text() == _appended(_session_body("dev"), ["#42"]), (
        "a valid --branch must not change the appended row"
    )
    assert _git_text(repo, "rev-parse", "HEAD") == head_before, "--no-commit runs no git commit"
    # The line must say the flag changed nothing, not hint at a target branch.
    assert "nothing was committed or pushed" in proc.stdout, (
        f"--branch must be reported as having no effect: {proc.stdout!r}"
    )
    assert "target branch" not in proc.stdout, proc.stdout


def test_task_and_branch_guards_are_anchored_against_a_trailing_newline(tmp_path):
    """The two guards must be anchored at the tail, not just prefixed.

    Under re.match, '$' also matches before a final newline, so '^\\S+$' accepts
    '#42\\n'. Two layers happen to stand in front of that today, and both are
    incidental: main() strips the argument before the guard, and the census
    strips every line it parses, so a broken row reaches no check and no
    consumer — the regex is the only guard that would ever see it. Hence this
    pins the guard itself (fullmatch plus a tail anchor, read off the shipped
    source) and not just the behaviour.
    """
    # The guard: pattern and call site, read from the file claim.py ships
    # (re.compile(...) is a Call, not a literal, so _script_constant cannot
    # reach these constants).
    source = _harness_source(CLAIM)
    for name in ("TASK_RE", "BRANCH_RE"):
        decl = re.search(rf"^{name} = re\.compile\(r\"(.*)\"\)", source, re.MULTILINE)
        assert decl is not None, f"claim.py does not define {name} as expected"
        assert decl.group(1).endswith("$"), (
            f"{name} = {decl.group(1)!r}: must end with a tail anchor"
        )
        assert f"{name}.fullmatch(" in source, (
            f"{name} must be applied with fullmatch: under match, '$' also "
            f"matches before a trailing newline"
        )

    # The end state, for every way a newline can ride in on the task. Each
    # case either exits 4 having written nothing, or exits 0 with the file
    # byte-for-byte identical to a clean '#42' claim. Byte-for-byte, not
    # splitlines(): an unanchored guard writes "- claim: #42\n\n", and the
    # trailing blank line vanishes under splitlines() while the census's own
    # per-line strip makes it read that row as a clean claim. Nothing else in
    # the stack would notice the corruption, so this comparison is the check.
    clean = _make_session(tmp_path / "t-clean")
    assert run_claim(clean, SESSION_ID, "#42", **{"no-commit": None}).returncode == 0
    expected = _session_path(clean).read_text()
    for index, task in enumerate(("#42\n", "\n#42", "#42\r", "#42", "  #42  ")):
        repo = _make_session(tmp_path / f"t-{index}")
        proc = run_claim(repo, SESSION_ID, task, **{"no-commit": None})
        assert proc.returncode in (0, 4), f"{task!r}: {proc.returncode} {proc.stderr}"
        body = _session_path(repo).read_text()
        if proc.returncode == 0:
            assert body == expected, (
                f"--task {task!r} must land byte-for-byte as a clean '#42' claim; "
                f"got {body!r} vs {expected!r}"
            )
        else:
            assert "task" in proc.stderr.lower()
            assert body == _session_body("dev"), f"{task!r} refused after writing"

    # A newline in the middle is a real two-token task and was always refused.
    repo = _make_session(tmp_path / "t-middle")
    body_before = _session_path(repo).read_text()
    proc = run_claim(repo, SESSION_ID, "#42\nx")
    assert proc.returncode == 4, f"expected exit 4, got {proc.returncode}: {proc.stderr}"
    assert "task" in proc.stderr.lower(), f"stderr must name the task: {proc.stderr}"
    assert _session_path(repo).read_text() == body_before, (
        "a refused --task must leave the register file byte-for-byte as it was"
    )
    assert _git_text(repo, "status", "--porcelain") == "", "the refusal writes nothing"

    # The branch guard is anchored the same way: it feeds a push refspec, and
    # no strip stands in front of it.
    repo = _make_session(tmp_path / "t-branch")
    body_before = _session_path(repo).read_text()
    proc = run_claim(repo, SESSION_ID, "#42", branch="main\n", **{"no-commit": None})
    assert proc.returncode == 4, f"expected exit 4, got {proc.returncode}: {proc.stderr}"
    assert "branch" in proc.stderr.lower(), f"stderr must name the branch: {proc.stderr}"
    assert _session_path(repo).read_text() == body_before


# --- rebase conflict / refusal -------------------------------------------------


def _rebase_state_paths(repo: Path) -> list[Path]:
    """The directories a stopped rebase can leave, resolved through git itself
    (plumbing only: rev-parse --git-path, never a hand-built .git).

    The names come from claim.py's own REBASE_STATE_DIRS, so the set this file
    asserts on and the set the classifier probes are one list: a backend
    directory added to the constant is probed and asserted, never half of it.
    """
    out = []
    for name in _script_constant(_script_ast(CLAIM), "REBASE_STATE_DIRS", CLAIM.name):
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

    reg = run_register(clone, "developer", host="clone", worktree=str(clone))
    assert reg.returncode == 0, reg.stderr
    registered = reg.stdout.strip()
    needle = "registered session "
    assert needle in registered, (
        f"register.py no longer prints its documented success line ({needle!r}): "
        f"{registered!r}"
    )
    sid = registered.split(needle)[1].split()[0]
    session_file = f"noni/sessions/{sid}.md"
    _git(clone, "add", "noni/sessions/")
    _git(clone, "commit", "-q", "-m", "register")
    _git(clone, "push", "-q", "origin", "main")
    return origin, clone, sid, session_file


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


# --- doc / code parity ---------------------------------------------------------


def _module_exit_codes(tree: ast.Module) -> set[int]:
    """The set of codes the EXIT_* module constants hold, read via AST (no
    import: claim.py is a script the suite reaches as a subprocess).

    The constants carry an ``int`` annotation each, which makes this an
    AnnAssign node rather than an Assign; both forms are accepted so the check
    keeps working whichever way they are written. ``type() is int``, not
    isinstance: bool is an int subclass, and an exit code that drifted to
    True would otherwise pass.
    """
    codes: set[int] = set()
    for node in tree.body:
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if not isinstance(value, ast.Constant):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id.startswith("EXIT_"):
                assert type(value.value) is int, f"{target.id} is not an int"
                codes.add(value.value)
    assert codes, "claim.py defines no EXIT_* constants"
    return codes


def _docstring_exit_codes(doc: str) -> set[int]:
    """The codes listed in the docstring's 'Exit codes:' block."""
    lines = doc.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "Exit codes:")
    except StopIteration:
        raise AssertionError("docstring has no 'Exit codes:' block") from None
    codes: set[int] = set()
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        if not line.startswith(" " * 4):
            break  # the block ended; the prose after it is not an exit row
        head = line.strip().split(maxsplit=1)
        if head and head[0].isdigit():
            codes.add(int(head[0]))
    assert codes, "the 'Exit codes:' block lists no codes"
    return codes


def _parser_flags(tree: ast.Module) -> set[str]:
    """The long option strings claim.py's argparse parser declares."""
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    flags: set[str] = set()
    for node in ast.walk(main):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if arg.value.startswith("--"):
                        flags.add(arg.value)
    assert flags, "no add_argument calls found in main()"
    return flags


def _parser_dests(tree: ast.Module) -> dict[str, str]:
    """Map each long option string to the attribute name its action writes.

    The dash spelling alone is not the whole contract: claim.py reads
    ``args.no_commit``, so the dest is the other half and is what an alias or a
    renamed dest would silently break.
    """
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    dests: dict[str, str] = {}
    for node in ast.walk(main):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            opts = [
                arg.value for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                and arg.value.startswith("--")
            ]
            dest = next(
                (
                    kw.value.value
                    for kw in node.keywords
                    if kw.arg == "dest" and isinstance(kw.value, ast.Constant)
                ),
                None,
            )
            if dest is None and opts:
                # argparse's own rule: the first long option, dashes to
                # underscores.
                dest = opts[0].lstrip("-").replace("-", "_")
            if dest:
                for opt in opts:
                    dests[opt] = dest
    return dests


def _docstring_usage_flags(doc: str) -> set[str]:
    """Every --flag token anywhere in the docstring's 'Usage:' block."""
    # Anchor on the line, not the word: the prose above the block mentions
    # 'the Usage line' and would otherwise win the split.
    lines = doc.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "Usage:")
    except StopIteration:
        raise AssertionError("docstring has no 'Usage:' block") from None
    flags: set[str] = set()
    for line in lines[start + 1:]:
        if not line.startswith(" " * 4):
            break
        flags.update(re.findall(r"--[A-Za-z][A-Za-z0-9-]*", line))
    assert flags, "the 'Usage:' block names no flags"
    return flags


def test_docstring_exit_codes_match_the_exit_constants():
    """The docstring's exit table, the markdown tables and the EXIT_* constants
    are one contract: the same set of codes, pinned to PM's settled 0-6."""
    tree = _claim_tree()
    documented = _docstring_exit_codes(_claim_docstring(tree))
    published = _module_exit_codes(tree)
    assert documented == published, (
        f"docstring lists {sorted(documented)} but the constants are {sorted(published)}"
    )
    # PM's settled table, so a constant that quietly changes code fails here
    # rather than only in the tests that read the number.
    assert published == {0, 1, 2, 3, 4, 5, 6}
    # The two markdown copies are the operator-facing contract; the docstring
    # parity above says nothing about them, so they are parsed against the same
    # set. references/claim.md carries the one full table; SKILL.md keeps its
    # own copy for the operator who reads only the skill.
    for path in (
        REPO / "skills" / "sessions-claims" / "SKILL.md",
        REPO / "skills" / "sessions-claims" / "references" / "claim.md",
    ):
        markdown = _markdown_exit_codes(
            path.read_text(encoding="utf-8"), path.name, only=published
        )
        assert markdown == published, (
            f"{path.name} lists {sorted(markdown)} of the claim codes but the "
            f"constants are {sorted(published)}"
        )


def test_docstring_usage_flags_match_the_parser():
    """Every flag the parser accepts is documented in the Usage block,
    the block names nothing the parser would reject, and each flag writes the
    attribute name the code reads."""
    tree = _claim_tree()
    parser = _parser_flags(tree) - {"--help"}
    documented = _docstring_usage_flags(_claim_docstring(tree))
    assert documented == parser, (
        f"Usage block {sorted(documented)} vs parser {sorted(parser)}"
    )
    # The dash spelling is only half the contract: claim.py reads
    # args.no_commit and args.session_id, so the dest is asserted too.
    dests = _parser_dests(tree)
    assert dests["--no-commit"] == "no_commit", dests
    assert dests["--session-id"] == "session_id", dests
    assert dests["--push"] == "push", dests


def test_no_commit_is_a_real_option_of_claim_parser():
    """--no-commit is a flag claim.py's own parser declares (so the harness can
    forward it and the --push combination can be refused), read from the product
    rather than from a parser this test builds: the behaviour itself is covered
    by the --no-commit tests and the Usage-block parity test above."""
    flags = _parser_flags(_claim_tree())
    assert "--no-commit" in flags, f"claim.py declares {sorted(flags)}"
    assert "--push" in flags, f"claim.py declares {sorted(flags)}"
