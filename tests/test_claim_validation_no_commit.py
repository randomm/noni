"""--no-commit on claim.py: the same validation chain, no git at all.

Extracted from the claim suite: the path that appends a claim without running a
single git command, checked by a git that fails loudly if it is ever invoked."""

import re

from _harness import (
    CLAIM,
    SRC,
    _git,
    _harness_source,
    _init_repo,
    run_claim,
)
from claim_fixtures import (
    SESSION_ID,
    _appended,
    _git_text,
    _make_session,
    _session_body,
    _session_path,
)

# --- --no-commit --------------------------------------------------------------


def test_no_commit_appends_without_touching_git(tmp_path):
    """--no-commit writes the row through the same chain and runs neither
    git add nor git commit: HEAD does not move and the row stays dirty."""
    repo = _make_session(tmp_path)
    head_before = _git_text(repo, "rev-parse", "HEAD")
    proc = run_claim(repo, SESSION_ID, "#42", **{"no-commit": None})
    assert proc.returncode == 0, f"expected exit 0, got {proc.returncode}: {proc.stderr}"
    # One line naming the file and saying the change is uncommitted (the
    # documented needle, not a paraphrase of it). The path is the caller-cwd
    # form -- ``--repo`` joined to ``noni/sessions/<id>.md`` -- the same token
    # the committed line names (issue #77, AC2).
    assert f"appended #42 to {repo / 'noni' / 'sessions' / f'{SESSION_ID}.md'}" \
        in proc.stdout
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
    """The guards must be anchored at the tail, not just prefixed.

    Under re.match, '$' also matches before a final newline, so '^\\S+$' accepts
    '#42\\n'. Two layers happen to stand in front of that today, and both are
    incidental: main() strips the argument before the guard, and the census
    strips every line it parses, so a broken row reaches no check and no
    consumer — the regex is the only guard that would ever see it. Hence this
    pins the guard itself (fullmatch plus a tail anchor, read off the shipped
    source) and not just the behaviour.

    The task guard is claim.py's own. The branch guard now lives where every
    path into a push must pass: ``_session_push.unsafe_branch_reason``, whose
    ``BRANCH_NAME_RE`` is read off that module's shipped source. claim.py's
    remaining ``BRANCH_SEGMENT_RE`` is pinned too, as is the fact that main()
    applies each of them with ``fullmatch``.
    """
    # The guards: pattern and call site, read from the files as shipped
    # (re.compile(...) is a Call, not a literal, so _script_constant cannot
    # reach these constants).
    source = _harness_source(CLAIM)
    anchor_pins = ((source, CLAIM.name, "TASK_RE"),
                   (source, CLAIM.name, "BRANCH_SEGMENT_RE"),
                   ((SRC / "noni" / "_session_push.py").read_text(encoding="utf-8"),
                    "_session_push.py", "BRANCH_NAME_RE"))
    for shipped, origin, name in anchor_pins:
        decl = re.search(rf"^{name} = re\.compile\(r\"(.*)\"\)", shipped, re.MULTILINE)
        assert decl is not None, f"{origin} does not define {name} as expected"
        assert decl.group(1).endswith("$"), (
            f"{name} = {decl.group(1)!r}: must end with a tail anchor"
        )
        applied = f"{name}.fullmatch(" in shipped
        if name == "BRANCH_NAME_RE":
            # The shared validator is the one call site, and it is a fullmatch.
            assert "BRANCH_NAME_RE.fullmatch(" in shipped, (
                f"{name} must be applied with fullmatch")
        assert applied, (
            f"{name} must be applied with fullmatch: under match, '$' also "
            f"matches before a trailing newline"
        )
    # The branch validation is one rule, not two that can drift: claim.py
    # routes its --branch through the shared validator rather than keeping a
    # regex of its own for the shapes git refuses.
    assert "unsafe_branch_reason(" in source, (
        f"{CLAIM.name} must validate --branch through the push loop's own "
        "validator, not a second pattern")

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
    # no strip stands in front of it. A newline is refused both as a leading
    # and as a trailing byte, and the refusal writes nothing.
    repo = _make_session(tmp_path / "t-branch")
    body_before = _session_path(repo).read_text()
    proc = run_claim(repo, SESSION_ID, "#42", branch="main\n", **{"no-commit": None})
    assert proc.returncode == 4, f"expected exit 4, got {proc.returncode}: {proc.stderr}"
    assert "branch" in proc.stderr.lower(), f"stderr must name the branch: {proc.stderr}"
    assert _session_path(repo).read_text() == body_before
