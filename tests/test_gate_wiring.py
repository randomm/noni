"""The quality-gate wiring itself, asserted from the committed config.

AGENTS.md states a coverage floor of at least 80 percent for new code and
runs ruff over the tree. Until this file neither was enforced by any check:
ruff excluded skills/ and there was no coverage configuration at all, so a
regression in either gate was invisible until an external reviewer noticed.

These tests read the two config artifacts (pyproject.toml and the CI
workflow) and assert the properties the gate depends on. They are the
mechanical half of the "prose is convention, not enforcement" rule in
AGENTS.md: a claim about the gate is only true if a check says so.

What is asserted, and why each one matters:

- fail_under >= 80: the floor is the ticket's acceptance criterion, so a config
  that no longer carries it silently un-enforces the AGENTS.md rule.
- subprocess in [tool.coverage.run] patch, and parallel true: register.py,
  claim.py and census-sessions.py are reached only as subprocesses, so
  without subprocess measurement the gate would report a green total while
  never having executed the three scripts it most needs to cover.
- the seven product modules named in [tool.coverage.report] include, matching
  the harness list exactly, and each of them present on disk: the gate measures
  the shipped code, so a module that drops out of the list stops being
  measured without anything failing.
- "skills" not in ruff's extend-exclude (and noni/decisions still excluded):
  skills/ holds shipped Python, so excluding it is the gap this ticket closes.
- the CI pins for coverage, pytest and ruff equal the pyproject dev pins, and
  CI actually runs `ruff check .` plus the three coverage steps: a developer
  and CI running different tool versions, or CI skipping a step, means two
  different gates.

The total the gate reports today is not asserted here: it moves with the test
suite, so pinning it would fail on unrelated changes. `coverage report` fails
below `fail_under` in CI, which is what enforces the floor itself.
"""

from __future__ import annotations

import re
import tomllib

from _harness import PRODUCT_MODULES, REPO

PYPROJECT = REPO / "pyproject.toml"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"

# Pinned tool versions the gate runs on; CI and pyproject must agree exactly.
GATED_TOOLS = ("coverage", "pytest", "ruff")


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _coverage_section(name: str) -> dict:
    tool = _pyproject().get("tool", {})
    return tool.get("coverage", {}).get(name, {})


def _ci_install_line() -> str:
    """The single workflow line that installs the dev tools into the venv."""
    lines = [
        line.strip()
        for line in CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
        if "pip install" in line
    ]
    assert len(lines) == 1, f"expected one pip install step in CI, found: {lines}"
    return lines[0]


def test_fail_under_is_at_least_80():
    """The coverage floor the AGENTS.md rule promises is configured."""
    report = _coverage_section("report")
    assert "fail_under" in report, "pyproject.toml sets no [tool.coverage.report] fail_under"
    assert report["fail_under"] >= 80, (
        f"fail_under is {report['fail_under']}, below the 80 floor AGENTS.md states"
    )


def test_subprocess_measurement_is_enabled():
    """Subprocess coverage is on, so the three script-launched modules count.

    parallel must be true as well: subprocess data is written to its own
    file and merged by `coverage combine`, which only runs against parallel
    data files.
    """
    run = _coverage_section("run")
    assert "subprocess" in run.get("patch", []), (
        "coverage must patch subprocess, or launched scripts are never measured"
    )
    assert run.get("parallel") is True, "coverage must run in parallel mode to combine subprocess data"


def test_gate_names_the_seven_product_modules():
    """Every product module is measured, and nothing else is in the list.

    The list lives in [tool.coverage.report] include: [tool.coverage.run]
    source cannot carry individual script files, because coverage treats a
    source entry that is not a directory as an importable package name.
    """
    include = _coverage_section("report").get("include", [])
    assert sorted(include) == sorted(PRODUCT_MODULES), (
        "the coverage include list and the harness product-module list disagree:\n"
        f"  pyproject: {sorted(include)}\n  harness:   {sorted(PRODUCT_MODULES)}"
    )
    for rel in PRODUCT_MODULES:
        assert (REPO / rel).is_file(), f"the gate names a module that does not exist: {rel}"


def test_ruff_lints_skills():
    """skills/ is linted: it holds shipped Python, so it is not excludable.

    noni/decisions stays excluded — those are data records, not code.
    """
    extend_exclude = _pyproject()["tool"]["ruff"].get("extend-exclude", [])
    assert "skills" not in extend_exclude, (
        "ruff still excludes skills/, so the shipped skill scripts are unlinted"
    )
    assert "noni/decisions" in extend_exclude, (
        "noni/decisions holds decision records, not Python: it must stay excluded"
    )


def test_ci_pins_match_pyproject_dev_pins():
    """CI and the local dev extra install byte-identical tool versions."""
    dev = _pyproject()["project"]["optional-dependencies"]["dev"]
    local = {}
    for spec in dev:
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", spec)
        assert match, f"dev extra {spec!r} is not an exact pin (name==version)"
        local[match.group(1).lower()] = match.group(2)

    install = _ci_install_line()
    ci = {name.lower(): ver for name, ver in re.findall(r"([A-Za-z0-9_.-]+)==([^\s]+)", install)}

    for tool in GATED_TOOLS:
        assert tool in local, f"pyproject dev extras do not pin {tool!r}"
        assert tool in ci, f"CI does not pin {tool!r} in its install step: {install}"
        assert ci[tool] == local[tool], (
            f"{tool} is pinned {ci[tool]!r} in CI but {local[tool]!r} in pyproject dev extras"
        )


def test_ci_runs_ruff_and_the_coverage_gate():
    """CI runs the documented gate: lint, then run/combine/report."""
    body = CI_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"ruff\s+check\s+\.", body), "CI does not run `ruff check .`"
    for step in ("coverage run", "coverage combine", "coverage report"):
        assert step in body, f"CI is missing the coverage step {step!r}"
