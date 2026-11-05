"""Shared assertions for the census refusals that must print no verdict.

A census that refused to apply a schema has read nothing, so it has no standing
to report a clean tree: neither stream may carry a warn verdict or a report row.
These two assertions are needed by more than one test module, and the file-size
cap (AGENTS.md, Source file size) keeps each module the size one responsibility
is worth. A helper module: never named ``test_*``.
"""

from __future__ import annotations

import subprocess


def assert_no_report_and_no_warn_row(proc: subprocess.CompletedProcess[str],
                                     why: str) -> None:
    """A census that refused to apply a schema printed no report and no warn row.

    ``why`` names the refusal under test, so the failure text says which probe
    let a verdict escape rather than leaving the reader to guess.
    """
    assert "42:" not in proc.stdout + proc.stderr, (
        f"a warn verdict escaped a refused census ({why}): "
        f"{proc.stdout}{proc.stderr}")
    assert proc.stdout.strip() == "", (
        f"a census that could not apply a schema printed a report ({why}): "
        f"{proc.stdout}")
