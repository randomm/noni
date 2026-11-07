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
- subprocess in [tool.coverage.run] patch, and parallel true: the writers and
  the census are reached as subprocesses, so without subprocess measurement the
  gate would report a green total while never having executed the scripts it
  most needs to cover.
- the product modules named in [tool.coverage.report] include, matching
  the harness list exactly, and each of them present on disk: the gate measures
  the shipped code, so a module that drops out of the list stops being
  measured without anything failing.
- "skills" not in ruff's extend-exclude (and noni/decisions still excluded):
  skills/ holds shipped Python, so excluding it is the gap this ticket closes.
- the CI pins for coverage, pytest, ruff and build equal the pyproject dev pins,
  and CI actually runs `ruff check .` plus the three coverage steps: a developer
  and CI running different tool versions, or CI skipping a step, means two
  different gates. The wheel job's install line is pinned too, because the tool
  that builds the distribution is part of the gate the reader's install depends
  on.
- CONTRIBUTING.md still documents the venv route the gate is built on, after the
  page-set sweep that moved every *reader's* install onto the quickstart's uv and
  clean-venv forms. The contributor's editable install is the local half of the
  CI gate and a different thing from a reader's install, so it stays in this file
  with the pins it must match rather than following the reader to the quickstart
  (issue #75).
- the public-repo hygiene scrub step exists, sits after the editable install, and
  its own shell is *executed* against each exit code the gate can return: 0 and 2
  pass, 1 and the gate's own could-not-run code (3) fail. The step is a shell
  expression, so only running it says which codes it accepts.

The total the gate reports today is not asserted here: it moves with the test
suite, so pinning it would fail on unrelated changes. `coverage report` fails
below `fail_under` in CI, which is what enforces the floor itself.
"""

from __future__ import annotations

import os
import re
import tomllib

from _harness import PRODUCT_MODULES, REPO, SRC

PYPROJECT = REPO / "pyproject.toml"
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"

# Pinned tool versions the gate runs on; CI and pyproject must agree exactly.
# `build` is in the list because the wheel job builds the distribution with it:
# the job that proves the wheel is part of the gate that must not drift from the
# dev extra.
GATED_TOOLS = ("build", "coverage", "pytest", "ruff")


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _coverage_section(name: str) -> dict:
    tool = _pyproject().get("tool", {})
    return tool.get("coverage", {}).get(name, {})


def _ci_install_lines() -> list[str]:
    """Every workflow line that installs something into a venv.

    Two jobs install: the in-place suite (the pinned dev tools, then the
    editable package) and the wheel job (the build tool, then the built wheel
    into a fresh venv). They are returned in file order and the assertions below
    say which line each one is, so an install step cannot be added or dropped
    without one of them failing.
    """
    lines = [
        line.strip()
        for line in CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
        if "pip install" in line
    ]
    assert lines, "CI has no pip install step at all"
    return lines


def _ci_inplace_line() -> str:
    """The in-place job's pinned-tool install line (the one carrying the gate pins)."""
    lines = [line for line in _ci_install_lines() if "-e " not in line and "dist/" not in line]
    assert lines, f"CI installs no pinned tool set: {_ci_install_lines()}"
    return lines[0]


def _ci_build_line() -> str:
    """The wheel job's build-tool install line.

    One line installs the build tool and the [build-system] backend together:
    `--no-isolation` means the build uses this venv's setuptools rather than
    resolving one, so the backend has to be installed for the build to run at
    all. Both pins are compared against the dev extra.
    """
    lines = [line for line in _ci_install_lines() if re.search(r"\bbuild==", line)]
    assert len(lines) == 1, f"expected exactly one CI line pinning build, found: {lines}"
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


def test_gate_names_the_product_modules():
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


def test_gate_names_every_package_module():
    """No module under src/noni/ can be re-forgotten from the gate.

    The move brought decide.py, gitwrite.py and targetschema.py under the gate
    for the first time. A module added to the package later would otherwise sit
    outside the total unnoticed, so the check runs from the other direction:
    every shipped module in the package directory must be in the list. The
    package's own ``__init__.py`` is the one exclusion — a docstring and an
    ``__all__``, with no statement to cover.
    """
    shipped = sorted(
        (SRC / "noni" / name).relative_to(REPO).as_posix()
        for name in sorted(os.listdir(SRC / "noni"))
        if name.endswith(".py") and name != "__init__.py"
    )
    assert shipped, "no package modules found under src/noni/"
    missing = [rel for rel in shipped if rel not in set(PRODUCT_MODULES)]
    assert not missing, (
        "package modules are outside the coverage gate (add them to "
        f"PRODUCT_MODULES and the include list): {missing}"
    )


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
    """CI and the local dev extra install byte-identical tool versions.

    The pin-equality assertion applies to the in-place job's line (the gate the
    developer runs) and, for ``build`` alone, to the wheel job's line: the tool
    that builds the distribution must not be free to differ from the dev extra.
    """
    dev = _pyproject()["project"]["optional-dependencies"]["dev"]
    local = {}
    for spec in dev:
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", spec)
        assert match, f"dev extra {spec!r} is not an exact pin (name==version)"
        local[match.group(1).lower()] = match.group(2)

    install = _ci_inplace_line()
    ci = {name.lower(): ver for name, ver in re.findall(r"([A-Za-z0-9_.-]+)==([^\s]+)", install)}

    for tool in GATED_TOOLS:
        assert tool in local, f"pyproject dev extras do not pin {tool!r}"
        # `build` is the wheel job's tool, not the in-place gate's: it is pinned
        # on its own line and compared there below.
        if tool == "build":
            continue
        assert tool in ci, f"CI does not pin {tool!r} in its install step: {install}"
        assert ci[tool] == local[tool], (
            f"{tool} is pinned {ci[tool]!r} in CI but {local[tool]!r} in pyproject dev extras"
        )

    build_line = _ci_build_line()
    build = {name.lower(): ver
             for name, ver in re.findall(r"([A-Za-z0-9_.-]+)==([^\s]+)", build_line)}
    assert build.get("build") == local.get("build"), (
        f"build is pinned {build.get('build')!r} in the CI wheel job but "
        f"{local.get('build')!r} in pyproject dev extras"
    )
    # The backend has to be present in the same venv the build runs in, or
    # --no-isolation fails with "Backend 'setuptools.build_meta' is not
    # available" -- a job-level failure that looks like a packaging bug.
    assert "setuptools==" in build_line, (
        f"the wheel job builds with --no-isolation but installs no setuptools: {build_line}"
    )


def test_ci_builds_the_wheel_and_installs_it_in_a_fresh_venv():
    """The wheel job exists and is the install route the README sells.

    The acceptance criterion is that a fresh venv with the built wheel provides
    ``noni``; the CI that proves it must build the wheel without network
    isolation (the venv already carries setuptools) and install it into a
    second venv rather than the one running the suite.
    """
    body = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "python -m build --wheel" in body, "CI never builds a wheel"
    assert "--no-isolation" in body, (
        "CI builds the wheel with network isolation, which needs a resolver the "
        "job does not install; build with --no-isolation against setuptools"
    )
    assert re.search(r"python -m venv \.venv-wheel", body), (
        "CI installs the wheel into the same venv as the in-place suite"
    )
    assert re.search(r"\.venv-wheel/bin/pip install [^\n]*dist/\*\.whl", body), (
        "CI does not install the built wheel into the fresh venv"
    )
    for test_module in ("tests/test_console_equivalence.py", "tests/test_wheel_contents.py",
                        "tests/test_readme.py"):
        assert test_module in body, f"the wheel job never runs {test_module}"


def test_ci_proves_the_installed_console_command_runs():
    """The wheel job calls the installed script, not just the module.

    ``python -m noni.cli`` exercises the dispatch; only ``noni --help`` proves the
    console script the wheel's ``entry_points.txt`` registers exists and resolves
    on PATH, which is the first thing a reader who ran ``pip install`` types.
    """
    body = CI_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"\.venv-wheel/bin/noni --help", body), (
        "the wheel job never runs the installed noni script"
    )
    from noni import cli

    # Parsed from the loop header rather than matched as a literal, so the
    # assertion follows cli.TOOLS: a verb added to the dispatch table must be
    # dispatched by the wheel job without either file being edited by hand, and
    # a verb dropped from the loop fails here instead of passing silently.
    match = re.search(r"for tool in ([^;\n]+); do", body)
    assert match, "the wheel job has no `for tool in ...; do` dispatch loop"
    looped = set(match.group(1).split())
    assert looped == set(cli.TOOLS), (
        "the wheel job's dispatch loop is not the set of subcommands the console "
        f"names: loop has {sorted(looped - set(cli.TOOLS))}, "
        f"missing {sorted(set(cli.TOOLS) - looped)}"
    )
    # The loop must actually dispatch its variable, not merely name eight verbs.
    assert 'noni "$tool" --help' in body, (
        "the wheel job's loop does not dispatch the loop variable of the "
        "installed command"
    )


