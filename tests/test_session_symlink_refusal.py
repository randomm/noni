"""The four session writers refuse a symlinked session file, a symlinked
``noni/sessions/`` and a symlinked ``noni/``, on the code docs/PRODUCT.md 7 owes
each of them (issue #68).

The writers already refused a state root that was itself a link, and the census
already refuses to read through a symlinked session file. What nothing refused
was the session FILE reached by a writer: ``is_file()`` follows a link, so a
symlinked file read as present and the writer's atomic replace landed on the
link's target -- the link unmade and somebody's file replaced with session bytes.
A symlinked ``noni/sessions/`` was the same fault one level up: the file landed
outside the tree and git refused a path "beyond a symbolic link".

A third shape sits above both of those, and is the reason the guard asks its
directory question of every component under the state root rather than of the two
it writes into. With ``noni/`` itself a link, ``lstat`` resolves it and the
sessions directory and the file beneath it answer exactly what they should: the
guard sees nothing, the write composes onto a file outside the clone, and git --
not noni -- is what objects, with a code no page documents.

So the verdict is a refusal, on the code docs/PRODUCT.md 7 already gives each tool
for a wrong path (2 for ``register``, 4 for ``claim``, ``close`` and ``release``),
in noni's words, naming the path. Each test here is the run plus what the run did
NOT do: the link is still a link, the target's bytes are the bytes the fixture
wrote, the state clone's tracked files are unmoved, and HEAD is unmoved. For
``register`` the promise has two extra clauses, because it is the writer that
creates the sessions directory and the working-copy marker.

The last two cases are the other half of the contract: a regular session file
still writes, and a project reached *through* a linked ancestor is still a normal
run, so the guard cannot turn the quickstart's own layout into a refusal.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from _harness import CLAIM, CLOSE, REGISTER, RELEASE, _git_ok, run_from, subprocess_env
from session_git_support import STATE_BODY, STATE_DIR, _nested_state, _pinned_allocation_driver

# The id the nested-state fixture commits its session at.
SID = "2026-10-01-cccccc"

# Each writer, the wrapper the skills document for it, the code docs/PRODUCT.md 7
# owes it for a wrong path, and the argv beyond --repo. One table drives both
# sweeps, so "all four refuse the same shapes on the same codes" is one assertion
# over four rows rather than four tests that could each drift.
WRITERS = (
    ("register", REGISTER, 2, ("--identity", "developer")),
    ("claim", CLAIM, 4, ("--session-id", SID, "--task", "#9")),
    ("close", CLOSE, 4, ("--session-id", SID)),
    ("release", RELEASE, 4, ("--session-id", SID, "--task", "#1")),
)

# A body the writers would have accepted, and so the bytes the link's target must
# still hold after a run that was supposed to change them.
TARGET_BODY = STATE_BODY.format(sid=SID, status="active")


def _run(project: Path, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One writer launched from the project cwd with the argv the caller owns."""
    return run_from(project, script, *args)


def _assert_refused(proc, state: Path, planted: Path, target: Path,
                    label: str, code: int, what: str,
                    dirty_before: list[str] | None = None) -> None:
    """The shared post-conditions for one refusal, whatever the planted shape was.

    ``dirty_before`` is the porcelain the fixture itself already showed (a linked
    sessions directory hides a tracked file, so git reports a deletion before any
    run). It defaults to clean, which is the promise for the shapes that leave the
    index untouched.
    """
    assert proc.returncode == code, (
        f"{label}: docs/PRODUCT.md 7 documents exit {code} for a wrong path, got "
        f"{proc.returncode}: {proc.stderr}"
    )
    err = proc.stderr.lower()
    assert "symlink" in err, f"{label}: the refusal must say what is wrong: {proc.stderr}"
    # The refusal names the path the writer was about to touch, in the form the
    # operator passed it: --repo was given as STATE_DIR, so the name the writer
    # holds is the state root's own name joined to the path inside it.
    named = str(planted.relative_to(state))
    assert named in proc.stderr, (
        f"{label}: the refusal must name the offending path: {proc.stderr}"
    )
    assert "fatal:" not in err and "pathspec" not in err, (
        f"{label}: an opaque git error, not a noni diagnostic: {proc.stderr}"
    )
    assert "traceback" not in err, f"{label}: a crash, not a refusal: {proc.stderr}"
    assert planted.is_symlink(), f"{label}: the run unmade the link"
    assert target.read_text(encoding="utf-8") == TARGET_BODY, (
        f"{label}: the run wrote through the link into {target}"
    )
    assert _git_ok(state, "status", "--porcelain").stdout.splitlines() == (
        dirty_before if dirty_before is not None else []), (
        f"{label}: a refused run dirtied the state clone beyond the planted {what}"
    )


