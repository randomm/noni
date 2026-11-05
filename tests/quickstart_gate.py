"""The publishing gate, run as the page's reader runs it: from a clone's own root.

``tests/test_quickstart.py`` asserts the quickstart's exit-code sentence about
``scripts/public_safety.py``; this module is how it runs that command. It lives
beside the test rather than in it because the whole of the work here is assembling
the tree the gate reads, and that assembly is the reason the test is hermetic at all.

The gate derives the tree it audits from **the wrapper's own location**
(``REPO = Path(__file__).resolve().parent.parent`` in ``scripts/public_safety.py``),
not from the cwd, so a run cannot be pointed at a scratch tree by a flag. Running the
page's line in this checkout would therefore scan this checkout, and its verdict would
change with whatever untracked ``.noni-scrub-denylist`` the operator happens to hold
-- red for an operator, green in CI, for the same page. The builder below instead
copies the wrapper and the package it imports into a throwaway committed repository
under the caller's ``tmp_path``: the clone-root shape the page tells the reader to
stand in, at scratch scale, with no deny-list in it. That is the first-run case the
page's sentence speaks for, and it is the same tree on every host.

The argv is the golden DENYLIST command (:mod:`quickstart_golden`), not one typed
here, so the test runs the line a human reviewed and a page change reddens the golden
comparison rather than quietly retargeting this helper.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from _harness import REPO
from docs_commands import read
from docs_promises import PUBLISHING, QUICKSTART
from quickstart_golden import DENYLIST
from quickstart_runner import checked, git, route_commands
from quickstart_topology import init_repo, run_env

from noni import public_safety

# The gate's exit code for a deny-list class that did not run: the exit the page's
# first-run sentence promises. Nothing in the product names it (the wrapper returns
# the literal), so it is pinned here, and the two documents that state it are
# asserted against this value rather than trusted -- docs/PUBLISHING.md step 1, the
# checklist whose green run depends on the distinction, and the sentence the page
# prints beside the gate command.
GATE_DENYLIST_INACTIVE_EXIT = 2

# The bound on one gate run. A clean tree costs about a second of git plus a
# handful of opens; a scan that blocks on a pipe blocks forever, so the bound is
# what turns that into a failing test instead of a suite that never reports.
GATE_BOUND_SECONDS = 180



def gate_page_sentences() -> None:
    """The two documents that state the pinned exit code still state it.

    Called by the test that runs the gate, so the number below cannot drift from the
    prose while both stay green: the page's own sentence and the operator's checklist
    each have to name this exit for an inactive class.
    """
    assert f"exits {GATE_DENYLIST_INACTIVE_EXIT}" in read(QUICKSTART), (
        f"docs/QUICKSTART.md no longer states the gate's exit "
        f"{GATE_DENYLIST_INACTIVE_EXIT} for an inactive deny-list class")
    publishing = read(PUBLISHING)
    assert f"status {GATE_DENYLIST_INACTIVE_EXIT}" in publishing, (
        f"docs/PUBLISHING.md no longer states exit {GATE_DENYLIST_INACTIVE_EXIT} for "
        "an inactive deny-list class, so the number this suite pins has lost the "
        "checklist it came from")


def run_gate_on_tree_with_no_denylist(scratch: Path) -> subprocess.CompletedProcess[str]:
    """The golden publishing-gate command, run against a scratch tree of its own.

    The tree carries a copy of ``scripts/public_safety.py`` and of the package that
    wrapper imports -- which is what makes the copy a gate over *that* tree and not
    over this checkout -- plus one clean committed file, so the scan has tracked
    content to answer for. ``PYTHONPATH`` names the copied package because the
    installed venv is not what the page's reader has beside their clone.
    """
    _tree, _elapsed, proc = _run_gate_case(scratch)
    return proc


def run_gate_on_tree_with_a_tracked_fifo(
        scratch: Path) -> tuple[Path, float, subprocess.CompletedProcess[str]]:
    """The same gate command over a tree whose tracked path holds a pipe.

    The publishing gate is the second caller of ``scrub_tracked_files`` and the
    one AGENTS.md names, and it has no timeout of its own: a scan that blocks on
    a pipe hangs the operator's publish-before-push step rather than reporting
    it. The pipe is planted by the post-commit swap on a path ``git add -A``
    already committed (git indexes blobs, never pipes, so a staged fifo is not a
    thing the builder could have made).

    Returns ``(tree, elapsed, process)``. The tree is handed back so the caller
    can assert the pipe survived the scan -- a checker that deleted the offending
    path would otherwise pass an exit-code assertion -- and the elapsed seconds
    are the assertion that the gate returned rather than merely that the child
    died inside its own timeout, which is the difference between a pass and a
    green suite that never ran the check.
    """
    return _run_gate_case(scratch, plant_fifo=True)


def _run_gate_case(scratch: Path, plant_fifo: bool = False,
                   ) -> tuple[Path, float, subprocess.CompletedProcess[str]]:
    """One gate run over the scratch clone, optionally over a tree holding a pipe.

    One builder for both cases so the fifo run differs from the clean one by the
    pipe and nothing else: two builders would be two trees, and only one of them
    is the tree the page's exit-code sentence describes.
    """
    tree, env = _build_gate_tree(scratch)
    if plant_fifo:
        _plant_gate_fifo(tree)
    started = time.monotonic()
    proc = _run_gate(tree, env)
    return tree, time.monotonic() - started, proc


def _build_gate_tree(scratch: Path) -> tuple[Path, dict[str, str]]:
    """The committed scratch clone the gate reads: wrapper, package, one clean file.

    Shared by both gate runs so the fifo case differs from the clean one by the
    pipe and nothing else -- a second builder would be a second tree whose
    verdict the page's sentence does not describe.
    """
    tree = scratch / "gate-tree"
    (tree / "scripts").mkdir(parents=True)
    shutil.copy2(REPO / "scripts" / "public_safety.py", tree / "scripts")
    shutil.copytree(REPO / "src" / "noni", tree / "src" / "noni")
    (tree / "notes.md").write_text("# notes\n", encoding="utf-8")
    env = _gate_env_without_denylist()
    init_repo(tree, env=env)
    checked(git(tree, "add", "-A", env=env), "gate tree add")
    checked(git(tree, "commit", "-q", "-m", "clean tree", identity=True, env=env),
            "gate tree commit")
    return tree, env


def _plant_gate_fifo(tree: Path) -> Path:
    """Swap a committed regular file of the gate tree for a pipe, and track it."""
    target = tree / "notes.md"
    if not target.is_file():
        raise AssertionError(
            "the gate tree's notes.md was never committed: a tracked fifo is "
            "planted by replacing a committed regular file, since git cannot "
            "stage a pipe")
    target.unlink()
    os.mkfifo(target)
    return target


def _run_gate(tree: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """The page's gate command, launched against ``tree`` under a bound."""
    argv = _golden_gate_argv()
    env = dict(env)
    env["PYTHONPATH"] = str(tree / "src")
    return subprocess.run([sys.executable, *argv[1:]], capture_output=True,
                          text=True, cwd=tree, env=env, timeout=GATE_BOUND_SECONDS)


def _golden_gate_argv() -> list[str]:
    """The page's gate command, as the golden list prints it (unique, or fail)."""
    commands = [argv for argv in route_commands(DENYLIST)
                if argv[:2] == ["python", "scripts/public_safety.py"]]
    assert len(commands) == 1, f"the golden deny-list gate command is not unique: {commands}"
    return commands[0]


def _gate_env_without_denylist() -> dict[str, str]:
    """The launch env with any deny-list pointer removed.

    The page's promise is about a tree that has no deny-list yet, which is what a
    first run has; a host variable naming one would turn the gate's refusal into a
    different experiment than the one the page describes. conftest clears the
    variable per test, so this is belt-and-braces over the one env builder the
    quickstart harness uses.
    """
    env = run_env()
    env.pop(public_safety.DENYLIST_ENV_VAR, None)
    return env