def test_ci_names_the_editable_install():
    """The in-place suite installs the package, so the wrappers import it.

    Each skills/*/scripts/ entry point is a thin wrapper over the package, so
    without an installed (or PYTHONPATH-visible) noni the whole suite would fail
    on an import rather than on a product fault. CONTRIBUTING.md documents the
    same line as the local route.
    """
    lines = _ci_install_lines()
    assert any('-e ".[dev]"' in line or "-e '.[dev]'" in line for line in lines), (
        f"CI never installs the package itself, only the tools: {lines}"
    )
    contributing = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert '-e ".[dev]"' in contributing, (
        "CONTRIBUTING.md does not document the editable install CI runs"
    )


def test_contributing_keeps_the_developer_install_after_the_page_set_sweep():
    """The page-set sweep left the contributor's install on the page that runs the gate.

    The sweep that moved every *reader's* install onto the quickstart's uv and
    clean-venv forms (issue #75) deliberately stopped at this page: a contributor
    needs an editable install with the pinned dev extra, so the suite, the lint and
    the coverage gate all run against one pinned tool set, and a reader following
    ``uv tool install`` gets neither the extras nor an editable tree. CONTRIBUTING.md
    is the only page that prints the line CI prints, so this is the check that keeps
    the local half and the CI half of one gate from drifting apart -- which is the
    same claim the pin equality above makes about the tool versions, made about the
    install itself.

    The three assertions are the sentence, the command and the CI match, in that
    order: a page that deleted its Development section would fail on the first, and
    one that kept the prose and lost the command would fail on the second.
    """
    contributing = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
    # The reader's install belongs to the quickstart and the README points there; a
    # contributor's route is a different install and this page owns it. Scoped to the
    # body of the section that carries the install: a cross-reference elsewhere on
    # the page ("the reader's steps are in docs/QUICKSTART.md") is a sentence worth
    # keeping, and it is not this page deferring the install.
    from docs_promises import CONTRIBUTING, section_body

    development = section_body(contributing, "Development")
    assert "docs/QUICKSTART.md" not in development, (
        f"{CONTRIBUTING.name}'s Development section now defers its install to the "
        "quickstart, which is the reader's route: a contributor needs the editable "
        "install with the dev extra that the CI gate is built on")
    assert "python -m venv .venv" in development, (
        "CONTRIBUTING.md no longer makes the venv the gate's tools are installed into")
    assert '.venv/bin/pip install -e ".[dev]"' in development, (
        "CONTRIBUTING.md no longer documents the editable install the suite and the "
        "wrappers need")
    # The same line, from CI: the page and the workflow are one gate, read twice.
    line = next((entry for entry in _ci_install_lines() if '-e ".[dev]"' in entry), "")
    assert line, f"CI has no editable install to compare against: {_ci_install_lines()}"
    for token in ('-e ".[dev]"', ".venv/bin/pip", "install"):
        assert token in line, f"the CI editable install lost {token!r}: {line}"
        assert token in contributing, (
            f"CONTRIBUTING.md's install line does not carry {token!r}, which CI runs: "
            f"{line}")


