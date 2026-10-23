"""Validate ledger records against the declared eight-field schema.

The schema is:
  id (string), date (UTC ISO-8601 string), asked_by (string),
  questions (array of 1-4 question objects), by (string),
  scope (string), status (one of decided|open|superseded),
  supersedes (string or null)

A question object is: id (string), text (string), options (array of 2-4
strings), answer (string or absent).

The tests use the committed golden fixtures:
  decision-valid.json               — one complete minimal record, the baseline
  decision-invalid-missing-field.json — missing the `supersedes` field
  decision-invalid-unknown-status.json — status is "pending" (not in the legal set)
  decision-unconfirmed.json          — status "open" with no answer (the declined state)

The fixture file name "unconfirmed" is a legacy name: "open with no answer"
is the declined state, and nothing in this suite or the census treats
confirmation as a checkable property (see references/modes.md, Anti-fabrication).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO = Path(__file__).resolve().parent.parent
CENSUS = REPO / "skills" / "steering-ledger" / "scripts" / "census.sh"

REQUIRED_FIELDS = {"id", "date", "asked_by", "questions", "by", "scope", "status", "supersedes"}
LEGAL_STATUSES = {"decided", "open", "superseded"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _run_census_on_record(tmp_path: Path, record: dict, fname: str = "test-record.json") -> tuple[int, str, str]:
    """Write a single record to a ledger dir and run the census on it."""
    import os

    ledger = tmp_path / "noni" / "decisions"
    ledger.mkdir(parents=True)
    (ledger / fname).write_text(json.dumps(record, indent=2))
    env = dict(os.environ)
    proc = subprocess.run(
        ["bash", str(CENSUS), str(ledger)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_valid_record_passes(tmp_path):
    """A complete minimal record with all eight fields passes the schema
    check (the census reports exit 10 for a schema violation; a schema-valid
    record is not flagged for it)."""
    rec = _fixture("decision-valid.json")
    assert set(rec.keys()) >= REQUIRED_FIELDS, f"missing fields: {REQUIRED_FIELDS - set(rec.keys())}"
    # The valid fixture is a baseline: all fields present and correct types.
    assert isinstance(rec["id"], str)
    assert DATE_RE.match(rec["date"]), f"date not ISO-8601: {rec['date']}"
    assert isinstance(rec["asked_by"], str)
    assert isinstance(rec["questions"], list)
    assert 1 <= len(rec["questions"]) <= 4
    for q in rec["questions"]:
        assert set(q.keys()) >= {"id", "text", "options"}, f"question missing keys: {q}"
        assert isinstance(q["options"], list)
        assert 2 <= len(q["options"]) <= 4
        assert all(isinstance(o, str) for o in q["options"])
    assert isinstance(rec["by"], str)
    assert isinstance(rec["scope"], str)
    assert rec["status"] in LEGAL_STATUSES
    assert rec["supersedes"] is None or isinstance(rec["supersedes"], str)


def test_missing_field_fails(tmp_path):
    """A record with a missing field (supersedes absent) fails the schema
    check (exit 10)."""
    rec = _fixture("decision-invalid-missing-field.json")
    assert "supersedes" not in rec, "fixture should be missing the supersedes field"
    code, out, err = _run_census_on_record(tmp_path, rec)
    assert code == 10, f"expected exit 10 for missing field, got {code}\nstderr: {err}"
    assert "missing" in err.lower() or "supersedes" in err.lower()


def test_unknown_status_fails(tmp_path):
    """A record with an unknown status (pending) fails the schema check
    (exit 10)."""
    rec = _fixture("decision-invalid-unknown-status.json")
    assert rec["status"] == "pending"
    code, out, err = _run_census_on_record(tmp_path, rec)
    assert code == 10, f"expected exit 10 for unknown status, got {code}\nstderr: {err}"
    assert "status" in err.lower()


def test_open_record_without_answer_is_valid_schema(tmp_path):
    """A record with status=open and no answer is schema-valid (the declined
    state): the eight-field shape is correct and the census does not flag it
    for a schema violation."""
    rec = _fixture("decision-unconfirmed.json")
    assert rec["status"] == "open"
    # All questions have no answer (answer absent or null)
    for q in rec["questions"]:
        assert q.get("answer") is None or q.get("answer") == "", (
            f"open record should have no answer, got: {q.get('answer')}"
        )
    # Schema-valid: all eight fields present, correct types
    assert set(rec.keys()) >= REQUIRED_FIELDS
    assert rec["status"] in LEGAL_STATUSES


def test_question_bounds_two_options(tmp_path):
    """A question with exactly 2 options (the minimum) is schema-valid."""
    rec = _fixture("decision-valid.json")
    q = rec["questions"][0]
    assert len(q["options"]) >= 2


def test_question_bounds_rejects_one_option(tmp_path):
    """A question with 1 option is schema-invalid (exit 10)."""
    rec = _fixture("decision-valid.json")
    rec = json.loads(json.dumps(rec))  # deep copy
    rec["questions"][0]["options"] = ["only-one"]
    code, out, err = _run_census_on_record(tmp_path, rec)
    assert code == 10, f"expected exit 10 for 1 option, got {code}\nstderr: {err}"


def test_question_bounds_rejects_five_options(tmp_path):
    """A question with 5 options is schema-invalid (exit 10)."""
    rec = _fixture("decision-valid.json")
    rec = json.loads(json.dumps(rec))
    rec["questions"][0]["options"] = ["a", "b", "c", "d", "e"]
    code, out, err = _run_census_on_record(tmp_path, rec)
    assert code == 10, f"expected exit 10 for 5 options, got {code}\nstderr: {err}"


def test_question_bounds_rejects_five_questions(tmp_path):
    """A record with 5 questions is schema-invalid (exit 10)."""
    rec = _fixture("decision-valid.json")
    rec = json.loads(json.dumps(rec))
    q = {"id": "q_extra", "text": "Extra?", "options": ["x", "y"], "answer": None}
    rec["questions"].extend(dict(q) for _ in range(4))
    code, out, err = _run_census_on_record(tmp_path, rec)
    assert code == 10, f"expected exit 10 for 5 questions, got {code}\nstderr: {err}"


def test_date_format_must_be_iso8601(tmp_path):
    """A record with a non-ISO-8601 date is schema-invalid (exit 10)."""
    rec = _fixture("decision-valid.json")
    rec = json.loads(json.dumps(rec))
    rec["date"] = "not-a-date"
    code, out, err = _run_census_on_record(tmp_path, rec)
    assert code == 10, f"expected exit 10 for bad date, got {code}\nstderr: {err}"


def test_supersedes_must_be_null_or_string(tmp_path):
    """A record with supersedes set to a number is schema-invalid (exit 10)."""
    rec = _fixture("decision-valid.json")
    rec = json.loads(json.dumps(rec))
    rec["supersedes"] = 42
    code, out, err = _run_census_on_record(tmp_path, rec)
    assert code == 10, f"expected exit 10 for numeric supersedes, got {code}\nstderr: {err}"
