"""register refuses its name before a byte is written (the #57 contract).

register is the writer that allocates its own path, so it is the one whose refusal
could leave a file and a marker behind: perform the derivation after the write and
a run git never took would still have produced both. These three cases pin the
ordering the #57 contract requires -- refuse, then write -- on the two trees a
refusal must leave alone: no session file, no ``noni/``, and no working-copy
marker. Each is reached a different way, because register guards its path from
three directions: the state root, the ``--file`` argument, and its own allocation.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _harness import REGISTER, run_from, subprocess_env
from register_refusal_fixtures import _git_repo, _head, _no_committer_env
from session_git_support import _git_cached, _pinned_allocation_driver


def _run_driver(driver, repo: Path, session_id: str,
                env: dict) -> subprocess.CompletedProcess:
    """One register run through the pinned-allocation driver."""
    full = subprocess_env()
    full.update(env)
    full["NONI_TEST_SESSION_ID"] = session_id
    return subprocess.run([sys.executable, str(driver), "--repo", str(repo),
                           "--identity", "developer"],
                          capture_output=True, text=True, env=full, timeout=120)


def test_register_refuses_a_symlinked_state_root_before_writing_anything(tmp_path):
    """A symlinked ``--repo`` is refused on register's own usage code, with no
    file and no marker: the guard runs ahead of every write."""
    root = _git_repo(tmp_path)
    link = tmp_path / "state-link"
    link.symlink_to(root)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    head_before = _head(root)

    proc = run_from(cwd, REGISTER, "--repo", str(link), "--identity", "developer")

    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert "symlink" in proc.stderr.lower(), proc.stderr
    assert not (root / "noni").exists(), "a refused run created the sessions directory"
    assert not (root / ".git" / "noni-session").exists(), (
        "a refused run wrote the working-copy marker")
    assert _head(root) == head_before, "a refused run committed into the state root"


def test_register_refuses_a_file_it_did_not_allocate_before_writing_anything(tmp_path):
    """The other refusal register reaches from its own command line, measured the
    same way: exit 2, and neither tree it might have written has moved.

    This is the case a derivation performed after ``atomic_write`` cannot survive:
    the writer that wrote first and refused afterwards leaves a session file whose
    commit nobody asked for, and a marker naming it.
    """
    root = _git_repo(tmp_path)
    other = root / "noni" / "sessions" / "2026-01-01-dead07.md"
    other.parent.mkdir(parents=True)
    other.write_text("- identity: someone-else\n", encoding="utf-8")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    head_before = _head(root)
    marker = root / ".git" / "noni-session"

    proc = run_from(cwd, REGISTER, "--repo", str(root), "--identity", "developer",
                    "--file", "noni/sessions/2026-01-01-dead07.md")

    assert proc.returncode == 2, f"{proc.returncode}: {proc.stderr}"
    assert "refusing to write" in proc.stderr, proc.stderr
    assert [p.name for p in other.parent.glob("*.md")] == ["2026-01-01-dead07.md"], (
        "a refused run wrote a session file it did not allocate")
    assert not marker.exists(), "a refused run wrote the working-copy marker"
    assert _head(root) == head_before
    assert _git_cached(root) == [], "a refused run staged a path"



def test_register_refuses_its_derived_name_before_writing_anything(tmp_path):
    """The ordering the #57 contract requires, measured on the allocation itself.

    register's ``--file`` guard cannot be steered to a name its own primitive
    refuses, so the allocator is pinned to one (``test_register_refusals`` pins it
    the same way for the idempotency branches). The two trees a refusal must leave
    alone are then the assertion: with the derivation ahead of ``atomic_write``
    neither moves, and with it moved back the session file and the working-copy
    marker both exist before the refusal is printed.
    """
    root = _git_repo(tmp_path)
    head_before = _head(root)
    marker = root / ".git" / "noni-session"
    driver = _pinned_allocation_driver(tmp_path, "../../../../escape")

    proc = _run_driver(driver, root, "../../../../escape", _no_committer_env(tmp_path))

    assert proc.returncode == 3, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert "inside the state root" in proc.stderr, proc.stderr
    assert not (root / "noni" / "sessions" / "escape.md").exists(), (
        "register wrote its session file before refusing the name it derived")
    assert not (root / "noni").exists(), "register created noni/ before refusing"
    assert not marker.exists(), "register marked the working copy before refusing"
    assert _head(root) == head_before, "register committed before refusing"
