"""Repository paths, the gated product-module list, and the wrapper paths.

Moved out of ``_harness.py`` for the file-size ratchet (issue #52) and
re-exported from there, so every existing ``from _harness import`` keeps
resolving. Pure data plus the shared scratch rule; nothing here imports the
product.

"""

from __future__ import annotations

from pathlib import Path
from shutil import ignore_patterns as _ignore_patterns

REPO = Path(__file__).resolve().parent.parent

# The ceiling every subprocess the suite starts is given for git's upward
# repository discovery (issue #220, AC2). A child that resolves a repository from
# its working directory must not be able to walk out of the test's own tree and
# find the checkout it is being run from; that is how a fixture's throwaway
# identity ended up in the real repository's shared config, once a basetemp lived
# under this tree's ignored ``tmp/``.
#
# The value is this harness's own root -- the one directory every tree the suite
# builds is under, whatever ``--basetemp`` a developer passed (a basetemp under the
# checkout, the platform default, or one named by a driver for a worktree). A ceiling
# at an *ancestor* of the checkout would stop nothing at all, because the checkout is
# below it and still discoverable, so naming the tmp root as a bare constant would
# have been the weaker half of the pair and passed its own test by accident.
#
# Resolved, so a ``/tmp`` symlink cannot put a ceiling git would step straight over.
# Where the suite is run from outside a repository, git's own ceiling rule is
# unreachable from below and the top-level check is the half that contains it.
TEST_TMP_CEILING = Path(__file__).resolve().parent.parent

# The package's modules, measured by the gate and imported by the tests as
# ``noni.<module>``. The package must be installed (``pip install -e ".[dev]"``
# or the built wheel) or its ``src/`` put on ``PYTHONPATH``; conftest.py does the
# latter so the in-place suite needs no install step.
SRC = REPO / "src"

# The Python product modules the coverage gate measures, relative to the repo
# root. Naming them here keeps the list in one place: pyproject's
# [tool.coverage.report] include carries the same paths and
# tests/test_gate_wiring.py compares the two, so a module cannot quietly
# disappear from the gate. Tests are excluded by construction — only these
# files are measured, so the reported total is the coverage of shipped code.
# The package modules under src/noni/ are the shipped code; the skills/*/
# scripts/ wrappers are thin shims and are deliberately not measured.
PRODUCT_MODULES = (
    "integrations/adapter_protocol.py",
    "integrations/github-issues/github_issues_adapter.py",
    "src/noni/__main__.py",
    "src/noni/_path_kind.py",
    "src/noni/_safe_text.py",
    "src/noni/_decide_flags.py",
    "src/noni/_why.py",
    "src/noni/_decide_state_root.py",
    "src/noni/brief.py",
    "src/noni/brief_intent.py",
    "src/noni/brief_page.py",
    "src/noni/census.py",
    "src/noni/census_git.py",
    "src/noni/census_group_gate.py",
    "src/noni/census_hygiene.py",
    "src/noni/census_hygiene_rows.py",
    "src/noni/census_intent.py",
    "src/noni/census_intent_readers.py",
    "src/noni/census_json.py",
    "src/noni/census_row.py",
    "src/noni/census_ledger_checks.py",
    "src/noni/ledger_schema.py",
    "src/noni/ledger_level.py",
    "src/noni/_writer.py",
    "src/noni/census_ledger_edited.py",
    "src/noni/census_ledger.py",
    "src/noni/census_ordering.py",
    "src/noni/census_ordering_closed.py",
    "src/noni/census_ordering_readers.py",
    "src/noni/census_cli.py",
    "src/noni/census_run.py",
    "src/noni/census_render.py",
    "src/noni/census_report.py",
    "src/noni/census_wrapper.py",
    "src/noni/census_text.py",
    "src/noni/cli.py",
    "src/noni/decide.py",
    "src/noni/gitenv.py",
    "src/noni/gitwrite.py",
    "src/noni/record_read.py",
    "src/noni/intent.py",
    "src/noni/intentschema.py",
    "src/noni/intentschema_headings.py",
    "src/noni/labels.py",
    "src/noni/order.py",
    "src/noni/order_gitwrite.py",
    "src/noni/order_add.py",
    "src/noni/order_commit.py",
    "src/noni/order_json.py",
    "src/noni/order_plan.py",
    "src/noni/order_probe.py",
    "src/noni/orderschema.py",
    "src/noni/orderstate.py",
    "src/noni/public_safety.py",
    "src/noni/public_safety_io.py",
    "src/noni/public_safety_allowlist.py",
    "src/noni/public_safety_scan.py",
    "src/noni/shim_help.py",
    "src/noni/wrapper_bash.py",
    "src/noni/targetschema.py",
)

# The env var coverage's subprocess support needs. A launched interpreter
# starts measuring only when this names the config file to read, so it is set
# here — in the launcher itself, not only in the shell that started pytest —
# and a bare local `pytest` gets the same measurement as the documented
# three-command gate.
COVERAGE_PROCESS_START = str(REPO / "pyproject.toml")


# Width every launched tool sees, pinned so the --help byte-for-byte
# comparisons cannot depend on the terminal the suite happened to run under.
# The launchers force this value (not setdefault): a caller's own COLUMNS --
# including one a test deliberately sets to 80 to prove width-independence --
# must not change the bytes argparse emits.
HELP_COLUMNS = "100"

