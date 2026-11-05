"""A tracked file the scan cannot read is a finding, never a silent skip (issue #91, lens HIGH).

The FIFO guard of #91 made every skip silent: ``_read_text_lenient`` answered
``None`` for the non-regular kinds *and* for a regular file whose ``open`` or
``read`` raised, and the scan's loop treated all of them as "not there". A tree
whose tracked file was sealed with ``chmod 000`` therefore scanned clean -- exit 0
from the publishing gate, zero hygiene rows from the census -- on bytes nobody had
held. A public-safety scan that cannot read a file may report that it could not
read it; it may not certify it.

The answers a scan can get are now separated by *kind*, not by prose: non-regular
paths (pipes, sockets, devices, directories), binary or non-UTF-8 content, and
bodies past the size bound stay silent skips, while an ``OSError`` on a regular
file earns a row in the scan's existing ``<path>:<line>: <label>`` shape. An
``open`` that faults with ENOENT/ENOTDIR after the listing is still a skip: the
file was there when git named it, and its absence is not a refusal.

The row names the fault by its **class** (``PermissionError``), never by the
exception's message, which carries the path the syscall failed on -- the same rule
the census's own rows follow (``census_text.fault_text``).

The fixture is the repo's one sealed-file builder (``tests/harness_faults.py``),
the sibling of the FIFO builder, and skips on a host whose euid reads anything:
there a 000-mode file opens and the test would assert nothing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import public_safety
import pytest
from _harness import (
    SRC,
    _git,
    _home_path_violation,
    _init_repo,
    _mkfifo_available,
    _plant_fifo,
    _plant_unreadable_tracked_file,
)
from fifo_child_runs import scrub_in_time
from harness_paths import REPO
from harness_runners import subprocess_env

# Generous against a scan that finishes in milliseconds; the bound is what tells a
# hung gate apart from a red one (the wrapper carries no timeout of its own).
GATE_BOUND_SECONDS = 120

# The publishing gate's exit code for a violation, as docs/PUBLISHING.md step 1
# names it. The unreadable file must produce it and not the deny-list-inactive 2:
# a sealed file is a violation whether or not a deny-list was read.
GATE_VIOLATION_EXIT = 1


def _sealed_repo(tmp_path: Path, name: str = "sealed") -> tuple[Path, Path]:
    """A committed repo holding one sealed tracked file and one clean neighbour.

    The neighbour is the control: a scan that bailed out of the whole run, or
    flagged every path it saw, would pass an assertion about the sealed file alone.
    """
    repo = _init_repo(tmp_path / name)
    (repo / "README.md").write_text("# clean\n", encoding="utf-8")
    _git(repo, "add", "--", "README.md")
    _git(repo, "commit", "-q", "-m", "clean file")
    return repo, _plant_unreadable_tracked_file(repo, "sealed.md")


def test_a_tracked_file_that_cannot_be_opened_is_one_violation(tmp_path):
    """AC1: the scan names the unreadable file, once, and prints no host path.

    Three assertions on the one row: its path and line 0 (the file, not a line of
    it), the fault's class, and the absence of the machine-local path the kernel put
    in the exception's message -- a row that carried it would turn a public-safety
    report into a leak of the machine it ran on. The clean neighbour is the control
    that says the scan flagged the file it could not read and not every path it saw.
    """
    repo, _sealed = _sealed_repo(tmp_path)

    violations = scrub_in_time(repo)

    assert violations == [f"sealed.md:0: {public_safety.UNREADABLE_TRACKED_FILE_LABEL}"
                          " (PermissionError: Permission denied)"], (
        f"the unreadable file did not earn its one row: {violations}")
    assert _home_path_violation().split("/")[3] not in str(violations), (
        f"the row carried a machine-local path: {violations}")


def test_the_publishing_gate_exits_one_for_an_unreadable_tracked_file(tmp_path):
    """AC1, end to end: ``scripts/public_safety.py`` returns 1 on a sealed file.

    The wrapper's own exit is the contract AGENTS.md makes a gate, so this runs the
    real command over a scratch tree holding its own copy of the wrapper and of the
    package it imports (the shape ``quickstart_gate`` builds): the wrapper derives
    the tree it audits from its own location, so running this checkout's wrapper
    would scan this checkout, and a scan that reported the row but left the CLI at
    2 -- the deny-list-inactive answer this tree would otherwise earn -- would not
    stop a publish.
    """
    tree, env = _gate_tree(tmp_path, "gate-sealed")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-q", "-m", "tracked file to seal")
    _plant_unreadable_tracked_file(tree, "sealed.md")
    assert "sealed.md" in _git(tree, "ls-files").stdout.split(), (
        "git does not track the sealed file, so the gate would scan nothing")

    proc = subprocess.run([sys.executable, "-B", str(tree / "scripts" / "public_safety.py")],
                          capture_output=True, text=True, env=env, cwd=tree,
                          timeout=GATE_BOUND_SECONDS)

    assert proc.returncode == GATE_VIOLATION_EXIT, (
        f"the gate exited {proc.returncode} on a tracked file it could not read; a "
        f"sealed file is a violation, not a skip\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
    assert "sealed.md:0:" in proc.stderr, (
        f"the gate's refusal did not name the unreadable file: {proc.stderr!r}")


def _gate_tree(scratch: Path, name: str) -> tuple[Path, dict[str, str]]:
    """A scratch clone-root holding the wrapper, the package it imports, one file.

    Returns the tree and the launch env (deny-list pointer removed, the copied
    package first on ``PYTHONPATH``) so a caller plants its own state after the
    commit and runs the gate's own command from the tree's root.
    """
    tree = scratch / name
    (tree / "scripts").mkdir(parents=True)
    (tree / "src").mkdir()
    shutil.copy2(REPO / "scripts" / "public_safety.py", tree / "scripts")
    shutil.copytree(SRC / "noni", tree / "src" / "noni")
    (tree / "notes.md").write_text("# notes\n", encoding="utf-8")
    _init_repo(tree)
    env = subprocess_env()
    env["PYTHONPATH"] = str(tree / "src")
    env.pop(public_safety.DENYLIST_ENV_VAR, None)
    return tree, env


def test_a_fifo_beside_an_unreadable_file_is_still_silently_skipped(tmp_path):
    """The guard of #91 stays: a pipe earns no row while a sealed file earns one.

    Both faults sit in one tree so neither half can be satisfied by an
    implementation that reported everything (a pipe is not a violation source) or
    nothing (a sealed file is). The pipe is still a pipe afterwards, which is the
    assertion that the scan refused it rather than read it.
    """
    if not _mkfifo_available():  # pragma: no cover - non-POSIX host only
        pytest.skip("os.mkfifo is POSIX-only, so this host cannot plant a named pipe")
    repo, _sealed = _sealed_repo(tmp_path, name="sealed-and-pipe")
    pipe = _plant_fifo(repo, "pipe.md")

    violations = scrub_in_time(repo)

    assert any(v.startswith("sealed.md:0:") for v in violations), violations
    assert not any("pipe.md" in v for v in violations), (
        f"a FIFO is not a violation source: {violations}")
    assert pipe.exists() and not pipe.is_file(), "the scan consumed the pipe it skipped"


def test_the_row_label_is_public_safety_s_and_the_census_split_knows_it():
    """The label is the checker's and the census's split recognises it.

    The census reads its label vocabulary out of this module
    (``census_hygiene._hygiene_labels``) rather than hard-coding one, and a label it
    had never seen would be reported verbatim instead of split into path, line and
    label. The row below is assembled the way the scan assembles one, so the
    assertion is about the shape the scan emits rather than a string copied here.
    """
    import census

    labels = census._hygiene_labels(public_safety)
    assert public_safety.UNREADABLE_TRACKED_FILE_LABEL in labels, sorted(labels)

    label = public_safety.UNREADABLE_TRACKED_FILE_LABEL
    fault = "(PermissionError: Permission denied)"
    row = f"sealed.md:0: {label} {fault}"
    # The fault tail survives the split: the census row must say who refused the read,
    # not merely that something was refused.
    assert census._split_violation(row, labels) == ("sealed.md", 0, f"{label} {fault}"), (
        f"the census did not split the row the scan emits: {row}")


def test_a_file_that_vanished_after_the_listing_is_still_a_skip(tmp_path):
    """ENOENT/ENOTDIR after ``git ls-files`` is absence, so the scan stays silent.

    The other half of the distinction: a path the listing named and the open then
    could not find is a file that is not there, not a file the filesystem refused,
    and a row for it would be a false finding. The preconditions name the state the
    scan is asked about, because "no row" is also what a scan that never reached the
    path would report.
    """
    repo, sealed = _sealed_repo(tmp_path, name="vanished")
    sealed.unlink()
    listing = _git(repo, "ls-files").stdout.split()
    assert "sealed.md" in listing and not sealed.exists(), (
        f"not the state this test is about: tracked={listing}, present={sealed.exists()}")

    assert scrub_in_time(repo) == [], "a vanished tracked file earned a row"


def test_the_deny_list_read_still_degrades_on_a_sealed_candidate(tmp_path):
    """The other lenient caller is unchanged: a sealed deny-list stays a skip, not a finding.

    ``load_denylist`` shares the guarded open, so the fault path added for tracked
    files must not have turned its three statuses into violations: an unreadable
    deny-list is still the inactive-class answer the publishing checklist names, and
    the tree's own scan still reports no row for it.
    """
    repo, _ = _sealed_repo(tmp_path, name="denylist-sealed")
    sealed = tmp_path / "sealed-denylist.txt"
    sealed.write_text("synthetic-project-name\n", encoding="utf-8")
    sealed.chmod(0o000)
    if os.access(sealed, os.R_OK):
        sealed.chmod(0o644)
        pytest.skip("root reads anything, so the 000-mode file cannot be planted")

    public_safety._default_denylist_file = lambda _repo: sealed
    try:
        result = public_safety.load_denylist(repo)
    finally:
        public_safety._default_denylist_file = public_safety.default_denylist_file

    assert result.status == "absent", (
        f"a sealed candidate must keep the walk going, not classify the run: {result}")
    assert result.entries == []
