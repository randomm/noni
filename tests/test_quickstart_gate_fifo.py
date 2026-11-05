"""The publishing gate over a tree whose tracked path is a named pipe (issue #91).

``scripts/public_safety.py`` is the second caller of the scan and the command
AGENTS.md makes a gate: exit 1 on a violation, exit 2 when the deny-list class
was not active, exit 0 only when both halves ran. It imports the package module,
so it inherited the blocking read -- and it carries no timeout of its own, so the
operator's publishing run stopped with no verdict, no reason and no way to tell a
hung scan from a slow filesystem.

The gate derives the tree it audits from the wrapper's own location, which is why
the run happens in the scratch clone-root ``quickstart_gate`` builds rather than
here: a run whose cwd is this checkout would scan this checkout and its verdict
would move with whatever untracked deny-list the operator happens to hold.

The FIFO variant shares that builder and differs from the plain run in exactly
one thing -- a pipe at a path ``git add -A`` already committed -- so the two exit
codes are comparable: a pipe holds no stored content, so the gate must still
refuse on the inactive deny-list class and on nothing else.

The FIFO case skips where ``os.mkfifo`` is unavailable (a non-POSIX host has no
pipes to plant, and the suite's offline-determinism rule says it skips rather
than errors).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from harness_faults import _mkfifo_available
from quickstart_gate import (
    GATE_BOUND_SECONDS,
    GATE_DENYLIST_INACTIVE_EXIT,
    build_gate_tree,
    run_gate_on_tree,
    run_gate_on_tree_with_a_tracked_fifo,
)

pytestmark = pytest.mark.skipif(
    not _mkfifo_available(),
    reason="os.mkfifo is POSIX-only, so this host cannot plant a named pipe",
)


def test_the_gate_refuses_an_inactive_class_over_a_tracked_fifo(tmp_path: Path) -> None:
    """The publishing gate over a pipe: exit 2, promptly, and no violation named.

    Three assertions, because each is a different regression:

    - the exit is the page's own ``exits 2`` for a tree with no deny-list -- a
      gate that skipped the pipe *and* forgot to refuse would report clean;
    - the refusal names the class it skipped, so the operator is not left to
      guess which half of the check did not run;
    - it returns within the bound, which is the only assertion that can see a
      hang: no exit code is produced by a process that never finishes.

    The pipe is still on disk afterwards: a gate that consumed it read it, and
    reading it is what this issue is about.
    """
    proc = run_gate_on_tree_with_a_tracked_fifo(tmp_path)

    assert proc.returncode == GATE_DENYLIST_INACTIVE_EXIT, (
        f"the gate reported {proc.returncode} on a tree with no deny-list and a "
        f"tracked pipe; the page promises {GATE_DENYLIST_INACTIVE_EXIT}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
    assert "deny-list class inactive" in proc.stderr, (
        f"the gate's refusal did not name the class it skipped: {proc.stderr!r}")
    assert "notes.md" not in proc.stdout + proc.stderr, (
        f"the gate called the skipped pipe a violation: {proc.stderr!r}")
    pipe = tmp_path / "gate-tree-fifo" / "notes.md"
    assert pipe.exists() and not pipe.is_file(), (
        "the gate read the pipe away instead of skipping it")


def test_the_gate_run_is_bounded_so_a_hang_is_a_failure(tmp_path: Path) -> None:
    """The bound exists, and the clean tree passes inside it.

    The wrapper has no timeout of its own, so the bound is this harness's; if it
    were absent the FIFO case above would hang the suite exactly as the product
    hung the publishing gate. The clean-tree run is the control that the bound is
    generous and not merely short: the same command, the same builder, one
    ordinary file where the pipe goes.
    """
    tree, env = build_gate_tree(tmp_path, name="gate-tree-clean")
    (tree / "notes.md").write_text("# notes\n", encoding="utf-8")
    assert (tree / "notes.md").is_file(), "the control tree must hold a regular file"

    proc = run_gate_on_tree(tree, env)

    assert proc.returncode == GATE_DENYLIST_INACTIVE_EXIT, (
        f"the clean tree did not reproduce the plain gate run: {proc.returncode} "
        f"{proc.stderr}")
    assert GATE_BOUND_SECONDS > 0, "a zero bound would fail every gate run"
