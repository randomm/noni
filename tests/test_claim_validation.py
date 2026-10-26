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

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

from _harness import (
    REPO,
    _git,
    _git_e2,
    _init_repo,
    advance_origin_with_claim,
    build_bare_origin,
    run_claim,
    run_register,
)

CLAIM = REPO / "skills" / "sessions-claims" / "scripts" / "claim.py"
SESSION_ID = "2026-10-01-aaaaaa"


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


def _git_text(repo: Path, *args: str) -> str:
    """Stdout of a plumbing git call (no identity needed, so nothing is written)."""
    return _git_e2(repo, *args).stdout.strip()


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


# --- rebase conflict / refusal -------------------------------------------------


def _rebase_state_paths(repo: Path) -> list[Path]:
    """The two directories a stopped rebase can leave, resolved through git
    itself (plumbing only: rev-parse --git-path, never a hand-built .git)."""
    out = []
    for name in ("rebase-merge", "rebase-apply"):
        raw = Path(_git_text(repo, "rev-parse", "--git-path", name))
        out.append(raw if raw.is_absolute() else repo / raw)
    return out


def _seed_ahead_of_tracking_ref(origin: Path, clone: Path, session_file: str) -> str:
    """Move ``origin`` ahead of ``clone`` without ``clone`` ever fetching.

    The distinction matters: claim.py rebases onto origin/<branch>, which git
    resolves against its own remote-tracking ref, not against the real tip.
    A clone that has already fetched the seed commit finds itself up to date,
    its rebase is a no-op, and the push goes through - so the fetch-rebase-push
    branch would never be entered and a conflict or refusal test would pass on
    nothing. Seeding through a throwaway clone leaves the caller's
    origin/<branch> stale: the push is then rejected on every attempt, and the
    rebase is what the test is actually about.

    Returns the seed commit's sha. Callers that need a real same-file conflict
    must still assert the stop themselves (_precondition_rebase_stops).
    """
    sha = advance_origin_with_claim(origin, clone.parent / "seeder", session_file, "#99")
    assert _git_text(clone, "rev-parse", "origin/main") != sha, (
        "precondition: the clone must not already hold the seed commit in "
        "origin/main, or its rebase is a no-op and the push never gets rejected"
    )
    return sha


def _precondition_rebase_stops(repo: Path, branch: str) -> None:
    """Prove the rebase actually stopped in a conflict, from real evidence.

    Called after the run whose behaviour is under test: a run that reported a
    conflict while leaving the clone wedged, or while never entering a rebase
    at all, is exactly the bug, so the check belongs on the post-run state and
    never on a synthetic pre-run probe (which would itself move HEAD and make
    the comparison below meaningless).
    """
    for state in _rebase_state_paths(repo):
        assert not state.exists(), f"{state} left behind: the clone is wedged mid-rebase"
    assert _git_text(repo, "rev-parse", "--abbrev-ref", "HEAD") == branch, (
        f"HEAD must be back on {branch!r} after the abort"
    )


def test_rebase_conflict_is_aborted_and_reported_as_exit_5(tmp_path):
    """A fetch-rebase-push that hits a same-file conflict exits 5, leaves no
    rebase-merge/ or rebase-apply/ behind, keeps HEAD on the original branch
    at the pre-attempt sha with the claim commit intact, and prints git's own
    output plus a fix hint on stderr."""
    origin = tmp_path / "origin.git"
    clone = tmp_path / "clone"
    build_bare_origin(origin, [clone])

    reg = run_register(clone, "developer", host="clone", worktree=str(clone))
    assert reg.returncode == 0, reg.stderr
    sid = reg.stdout.strip().split("->")[0].split("registered session ")[1].strip()
    session_file = f"noni/sessions/{sid}.md"
    _git(clone, "add", "noni/sessions/")
    _git(clone, "commit", "-q", "-m", "register")
    _git(clone, "push", "-q", "origin", "main")

    # A second writer lands a claim row at EOF of the same file, and the
    # clone's remote-tracking ref stays behind it: both sides append, so the
    # caller's rebase must stop in a conflict.
    _seed_ahead_of_tracking_ref(origin, clone, session_file)

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

    # Post-conditions, all via plumbing: nothing left mid-rebase, and HEAD
    # restored byte-identically to the claim commit this run created.
    for state in _rebase_state_paths(clone):
        assert not state.exists(), f"{state} left behind after the abort"
    assert _git_text(clone, "rev-parse", "--abbrev-ref", "HEAD") == branch_before, (
        "HEAD must be back on the original branch"
    )
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


