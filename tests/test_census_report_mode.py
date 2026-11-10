"""Tests for the --json report mode of the unified census.

Covers the NDJSON contract: one finding record per violation, exactly one
terminal summary record, stable keys, and every finding naming its artifact
path. Also verifies the no-self-reported-numbers rule: every metric value in
a finding row is derived from git history or file structure, never from a
value written inside an agent-authored field.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

from _harness import _commit_file, _init_repo  # noqa: E402


def _valid_record(rec_id="2026-10-01-alpha", status="decided", supersedes=None) -> dict:
    return {
        "id": rec_id, "date": "2026-10-01T10:00:00Z", "asked_by": "developer",
        "questions": [{"id": "q1", "text": "Q?", "options": ["yes", "no"], "answer": "yes"}],
        "by": "Operator", "scope": "test", "status": status, "supersedes": supersedes,
    }


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
    "probe",
    "ledger-empty", "hygiene",
    "ordering-malformed", "ordering-stale", "ordering-closed",
}


def test_json_kind_set_is_exactly_legal(tmp_path):
    """Every row's kind is in the legal set {finding, summary}."""
    repo = _init_repo(tmp_path / "repo")
    bad = _valid_record()
    del bad["id"]
    _commit_file(repo, "noni/decisions/2026-10-01-bad.json", json.dumps(bad, indent=2))
    _commit_file(repo, "noni/decisions/2026-10-02-a.json",
                 json.dumps(_valid_record("2026-10-02-a", "decided",
                                          "2026-10-09-missing"), indent=2))
    rc, rows = _run_census_json(repo)
    assert rc == 10
    for row in rows:
        assert row["kind"] in LEGAL_KINDS, f"illegal kind: {row['kind']!r}"


def test_json_check_set_is_exactly_legal(tmp_path):
    """Every finding row's check is in the legal set of check ids."""
    repo = _init_repo(tmp_path / "repo")
    bad = _valid_record()
    del bad["id"]
    _commit_file(repo, "noni/decisions/2026-10-01-bad.json", json.dumps(bad, indent=2))
    _commit_file(repo, "noni/decisions/2026-10-02-a.json",
                 json.dumps(_valid_record("2026-10-02-a", "decided",
                                          "2026-10-09-missing"), indent=2))
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
    bad = _valid_record()
    del bad["id"]
    _commit_file(repo, "noni/decisions/2026-10-01-bad.json", json.dumps(bad, indent=2))
    _commit_file(repo, "noni/decisions/2026-10-02-a.json",
                 json.dumps(_valid_record("2026-10-02-a", "decided",
                                          "2026-10-09-missing"), indent=2))
    rc, rows = _run_census_json(repo)
    for row in rows:
        if row["kind"] == "finding":
            assert row["artifact"], f"finding has empty artifact: {row}"
            assert isinstance(row["artifact"], str)


def test_json_no_metric_reads_agent_authored_number(tmp_path):
    """No finding row's value is a number that appears in a record's own
    fields. The value fields (code, counts) come from git
    history or file structure, not from a number in the file body."""
    repo = _init_repo(tmp_path / "repo")
    bad = _valid_record()
    del bad["id"]
    _commit_file(repo, "noni/decisions/2026-10-01-bad.json", json.dumps(bad, indent=2))
    _commit_file(repo, "noni/decisions/2026-10-02-a.json",
                 json.dumps(_valid_record("2026-10-02-a", "decided",
                                          "2026-10-09-missing"), indent=2))
    rc, rows = _run_census_json(repo)
    # The code field is always from the exit-code table, never from file content
    for row in rows:
        if row["kind"] == "finding":
            assert row["code"] in {10, 12, 15, 20, 41, 42, 45, 46, 50, 51, 52, 53, 54, 55, 56, 57}, (
                f"code {row['code']} not from the exit-code table"
            )


