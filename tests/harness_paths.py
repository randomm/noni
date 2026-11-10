"""Repository paths, the gated product-module list, and the wrapper paths.

Moved out of ``_harness.py`` for the file-size ratchet (issue #52) and
re-exported from there, so every existing ``from _harness import`` keeps
resolving. Pure data: nothing here imports the product.

"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

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
