"""The publishing gate over a tree whose tracked path is a pipe (issue #91).

The gate CLI is the operator's publish-before-push step, the second caller of
``scrub_tracked_files``, and the one AGENTS.md names. It carries no timeout of
its own, so a scan that blocks on a fifo hung it forever: no exit code, no line
of output, and no way for the publishing checklist to say why.

Split out of ``tests/test_quickstart.py`` for the size rule (AGENTS.md, Source
file size) and because the claim is the gate's rather than the page's: the tree
it runs over is built by :mod:`quickstart_gate`, shared with the clean-tree run
the page's exit-code sentence is pinned against.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from quickstart_gate import (
    GATE_BOUND_SECONDS,
    run_gate_on_tree_with_a_tracked_fifo,
)


def test_the_gate_does_not_hang_on_a_tracked_fifo(tmp_path: Path) -> None:
    """The publishing gate returns promptly over a tree whose tracked path is a pipe.

    The gate CLI is the operator's publish-before-push step and the second caller
    of the scan, and it carries no timeout of its own: before the read guard, a
    fifo at a tracked path hung it forever -- no exit code, no line of output.
    The pipe is planted by the post-commit swap on a path the builder's own
    ``git add -A`` committed, since git indexes blobs and cannot stage a pipe.

    The gate must still refuse to report clean and must leave the pipe on disk:
    a checker that deleted the path it could not read would pass an exit-code
    assertion while destroying the operator's tree. The bound is the subprocess's
    own, and the elapsed assertion is what says the scan returned rather than
    merely that the child died.

    The refusal's words are the scan's own -- ``hygiene scan skipped ... non-
    regular`` -- which is why this asserts a refusal to read the tree clean
    rather than one of the gate's fixed sentences: the skip line is a finding,
    so the gate exits on findings before it reaches its deny-list half, exactly
    as it does for a violating file. An unguarded scan prints neither line and
    hangs, which is what the bound above fails.
    """
    tree, elapsed, proc = run_gate_on_tree_with_a_tracked_fifo(tmp_path)
    output = proc.stdout + proc.stderr
    assert elapsed < GATE_BOUND_SECONDS, f"the gate took {elapsed:.1f}s"
    assert stat.S_ISFIFO(os.lstat(tree / "notes.md").st_mode), (
        "the gate removed the tracked path it was meant to skip")
    assert "notes.md" not in output, (
        f"the gate named the path it refused to read: {output!r}")
    # The gate's refusal has two halves on this tree, and the page's sentence is
    # about the first: it must still refuse to report clean because the deny-list
    # class was inactive. The second is the scan's own line about the path it
    # would not open, which is the reason the run cannot be read as a clean one
    # either. An unguarded scan would print neither and hang instead, which is
    # what the bound above fails.
    assert "hygiene scan skipped" in output and "non-regular" in output, (
        f"the gate read the pipe as an empty file and said nothing about it: "
        f"{output!r}")
    assert "not a hygiene-clean guarantee" in output, (
        f"the gate did not refuse to read a tree holding a path it could not "
        f"open as clean: {output!r}")
    assert proc.returncode == 1, (
        f"a path the scan refused to read must be reported, not swallowed: "
        f"rc={proc.returncode} ({output!r})")
