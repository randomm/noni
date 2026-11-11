"""The public checkout of noni is not a noni state root.

The bug issue #162 was filed about is a writer pointed at the wrong repository: an
agent passed a project checkout where the state clone was meant and ``decide``
committed direction content into the public tree. This repository is the tree that
mistake lands on most often, so it carries the two facts the guard depends on and
pays for them here: it tracks no ``noni/`` directory at all, and an unflagged
``decide`` run against a copy of it is refused.

Both halves are product claims, not tidiness. A tracked ``noni/decisions/.gitkeep``
would make every clone of noni a state root on the census's and the writer's own
account, and the writer would then admit an unflagged run into it; a checkout that
held no ``noni/`` but let a record in anyway would leave the public repository
carrying direction state, which docs/PRODUCT.md 7 and the public-repo rule forbid.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from _harness import DECIDE, REPO, _git, _init_repo, subprocess_env

# The argv one first-run ``decide`` needs beyond ``--repo``: values no assertion
# reads, because the run is refused before any of them is asked about.
DECIDE_ARGV = ("--slug", "public-checkout", "--date", "2026-10-01",
               "--scope", "release", "--asked-by", "developer",
               "--question", "q1=Ship?", "--option", "q1=yes",
               "--option", "q1=no", "--answer", "q1=yes")


def _tracked_files(*paths: str) -> list[str]:
    """The ``git ls-files`` names of the checkout, optionally below ``paths``.

    Tracked files are the claim: a directory that exists only in one working tree
    is nobody's contract, and a fresh clone would not carry it.
    """
    listing = subprocess.run(["git", "-C", str(REPO), "ls-files", *paths],
                             capture_output=True, text=True,
                             env=subprocess_env(), timeout=120)
    assert listing.returncode == 0, listing.stderr
    return [line for line in listing.stdout.splitlines() if line.strip()]


def test_the_repository_tracks_no_noni_directory():
    """``git ls-files`` names nothing under ``noni/``, so a clone is no state root.

    The scan is git's own list, so an untracked scratch ``noni/`` cannot make this
    pass and a tracked placeholder cannot make it fail quietly.
    """
    tracked = _tracked_files("noni")
    assert not tracked, (
        f"the public repository tracks {tracked}: a clone of noni would hold a "
        f"noni/ directory, and every guard that calls such a tree a state root "
        f"would then admit an unflagged writer into it")
    assert not (REPO / "noni").exists(), (
        "this checkout holds a noni/ directory that git does not track: it is "
        "scratch, and belongs under tmp/issue-N/")


def test_decide_refuses_a_copy_of_this_checkout_without_the_flag(tmp_path):
    """An unflagged ``decide`` on a copy of this tree is refused and writes nothing.

    A copy, never the checkout: a run that wrote here would dirty the very tree the
    guard protects, and a refused run must be proven harmless in a place where a
    regression could not damage the repository itself. Only tracked files are
    copied -- the content a reader clones -- and the copy is made a work tree with
    the harness identity, so the refusal under test is the state-root one and not a
    git probe or the attribution check that run ahead of it.
    """
    copy = tmp_path / "noni-checkout"
    copy.mkdir()
    for rel in _tracked_files():
        target = copy / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, target)
    _init_repo(copy)
    _git(copy, "config", "user.name", "Replay")
    _git(copy, "config", "user.email", "replay@fixture.invalid")

    assert not (copy / "noni").exists(), "the copy carries a noni/ directory"
    proc = subprocess.run(
        [sys.executable, str(DECIDE), "--repo", str(copy), *DECIDE_ARGV],
        capture_output=True, text=True, env=subprocess_env(),
        cwd=str(copy), timeout=120)
    assert proc.returncode == 3, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert "is not a noni state root" in proc.stderr, proc.stderr
    assert "no noni/" in proc.stderr, proc.stderr
    assert "--init" in proc.stderr, (
        f"a refused first run must name the flag that opens a new state root: "
        f"{proc.stderr}")
    assert not (copy / "noni").exists(), (
        f"a refused run created {copy / 'noni'} in a copy of the public checkout")
