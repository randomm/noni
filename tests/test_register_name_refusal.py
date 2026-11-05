"""register refuses its name before a byte is written (the #57 contract).

register is the writer that allocates its own path, so it is the one whose refusal
could leave a file and a marker behind: perform the derivation after the write and
a run git never took would still have produced both. These three cases pin the
ordering the #57 contract requires -- refuse, then write -- on the two trees a
refusal must leave alone: no session file, no ``noni/``, and no working-copy
marker. Each is reached a different way, because register guards its path from
three directions: the state root, the ``--file`` argument, and its own allocation.

The allocation is guarded twice, and the two guards answer different faults. The
path kind is answered by ``_session_guard.session_write`` (a link, a directory or a
device at the name is refused in the words that name the kind actually found); the
question issue #103 added -- whether a position those guards pass belongs to somebody
else -- is the subject of ``test_register_taken_name_refusal.py``. The two must not be
collapsed into one existence check: a refusal that reads "already exists" about a
symlink sends the operator to delete a file that is a link.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _harness import REGISTER, _git_ok, run_from, run_register, subprocess_env
from register_refusal_fixtures import (
    _git_repo,
    _head,
    _no_committer_env,
    _sid_of,
)
from session_git_support import (
    STATE_DIR,
    _git_cached,
    _nested_state,
    _pinned_allocation_driver,
)

from noni import _marker

# The id the nested-state fixture commits a session at, the same one the other
# relative-repo suites use.
SID = "2026-10-01-cccccc"


def _run_driver(driver, repo: Path, session_id: str,
                env: dict) -> subprocess.CompletedProcess:
    """One register run through the pinned-allocation driver."""
    full = subprocess_env()
    full.update(env)
    full["NONI_TEST_SESSION_ID"] = session_id
    return subprocess.run([sys.executable, str(driver), "--repo", str(repo),
                           "--identity", "developer"],
                          capture_output=True, text=True, env=full, timeout=120)


def _counting_allocation_driver(tmp_path: Path) -> Path:
    """A driver that runs register.main() with a ``_make_session_id`` that counts.

    The one way to see a second mint: the real allocator returns a fresh id every
    call, so two calls look like one id that happens to differ from another run's
    and every assertion on a single artefact still passes. The counter turns the
    question into a number the test can read.
    """
    from _harness import SRC

    driver_dir = tmp_path / "_counting_driver"
    driver_dir.mkdir(exist_ok=True)
    driver = driver_dir / "drive_counted_register.py"
    driver.write_text(
        "import os\n"
        "import sys\n"
        f"sys.path.insert(0, {str(SRC)!r})\n"
        "from noni import register\n"
        "_calls = [0]\n"
        "_real = register._make_session_id\n"
        "def _counted():\n"
        "    _calls[0] += 1\n"
        "    return _real()\n"
        "register._make_session_id = _counted\n"
        "rc = register.main(sys.argv[1:])\n"
        "print('MAINTS=' + str(_calls[0]))\n"
        "raise SystemExit(rc)\n",
        encoding="utf-8",
    )
    return driver


def _run_plain_driver(driver: Path, repo: Path) -> subprocess.CompletedProcess:
    """One register run through ``driver``, committed under the harness identity.

    The counter test asserts a commit landed, so the run needs an author: the
    identity pin is the one the harness's own ``run_register`` applies, taken
    from the same table so the two launchers cannot disagree about it.
    """
    from _harness import _git_env_with_identity

    full = subprocess_env()
    full.update(_git_env_with_identity())
    return subprocess.run([sys.executable, str(driver), "--repo", str(repo),
                           "--identity", "developer"],
                          capture_output=True, text=True,
                          env=full, timeout=120)


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

    assert proc.returncode == 4, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert "inside the state root" in proc.stderr, proc.stderr
    # register's own argument code, not EXIT_GIT: the fault is a name the writer
    # derived, and EXIT_GIT would send the operator to fix --repo or a symlink
    # that were never wrong. The hint says which argument to look at.
    assert "--repo" not in proc.stderr, (
        f"a bad name must not blame --repo: {proc.stderr}")
    assert "symlink" not in proc.stderr, (
        f"a bad name must not blame a symlink: {proc.stderr}")
    assert "--identity" in proc.stderr, (
        f"the hint must name an argument the operator can act on: {proc.stderr}")
    assert not (root / "noni" / "sessions" / "escape.md").exists(), (
        "register wrote its session file before refusing the name it derived")
    assert not (root / "noni").exists(), "register created noni/ before refusing"
    assert not marker.exists(), "register marked the working copy before refusing"
    assert _head(root) == head_before, "register committed before refusing"


def test_register_mints_one_session_id_for_every_use_of_it(tmp_path):
    """One ``_make_session_id()`` call per run, threaded through all six uses.

    The id names the file written, the path git is handed, the marker's contents,
    the commit subject, the printed line and the file's own ``# session`` heading.
    Minting it twice is not a cosmetic fault: the printed line and the committed
    path can then name two different sessions, and a working copy can end up
    marked for a file git never received. The allocator is pinned to a counter so
    a second call is observable rather than merely a different-looking id.

    The taken-name re-mint issue #103 adds must not be paid for here: a free name is
    free on the first mint, so the retry loop is invisible on the ordinary route.
    """
    root = _git_repo(tmp_path)
    driver = _counting_allocation_driver(tmp_path)

    proc = _run_plain_driver(driver, root)

    assert proc.returncode == 0, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    # The counter driver prints its own call count on the last line of stdout.
    calls = int(proc.stdout.strip().splitlines()[-1].split("=", 1)[1])
    assert calls == 1, f"register minted the session id {calls} times"
    sid = proc.stdout.split("registered session ")[1].split(" ->")[0].strip()
    rel = f"noni/sessions/{sid}.md"
    # Every artefact names that one id: nothing was written at a name derived
    # from a second, different mint.
    assert (root / rel).is_file(), f"{rel} was not written"
    assert f"# session {sid}" in (root / rel).read_text(encoding="utf-8")
    assert _git_ok(root, "log", "-1", "--format=%s").stdout.strip() == f"register: {sid}"
    assert _git_ok(root, "diff", "--name-only", "HEAD~1", "HEAD").stdout.split() == [rel]
    assert (root / ".git" / "noni-session").read_text(encoding="utf-8") == sid + "\n"
    assert f"registered session {sid} -> {root / rel}" in proc.stdout


def test_register_refuses_marker_text_that_is_not_a_session_id(tmp_path):
    """A path is never built from marker text.

    The marker is the working copy's own uncommitted file, so a run must read it
    the way it reads a command line: through the same gate. Text that is not a
    session id is not a marker for a session, so the documented contract (the
    marker holds the id this command wrote) says what the run does with it -- it
    says so, treats the working copy as unmarked, and allocates afresh. The three
    faults that follow from the opposite choice are the assertions: an active
    session outside the root must not be continued, ``--file`` must not be
    admitted to it, and the run's own marker must name the session it actually
    wrote.
    """
    root = _git_repo(tmp_path)
    marker = root / ".git" / _marker.MARKER_NAME
    marker.parent.mkdir(exist_ok=True)
    # A session outside the state root, and one whose status an active session
    # would have: the shape an id-level guard is the only thing that refuses.
    outside = tmp_path / "victim.md"
    outside.write_text("- identity: dev\n- status: active\n- claims:\n",
                       encoding="utf-8")
    marker.write_text("../../../../victim\n", encoding="utf-8")
    head_before = _head(root)

    proc = run_register(root, "developer")

    assert proc.returncode == 0, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    err = proc.stderr.lower()
    assert "not a session id" in err, proc.stderr
    assert _marker.MARKER_NAME in proc.stderr, proc.stderr
    # The unmarked branch was taken: a fresh allocation, marked for itself.
    sid = _sid_of(proc.stdout)
    assert (root / "noni" / "sessions" / f"{sid}.md").is_file()
    assert marker.read_text(encoding="utf-8") == sid + "\n", (
        "the marker still names text the writer refused to build a path from")
    assert _head(root) != head_before, "the run should have committed its own file"
    # Nothing outside the root was read from or written to.
    assert outside.read_text(encoding="utf-8") == \
        "- identity: dev\n- status: active\n- claims:\n"
    assert not list(tmp_path.glob("noni")), "register wrote beside the state root"


def test_register_with_a_relative_repo_pushes_to_the_origin_it_names(tmp_path):
    """--push on the relative-repo route: origin's main ends at the clone's HEAD.

    Every relative-repo test in this suite runs a commit, and none ran a push, so
    the push half of the route was unmeasured: the loop resolves its own upstream
    and hands git a refspec, and a path built from a relative ``--repo`` would
    show up there rather than in the commit. The fixture gives the state clone an
    origin with ``main`` already pushed, so the assertion is the one that matters
    after the run: origin's ``main`` names the commit the state clone is on.
    """
    project, state, _session = _nested_state(tmp_path, SID, name="push-relative")
    origin = tmp_path / "push-relative.origin.git"
    assert origin.is_dir(), "precondition: the fixture gives the clone an origin"

    proc = run_from(project, REGISTER, "--repo", STATE_DIR, "--identity", "developer",
                    "--push")

    assert proc.returncode == 0, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    head = _git_ok(state, "rev-parse", "HEAD").stdout.strip()
    on_origin = _git_ok(origin, "rev-parse", "refs/heads/main").stdout.strip()
    assert on_origin == head, (
        f"origin's main is {on_origin}, the state clone is {head}: the --push of "
        f"a run with a relative --repo did not land the commit it made")
    assert _git_ok(state, "status", "--porcelain").stdout.splitlines() == []
