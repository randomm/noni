"""register refuses an allocated name that a file already holds (issue #103).

register is the only session writer that mints its own path: ``claim``, ``close`` and
``release`` take ``--session-id`` from the operator and refuse a session they were not
registered for, so they cannot land on a name somebody else holds. That makes
register's allocating route the one place where a mint and a committed file can meet,
and until issue #103 nothing stood between them: the route ran from
``target_file = repo / target`` straight to the atomic write, and that primitive is
``os.replace`` -- it replaces whatever is there. The one existing-file refusal the
writer had lived in ``_reuse``, which is reached only when the working copy's marker
names a file, so a clean checkout took the overwriting path, exited 0, and committed
the erasure of another session's identity, ``started`` stamp and claim rows. The
census never notices either: the file keeps the name it had.

Six hex characters over one UTC day are about 16.7M slots, so a repeated id is rare
and not impossible -- the writer therefore checks the name it minted instead of
trusting it, mints again while the name is held, and refuses (exit 2, creating
nothing) when the bound runs out.

Two guards answer for an allocated name and they must not be collapsed. The path kind
belongs to ``_session_guard.session_write``, which names the kind its ``lstat``
actually found; the question added here is whether a position that guard passed --
absent or a regular file -- is already spoken. A single existence check would answer
"already exists" about a directory, a fifo or a dangling link and send the operator
off to delete a file that is a link, so each shape keeps its own verdict below.

The #57 contract applies to every refusal here: no session file, no ``noni/``, no
working-copy marker, HEAD unmoved. The allocation is pinned because the fault is a
collision between two mints and nothing else can produce one on demand; see
``register_allocation_drivers``.
"""

from __future__ import annotations

import os
from pathlib import Path

from _harness import _git_ok, run_register
from register_allocation_drivers import (
    VICTIM_BODY,
    VICTIM_SID,
    always_taken_driver,
    mints,
    run_scripted,
    taken_then_free_driver,
)
from register_refusal_fixtures import _git_repo, _head, _no_committer_env, _sid_of
from session_git_support import _pinned_allocation_driver

from noni import _marker, _session_body

# How many names the allocating route mints before it refuses, read off the product
# rather than copied: a bound changed in the source changes the count assertion below
# instead of quietly passing it. One first allocation plus the re-mints.
MAX_MINTS = _session_body.ALLOCATION_RETRIES + 1


def _victim_repo(tmp_path: Path, name: str) -> tuple[Path, Path]:
    """A git repo holding one committed victim session file: ``(repo, victim)``.

    Committed, so the file is part of what a clean checkout reproduces rather than
    uncommitted dirt a run could be said to have been invited to replace;
    ``.git/noni-session`` is absent, so a run reaches the allocating route and the
    ``_reuse`` identity check is never consulted -- which is exactly how the bug
    erased a session and reported success.
    """
    parent = tmp_path / name
    parent.mkdir()
    repo = _git_repo(parent)
    victim = repo / "noni" / "sessions" / f"{VICTIM_SID}.md"
    victim.parent.mkdir(parents=True)
    victim.write_text(VICTIM_BODY, encoding="utf-8")
    _git_ok(repo, "add", f"noni/sessions/{VICTIM_SID}.md")
    _git_ok(repo, "-c", "user.name=Replay", "-c", "user.email=replay@fixture.invalid",
            "commit", "-q", "-m", f"register: {VICTIM_SID}")
    return repo, victim


