"""Scripted allocator drivers shared by the two register refusal suites.

register mints its own session id, so the only way to hand the writer a name of the
test's choosing is to fix what the allocator produces: ``--file`` cannot be steered
there because register's own token guard refuses a path it did not allocate. The
drivers here run ``register.main()`` in a child with ``register._make_session_id``
replaced, which is also how the register suites reach the idempotency branches.
register.py itself is never modified and nothing is created inside the shipped
skills/ tree.

Three shapes, because the questions differ. An allocation pinned to one id cannot
tell a re-mint from a run that gave up; an allocator that hands back a taken name
once and a fresh name after cannot tell a re-mint from a retry that never looked at
the filesystem; and an allocator that always answers the same taken name is the only
way to reach the bound. Every variant counts its own calls and prints ``MAINTS=<n>``,
because the number of mints is the observable that separates those cases from each
other -- a guard that never asked the filesystem and a guard that retried past a free
name both look like an ordinary successful run from their stdout alone.

The child is launched by the caller under ``sys.executable`` with the harness env
(which pins ``PYTHONPATH`` to this tree's ``src/`` so the venv's editable install of
another checkout cannot answer ``from noni import register``), which is also what
keeps it inside the coverage measurement.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _harness import _git_env_with_identity, subprocess_env
from harness_paths import SRC

# The allocation every collision case pins, and the victim's own bytes quoted in
# full: "byte-identical" has to mean these bytes and not merely "a file is still
# there". The claim row is the point of quoting the whole file -- the body a
# registration writes always ends in an empty '- claims:' section, so the erasure
# issue #103 reproduced dropped that row, moved the started stamp and renamed the
# identity, and only a whole-file comparison says otherwise.
VICTIM_SID = "2026-01-01-dead07"
VICTIM_BODY = (f"# session {VICTIM_SID}\n\n"
               "- identity: someone-else\n"
               "- host/worktree: host-a (repo-a)\n"
               "- started: 2026-01-01T00:00:00Z\n"
               "- status: active\n"
               "- claims:\n"
               "  - claim: #42\n")


def scripted_allocation_driver(tmp_path: Path, name: str, script: str) -> Path:
    """A driver that runs ``register.main()`` with the ``script``ed allocator.

    ``script`` defines ``_calls`` (a one-element counter) and ``_scripted`` (the
    function the driver installs as ``register._make_session_id``); the driver prints
    the counter as ``MAINTS=<n>`` after main() returns, so a test reads the number of
    mints off stdout. ``name`` keeps one test's driver directory from landing inside
    another's.
    """
    driver_dir = tmp_path / f"_scripted_driver_{name}"
    driver_dir.mkdir(exist_ok=True)
    driver = driver_dir / "drive_register.py"
    driver.write_text(
        "import os\n"
        "import sys\n"
        f"sys.path.insert(0, {str(SRC)!r})\n"
        "from noni import register\n"
        f"{script}\n"
        "register._make_session_id = _scripted\n"
        "rc = register.main(sys.argv[1:])\n"
        "print('MAINTS=' + str(_calls[0]))\n"
        "raise SystemExit(rc)\n",
        encoding="utf-8",
    )
    return driver


def counting_allocation_driver(tmp_path: Path) -> Path:
    """A driver whose allocator counts calls and always returns a real mint.

    The one way to see a second mint on the ordinary route: the real allocator
    returns a fresh id every call, so two calls look like one id that happens to
    differ from another run's and every assertion on a single artefact still passes.
    """
    return scripted_allocation_driver(
        tmp_path, "counted",
        "_calls = [0]\n"
        "_real = register._make_session_id\n"
        "def _scripted():\n"
        "    _calls[0] += 1\n"
        "    return _real()\n")


def taken_then_free_driver(tmp_path: Path) -> Path:
    """A driver whose first mint is ``NONI_TEST_SESSION_ID`` and every later one a real mint.

    The shape a real collision leaves: the name this run's first allocation produced
    is already spoken, so the run must ask for another and use it.
    """
    return scripted_allocation_driver(
        tmp_path, "remint",
        "_calls = [0]\n"
        "_taken = os.environ['NONI_TEST_SESSION_ID']\n"
        "_real = register._make_session_id\n"
        "def _scripted():\n"
        "    _calls[0] += 1\n"
        "    return _taken if _calls[0] == 1 else _real()\n")


def always_taken_driver(tmp_path: Path) -> Path:
    """A driver that answers every mint with ``NONI_TEST_SESSION_ID``, and counts them.

    The only way to reach the retry bound: a real allocator returns a fresh name each
    call, so the pathological state -- every name this run can produce is held --
    cannot be built from the command line. The count is the number of tries, which is
    exactly what the bound decides.
    """
    return scripted_allocation_driver(
        tmp_path, "always_taken",
        "_calls = [0]\n"
        "_taken = os.environ['NONI_TEST_SESSION_ID']\n"
        "def _scripted():\n"
        "    _calls[0] += 1\n"
        "    return _taken\n")


def run_scripted(driver: Path, repo: Path, session_id: str, *extra: str,
                 identity: bool = True, env: dict | None = None
                 ) -> subprocess.CompletedProcess[str]:
    """One register run through a scripted driver, at ``repo``, argv spelled out.

    The harness env goes on every launch (it pins ``PYTHONPATH`` to this tree, which
    is what stops the venv's editable install of another checkout from answering the
    driver's ``from noni import register``). ``identity`` applies the same committer
    pin the harness's own ``run_register`` uses, so a run that reaches a registration
    can make its commit; a caller measuring a refusal that must not commit passes
    ``identity=False`` and its own ``env``.
    """
    full = subprocess_env()
    if env is not None:
        full.update(env)
    if identity:
        full.update(_git_env_with_identity())
    full["NONI_TEST_SESSION_ID"] = session_id
    return subprocess.run([sys.executable, str(driver), "--repo", str(repo),
                           "--identity", "developer", *extra],
                          capture_output=True, text=True,
                          env=full, timeout=120)


def mints(proc: subprocess.CompletedProcess) -> int:
    """The scripted driver's mint count, from its own ``MAINTS=`` line."""
    tail = proc.stdout.strip().splitlines()[-1]
    assert tail.startswith("MAINTS="), proc.stdout
    return int(tail.split("=", 1)[1])