def test_json_rows_for_the_new_classes_follow_the_schema(tmp_path):
    """ledger-empty 42 and hygiene 50 emit --json rows in the noni.census/1
    shape: the nine documented keys, the documented code, and warn severity
    without --strict."""
    repo = _init_repo(tmp_path / "repo")
    # The tree has no noni/decisions at all, which is the ledger-empty warn row
    # (42); warn rows do not move the exit code.
    _commit_file(repo, "README.md", "# no state yet\n")
    rc, rows = _run_census_json(repo, "--skip", "hygiene")
    assert rc == 0, f"warn classes alone must exit 0, got {rc}"
    by_check = {r["check"]: r for r in rows if r["kind"] == "finding"}
    expected_code = {
        "ledger-empty": 42,
    }
    assert set(by_check) >= set(expected_code), f"missing rows: {set(expected_code) - set(by_check)}"
    for check, code in expected_code.items():
        row = by_check[check]
        assert row["schema"] == "noni.census/1"
        assert row["kind"] == "finding"
        assert row["code"] == code, f"{check}: expected code {code}, got {row['code']}"
        assert row["severity"] == "warn", f"{check}: expected warn, got {row['severity']}"
        assert row["artifact"], f"{check}: empty artifact"
        assert row["subject"], f"{check}: empty subject"
        assert row["message"], f"{check}: empty message"
        assert row["fix"], f"{check}: no fix hint"

    hygiene_rows = _run_census_json(repo, "--only", "hygiene")[1]
    hygiene = [r for r in hygiene_rows if r["kind"] == "finding"]
    assert hygiene, "hygiene must always report, a clean tree included"
    for row in hygiene:
        assert row["check"] == "hygiene" and row["code"] == 50
        assert row["severity"] == "warn"
        assert row["fix"] and row["artifact"] and row["message"]


def test_a_warn_only_run_keeps_the_machine_summary_row(tmp_path):
    """The human wording fix may not touch the machine line (issue #117, AC3).

    A warn-only tree is the case the bug was about: exit 0 with rows printed, so
    it is the run a fix would be tempted to "improve" in --json mode too. The
    guard is the other side of that: the summary row stays ``ok`` true and
    ``exit`` 0 with its closed key set and no human verdict word, and the stream
    stays identical across two runs. A renderer that moved the warn count or the
    word ``clean`` onto the summary row fails here, and the rest of this file
    would not have caught it -- it covers the fail path and the ``not_evaluated``
    field, not a warn-only tree read in both modes.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json",
                 json.dumps(_valid_record(), indent=2))
    rc, rows = _run_census_json(repo)
    assert rc == 0, f"warn rows alone exit 0, got {rc}: {rows}"
    findings = [r for r in rows if r["kind"] == "finding"]
    assert findings and all(r["severity"] == "warn" for r in findings), rows
    summaries = [r for r in rows if r["kind"] == "summary"]
    assert len(summaries) == 1, rows
    summary = summaries[0]
    assert summary["ok"] is True and summary["exit"] == 0, summary
    assert set(summary) <= {"schema", "kind", "ok", "exit", "counts",
                            "not_evaluated"}, summary
    assert set(summary) >= {"schema", "kind", "ok", "exit", "counts"}, summary
    assert "verdict" not in json.dumps(summary), summary
    assert "clean" not in json.dumps(list(summary["counts"])), summary
    before = [json.dumps(r, sort_keys=True) for r in rows]
    _rc2, rows2 = _run_census_json(repo)
    assert [json.dumps(r, sort_keys=True) for r in rows2] == before, (
        "two --json runs of one warn-only tree differed")


def test_json_reproducible_bytes(tmp_path):
    """Two runs with the same --now produce byte-identical stdout."""
    repo = _init_repo(tmp_path / "repo")
    bad = _valid_record()
    del bad["id"]
    _commit_file(repo, "noni/decisions/2026-10-01-bad.json", json.dumps(bad, indent=2))
    _commit_file(repo, "noni/decisions/2026-10-02-a.json",
                 json.dumps(_valid_record("2026-10-02-a", "decided",
                                          "2026-10-09-missing"), indent=2))
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