def test_rebase_refused_by_dirty_worktree_exits_6(tmp_path):
    """When git refuses to start the rebase (an unstaged modification of a
    tracked file other than the session file) claim.py exits 6, runs no
    abort, and its hint names committing or stashing."""
    origin = tmp_path / "origin.git"
    clone = tmp_path / "clone"
    build_bare_origin(origin, [clone])

    reg = run_register(clone, "developer", host="clone", worktree=str(clone))
    assert reg.returncode == 0, reg.stderr
    sid = reg.stdout.strip().split("->")[0].split("registered session ")[1].strip()
    session_file = f"noni/sessions/{sid}.md"
    _git(clone, "add", "noni/sessions/")
    _git(clone, "commit", "-q", "-m", "register")
    _git(clone, "push", "-q", "origin", "main")

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
    assert "claim: #42" in _git_text(clone, "log", "-1", "--format=%B", claim_commit), (
        "the run must have committed the claim before the push failed"
    )
    assert _git_text(clone, "status", "--porcelain") == "M README.md", (
        "a refusal touches nothing: the unstaged dirt is exactly where it was "
        "(porcelain XY, with the modification unstaged)"
    )

    low = proc.stderr.lower()
    assert "stash" in low, f"the refusal hint must name stashing: {proc.stderr}"
    assert "commit" in low, f"the refusal hint must name committing: {proc.stderr}"
    assert "refus" in low, f"stderr must say the rebase was refused: {proc.stderr}"
    assert "Traceback" not in proc.stderr, f"unhandled exception: {proc.stderr}"


def test_rebase_timeout_is_push_class_not_conflict(tmp_path, monkeypatch):
    """A rebase that times out (124, what claim.py's GIT_TIMEOUT produces)
    says nothing about conflicts: the probe for rebase-merge/rebase-apply is
    what selects 5 vs 6, so a timeout routes to exit 3 rather than either."""
    sys.path.insert(0, str(CLAIM.parent))
    import claim as claim_mod

    def timed_out(args, cwd):
        return subprocess.CompletedProcess(
            ["git"] + args, returncode=124, stdout="",
            stderr=f"git {args[0]} timed out after {claim_mod.GIT_TIMEOUT}s",
        )

    monkeypatch.setattr(claim_mod, "_git", timed_out)
    monkeypatch.setattr(
        claim_mod, "_rebase_stopped",
        lambda repo: (_ for _ in ()).throw(AssertionError("classifier must not run for a timeout")),
    )
    assert claim_mod._push_with_retry(Path("/does-not-matter"), "main", attempts=2) == claim_mod.EXIT_PUSH_FAILED


# --- doc / code parity ---------------------------------------------------------


def _module_exit_codes() -> set[int]:
    """The set of codes the EXIT_* module constants hold, read via AST (no
    import: claim.py is a script the suite reaches as a subprocess)."""
    tree = ast.parse(CLAIM.read_text(encoding="utf-8"))
    codes: set[int] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.startswith("EXIT_"):
                    assert isinstance(node.value.value, int), f"{target.id} is not an int"
                    codes.add(node.value.value)
    assert codes, "claim.py defines no EXIT_* constants"
    return codes


def _docstring_exit_codes() -> set[int]:
    """The codes listed in the docstring's 'Exit codes:' block."""
    doc = ast.get_docstring(ast.parse(CLAIM.read_text(encoding="utf-8")))
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


def _parser_flags() -> set[str]:
    """The long option strings claim.py's argparse parser declares."""
    tree = ast.parse(CLAIM.read_text(encoding="utf-8"))
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


def _docstring_usage_flags() -> set[str]:
    """Every --flag token anywhere in the docstring's 'Usage:' block."""
    doc = ast.get_docstring(ast.parse(CLAIM.read_text(encoding="utf-8")))
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
    """The documented exit table and the EXIT_* constants are one contract:
    every code claim.py can return is documented, and nothing documented is
    unreachable in code."""
    documented = _docstring_exit_codes()
    published = _module_exit_codes()
    assert documented == published, (
        f"docstring lists {sorted(documented)} but the constants are {sorted(published)}"
    )
    # PM's settled table, so a constant that quietly changes code fails here
    # rather than only in the tests that read the number.
    assert published == {0, 1, 2, 3, 4, 5, 6}


def test_docstring_usage_flags_match_the_parser():
    """Every flag the parser accepts is documented in the Usage block, and
    the block names nothing the parser would reject."""
    parser = _parser_flags() - {"--help"}
    documented = _docstring_usage_flags()
    assert documented == parser, (
        f"Usage block {sorted(documented)} vs parser {sorted(parser)}"
    )


def test_parser_accepts_no_commit_and_rejects_unknown_flag():
    """The --no-commit flag is a real argparse option (so the harness can
    forward it), and an unknown flag is still argparse's own refusal."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-commit", action="store_true")
    assert parser.parse_args(["--no-commit"]).no_commit is True
    try:
        parser.parse_args(["--nope"])
    except SystemExit:
        pass
    else:  # pragma: no cover - argparse must refuse an unknown flag
        raise AssertionError("argparse accepted an unknown flag")
