"""The session guard over the real checkout's ``.git/config`` is not vacuous (issue #220, AC4).

``tests/conftest.py`` digests the checkout's shared ``.git/config`` at session start
and fails the session if the bytes are not those at teardown. On the real checkout
that comparison is only ever seen agreeing -- which is exactly how a guard like this
one would pass while blind, and it is the guard the whole ticket depends on being
believed about. So its two halves are exercised here on a planted repository: the
comparison must report a change when a sentinel is written, and it must name the file
and the difference it saw.

Nothing in this module writes the real checkout's config. The checkout is only ever
read, and the file it names is the operator's to repair, not the suite's.

The runner-side half of the same incident -- the refusal, the ceiling, the pairing
controls that show a bare ``git -C <dir> config`` really does leak -- is
``tests/test_harness_git_containment.py``.
"""

from __future__ import annotations

import subprocess

import conftest
from _harness import REPO
from git_containment_plant import plant_enclosing_repo


def test_the_session_comparison_reports_a_changed_config(tmp_path):
    """The pairing control for the session guard (PM ruling 4), on a planted repository.

    :func:`conftest.config_changed` is the one function the session fixture's verdict
    rests on, and on the real checkout it is only ever seen returning ``None``. So it
    is handed a planted repository whose config gains a sentinel, and must name the
    file and the difference.
    """
    enclosing = plant_enclosing_repo(tmp_path)
    config = conftest.shared_git_config_path(enclosing)
    assert config.is_file(), f"the plant's shared config is missing at {config}"
    before = conftest.shared_git_config_bytes(enclosing)
    assert conftest.config_changed(before, before, config) is None, (
        "an unchanged config reported a change; the session guard would fail every run")

    subprocess.run(["git", "-C", str(enclosing), "config", "user.name", "Sentinel"],
                   capture_output=True, text=True, timeout=60, check=True)
    after = conftest.shared_git_config_bytes(enclosing)

    report = conftest.config_changed(before, after, config)
    assert report is not None, (
        "the session guard's comparison saw no change after a sentinel was written "
        "to the plant's config -- the guard passes vacuously")
    assert str(config) in report, f"the report does not name the file: {report}"
    assert "Sentinel" in report, f"the report does not show what changed: {report}"


def test_the_session_guard_reads_the_shared_config_not_a_worktrees_pointer(tmp_path):
    """The guard digests the shared config, which is the file the bug wrote.

    Under a worktree -- where this suite really runs -- ``<root>/.git`` is a pointer
    file, so the guard cannot join ``.git/config`` onto the root. It asks git for the
    common git directory, and on a worktree that is the main checkout's ``.git``.
    Asserted on the checkout this run is really in, because that is the claim: a guard
    that digested a worktree's own pointer file would have watched a file that never
    changed while the shared one filled up with fixture identities.
    """
    shared = conftest.shared_git_config_path()
    assert shared.is_file(), f"no shared config found for {REPO}: {shared}"
    assert shared.read_bytes() == conftest.shared_git_config_bytes()
    assert conftest.shared_git_config_path() == shared, (
        "the shared config moved between two calls; the digest is not of a stable file")


def test_the_session_guard_reports_a_config_that_appeared(tmp_path):
    """A digest of no bytes against a config that holds one is a change, not a shrug.

    The digest reports ``b''`` for a repository with no config file at all rather than
    raising, which is what lets the guard fire on the case that matters most: a tree
    that had nothing and now holds a ``[user]`` section. The empty side is the real
    checkout's bytes (which always exist here), so the assertion is made on the
    comparison the fixture itself would make, with the plant standing in for the tree
    that gained the section.
    """
    enclosing = plant_enclosing_repo(tmp_path)
    config = conftest.shared_git_config_path(enclosing)
    gained = config.read_bytes() + b"[user]\n\tname = Replay\n"

    report = conftest.config_changed(b"", gained, config)
    assert report is not None, (
        "a tree that gained a config during the session read as unchanged")
    # The report names the file and the first difference it saw; naming the leaked
    # identity is the first test's job, where a sentinel is what was written.
    assert str(config) in report, report
    assert "[core]" in report, report
