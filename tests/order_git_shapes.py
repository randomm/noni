"""The two stdin-less git shapes the order fixtures share.

``_harness._git`` checks and discards stdout and ``_harness._git_e2`` keeps stdout
without checking; a fixture that reads an object id out of git, or hands git bytes,
wants the checked *and* capturing form, which is what these two are. Moved out of
``order_fixtures`` so that module stays the fixtures rather than a second git layer.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def git_output(repo: Path, *args: str) -> str:
    """One git call whose ANSWER is stdout, with the harness identity and no stdin.

    The checked half of the harness's two stdin-less shapes: ``_git`` checks and
    discards stdout, ``_git_e2`` keeps stdout and does not check. A fixture that reads
    an object id out of git wants both, and wants the failure to be a clear message
    rather than an empty string the next step mistakes for an answer.
    """
    return _run(repo, args, text=None)


def git_input(repo: Path, *args: str, text: str) -> str:
    """One git call that feeds ``text`` on stdin, with the harness identity.

    The harness's ``_git`` / ``_git_e2`` pipe no stdin, so a fixture that must hand git
    bytes (a blob written with ``hash-object -w --stdin``) builds the same argv here
    rather than inventing a fourth shape for the harness's git calls. ``-w`` STORES the
    object: an id the index is told to hold must be one the store can answer for, or a
    later comparison would be measuring a dangling fixture rather than its own read.
    """
    return _run(repo, args, text=text)


def _run(repo: Path, args: tuple[str, ...], text: str | None) -> str:
    """One git call with the harness identity, checking its exit code.

    ``text`` is what goes to stdin, or None for a call that must not wait on a
    terminal. Both shapes want the same four ``-c`` overrides, so they are spelled
    once here: the identity the suite pins, and no hooks path to run.
    """
    cmd = ["git", "-C", str(repo),
           "-c", "user.name=Replay",
           "-c", "user.email=replay@fixture.invalid",
           "-c", "commit.gpgsign=false",
           "-c", f"core.hooksPath={os.devnull}", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, input=text)
    if proc.returncode != 0:
        raise RuntimeError(f"git {args} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()
