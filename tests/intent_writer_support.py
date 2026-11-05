"""Launchers and tree-wide assertions for the ``intent.py`` writer tests.

The writer is the only thing that may create ``noni/direction/intent.md``, so the
tests need three things a fixture repo alone does not give them: a run with the
deterministic git identity the writers commit under, a draft file to hand it, and
a way to say "the tree is byte-identical to before" about every tracked file at
once. Held in a non-test module so the writer's test files share one launcher and
pytest never collects the builders as tests.

The launcher goes through the in-place wrapper (the form the skill documents), so
what the tests assert is the product's public entry point rather than an import
of its internals.

``--now`` is filled in by the launcher when the caller did not name it, and the
day it fills is the day the fixture's commits are dated at: a writer test that
compared two runs would otherwise compare two stamps whenever the second run
crossed a UTC midnight, which is the flake the ordering writer's own launcher
avoids the same way.
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
from pathlib import Path

from _harness import INTENT, REPO, _git, _script_ast, subprocess_env
from harness_git import _git_env_with_identity

# The skill directory the writer's documents live in, named once so the docs
# tests and the scrub pointer agree on where they are.
INTENT_SKILL_DIR = REPO / "skills" / "direction"

# The day every fixture commit and every stamp in this suite carries: the same
# one ``intent_fixtures.NOW`` dates the commits with, so a writer run and the
# census run that judges it agree without either of them reading a clock.
STAMP = "2026-10-27T12:00:00Z"


def intent_run(repo: Path, *args: str, repo_override: Path | None = None,
               env: dict[str, str] | None = None, cwd: Path | None = None,
               ) -> subprocess.CompletedProcess[str]:
    """Run the intent writer against ``repo`` with the arguments given verbatim.

    The caller owns the exact command line (``"set", "--from", path``), which is
    what the exit-code tests assert. ``--repo`` is prepended with ``repo`` unless
    ``repo_override`` names a different path, which is how a test aims the flag at
    something that is not a directory. Runs under the deterministic identity env,
    like every writer that commits: the writer makes its own commit and the suite
    clears ``GIT_AUTHOR_*`` from the environment, so a launcher that inherited the
    ambient env would have git refuse it for want of an identity.

    A caller that names ``--now`` itself keeps its own value: that flag is under
    test in the stamp tests and the launcher must not overwrite it.
    """
    argv = [sys.executable, str(INTENT), "--repo",
            str(repo_override if repo_override is not None else repo), *args]
    if "--now" not in args:
        argv += ["--now", STAMP]
    full = subprocess_env()
    full.update(_git_env_with_identity() if env is None else env)
    return subprocess.run(argv, capture_output=True, text=True, env=full,
                          timeout=120, cwd=None if cwd is None else str(cwd))


def intent_home_isolation(repo: Path, home: Path, *args: str,
                          ) -> subprocess.CompletedProcess[str]:
    """One run with HOME, USERPROFILE and the XDG dirs pinned to an empty ``home``.

    The writer resolves nothing from HOME by design; this launcher makes that
    refusable, so a regression that read a gitconfig or a decoy ``noni/`` out of
    the environment shows up as a written file under ``home`` rather than as a
    passing run. ``GIT_CONFIG_GLOBAL`` is deliberately NOT pointed at the decoy
    directory: git refuses a directory there outright, which would fail the run
    for a reason the test is not asserting. The harness identity env supplies a
    valid ``/dev/null`` for it instead, so the only host config the run could read
    is one that holds nothing.
    """
    full = subprocess_env()
    full.update(_git_env_with_identity())
    for var in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
                "XDG_DATA_HOME"):
        full[var] = str(home)
    argv = [sys.executable, str(INTENT), "--repo", str(repo), *args]
    if "--now" not in args:
        argv += ["--now", STAMP]
    return subprocess.run(argv, capture_output=True, text=True, env=full,
                          timeout=120)


def draft(tmp_path: Path, text: str | bytes, name: str = "draft.md") -> str:
    """Write a draft outside the audited tree and return its path as text.

    A draft is input, not state, so it lives in the test's own scratch directory:
    a draft inside the repo would be an untracked file the census's hygiene class
    would read.
    """
    path = tmp_path / name
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return str(path)


def tracked_digests(repo: Path) -> dict[str, str]:
    """Every tracked file of ``repo`` as path -> sha256 of its working bytes.

    The refusal assertion for a writer: a run that exits non-zero left these
    bytes alone, so a partial write or a truncated file cannot pass as a refusal.
    """
    listing = _git(repo, "ls-files").stdout.split()
    return {rel: hashlib.sha256((repo / rel).read_bytes()).hexdigest()
            for rel in listing}


def intent_ast() -> ast.Module:
    """The writer's own source as a syntax tree, for the docs-parity tests.

    Read through the harness's own resolver, which follows the skill wrapper to
    the package module it dispatches to: the readers ask what the *product*
    declares, and the wrapper is a shim whose docstring says nothing about the
    tool's contract.
    """
    return _script_ast(INTENT)


def parser_flags(tree: ast.Module) -> set[str]:
    """The long options ``main()`` declares, read from the source."""
    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    flags: set[str] = set()
    for node in ast.walk(main):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "add_argument":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and arg.value.startswith("--"):
                    flags.add(arg.value)
    assert flags, "no add_argument calls found in intent.py's main()"
    return flags


def commit_count(repo: Path) -> int:
    """How many commits the tree holds, for 'committed nothing' assertions."""
    return int(_git(repo, "rev-list", "--count", "HEAD").stdout.strip())
