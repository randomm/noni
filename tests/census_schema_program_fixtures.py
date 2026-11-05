"""The fixture seam for a census.sh run whose schema program cannot be read.

``tests/test_census_ledger_empty.py`` holds the schema-program refusals, and the
file-size cap (AGENTS.md, Source file size) keeps that module the size one
responsibility is worth: the two runners these cases share live here, as they do
for the other census helpers. A helper module: never named ``test_*``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from _harness import REPO, subprocess_env

CENSUS_SH = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"


def copy_shim_to(scripts: Path) -> Path:
    """A plain copy of the shipped shim in ``scripts``, without its schema program.

    ``SCRIPT_DIR`` is the directory the shim was started from, so a refusal of a
    sibling the test controls requires a copy: the shipped ``scripts/`` dir can
    never hold an absent or unreadable ``census-schema.jq``.
    """
    scripts.mkdir()
    shim = scripts / "census.sh"
    shim.write_text(CENSUS_SH.read_text(encoding="utf-8"), encoding="utf-8")
    return shim


def run_copied_shim(scripts: Path, ledger: Path) -> subprocess.CompletedProcess[str]:
    """The copied ``scripts/census.sh`` over ``ledger``, in a clean environment."""
    return subprocess.run(["bash", str(scripts / "census.sh"), str(ledger)],
                          capture_output=True, text=True,
                          env=subprocess_env(), timeout=120)
