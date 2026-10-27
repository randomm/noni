"""Self-report ratchet for the unified census.

The no-self-reported-numbers rule: every metric in --json mode derives from
git history, file existence, or file byte size — never from a numeric value
written inside an agent-authored field (a session file's `started` timestamp,
a ledger record's `date`, or any other number in the file body).

This test scans the census source for any code path that reads a numeric
value from a file's body and uses it as a metric value. The mechanical
check is: no line in the source calls `.read_text()` / `.read_bytes()` on a
session or ledger file AND extracts a number from the result for use in a
finding row's `value` or `counts` field.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"

# Patterns that indicate reading a numeric value from file content.
# The census is allowed to:
#   - read file bytes for sha1 comparison (integrity check, not a metric)
#   - read file content for schema validation (structural, not a metric)
#   - count records/claims (count of lines or fields, not a value in the file)
# The census is NOT allowed to:
#   - extract a number from a file field and use it as a metric value
#   - read a `started` or `date` field and use the numeric value as a metric

# A metric value in a finding row is the `code` field (from the exit table)
# or the `counts` in the summary (from the findings list). Neither should
# come from a file body.

METRIC_SOURCE_PATTERNS = [
    # int(value) where value comes from a file read
    (re.compile(r"\bint\s*\(\s*fields\s*\["), "int() on a fields dict value"),
    (re.compile(r"\bfloat\s*\(\s*fields\s*\["), "float() on a fields dict value"),
    # Direct use of a date/started field as a number
    (re.compile(r"fields\s*\[\s*['\"](started|date)['\"]\s*\]\s*\)"), "date/started field used as number"),
]


def test_no_metric_reads_agent_authored_number():
    """No code path in census.py extracts a numeric value from a file body
    and uses it as a metric value."""
    source = CENSUS.read_text(encoding="utf-8")
    violations = []
    for lineno, line in enumerate(source.splitlines(), 1):
        for pattern, label in METRIC_SOURCE_PATTERNS:
            if pattern.search(line):
                violations.append(f"{lineno}: {label} — {line.strip()}")
    assert not violations, (
        "census.py extracts a numeric value from an agent-authored file field:\n"
        + "\n".join(violations)
    )


def test_every_finding_artifact_is_a_path_not_a_number(tmp_path):
    """In --json mode, every finding's artifact field is a file path string,
    never a number (which would indicate a self-reported value)."""
    import io
    import json
    from contextlib import redirect_stdout

    import census

    repo = tmp_path / "repo"
    (repo / "noni" / "sessions").mkdir(parents=True)
    (repo / "noni/sessions/2026-10-01-aaaaaa.md").write_text(
        "- identity: dev\n- host/worktree: ws\n- started: 2026-10-01T10:00:00Z\n"
        "- status: active\n- claims:\n  - claim: #42\n"
    )
    (repo / "noni/sessions/2026-10-01-bbbbbb.md").write_text(
        "- identity: rev\n- host/worktree: ws\n- started: 2026-10-01T11:00:00Z\n"
        "- status: active\n- claims:\n  - claim: #42\n"
    )

    out = io.StringIO()
    with redirect_stdout(out):
        census.main(["--repo", str(repo), "--json", "--now", "2026-10-02T00:00:00Z"])

    for line in out.getvalue().strip().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("kind") == "finding":
            assert isinstance(row["artifact"], str), f"artifact is not a string: {row['artifact']!r}"
            assert row["artifact"], f"artifact is empty: {row}"
            # A path has at least one / or . in it; a bare number does not
            assert not row["artifact"].lstrip("-").isdigit(), (
                f"artifact looks like a number (self-reported?): {row['artifact']!r}"
            )
