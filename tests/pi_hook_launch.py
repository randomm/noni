"""Launching the pi hook under node for tests/test_pi_extension.py.

The hook under ``integrations/pi/`` is a ``.ts`` file and the project runs no
node toolchain in CI, so the behavioural half of that suite is optional by
construction: :func:`node_available` reports whether the run can happen at all
and the caller skips when it cannot. :func:`run_hook` writes the driver in
``pi_hook_driver.py`` to a scratch file, launches it under node's own type
stripping with a fake ExtensionAPI, and returns the per-scenario JSON records the
driver printed. The driver asserts nothing; every gate is a Python assertion in
the suite that reads these records.

Two things the launcher owns that a caller cannot see:

``NONI_STATE_ROOT`` is dropped from the child's environment. The copy returned
by ``subprocess_env()`` is the one place to drop it: ``os.environ`` is shared
with the whole suite and tests/test_brief_now.py sets that variable, so a value
inherited from the calling shell would decide which arm of the hook's state-root
resolver the driver exercises.

``NODE_PATH`` gains the global module root. The hook's
``import type { ExtensionAPI }`` line is erased by type stripping, but a node
that keeps the specifier would not find the package from a scratch directory.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from _harness import subprocess_env
from pi_hook_driver import driver_source

# The environment names the driver reads for its two scratch layouts, and the
# global module root NODE_PATH gains. Both are facts about this host, looked up
# rather than assumed: the launcher still runs where node is absent.
_GLOBAL_MODULE_ROOT = Path("/usr/lib/node_modules")
_DRIVER_NAME = "driver.mjs"


def node_available() -> bool:
    """Whether a node binary exists to drive the hook with."""
    return shutil.which("node") is not None


def run_hook(tmp_path: Path, extension: Path) -> dict[str, dict]:
    """Drive the hook at ``extension`` in ``tmp_path``; return scenarios by name.

    ``tmp_path`` gains the two layouts the driver names: ``project/`` holds a
    ``noni/`` directory, so the resolver's candidate arm fires, and ``bare/``
    holds none, which is the arm with no state root at all. A nonzero exit or any
    stderr is a failure of the run itself, reported with both streams: the driver
    prints only its records, so anything else it wrote is the diagnosis.
    """
    state = tmp_path / "project"
    (state / "noni").mkdir(parents=True)
    bare = tmp_path / "bare"
    bare.mkdir()
    driver = tmp_path / _DRIVER_NAME
    driver.write_text(driver_source(str(extension.resolve())), encoding="utf-8")
    env = subprocess_env()
    env.pop("NONI_STATE_ROOT", None)
    env["STATE"] = str(state)
    env["NO_STATE"] = str(bare)
    if _GLOBAL_MODULE_ROOT.is_dir():
        env["NODE_PATH"] = (str(_GLOBAL_MODULE_ROOT) + os.pathsep
                            + env.get("NODE_PATH", "").rstrip(os.pathsep))
    proc = subprocess.run(
        ["node", "--experimental-strip-types", str(driver)],
        capture_output=True, text=True, timeout=120, env=env, cwd=str(tmp_path),
    )
    assert proc.returncode == 0, (
        f"node failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
    assert not proc.stderr.strip(), f"node reported on stderr:\n{proc.stderr}"
    return _records(proc.stdout)


def _records(stdout: str) -> dict[str, dict]:
    """Index the driver's JSON lines by scenario, refusing a scenario that raised.

    A scenario that throws is reported by the driver as an ``error`` field rather
    than dying, so that it is visible: here it becomes a failure naming each one,
    because a missing record would otherwise read as a key the caller forgot to
    assert on.
    """
    out: dict[str, dict] = {}
    for line in stdout.splitlines():
        if line.strip():
            record = json.loads(line)
            out[record["scenario"]] = record
    raised = [(name, record["error"]) for name, record in out.items() if "error" in record]
    assert not raised, f"the driver raised: {raised}"
    return out
