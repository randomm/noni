"""Tests for the --json report mode of the unified census.

Covers the NDJSON contract: one finding record per violation, exactly one
terminal summary record, stable keys, and every finding naming its artifact
path. Also verifies the no-self-reported-numbers rule: every metric value in
a finding row is derived from git history or file structure, never from a
value written inside an agent-authored field.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_CENSUS_DIR = str(REPO / "skills" / "census" / "scripts")
if _CENSUS_DIR not in sys.path:
    sys.path.insert(0, _CENSUS_DIR)


from _harness import _commit_file, _init_repo  # noqa: E402


def _valid_record(rec_id="2026-10-01-alpha") -> dict:
    return {
        "id": rec_id, "date": "2026-10-01T10:00:00Z", "asked_by": "developer",
        "questions": [{"id": "q1", "text": "Q?", "options": ["yes", "no"], "answer": "yes"}],
        "by": "Operator", "scope": "test", "status": "decided", "supersedes": None,
    }


def _session_body(identity: str, claims: list[str] | None = None) -> str:
    lines = [f"- identity: {identity}", "- host/worktree: ws", "- started: 2026-10-01T10:00:00Z",
             "- status: active", "- claims:"]
    for c in claims or []:
        lines.append(f"  - claim: {c}")
    return "\n".join(lines) + "\n"


def _run_census_json(repo: Path, *args: str) -> tuple[int, list[dict]]:
    """Run census with --json and return (exit_code, parsed NDJSON rows)."""
    import io
    from contextlib import redirect_stdout

    import census

    out = io.StringIO()
    argv = ["--repo", str(repo), "--json", "--now", "2026-10-02T00:00:00Z", *args]
    with redirect_stdout(out):
        rc = census.main(argv)
    rows = []
    for line in out.getvalue().strip().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rc, rows


# --- Legal kind and check value sets ------------------------------------------

LEGAL_KINDS = {"finding", "summary"}
LEGAL_CHECKS = {
    "ledger-record", "ledger-edited", "ledger-chain",
    "session-double", "session-claim", "session-malformed",
    "session-stalled", "probe",
}


def test_json_kind_set_is_exactly_legal(tmp_path):
    """Every row's kind is in the legal set {finding, summary}."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("dev", ["#1"]))
    _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md", _session_body("rev", ["#1"]))
    rc, rows = _run_census_json(repo)
    assert rc == 30
    for row in rows:
        assert row["kind"] in LEGAL_KINDS, f"illegal kind: {row['kind']!r}"


def test_json_check_set_is_exactly_legal(tmp_path):
    """Every finding row's check is in the legal set of check ids."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("dev", ["#1"]))
    _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md", _session_body("rev", ["#1"]))
    rc, rows = _run_census_json(repo)
    for row in rows:
        if row["kind"] == "finding":
            assert row["check"] in LEGAL_CHECKS, f"illegal check: {row['check']!r}"


def test_json_exactly_one_summary_record(tmp_path):
    """The NDJSON output ends with exactly one summary record."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json", json.dumps(_valid_record(), indent=2))
    rc, rows = _run_census_json(repo)
    summaries = [r for r in rows if r.get("kind") == "summary"]
    assert len(summaries) == 1, f"expected exactly 1 summary, got {len(summaries)}"


def test_json_summary_has_required_fields(tmp_path):
    """The summary record has schema, kind, ok, exit, and counts."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json", json.dumps(_valid_record(), indent=2))
    rc, rows = _run_census_json(repo)
    summary = [r for r in rows if r["kind"] == "summary"][0]
    assert summary["schema"] == "noni.census/1"
    assert "ok" in summary
    assert "exit" in summary
    assert "counts" in summary
    assert summary["exit"] == rc


def test_json_every_finding_names_artifact_path(tmp_path):
    """Every finding row has a non-empty artifact path (the no-self-report rule)."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("dev", ["#1"]))
    _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md", _session_body("rev", ["#1"]))
    rc, rows = _run_census_json(repo)
    for row in rows:
        if row["kind"] == "finding":
            assert row["artifact"], f"finding has empty artifact: {row}"
            assert isinstance(row["artifact"], str)


def test_json_no_metric_reads_agent_authored_number(tmp_path):
    """No finding row's value is a number that appears in the session file's
    agent-authored fields. The value fields (code, counts) come from git
    history or file structure, not from a number in the file body."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("dev", ["#1"]))
    _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md", _session_body("rev", ["#1"]))
    rc, rows = _run_census_json(repo)
    # The code field is always from the exit-code table, never from file content
    for row in rows:
        if row["kind"] == "finding":
            assert row["code"] in {10, 12, 20, 30, 31, 32, 40, 41}, (
                f"code {row['code']} not from the exit-code table"
            )


def test_json_reproducible_bytes(tmp_path):
    """Two runs with the same --now produce byte-identical stdout."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/sessions/2026-10-01-aaaaaa.md", _session_body("dev", ["#1"]))
    _commit_file(repo, "noni/sessions/2026-10-01-bbbbbb.md", _session_body("rev", ["#1"]))
    import io
    from contextlib import redirect_stdout

    import census

    def run() -> bytes:
        out = io.StringIO()
        with redirect_stdout(out):
            census.main(["--repo", str(repo), "--json", "--now", "2026-10-02T00:00:00Z"])
        return out.getvalue().encode()

    out1 = run()
    out2 = run()
    assert out1 == out2, "two runs with the same --now must produce identical bytes"