def _scrub_step_run() -> str:
    """The one-line ``run:`` body of the public-repo hygiene scrub step.

    Read out of the workflow rather than quoted as a literal, so the shell below
    is the command CI runs and not a copy of it: a step that was deleted, or
    renamed away from the name the tests name, fails here instead of leaving an
    assertion about a step nobody runs.
    """
    body = CI_WORKFLOW.read_text(encoding="utf-8")
    runs = re.findall(r"- name: Public-repo hygiene scrub\n\s+run: (.+)", body)
    assert len(runs) == 1, (
        "the test job must carry exactly one `Public-repo hygiene scrub` step "
        f"with a one-line run:, found {len(runs)}: {runs}"
    )
    command = runs[0].strip()
    assert command.startswith(".venv/bin/python scripts/public_safety.py"), (
        f"the scrub step does not run the gate AGENTS.md names, under the venv "
        f"interpreter the suite runs on: {command!r}"
    )
    return command


def _scrub_shell(run: str) -> str:
    """The shell left after the gate command is taken out of the step's run.

    The exit-code policy is the half of the step a test can actually run (see
    :func:`test_ci_scrub_step_accepts_only_exit_0_and_2`), so it is split from
    the command it governs rather than re-typed here. ``true`` stands in for the
    gate itself, so the ``||`` clause is still a syntactically complete command.
    """
    gate = ".venv/bin/python scripts/public_safety.py"
    assert gate in run, f"the scrub step does not run the gate: {run!r}"
    return run.replace(gate, "true", 1).strip()


