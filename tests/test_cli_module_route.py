"""``python -m noni <subcommand>`` runs the same CLI as the console script.

The only entry point this package shipped was the console script declared in
``pyproject.toml`` (``noni = "noni.cli:main"``), so the route docs/QUICKSTART.md
tells a reader to build when they would rather not install anything --
``PYTHONPATH=<clone>/src``, no script on ``PATH`` -- had no runnable command:
``python3 -m noni census --help`` died with ``No module named noni.__main__``
(issue #98). ``src/noni/__main__.py`` is what makes it runnable, and this module
is what keeps it honest.

Two things are asserted, and neither is the help text:

- **The route dispatches.** A ``__main__.py`` that imported the package and did
  nothing, or dispatched to one tool only, would still let ``import noni`` work
  and still print something, so each run here is checked against the code the
  console route returns for the same argv.
- **The byte-for-byte pair against the console route** lives in
  ``tests/test_console_equivalence.py``, which owns route equivalence and already
  compares all three routes for one ``--help`` and one refusal per affected tool.
  This file covers what is specific to the module route: that it exists, that it
  reaches every subcommand, and that the two routes' streams are identical.
"""

from __future__ import annotations

import sys

from _harness import CENSUS, INTENT, ORDER, REPO, run_module, run_noni, run_wrapper

# One representative argv per shipped subcommand, each a run whose output needs no
# state: the tool prints its own usage and exits 0, which is the shape a reader
# reaches for first and the one that must not differ between routes.
_HELP_ARGVS: tuple[tuple[str, ...], ...] = (
    ("census", "--repo", str(REPO)),
    ("order", "--repo", str(REPO)),
    ("intent", "--repo", str(REPO)),
)


def _assert_streams_match(module_argv: tuple[str, ...], label: str) -> None:
    """``python -m noni ...`` and ``python -m noni.cli ...``: same three answers.

    The comparison is on stdout, stderr and exit code rather than on "both
    succeeded", because the module route is a second dispatcher: a ``__main__.py``
    that dropped an argument, swallowed the tool's exit code, or printed the
    program name of its own file would keep both runs green under a success-only
    assertion.
    """
    via_module = run_module(*module_argv)
    via_console = run_noni(*module_argv)
    assert "Traceback (most recent call last)" not in via_module.stderr, (
        f"{label}: the module route crashed\n{via_module.stderr}")
    assert via_module.returncode == via_console.returncode, (
        f"{label}: exit codes differ ({via_module.returncode} vs "
        f"{via_console.returncode})\nmodule stderr: {via_module.stderr!r}")
    assert via_module.stdout == via_console.stdout, (
        f"{label}: stdout differs\nmodule: {via_module.stdout!r}\n"
        f"console: {via_console.stdout!r}")
    assert via_module.stderr == via_console.stderr, (
        f"{label}: stderr differs\nmodule: {via_module.stderr!r}\n"
        f"console: {via_console.stderr!r}")


def test_the_package_is_runnable_as_a_module():
    """``python -m noni`` resolves: the route the pilot's third complaint names.

    Asserted on output rather than on exit code alone: ``python -m noni`` exits 2
    with no subcommand by design (it prints its own help), so only a line the
    dispatch produced says the module ran.
    """
    proc = run_module("census", "--list")
    assert proc.returncode == 0, proc.stderr
    assert "ledger-record" in proc.stdout.splitlines(), proc.stdout


def test_the_module_route_prints_the_command_help_and_exits_zero():
    """``python -m noni --help`` is the console command's own help, at exit 0."""
    proc = run_module("--help")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("usage: noni "), proc.stdout[:80]
    assert "Traceback" not in proc.stderr, proc.stderr


def test_the_module_route_dispatches_every_helping_subcommand():
    """One run per subcommand that answers ``--help`` without needing state."""
    for argv in _HELP_ARGVS:
        _assert_streams_match(argv, " ".join(argv))


def test_the_module_route_refusals_match_the_console_route(tmp_path):
    """A refusal is compared too, since the label on stderr is the point.

    The program name a writer prints comes from ``noni.labels``, not from the file
    that was invoked: a route that let ``__main__.py`` reach the label would print
    a name no document mentions and still exit 2, so the comparison is on the
    bytes and not on the code. The label is located rather than assumed to be the
    first line, which is argparse's usage line here.
    """
    for tool, label in (("order", "order.py:"), ("intent", "intent.py:")):
        argv = (tool, "--repo", str(tmp_path), "--not-a-flag")
        _assert_streams_match(argv, f"{tool} unknown flag")
        module = run_module(*argv)
        assert module.returncode == 2, module.returncode
        named = [line for line in module.stderr.splitlines() if line.startswith(label)]
        assert named, f"{tool}: no {label} line in {module.stderr!r}"


def test_the_module_route_and_the_wrapper_agree_on_help_for_each_tool():
    """The wrapper and the module route are the two ends of the same contract.

    ``run_wrapper`` is the in-place form the skills document and ``run_module`` is
    the PYTHONPATH form the quickstart documents; the console script sits between
    them. Comparing the two ends directly is what pins the promise that one command
    name prints one set of bytes whichever way it was reached.
    """
    for script, tool in ((CENSUS, "census"), (ORDER, "order"), (INTENT, "intent")):
        wrapper = run_wrapper(script, "--help")
        module = run_module(tool, "--help")
        assert wrapper.returncode == module.returncode == 0, (
            f"{tool}: {wrapper.returncode} vs {module.returncode}\n"
            f"{wrapper.stderr}\n{module.stderr}")
        assert wrapper.stdout == module.stdout, (
            f"{tool}: wrapper {wrapper.stdout!r}\nmodule {module.stdout!r}")
        assert wrapper.stderr == module.stderr, (
            f"{tool}: wrapper {wrapper.stderr!r}\nmodule {module.stderr!r}")


def test_the_module_route_carries_the_interpreters_own_exit_code():
    """The launcher forwards the tool's code instead of raising it as an exception.

    ``raise SystemExit(main(...))`` and ``sys.exit(main(...))`` are the two forms
    that do this; ``SystemExit(main())`` inside a bare call, or a ``main`` whose
    return value is dropped, would leave every run exiting 0 whatever the tool
    decided. Exit 2 for a refusal is the observable difference.
    """
    proc = run_module("order", "--repo", str(REPO))
    assert proc.returncode == 2, f"{proc.returncode}: {proc.stdout}{proc.stderr}"
    assert proc.stdout == "", proc.stdout


def test_the_module_route_runs_on_the_interpreter_the_suite_uses():
    """The route is exercised on the interpreter running these tests.

    The criterion is "every Python the project supports", which is the floor
    ``requires-python`` states plus every release since; a test cannot install the
    others, so what it can do is refuse to pass vacuously here: the run must have
    produced the dispatch's own bytes on the interpreter at hand.
    """
    proc = run_module("census", "--list")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines(), f"no rows on {sys.version.split()[0]}"