STEERING_SKILL = REPO / "skills" / "steering-ledger" / "scripts"
DIRECTION_SKILL = REPO / "skills" / "direction" / "scripts"
CENSUS_SKILL = REPO / "skills" / "census" / "scripts"
# The in-place entry points: the thin wrappers the skills document. They are the
# compatibility route, and the paired test compares each of them against the
# console route, so the paths are the product's public surface, not a detail.
CENSUS_SH = STEERING_SKILL / "census.sh"
DECIDE = STEERING_SKILL / "decide.py"
ORDER = DIRECTION_SKILL / "order.py"
INTENT = DIRECTION_SKILL / "intent.py"
CENSUS = CENSUS_SKILL / "census.py"

# The four tools the ``noni`` command dispatches: subcommand -> the wrapper that
# must produce the same bytes. The shell census entry point is the other
# half of the wrapper surface: it is compared against the package route in
# tests/test_console_equivalence.py, so the path is pinned here as well.
TOOL_WRAPPERS: tuple[tuple[str, Path], ...] = (
    ("census", CENSUS),
    ("decide", DECIDE),
    ("order", ORDER),
    ("intent", INTENT),
)


# --- the one scratch rule for the repo-rooted walks -----------------------------
#
# Three harness walks start at ``REPO``: the two clones (``quickstart_topology
# .materialise_clone`` and ``readme_support._materialise_clone``) and the decide-skill
# page scan. AGENTS.md sends per-issue scratch to ``tmp/issue-N/``, so a dev run keeps
# venvs, basetemp trees and whole worktrees exactly where those walks recurse: the
# copies walked into their own output and never finished, and the page scan read every
# Markdown file the scratch held (issue #205). ``.gitignore`` already ignores ``/tmp/``
# and ``.worktrees`` is kept out by ``.git/info/exclude``; these are the same two
# names seen from the walk side.
#
# ``tmp`` is skipped only directly under the root the walk started from, which is what
# the leading slash of ``.gitignore``'s ``/tmp/`` means: a tracked page nested below a
# directory that happens to be named ``tmp`` is content, and a basename glob at any
# depth would have hidden it. ``.worktrees`` and ``.git`` are skipped by name wherever
# they appear, exactly as both clone lists already did.
SCRATCH_ROOT_NAME = "tmp"
SCRATCH_DIR_NAME = ".worktrees"

# The repository metadata folder. It is scratch for a walk for the same reason the two
# folders above are: a planning driver keeps its base copy of the docs under the
# checkout's own ``.git`` (``.git/pi-plan-base/<hash>/``), and a repo-rooted page scan
# that walked into it counted those stale pages as tracked pages of this repository
# (issue #231). One name here, consumed by both shapes below, so the predicate and the
# copytree callable cannot disagree about it the way they did before this constant.
GIT_DIR_NAME = ".git"

# The build droppings the two clones drop on top of the scratch rule. Both copies held
# byte-identical literals and nothing compared them; they are one tuple now. ``.git``
# is spelled from the constant above, so the shared rule and this list name one folder.
CLONE_IGNORE_NAMES = (GIT_DIR_NAME, "__pycache__", ".venv", "*.pyc", ".pytest_cache",
                      ".coverage", ".coverage.*", "noni.egg-info",
                      "noni_noni.egg-info")


def in_scratch(root: Path, path: Path) -> bool:
    """Whether ``path`` lies in scratch below ``root``: the rule for a walk.

    ``root`` is the directory the walk started from, so "at the root" is decided
    against the caller's root and not against ``REPO``: the same predicate answers for
    a planted tree under ``tmp_path`` and for the real checkout, whatever path pytest
    resolved that to. An ancestor that is not under ``root`` carries no root-relative
    claim, so only the ``.worktrees`` name half can apply to it: ``.worktrees`` names a
    scratch layout wherever the path happens to carry it, while a ``.git`` or a ``tmp``
    outside the caller's root says nothing about what that caller treats as scratch.
    """
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return SCRATCH_DIR_NAME in path.parts
    return bool(parts and (parts[0] == SCRATCH_ROOT_NAME
                           or SCRATCH_DIR_NAME in parts
                           or GIT_DIR_NAME in parts))


def scratch_ignore(root: Path):
    """The ``shutil.copytree`` ignore callable for the same rule, over ``root``.

    ``copytree`` hands this the directory it is listing and that directory's
    basenames, so the root is recovered from the directory and asked of
    :func:`in_scratch`: one rule in two shapes, pinned against itself by
    ``tests/test_scratch_walks.py``.
    """
    by_name = _ignore_patterns(*CLONE_IGNORE_NAMES, SCRATCH_DIR_NAME, GIT_DIR_NAME)

    def ignore(directory: str, names: list[str]) -> set[str]:
        skipped = set(by_name(directory, names))
        listed = Path(directory)
        if listed == root:
            skipped.add(SCRATCH_ROOT_NAME)
        elif SCRATCH_DIR_NAME in names:
            skipped.add(SCRATCH_DIR_NAME)
        if GIT_DIR_NAME in names:
            skipped.add(GIT_DIR_NAME)
        return skipped

    return ignore
