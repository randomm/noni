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

The fixtures and the byte-comparison come from ``console_route_support``, the module
the other half of this pair shares them from.
"""

from __future__ import annotations

import subprocess
import sys

from _harness import run_module, run_noni, subprocess_env
from console_route_support import assert_same
from decide_fixtures import ANSWERED, BASE, NEW_DATE, OPTIONS, QUESTION
from test_decide_state_root import _committed_code_repo


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


def test_the_module_route_carries_the_writers_state_root_refusal_unchanged(tmp_path):
    """The dispatch forwards a writer's own refusal without restating it.

    ``decide`` refuses a ``--repo`` that holds no ``noni/`` at 3 (issue #162), and the
    two routes the command owns must print that run's bytes: a dispatcher that mapped
    the writer's code to its own usage code, or printed the label of the dispatch
    module, would keep every help comparison here green. Compared against each other and
    asserted to carry the refusal, not only to match.
    """
    repo = _committed_code_repo(tmp_path, "equivalence")
    argv = ("decide", "--repo", str(repo), "--slug", "probe", "--date", NEW_DATE,
            *BASE, *QUESTION, *OPTIONS, *ANSWERED)
    assert_same(run_noni(*argv), run_module(*argv), "decide state-root refusal")
    refusal = run_module(*argv)
    assert refusal.returncode == 3, f"{refusal.returncode}: {refusal.stderr}"
    assert "is not a noni state root" in refusal.stderr, refusal.stderr
    assert "--init" in refusal.stderr, refusal.stderr


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
