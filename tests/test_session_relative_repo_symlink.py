"""A state root reached through a symlink is refused, not guessed at (issue #66).

The four session writers hand ``git -C`` the tree ``--repo`` named and do their
own path arithmetic against the same string. ``git`` resolves the real path of
the tree it works in; the writers compare on unresolved absolutes, because
``Path.resolve()`` cannot be used on a file that does not exist yet. A state root
that is itself a symlink is exactly where those two readings part company, and
the writer's own marker and any later audit of the commit would be kept against
a path nobody named on the command line.

So the verdict is a refusal, and it is the one docs/PRODUCT.md 7 states: a
noni-worded diagnostic naming the *real* path of the state root, on the exit code
that command already uses for a wrong path (2 for ``register``, 4 for ``claim``,
``close`` and ``release``). The other half of the contract is what is *not*
refused: a project directory that happens to be reached through a link is a
normal run, and a run whose ``--repo`` is a plain directory must never see this
diagnostic.

The refusal lands before any read or write, so each test here also asserts the
tree it did not touch: no session file created, no marker, no commit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from _harness import _git_ok, run_from
from harness_paths import CLAIM, CLOSE, REGISTER, RELEASE
from session_git_support import STATE_DIR, _nested_state

# Each writer and the code docs/PRODUCT.md 7 gives it for a wrong path: 2 for
# register, 4 for the other three. A tool that answered this state with a new
# code, or with another tool's code, fails here.
SYMLINK_REFUSAL = (
    (REGISTER, "register", 2, ("--identity", "developer")),
    (CLAIM, "claim", 4, ("--session-id", "2026-10-01-cccccc", "--task", "#42")),
    (CLOSE, "close", 4, ("--session-id", "2026-10-01-cccccc")),
    (RELEASE, "release", 4, ("--session-id", "2026-10-01-cccccc", "--task", "#1")),
)


def _linked_project(tmp_path: Path, name: str) -> tuple[Path, Path, Path]:
    """The private-state route with a symlink standing in for the state root.

    Returns ``(project, state root, link)`` where ``link`` is a symlink to the
    state clone, which is the shape the refusal exists for.
    """
    project, state, session = _nested_state(tmp_path, "2026-10-01-cccccc", name=name)
    link = project / "state-link"
    link.symlink_to(state)
    return project, state, link


def _run(project: Path, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One writer launched from the project cwd with the argv the caller owns."""
    return run_from(project, script, *args)


def test_each_writer_refuses_a_state_root_that_is_a_symlink(tmp_path):
    """AC9: the refusal is a noni diagnostic naming the state root's real path,
    on the code docs/PRODUCT.md 7 owes that tool, and it is not git's error."""
    for index, (script, _label, expected_code, extra) in enumerate(SYMLINK_REFUSAL):
        case = tmp_path / f"case-{index}"
        case.mkdir()
        project, state, link = _linked_project(case, f"project-{index}")
        head_before = _git_ok(state, "rev-parse", "HEAD").stdout.strip()

        proc = _run(project, script, "--repo", str(link), *extra)

        assert proc.returncode == expected_code, (
            f"{script.name}: docs/PRODUCT.md 7 documents exit {expected_code} for a "
            f"wrong --repo, got {proc.returncode}: {proc.stderr}"
        )
        err = proc.stderr.lower()
        assert str(state) in proc.stderr, (
            f"{script.name}: the refusal must name the real path of the state "
            f"root the link points at: {proc.stderr}"
        )
        assert "symlink" in err, (
            f"{script.name}: the refusal must say what is wrong with the path: "
            f"{proc.stderr}"
        )
        assert "fatal:" not in err and "pathspec" not in err, (
            f"{script.name}: an opaque git error, not a noni diagnostic: "
            f"{proc.stderr}"
        )
        # Refused before any read or write: the clone is exactly the fixture.
        assert _git_ok(state, "rev-parse", "HEAD").stdout.strip() == head_before, (
            f"{script.name}: a refused run committed into the state clone"
        )
        assert _git_ok(state, "status", "--porcelain").stdout.splitlines() == [], (
            f"{script.name}: a refused run dirtied the state clone"
        )
        assert not (state / ".git" / "noni-session").exists(), (
            f"{script.name}: a refused run wrote the working-copy marker"
        )


def test_a_relative_repo_that_is_a_symlink_is_refused_too(tmp_path):
    """The refusal does not depend on how the link was spelled: a relative
    ``--repo`` naming a link is refused with the real path named, so the
    diagnostic is actionable whatever form the caller passed."""
    case = tmp_path / "relative-link"
    case.mkdir()
    project, state, _link = _nested_state(case, "2026-10-01-cccccc", name="project")
    (project / "state-link").symlink_to(state)

    proc = _run(project, CLOSE, "--repo", "state-link",
                "--session-id", "2026-10-01-cccccc")

    assert proc.returncode == 4, f"{proc.returncode}: {proc.stderr}"
    assert str(state) in proc.stderr, proc.stderr
    assert "symlink" in proc.stderr.lower(), proc.stderr
    assert _git_ok(state, "status", "--porcelain").stdout.splitlines() == []


def test_a_project_reached_through_a_symlink_is_not_refused(tmp_path):
    """The other half of the contract (AC5): a project directory reached *through*
    a link is a normal run. Only a ``--repo`` that is itself a link is refused, so
    the guard must not turn the ordinary case into a false positive.

    The run is the one the bug report names: launched from a linked project
    directory with a relative ``--repo`` naming the nested clone. It commits, and
    the commit is the single repo-relative path.
    """
    case = tmp_path / "linked-project"
    case.mkdir()
    project, state, _link = _nested_state(case, "2026-10-01-cccccc", name="project")
    link_dir = case / "project-link"
    link_dir.symlink_to(project)

    proc = _run(link_dir, CLOSE, "--repo", STATE_DIR,
                "--session-id", "2026-10-01-cccccc")

    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    assert "symlink" not in proc.stderr.lower(), proc.stderr
    assert _git_ok(state, "log", "-1", "--format=%s").stdout.strip() == \
        "close: 2026-10-01-cccccc"
    committed = _git_ok(state, "show", "HEAD:noni/sessions/2026-10-01-cccccc.md").stdout
    assert "- status: closed" in committed, committed
    assert _git_ok(state, "diff", "--name-only", "HEAD~1", "HEAD").stdout.split() == \
        ["noni/sessions/2026-10-01-cccccc.md"]


def test_a_plain_relative_repo_is_never_told_it_is_a_symlink(tmp_path):
    """No false positive on the form the quickstart sells: ``--repo st`` naming a
    real directory runs, and never hears the word symlink."""
    case = tmp_path / "plain-relative"
    case.mkdir()
    project, state, _session = _nested_state(case, "2026-10-01-cccccc", name="project")

    proc = _run(project, CLOSE, "--repo", STATE_DIR, "--session-id", "2026-10-01-cccccc")

    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    assert "symlink" not in (proc.stdout + proc.stderr).lower()
    assert _git_ok(state, "status", "--porcelain").stdout.splitlines() == []
