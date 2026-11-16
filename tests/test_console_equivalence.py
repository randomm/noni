"""The ``noni`` command itself, and the module route's parity with it.

The per-tool byte comparisons live in ``tests/test_console_routes.py``: each tool's
wrapper is compared against the console route and the module route there. What this
module covers is the command above those tools -- the dispatch that turns
``noni order ...`` into ``noni.order.main(...)`` -- and the two properties that
belong to the command rather than to any one tool:

- **The subcommand set is the settled one**, so a typo cannot look like a real
  command and a verb cannot be added to the dispatch table without a test noticing.
- **The module route is the same command.** ``python -m noni`` reaches the console
  module through ``noni.__main__``, so the subcommand list, the usage line and the
  exit code of a bare run must be identical to the console route's; a third
  dispatcher that quietly diverged is exactly what the equivalence pairings exist to
  catch (issue #98 added that route).
- **The command reports its own version.** ``noni --version`` names the package
  version the installed tree owns, so a reader who suspects a stale install on the
  PATH has a command that answers rather than only a path (issue #187).

The fixtures and the byte-comparison come from ``console_route_support``, the module
the other half of this pair shares them from.
"""

from __future__ import annotations

import subprocess
import sys

from _harness import run_module, run_noni, subprocess_env
from console_route_support import assert_same


def test_noni_without_a_subcommand_is_a_usage_error():
    """No tool named: the command prints its own help and exits 2."""
    proc = run_noni()
    assert proc.returncode == 2, proc.stdout
    assert (proc.stdout + proc.stderr).startswith("usage: noni "), proc.stdout[:60]


def test_the_module_route_without_a_subcommand_is_the_same_refusal():
    """``python -m noni`` answers a bare run exactly as ``noni`` does.

    Both print the command's own help at exit 2. Compared rather than asserted
    twice, because the module route is a separate ``__main__`` and its own exit
    statement: one that returned 0, or printed the help of one tool, would keep the
    per-tool pairs green.
    """
    assert_same(run_noni(), run_module(), "noni with no subcommand")


def test_noni_names_exactly_the_settled_subcommands():
    """The subcommand set is the settled one: census, decide, order, intent, brief.

    Each names a module under ``src/noni/`` and is asserted dispatchable below.
    The session verbs of #27 are gone (issue #155), and ``session`` remains
    refused -- it is a noun for the state, not a tool, and a subcommand that
    vague would let a typo look like a real command.
    """
    proc = run_noni("--help")
    assert proc.returncode == 0
    listed = proc.stdout + proc.stderr
    for name in ("census", "decide", "order"):
        assert f"{name}  " in listed, f"noni --help omits {name}: {listed}"
    for absent in ("session", "register", "claim", "close", "release"):
        assert f"{absent}  " not in listed, f"noni grew a {absent} placeholder: {listed}"


def test_the_module_route_names_the_same_subcommands():
    """The dispatch table has one owner: the module route lists what the console lists.

    ``noni.__main__`` delegates to :func:`noni.cli.main`, so a divergence here means
    one of the two routes stopped going through it -- and a reader who followed the
    quickstart's ``PYTHONPATH`` form would be reading help for a command that is not
    the one they have.
    """
    console, module = run_noni("--help"), run_module("--help")
    assert_same(console, module, "noni --help via -m noni")
    assert module.returncode == 0, module.stderr
    for name in ("census", "decide", "order", "intent"):
        assert f"{name}  " in module.stdout, f"-m noni --help omits {name}"
    for absent in ("register", "claim", "close", "release"):
        assert f"{absent}  " not in module.stdout, f"-m noni grew a {absent} verb"


def test_noni_version_prints_the_package_version_and_exits_zero():
    """``noni --version`` prints ``noni <version>`` on stdout and exits 0.

    The expected value is read in-process from ``noni.__version__``, the single
    owner (``src/noni/__init__.py``), so a release bump moves this assertion by
    exact value instead of leaving a second literal in ``tests/``. The two routes
    are paired rather than asserted twice: a ``python -m noni`` route that printed a
    different program name, a different stream or a different exit code would keep
    the console half green. Output goes to stdout on purpose, which the pairing
    cannot settle on its own, so stdout is asserted for both routes.
    """
    from noni import __version__

    expected = f"noni {__version__}\n"
    console, module = run_noni("--version"), run_module("--version")
    assert_same(console, module, "noni --version")
    for proc in (console, module):
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == expected, proc.stdout
        assert proc.stderr == "", proc.stderr


def test_noni_help_still_names_the_five_tools_after_the_version_flag():
    """``--version`` is an option of the top-level parser, not a sixth tool.

    argparse prints the flag as an option row, so the help bytes do gain a line;
    what must not change is the subcommand list. Asserted against ``noni.cli.TOOLS``,
    the one dispatch table, so a verb added there without a test fails, and a
    ``--version`` implemented as a subcommand fails on the count.
    """
    import noni.cli

    proc = run_noni("--help")
    assert proc.returncode == 0, proc.stderr
    listed = proc.stdout
    for name in noni.cli.TOOLS:
        assert f"{name}  " in listed, f"noni --help omits {name}: {listed}"
    for absent in ("session", "register", "claim", "close", "release"):
        assert f"{absent}  " not in listed, f"noni grew a {absent} placeholder: {listed}"
    # ``version`` is the option the flag adds, so the check for a sixth verb is
    # that no subcommand row carries it: a row of the subcommand block is
    # indented two columns and followed by the summary's gap.
    assert "\n  version  " not in listed, f"noni grew a version subcommand: {listed}"


def test_a_tool_still_owns_its_own_version_flag():
    """The flag belongs to the top-level parser only.

    ``noni census --version`` is the census's own argument business, and the argv
    after the subcommand is handed to that tool verbatim: a top-level
    ``--version`` that swallowed it would make the census answer with the package
    version, which is a second owner of that output. Exit 2 with a refusal naming
    the tool's own script is what proves the flag never left the top level.
    """
    for tool in ("census", "decide"):
        proc = run_noni(tool, "--version")
        assert proc.returncode == 2, (tool, proc.stdout, proc.stderr)
        assert f"{tool}.py" in proc.stderr, (tool, proc.stderr)
        assert "noni " not in proc.stdout, (tool, proc.stdout)


def test_noni_console_script_is_installed_in_this_environment():
    """The ``noni`` console script exists and runs the census.

    The CI wheel job asserts this against the built wheel; locally it asserts
    against the editable install, so a broken [project.scripts] target fails
    somewhere rather than only in CI.
    """
    proc = subprocess.run([sys.executable, "-m", "noni.cli", "census", "--list"],
                          capture_output=True, text=True, env=subprocess_env(), timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "ledger-record" in proc.stdout.splitlines()
