"""The size gate's git listing is hardened against the tree it measures.

Modelled on the fsmonitor control in ``tests/test_public_safety.py``: the gate
runs ``git ls-files`` on a tree whose own config may name a program for git to
exec, so the absence of that program's marker is the assertion, and the
offenders the gate still reports are the control that says the listing ran.

A helper module: never named ``test_*``.
"""

from __future__ import annotations

import os

from _harness import _git, _init_repo


def _repo_with_planted_violations(tmp_path, name: str):
    """A throwaway repo with one oversized tracked file and a deleted one."""
    repo = _init_repo(tmp_path / name)
    (repo / "long.py").write_text("# x\n" * 501, encoding="utf-8")
    (repo / "gone.py").write_text("# x\n" * 501, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "planted")
    (repo / "gone.py").unlink()
    return repo


def _arm_fsmonitor(repo, marker):
    """Point the repo's own ``core.fsmonitor`` at a helper that leaves a marker.

    The helper exits 0 so git's listing still succeeds: the point is that the
    tree's config cannot turn a read-only listing into execution, not that git
    fails. A fresh index mtime is what asks git to query the monitor; without
    it the stat cache answers and the helper is never reached, so the assertion
    would pass for no reason.
    """
    helper = repo / "fsmonitor-helper.sh"
    helper.write_text(
        "#!/bin/sh\n" + "printf x > " + str(marker) + "\nexit 0\n", encoding="utf-8"
    )
    helper.chmod(0o755)
    _git(repo, "config", "core.fsmonitor", str(helper))
    index = repo / ".git" / "index"
    stat_before = index.stat()
    os.utime(index, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns + 2_000_000_000))
