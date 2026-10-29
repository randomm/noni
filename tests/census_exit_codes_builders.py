"""The module-private builders and runners of the census exit-code tests.

Held in a non-test module so the exit-code suite can sit in two files without
duplicating the shapes, and so pytest never collects the builders as tests of
their own. Verbatim from main's ``tests/test_census_exit_codes.py``, except that
the census import is main's own.
"""

from __future__ import annotations

import json
from pathlib import Path

import census
from _harness import _home_path_violation, _secret_violation

# Synthetic violation shapes, built by tests/_harness.py from public_safety's
# own pattern tables (see there for why they are not literals and why the
# construction is not copy-pasted into this file).
_HOME_PATH = _home_path_violation()
_SECRET = _secret_violation()


def _valid_record(rec_id="2026-10-01-alpha", status="decided", supersedes=None) -> dict:
    return {
        "id": rec_id, "date": "2026-10-01T10:00:00Z", "asked_by": "dev",
        "questions": [{"id": "q1", "text": "Q?", "options": ["yes", "no"], "answer": "yes"}],
        "by": "T", "scope": "s", "status": status, "supersedes": supersedes,
    }




def _session_body(identity: str, claims: list[str] | None = None) -> str:
    lines = [f"- identity: {identity}", "- host/worktree: ws",
             "- started: 2026-10-01T10:00:00Z", "- status: active", "- claims:"]
    for c in claims or []:
        lines.append(f"  - claim: {c}")
    return "\n".join(lines) + "\n"



def _run(repo: Path, *args: str) -> int:
    import io
    from contextlib import redirect_stderr, redirect_stdout
    out, err = io.StringIO(), io.StringIO()
    argv = ["--repo", str(repo), "--now", "2026-10-02T00:00:00Z", *args]
    with redirect_stdout(out), redirect_stderr(err):
        return census.main(argv)



def _rows(repo: Path, *args: str) -> list[dict]:
    """The finding rows of a --json run (the exit code is asserted separately)."""
    import io
    from contextlib import redirect_stderr, redirect_stdout
    out, err = io.StringIO(), io.StringIO()
    argv = ["--repo", str(repo), "--now", "2026-10-02T00:00:00Z", "--json", *args]
    with redirect_stdout(out), redirect_stderr(err):
        census.main(argv)
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