def test_ci_runs_the_public_safety_scrub_after_the_editable_install():
    """CI runs the scrub AGENTS.md names, after the package is importable.

    Two halves, both of which a silent gap could take: the step exists in the
    *test* job (the wheel job's green says nothing about the gate), and it sits
    after the editable install, because ``scripts/public_safety.py`` imports
    ``noni.public_safety`` and exits 3 with an import failure before it has
    scanned a single tracked file -- a step ordered ahead of the install would
    report a code the step does not accept, for the wrong reason.
    """
    body = CI_WORKFLOW.read_text(encoding="utf-8")
    # The workflow is one file, so the position test is done on the test job's
    # own span: everything up to the wheel job, which is the only other job.
    wheel_at = body.index("\n  wheel:")
    test_job = body[:wheel_at]
    assert re.search(r"- name: Public-repo hygiene scrub\b", test_job), (
        "the test job never runs scripts/public_safety.py: AGENTS.md names it as "
        "a gate and no job ran it"
    )
    installed_at = test_job.index('-e ".[dev]"')
    assert test_job.index("Public-repo hygiene scrub") > installed_at, (
        "the scrub step runs before the editable install, so the package the "
        "scrub imports is not importable yet"
    )


def test_ci_scrub_step_accepts_only_exit_0_and_2():
    """The step's own shell passes on 0 and on 2, and on nothing else.

    The step is executed, not pattern-matched: the gate command is replaced by a
    stub that exits with each code in turn and the ``bash -c`` verdict is the
    assertion. Exit 2 is the state of a public runner (the deny-list is
    gitignored, so the class is absent and the gate refuses to report clean);
    the number is :data:`tests.quickstart_gate.GATE_DENYLIST_INACTIVE_EXIT`,
    imported rather than written again here. Exit 1 is a violation, exit
    :data:`tests.quickstart_gate.GATE_COULD_NOT_RUN_EXIT` is the gate failing to
    run at all (an unimportable package, so nothing was scanned), and exit 4 is
    an arbitrary other failure: all three must redden the job. A step written
    ``... || true``, or one that accepted 3 alongside 2, would keep the tree's
    hygiene unenforced while CI stayed green -- which is the whole reason 3 is a
    code of its own rather than a second use of 2.
    """
    import subprocess

    from quickstart_gate import GATE_COULD_NOT_RUN_EXIT, GATE_DENYLIST_INACTIVE_EXIT

    assert GATE_DENYLIST_INACTIVE_EXIT == 2, (
        f"the CI step below hard-codes the exit the docs pin as {GATE_DENYLIST_INACTIVE_EXIT}"
    )
    assert GATE_COULD_NOT_RUN_EXIT == 3, (
        f"the CI step below must fail on the gate's could-not-run exit, which is "
        f"pinned as {GATE_COULD_NOT_RUN_EXIT}"
    )
    shell = _scrub_shell(_scrub_step_run())
    assert shell == 'true || [ "$?" -eq 2 ]', (
        f"the scrub step's exit-code policy is not the one-line form the tests "
        f"below exercise: {shell!r}"
    )
    # The gate's own exit is planted where the command stood, so the verdict
    # below is the step's policy and nobody else's.
    for code, expected_pass in ((0, True), (GATE_DENYLIST_INACTIVE_EXIT, True),
                                (1, False), (GATE_COULD_NOT_RUN_EXIT, False),
                                (4, False)):
        planted = shell.replace("true ||", f"(exit {code}) ||", 1)
        proc = subprocess.run(["bash", "-c", planted],
                              capture_output=True, text=True, timeout=60)
        assert (proc.returncode == 0) is expected_pass, (
            f"the CI scrub step's shell {shell!r} "
            f"{'passed' if proc.returncode == 0 else 'failed'} on exit {code}; "
            f"expected {'pass' if expected_pass else 'fail'}"
        )


def test_ci_runs_ruff_and_the_coverage_gate():
    """CI runs the documented gate: lint, then run/combine/report."""
    body = CI_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"ruff\s+check\s+\.", body), "CI does not run `ruff check .`"
    for step in ("coverage run", "coverage combine", "coverage report"):
        assert step in body, f"CI is missing the coverage step {step!r}"


def test_pyproject_declares_the_package_and_the_console_command():
    """The wheel has exactly one thing to ship and one command to install.

    The old config named ``packages = []`` because the repo was a flat tree of
    scripts; the package replaces it, and the one console command is what makes
    'one install and one command' true.
    """
    data = _pyproject()
    # The distribution is named apart from the import package and the command:
    # the short name was already taken on the index, so the wheel a reader
    # installs and the `noni` they type are deliberately spelled differently.
    assert data["project"]["name"] == "noni-noni", (
        f"[project] name is not the distribution the project reserves: "
        f"{data['project'].get('name')!r}"
    )
    assert data["project"]["scripts"] == {"noni": "noni.cli:main"}, (
        f"[project.scripts] is not the one noni command: {data['project'].get('scripts')}"
    )
    setuptools = data["tool"]["setuptools"]
    assert setuptools.get("packages") != [], (
        "packages = [] is still configured: setuptools would ship no package at all"
    )
    assert setuptools["packages"]["find"]["where"] == ["src"], (
        f"the package is not found under src/: {setuptools['packages']}"
    )