def test_register_refuses_an_allocated_name_that_is_already_taken(tmp_path):
    """AC1/AC2/AC3: an allocation that lands on a committed session file is refused
    at exit 2, and the victim keeps its bytes.

    The assertions beside the refusal are the #57 contract the sibling suite pins for
    the other refusals: nothing is created before the run stops, and nothing is
    staged, so a collision is a non-event in the tree rather than a half-registration
    an operator has to notice and undo.
    """
    repo, victim = _victim_repo(tmp_path, "taken")
    head_before = _head(repo)
    marker = repo / ".git" / _marker.MARKER_NAME
    driver = always_taken_driver(tmp_path)

    proc = run_scripted(driver, repo, VICTIM_SID)

    assert proc.returncode == 2, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert f"{VICTIM_SID}.md" in proc.stderr, (
        f"the refusal must name the file it refused to replace: {proc.stderr}")
    assert "already exists" in proc.stderr, proc.stderr
    # AC3, the whole file: the erasure moved the identity, moved the started stamp
    # and dropped the claim row, so a whole-file comparison is the assertion a
    # partial write cannot satisfy.
    assert victim.read_text(encoding="utf-8") == VICTIM_BODY, (
        "the run replaced another session's file")
    assert [p.name for p in victim.parent.glob("*.md")] == [f"{VICTIM_SID}.md"], (
        "a refused run wrote a second session file")
    assert not marker.exists(), "a refused run wrote the working-copy marker"
    assert _head(repo) == head_before, "a refused run committed into the state root"


def test_register_refuses_a_taken_allocated_name_on_the_no_commit_route(tmp_path):
    """AC1/AC2 on ``--no-commit``: this route runs no git at all, which is what makes
    the guard load-bearing rather than a nicety.

    The committing route at least hands the overwrite to git. This one writes the file
    and stops, so a run that never checked the name reported success about somebody
    else's file -- the reproduction that needed no origin and no committer identity,
    just two pinned runs and one file.
    """
    repo, victim = _victim_repo(tmp_path, "taken-no-commit")
    head_before = _head(repo)
    marker = repo / ".git" / _marker.MARKER_NAME
    driver = always_taken_driver(tmp_path)

    proc = run_scripted(driver, repo, VICTIM_SID, "--no-commit")

    assert proc.returncode == 2, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert f"{VICTIM_SID}.md" in proc.stderr, proc.stderr
    assert "left uncommitted" not in proc.stdout, (
        f"a run that wrote nothing must not report a file it left: {proc.stdout}")
    assert victim.read_text(encoding="utf-8") == VICTIM_BODY, (
        "the --no-commit route replaced another session's file")
    assert not marker.exists(), "a refused run wrote the working-copy marker"
    assert _head(repo) == head_before, "a refused run moved HEAD"


def test_register_mints_again_when_the_allocated_name_is_taken(tmp_path):
    """AC2: the first name is held, so the run mints again and registers at the new one.

    Refusing on the first collision is the wrong fix: a 24-bit space is roomy enough
    that one retry settles it, and a run that refused would leave an operator unable
    to register at all. The mint count is the load-bearing assertion -- one mint means
    the guard never asked the filesystem, three means it retried past a free name, and
    two is the collision handled as designed.
    """
    repo, victim = _victim_repo(tmp_path, "remint")
    driver = taken_then_free_driver(tmp_path)

    proc = run_scripted(driver, repo, VICTIM_SID)

    assert proc.returncode == 0, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert mints(proc) == 2, (
        f"expected one mint for the taken name and one for the free one, got "
        f"{mints(proc)}")
    sid = _sid_of(proc.stdout)
    assert sid != VICTIM_SID, "the run registered at the name it found taken"
    # The victim survives untouched beside this run's own file, and every artefact
    # names the second mint rather than the first.
    assert victim.read_text(encoding="utf-8") == VICTIM_BODY
    assert (repo / "noni" / "sessions" / f"{sid}.md").is_file()
    assert (repo / ".git" / _marker.MARKER_NAME).read_text(
        encoding="utf-8") == sid + "\n"
    assert _git_ok(repo, "log", "-1", "--format=%s").stdout.strip() == f"register: {sid}"


