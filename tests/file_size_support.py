"""Shared hardening for the read-only ``git ls-files`` the size gate runs.

Moved out of ``tests/test_file_size_limit.py`` so the rule statement, the
checker and its planted-violation proof each stay the size one responsibility
is worth (AGENTS.md, Source file size). A helper module: never named
``test_*``.

The listing is the only git call the gate makes, so everything the gate
measures is decided here: which paths git tracks, and nothing else.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from noni import gitenv


def tracked_files(repo: Path) -> list[str]:
    """The repository-relative paths git tracks in ``repo``, hardened.

    Tracked files only: an untracked scratch file is not a liability a size
    rule measures, and the listing is git's answer rather than a walk of the
    working tree. The tree being listed may carry a config that turns a
    read-only listing into execution, so fsmonitor, hooks and the external
    transport helper are disabled and the two host config files are pinned to
    the null device. The environment is the product's ``gitenv.child_env()``:
    it drops every inherited ``GIT_*`` variable that would relocate the
    repository, the index or the object store away from ``repo``, which is the
    one tree this gate answers for.
    """
    env = gitenv.child_env()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    proc = subprocess.run(
        ["git", "-C", str(repo),
         "-c", "core.fsmonitor=false",
         "-c", f"core.hooksPath={os.devnull}",
         "-c", "protocol.ext.allow=never",
         "ls-files", "-z"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {proc.stderr.strip()}")
    return [rel for rel in proc.stdout.split("\0") if rel]