def _plant_file(tmp_path: Path, name: str) -> tuple[Path, Path, Path, Path]:
    """The route with a symlink standing at the session file's path.

    Returns ``(project, state, planted, target)``: the fixture's committed session
    file is replaced by a link to a file that lives outside the state clone, so a
    reader reaches the target through it and a writer would replace the link.

    The link itself is planted by ``_nested_state(link_session=...)``, the one
    spelling every writer suite uses for this shape; this only reads the target back
    so the caller can assert its bytes are untouched.
    """
    project, state, session = _nested_state(tmp_path, SID, name=name,
                                            link_session=True)
    return project, state, session, Path(os.path.realpath(session))


def _plant_sessions_dir(tmp_path: Path, name: str) -> tuple[Path, Path, Path, Path]:
    """The route with a symlink standing where ``noni/sessions`` was.

    Returns ``(project, state, planted, target)``: the committed sessions directory
    is gone and a link to a regular file outside the tree stands in its place, so a
    writer that followed the link would replace that file with its session file.
    """
    project, state, _session = _nested_state(tmp_path, SID, name=name,
                                             link_sessions_dir=True)
    sessions = state / "noni" / "sessions"
    return project, state, sessions, Path(os.path.realpath(sessions))


def _plant_noni(tmp_path: Path, name: str) -> tuple[Path, Path, Path, Path]:
    """The route with a symlink standing where the state clone's ``noni`` was.

    Returns ``(project, state, planted, target)``: the whole ``noni`` directory now
    lives outside the clone and a link stands in its place, so the two paths the
    narrower guard examines both read as what they used to be -- ``lstat`` resolves
    the link and answers "directory" and "regular file" for everything beneath it.
    A writer that asked only those two questions would read a valid session and
    replace a file outside the state clone, which is the same damage one level above
    the paths the guard was first written for.
    """
    project, state, _session = _nested_state(tmp_path, SID, name=name,
                                             link_noni=True)
    planted = state / "noni"
    return project, state, planted, Path(os.path.realpath(planted)) / "sessions" / f"{SID}.md"


