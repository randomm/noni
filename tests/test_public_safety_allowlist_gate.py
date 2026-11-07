"""The publishing gate's verdict with a committed allowlist in the tree.

Each case runs ``scripts/public_safety.py`` in a child over a scratch clone, because the
assertion is an exit code and an in-process call cannot produce one. The states are the
ones the CI scrub step acts on, and the numbers are the product:

- 3 is the could-not-run code, which the CI step refuses. A malformed allowlist answered
  with 2 would go green, because 2 is the code the step tolerates (``|| [ "$?" -eq 2 ]``),
  and 1 would say a scan ran and disapproved when it never learned its exemptions;
- 1 is a finding: a stale entry is a violation, not a gate that could not run, and it may
  never answer 2 either;
- 0 is an exemption honoured, paired with the same tree exiting 1 once the entry is
  removed -- the control that makes the clean exit mean the exemption worked rather than
  that the fixture was never a token.

The exemption rules themselves (what a (path, label) pair covers, which entries are
refused at load, how a file is classified) are pinned in
``tests/test_public_safety_allowlist.py``; the split between the two files is the 500-line
cap in ``tests/test_file_size_limit.py``, and the seam is in-process verdicts versus the
CLI's exit code.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import public_safety
from _harness import REPO, _git, subprocess_env
from allowlist_tree import SECRET_LABEL, TOKEN_FIXTURE
from census_allowlist import _allowlist_line


def _gate_tree(tmp_path, *allowlist_lines: str) -> tuple[Path, dict[str, str]]:
    """A scratch clone holding the gate, the package it imports, and an allowlist.

    The gate picks its tree by the wrapper's own location, so the tree is built rather
    than pointed at: the same shape ``tests/quickstart_gate.py`` builds, kept here to the
    one thing this test adds -- a committed allowlist with contents of the caller's
    choosing.

    The scan reads two config files and both are pinned here, because the gate's exit code
    is only interpretable when neither can vary with the developer's machine: the deny-list
    by a *tracked* file (which :func:`subprocess_env` refuses to let the ambient
    ``NONI_SCRUB_DENYLIST`` override -- the env route is the operator's private vocabulary,
    and a gate test that depended on it would pass or fail on the host's config), and the
    allowlist by the file this helper writes.
    """
    import shutil

    tree = tmp_path / "gate-tree"
    (tree / "scripts").mkdir(parents=True)
    shutil.copy2(REPO / "scripts" / "public_safety.py", tree / "scripts")
    shutil.copytree(REPO / "src" / "noni", tree / "src" / "noni",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (tree / "notes.md").write_text("# notes\n", encoding="utf-8")
    # A deny-list word the tree does not contain: activating the class (so the gate can
    # answer 0 rather than the inactive 2) without adding a finding the allowlist entry
    # under test would have to cover.
    # The deny-list is activated by an *untracked* file, which is what the product
    # requires of operator vocabulary: a tracked deny-list is tree content and would
    # itself be scanned, so committing one would make the word a violation and every
    # gate case below answer for a finding it is not about.
    env = subprocess_env()
    env.pop(public_safety.ALLOWLIST_ENV_VAR, None)
    pointer = tmp_path / "gate-denylist"
    pointer.write_text("synthetic-vocab-name\n", encoding="utf-8")
    env[public_safety.DENYLIST_ENV_VAR] = str(pointer)
    if allowlist_lines:
        (tree / public_safety.ALLOWLIST_FILENAME).write_text(
            "\n".join(allowlist_lines) + "\n", encoding="utf-8")
    _git(tree, "init", "-q")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-q", "-m", "tree with an allowlist")
    return tree, env


def _run_gate(tree: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run the gate in a child: the exit code is the assertion, so it must be an exit."""
    return subprocess.run([sys.executable, "scripts/public_safety.py"],
                          capture_output=True, text=True, cwd=tree, env=env, timeout=180)


# --- AC4 at the gate: exit 3, proven in a child --------------------------------------


def test_the_gate_reads_the_tree_it_sits_in(tmp_path):
    """The tree is a parameter, not the checkout the harness was run from.

    The precondition every gate test here rests on, and a property of the wrapper the
    other exit-code cases assume: it resolves its tree from the wrapper's own location,
    so a scratch clone audits itself. Asserted on the finding rather than on the exit
    code -- ``fixtures/gone.txt`` is a path that exists in no real tree -- because an
    assertion on the code alone would pass on a wrapper that read this checkout and
    reported some other tree's problem.
    """
    tree, env = _gate_tree(tmp_path, _allowlist_line("fixtures/gone.txt", SECRET_LABEL))
    proc = _run_gate(tree, env)
    assert "fixtures/gone.txt" in proc.stderr, (
        f"the gate did not audit the tree it was copied into: {proc.stderr!r}")
    assert proc.returncode == 1, (
        f"expected exit 1 for a stale entry, got {proc.returncode}\n{proc.stderr}")
    assert "matches nothing" in proc.stderr, proc.stderr


def test_the_wrapper_exits_3_on_a_malformed_allowlist(tmp_path):
    """The gate could not run: exit 3, the code the CI step refuses.

    Not 1 and not 2. Exit 1 would say the scan ran and disapproved, and exit 2 is the one
    code the CI scrub step tolerates (``|| [ "$?" -eq 2 ]``) -- so a malformed allowlist
    answered with 2 would leave the publishing gate green on a scan that never knew its
    exemptions. The branch runs in a child because the exit code, not the in-process
    coverage of the wrapper, is the assertion.
    """
    tree, env = _gate_tree(tmp_path, "no delimiters here at all")
    proc = _run_gate(tree, env)
    assert proc.returncode == 3, (
        f"the gate answered {proc.returncode} on a malformed allowlist; expected 3, the "
        f"could-not-run exit\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
    assert "public-safety: clean" not in proc.stdout + proc.stderr, (
        "a gate that could not read its exemptions called itself clean")
    assert "allowlist" in proc.stderr, (
        f"the refusal said nothing about the file it could not use: {proc.stderr!r}")


def test_the_wrapper_exits_1_on_a_stale_entry_but_never_2(tmp_path):
    """A stale entry is a finding (exit 1), not a gate that could not run.

    The two states earn different codes because they have different fixes, and neither may
    land on 2: that is the code CI passes on, and a tree with a stale exemption is not a
    tree with nothing to report. The tree carries a tracked deny-list, so exit 2 cannot
    answer for this run at all and the number can only mean the stale row.
    """
    tree, env = _gate_tree(tmp_path, _allowlist_line("fixtures/gone.txt", SECRET_LABEL))
    proc = _run_gate(tree, env)
    assert proc.returncode == 1, (
        f"expected exit 1 for a stale entry, got {proc.returncode}\n{proc.stderr}")
    assert "matches nothing" in proc.stderr, proc.stderr


def test_the_wrapper_reports_clean_with_a_live_entry(tmp_path):
    """The happy path at the gate: a fixture the allowlist covers, and a clean 0.

    The tree holds a tracked deny-list, so this is the exit 0 the publishing pipeline
    actually needs -- which is also what proves the exemption is honoured by the gate and
    not merely by the loader: with the entry removed the same tree exits 1 on the token.
    """
    tree, env = _gate_tree(tmp_path, _allowlist_line("notes.md", SECRET_LABEL))
    (tree / "notes.md").write_text(TOKEN_FIXTURE, encoding="utf-8")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-q", "-m", "a fixture the allowlist covers")
    proc = _run_gate(tree, env)
    assert proc.returncode == 0, (
        f"expected the clean exit with the fixture exempted, got {proc.returncode}\n"
        f"{proc.stdout}\n{proc.stderr}")
    assert "notes.md" not in proc.stderr, (
        f"the exempted fixture was reported as a violation: {proc.stderr}")


def test_the_wrapper_exits_1_on_that_fixture_without_the_entry(tmp_path):
    """The control for the case above: the same tree, no allowlist, exit 1.

    Without it the clean exit would only prove the token was never a token.
    """
    tree, env = _gate_tree(tmp_path)
    (tree / "notes.md").write_text(TOKEN_FIXTURE, encoding="utf-8")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-q", "-m", "a fixture nobody exempted")
    proc = _run_gate(tree, env)
    assert proc.returncode == 1, (
        f"the planted token was not flagged without the exemption: {proc.returncode}\n"
        f"{proc.stderr}")
    assert "notes.md:1:" in proc.stderr, proc.stderr
