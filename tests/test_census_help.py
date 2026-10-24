"""The --help output of the census entry points.

The census scripts generate their help from their own header comment (no
hard-coded sed line range), so the help text is stable as long as the header
keeps the documented usage string and the field-count line. These tests
assert on the exact strings the header must carry, so a header edit that
drops a line (or the sed-range drift the old code was vulnerable to) fails
here rather than surfacing as a silently-truncated --help.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from _harness import REPO

CENSUS_SH = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"
CENSUS_SESSIONS_SH = REPO / "skills" / "sessions-claims" / "scripts" / "census-sessions.sh"
FIXTURES = REPO / "tests" / "fixtures" / "census-sh"


def _run_help(script: Path) -> str:
    proc = subprocess.run(
        ["bash", str(script), "--help"],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, f"{script.name} --help: exit {proc.returncode}\n{proc.stderr}"
    return proc.stdout


def test_census_sh_help_matches_header_fixture():
    """census.sh --help carries the documented usage lines and the field
    count (generated from the header, not a hard-coded line range)."""
    out = _run_help(CENSUS_SH)
    for line in (FIXTURES / "usage.txt").read_text().splitlines():
        assert line in out, f"census.sh --help missing {line!r}:\n{out}"


def test_census_sessions_sh_help_matches_header_fixture():
    """census-sessions.sh --help carries the documented usage line."""
    out = _run_help(CENSUS_SESSIONS_SH)
    for line in (FIXTURES / "sessions-usage.txt").read_text().splitlines():
        assert line in out, f"census-sessions.sh --help missing {line!r}:\n{out}"