def _run_register_at(tmp_path: Path, project: Path, sid: str,
                     extra: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    """One register run whose allocation IS ``sid``.

    register mints a fresh id per run, so the file it would write is never the
    planted link: without this the allocating run would pass by writing somewhere
    else. The pinned-allocation driver (see ``session_git_support``) is the suite's
    existing way to hand register a name of its own choosing.
    """
    driver = _pinned_allocation_driver(tmp_path, sid)
    env = subprocess_env()
    env["NONI_TEST_SESSION_ID"] = sid
    return subprocess.run([sys.executable, str(driver), "--repo", STATE_DIR, *extra],
                          capture_output=True, text=True, env=env,
                          cwd=str(project), timeout=120)


def test_each_writer_refuses_a_symlinked_session_file(tmp_path):
    """AC1/AC2: a symlink at ``noni/sessions/<sid>.md`` is refused before the
    read, on the tool's own code, with the link and its target untouched."""
    for index, (label, script, code, extra) in enumerate(WRITERS):
        case = tmp_path / f"file-{index}"
        case.mkdir()
        project, state, planted, target = _plant_file(case, f"p{index}")
        head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()

        if label == "register":
            # The allocation is pinned to the planted name: an allocating run
            # writes a path nobody planted and refuses nothing.
            proc = _run_register_at(case, project, SID, ("--identity", "developer"))
        else:
            proc = _run(project, script, "--repo", STATE_DIR, *extra)

        # Turning a tracked regular file into a link is itself a work-tree change
        # (git reports ' T'), the fixture's and not the run's, so the porcelain is
        # snapshotted here and compared for.
        dirty_before = _git_ok(state, "status", "--porcelain").stdout.splitlines()
        _assert_refused(proc, state, planted, target, label, code, "session file",
                        dirty_before)
        assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before, (
            f"{label}: a refused run committed into the state clone"
        )


def test_each_writer_refuses_a_symlinked_sessions_directory(tmp_path):
    """AC1/AC2: a symlink at ``noni/sessions`` is refused before ``mkdir`` and
    before any write, so no session file lands at the target outside the tree."""
    for index, (label, script, code, extra) in enumerate(WRITERS):
        case = tmp_path / f"dir-{index}"
        case.mkdir()
        project, state, sessions, target = _plant_sessions_dir(case, f"p{index}")
        head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()
        dirty_before = _git_ok(state, "status", "--porcelain").stdout.splitlines()

        proc = _run(project, script, "--repo", STATE_DIR, *extra)

        _assert_refused(proc, state, sessions, target, label, code,
                        "sessions link", dirty_before)
        assert not (target / f"{SID}.md").exists(), (
            f"{label}: a refused run wrote its session file through the sessions link")
        assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before, (
            f"{label}: a refused run committed into the state clone"
        )


def test_each_writer_refuses_a_symlinked_noni_directory(tmp_path):
    """AC1/AC2 one level above the two named paths: a symlink where the state
    clone's ``noni`` was is refused too, because ``lstat`` cannot see through it
    from the two paths below -- without this the same clobber simply moves up."""
    for index, (label, script, code, extra) in enumerate(WRITERS):
        case = tmp_path / f"noni-{index}"
        case.mkdir()
        project, state, planted, target = _plant_noni(case, f"p{index}")
        head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()
        dirty_before = _git_ok(state, "status", "--porcelain").stdout.splitlines()

        if label == "register":
            proc = _run_register_at(case, project, SID, ("--identity", "developer"))
        else:
            proc = _run(project, script, "--repo", STATE_DIR, *extra)

        _assert_refused(proc, state, planted, target, label, code,
                        "noni link", dirty_before)
        assert not (target.parent / f"{SID}.md").exists() or \
            target.read_text(encoding="utf-8") == TARGET_BODY, (
            f"{label}: a refused run wrote through the noni link")
        assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before, (
            f"{label}: a refused run committed into the state clone"
        )


def test_register_refuses_both_before_it_creates_anything(tmp_path):
    """The register half of AC2, on the two things only this writer touches.

    register creates the sessions directory and the working-copy marker, so a
    refusal has two more clauses to satisfy: no marker is written, and the tree it
    would have created is still absent.
    """
    case = tmp_path / "register-nothing"
    case.mkdir()
    project, state, _session = _nested_state(case, SID, name="project",
                                             link_sessions_dir=True)
    sessions = state / "noni" / "sessions"
    # The link the fixture plants points at a plain file here, so a writer that
    # followed it would have replaced that file with a session file: the byte
    # comparison and the link check below are what a refusal has to leave true.
    target = Path(os.path.realpath(sessions))
    # The sessions directory is taken away while its file is still tracked, the
    # way one goes missing in practice: register is the writer that would mkdir it
    # again, which is exactly the creation a refusal must not perform.
    head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()
    dirty_before = _git_ok(state, "status", "--porcelain").stdout.splitlines()

    proc = _run_register_at(case, project, SID, ("--identity", "developer"))

    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert "symlink" in proc.stderr.lower(), proc.stderr
    assert str(sessions.relative_to(state)) in proc.stderr, proc.stderr
    assert not (state / ".git" / "noni-session").exists(), (
        "a refused run wrote the working-copy marker")
    assert sessions.is_symlink(), "a refused run replaced the sessions link"
    assert target.read_text(encoding="utf-8") == TARGET_BODY, (
        "a refused run wrote through the sessions link")
    assert _git_ok(state, "status", "--porcelain").stdout.splitlines() == dirty_before, (
        "a refused run changed the state clone")
    assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before


def test_a_plain_session_file_still_writes_with_no_symlink_word(tmp_path):
    """AC3, the file half: the fixture's regular session file is closed, and the
    word symlink never appears."""
    case = tmp_path / "plain"
    case.mkdir()
    project, state, _session = _nested_state(case, SID, name="project")

    proc = _run(project, CLOSE, "--repo", STATE_DIR, "--session-id", SID)

    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    assert "symlink" not in (proc.stdout + proc.stderr).lower()
    committed = _git_ok(state, "show", f"HEAD:noni/sessions/{SID}.md").stdout
    assert "- status: closed" in committed, committed


def test_a_project_reached_through_a_symlinked_ancestor_still_writes(tmp_path):
    """AC3, the ancestor half: the guard examines no ancestor, so the layout the
    quickstart sells -- a project opened through a link -- is a normal run."""
    case = tmp_path / "linked-ancestor"
    case.mkdir()
    project, state, _session = _nested_state(case, SID, name="project")
    through = case / "project-link"
    through.symlink_to(project)

    proc = _run(through, CLAIM, "--repo", STATE_DIR, "--session-id", SID,
                "--task", "#77")

    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    assert "symlink" not in (proc.stdout + proc.stderr).lower()
    assert _git_ok(state, "log", "-1", "--format=%s").stdout.strip() == "claim: #77"