def test_register_refuses_when_every_allocated_name_is_taken(tmp_path):
    """AC2, the bound: every name the run can produce is held, so it refuses at exit 2.

    The count is what makes this a bound rather than a hope: an unbounded retry hangs
    this test instead of failing it, and a retry that gave up after one try would pass
    the refusal assertions above by accident. The name the run gave up on is the name
    it prints, so an operator who comes back later can go and look at the file.
    """
    repo, victim = _victim_repo(tmp_path, "all-taken")
    head_before = _head(repo)
    marker = repo / ".git" / _marker.MARKER_NAME
    driver = always_taken_driver(tmp_path)

    proc = run_scripted(driver, repo, VICTIM_SID)

    assert proc.returncode == 2, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert f"{VICTIM_SID}.md" in proc.stderr, (
        f"the refusal must name the last file it could not use: {proc.stderr}")
    assert mints(proc) == MAX_MINTS, (
        f"the run tried {mints(proc)} names; the bound is {MAX_MINTS} mints")
    assert victim.read_text(encoding="utf-8") == VICTIM_BODY
    assert not marker.exists(), "a refused run wrote the working-copy marker"
    assert _head(repo) == head_before, "a refused run committed into the state root"


def test_register_still_refuses_a_non_regular_kind_at_the_allocated_name(tmp_path):
    """The taken-name guard must not swallow the sibling path-kind refusals.

    Both guards answer "do not write here" at exit 2 for an allocated name, and it
    would be easy to collapse them into one existence check -- which is the shape
    that loses information: ``lstat`` finds a directory, a fifo or a dangling link,
    and the operator is told a file "already exists" and sent to delete a directory,
    or a symlinked session path is reported as somebody's register file. Each kind
    keeps the verdict that names it, and none of them is replaced.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    sessions = repo / "noni" / "sessions"
    sessions.mkdir(parents=True)
    planted = (
        ("directory", lambda p: p.mkdir()),
        ("fifo", os.mkfifo),
        ("dangling symlink", lambda p: p.symlink_to("nowhere-at-all")),
    )
    for index, (kind, plant) in enumerate(planted):
        sid = f"2026-01-01-dead0{index}"
        target = sessions / f"{sid}.md"
        plant(target)
        driver = _pinned_allocation_driver(tmp_path, sid)

        proc = run_scripted(driver, repo, sid, identity=False,
                            env=_no_committer_env(tmp_path))

        assert proc.returncode == 2, f"{kind}: {proc.returncode}: {proc.stderr}"
        assert "already exists" not in proc.stderr, (
            f"a {kind} at the allocated name is not a file somebody allocated: "
            f"{proc.stderr}")
        assert ("not a regular file" in proc.stderr
                or "is a symlink" in proc.stderr), (
            f"a {kind} must be answered with the kind actually found: {proc.stderr}")
        assert target.is_symlink() or target.exists(), (
            f"the run replaced the planted {kind}")
        if kind == "directory":
            assert target.is_dir(), "the run replaced a directory with a session file"


def test_a_taken_allocation_leaves_the_marked_reuse_route_alone(tmp_path):
    """The marker route keeps answering exit 1, not this route's new exit 2.

    ``_reuse`` is the only refusal that reads a marked file's identity, and it is
    reached when the working copy's marker names an active file. A taken-name guard
    that also judged the marked file would turn an identity mismatch into a
    wrong-path refusal and tell the operator to go and delete a session that is
    simply somebody else's.
    """
    repo = _git_repo(tmp_path)
    first = run_register(repo, "developer")
    assert first.returncode == 0, first.stderr
    sid = _sid_of(first.stdout)
    marked = repo / "noni" / "sessions" / f"{sid}.md"
    marked_bytes = marked.read_bytes()
    (repo / ".git" / _marker.MARKER_NAME).write_text(sid + "\n", encoding="utf-8")

    proc = run_register(repo, "someone-else")

    assert proc.returncode == 1, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert "refusing to overwrite another session's file" in proc.stderr, proc.stderr
    assert marked.read_bytes() == marked_bytes, (
        "the identity refusal moved the marked session's bytes")
