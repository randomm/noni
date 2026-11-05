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
from harness_faults import _mkfifo_available
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

# The gate's exit when it could not run at all: the wrapper's ``import noni``
# failed, so no tracked file was read. Kept apart from the exit above on
# purpose -- CI passes on 2 (a public runner has no deny-list), so a code that
# means "nobody scanned anything" must never be answerable with it. Named here
# for the same reason the number above is: nothing in the product names it (the
# wrapper returns the literal), and the step's shell, the wrapper's own
# behaviour test and the two docs pages are all asserted against this value.
GATE_COULD_NOT_RUN_EXIT = 3


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

    The tree (see :func:`build_gate_tree`) carries a copy of
    ``scripts/public_safety.py`` and of the package that wrapper imports -- which
    is what makes the copy a gate over *that* tree and not over this checkout --
    plus one clean committed file, so the scan has tracked content to answer for.
    ``PYTHONPATH`` names the copied package because the installed venv is not what
    the page's reader has beside their clone.
    """
    tree, env = build_gate_tree(scratch)
    return run_gate_on_tree(tree, env)


# A gate that hangs is worse than a gate that fails: the publishing checklist
# stops with no verdict and no reason, which is what #91 did to this very command
# (the wrapper imports the package module, so it inherited the scan's blocking
# open). The bound is generous against a scan that finishes in well under a
# second and short enough that the regression reports itself instead of
# inheriting the absence of any timeout in the wrapper.
GATE_BOUND_SECONDS = 120


def build_gate_tree(scratch: Path, name: str = "gate-tree") -> tuple[Path, dict[str, str]]:
    """The scratch clone-root the gate audits, committed and clean.

    One builder for the plain run and the FIFO variant, because the two must
    differ in exactly one thing: a pipe at a path ``git add -A`` already
    committed. The tree carries a copy of ``scripts/public_safety.py`` and of the
    package that wrapper imports -- which is what makes the copy a gate over
    *that* tree and not over this checkout -- plus one clean committed file.

    Returns the tree and the launch env (deny-list pointer removed, package
    ``src/`` on ``PYTHONPATH``) so a caller can plant a state after the commit and
    before the run.
    """
    env = _gate_env_without_denylist()
    tree = scratch / name
    (tree / "scripts").mkdir(parents=True)
    shutil.copy2(REPO / "scripts" / "public_safety.py", tree / "scripts")
    shutil.copytree(REPO / "src" / "noni", tree / "src" / "noni")
    (tree / "notes.md").write_text("# notes\n", encoding="utf-8")
    init_repo(tree, env=env)
    checked(git(tree, "add", "-A", env=env), "gate tree add")
    checked(git(tree, "commit", "-q", "-m", "clean tree", identity=True, env=env),
            "gate tree commit")
    env["PYTHONPATH"] = str(tree / "src")
    return tree, env


def run_gate_on_tree(tree: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """The gate's own command, run from the scratch tree's root under a bound.

    The page's argv and the wrapper's own location decide the tree; the bound is
    the difference between a hung publishing gate and a red one.
    """
    argv = _golden_gate_argv()
    started = time.monotonic()
    try:
        proc = subprocess.run([sys.executable, *argv[1:]], capture_output=True,
                              text=True, cwd=tree, env=env,
                              timeout=GATE_BOUND_SECONDS)
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - a hung gate
        raise AssertionError(
            f"the publishing gate hung on this tree (no verdict in "
            f"{GATE_BOUND_SECONDS}s): {exc}") from None
    # A run that reached the bound tripped subprocess's own timeout above, so this
    # is the assertion that says the gate finished on its own, promptly.
    assert time.monotonic() - started < GATE_BOUND_SECONDS
    return proc


def run_gate_on_tree_with_a_tracked_fifo(scratch: Path) -> subprocess.CompletedProcess[str]:
    """The page's gate command over a tree whose tracked path is a named pipe.

    The pipe is planted by the only recipe that makes a path both tracked and a
    pipe -- commit a regular file, unlink it, ``os.mkfifo`` the same path -- on a
    path the builder's ``git add -A`` already committed. ``git add`` on a fresh
    pipe never lists it, so a variant that planted the pipe before the commit
    would run the gate over an ordinary file and pass with the hang in place.

    The expected outcome is the plain run's: exit ``GATE_DENYLIST_INACTIVE_EXIT``,
    because a pipe holds no stored content to flag and the deny-list class is the
    only thing this tree can refuse on.
    """
    if not _mkfifo_available():  # pragma: no cover - non-POSIX host only
        raise RuntimeError("this host cannot create a named pipe")
    tree, env = build_gate_tree(scratch, name="gate-tree-fifo")
    pipe = tree / "notes.md"
    pipe.unlink()
    os.mkfifo(pipe)
    # The precondition the whole variant rests on: git still lists the path, so
    # the scan really does reach the pipe. Without it the gate would be scanning
    # nothing and the exit code would mean nothing either.
    listed = git(tree, "ls-files", env=env)
    assert "notes.md" in listed.stdout.split(), (
        f"git no longer tracks the planted pipe, so the gate would scan nothing: "
        f"{listed.stdout!r}")
    return run_gate_on_tree(tree, env)


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
