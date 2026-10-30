"""The artifact order.py writes: canonical bytes, and what it refuses.

Extracted from the order writer suite: the file's bytes, its mode, and the
malformed shapes the writer will not touch."""

import json

from order_fixtures import (
    BASELINE_ID,
    NOW,
    _canonical,
    _entry,
    _order,
    _order_path,
    _repo,
    _seed,
)
from ordering_shapes import (
    MALFORMED_SHAPES,
)


def test_a_file_that_is_not_json_is_refused_and_left_untouched(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    _order_path(repo).write_text("{not json", encoding="utf-8")
    before = _order_path(repo).read_bytes()
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 4
    assert "not valid JSON" in proc.stderr
    assert _order_path(repo).read_bytes() == before


def test_a_wrong_schema_is_refused(tmp_path):
    repo = _repo(tmp_path)
    _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
    _order_path(repo).write_text(json.dumps({"schema": "noni.order/0", "entries": []}),
                                 encoding="utf-8")
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 4
    assert "noni.order/1" in proc.stderr


def test_malformed_entries_are_refused_without_being_overwritten(tmp_path):
    """Every shape the census reports as ordering-malformed is refused here
    before the write, so a writer run never turns a half-broken artifact into a
    fully written one. The table is the shared one in ``tests/ordering_shapes.py``
    -- the whole set, not a sample -- so this side and the census side of the
    contract are the same list read twice.

    The artifact is left exactly as it was for every shape: a refusal that
    reformats or truncates a file the operator committed would destroy an order
    the run was only asked to extend.
    """
    for index, (label, (body, _needle)) in enumerate(sorted(MALFORMED_SHAPES.items())):
        repo = _repo(tmp_path, f"repo-{index}")
        _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
        _order_path(repo).write_text(body, encoding="utf-8")
        proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
        assert proc.returncode == 4, f"{label}: exit {proc.returncode} {proc.stderr}"
        assert _order_path(repo).read_text(encoding="utf-8") == body, f"{label}: overwritten"


def test_non_canonical_bytes_are_refused_rather_than_reformatted(tmp_path):
    """Valid, well-shaped, but not the form this writer writes (one-space
    indent): the operator committed it, so reformatting it is not this run's
    to do."""
    repo = _repo(tmp_path)
    body = json.dumps({"schema": "noni.order/1", "entries": [_entry(1, BASELINE_ID)]},
                      indent=1) + "\n"
    _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
    _order_path(repo).write_text(body, encoding="utf-8")
    proc = _order(repo, "confirm", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "canonical form" in proc.stderr, proc.stderr
    assert _order_path(repo).read_text(encoding="utf-8") == body
    # The committed canonical form of the same content is accepted.
    _seed(repo, _entry(1, BASELINE_ID))
    assert _order(repo, "confirm", "--now", NOW).returncode == 0


def test_a_key_order_that_is_not_the_documented_one_is_refused(tmp_path):
    """Sorted keys are still valid JSON and still the wrong bytes: the writer's
    canonical form is the documented key order, not json.dumps' default."""
    repo = _repo(tmp_path)
    body = json.dumps({"entries": [_entry(1, BASELINE_ID)], "schema": "noni.order/1"},
                      indent=2) + "\n"
    _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
    _order_path(repo).write_text(body, encoding="utf-8")
    proc = _order(repo, "confirm", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert _order_path(repo).read_text(encoding="utf-8") == body


def test_the_artifact_path_being_a_directory_is_an_environment_fault(tmp_path):
    repo = _repo(tmp_path)
    _order_path(repo).mkdir(parents=True)
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 3, proc.stderr
    assert "not a regular file" in proc.stderr, proc.stderr


def test_a_symlink_at_the_artifact_path_is_refused_never_followed(tmp_path):
    """Reading through a link puts a file outside the tree into the writer's
    decisions; writing onto one replaces somebody's link with an order file."""
    repo = _repo(tmp_path)
    (repo / "elsewhere.json").write_text(_canonical([_entry(1, BASELINE_ID)]), encoding="utf-8")
    _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
    _order_path(repo).symlink_to(repo / "elsewhere.json")
    proc = _order(repo, "confirm", "--now", NOW)
    assert proc.returncode == 3, proc.stderr
    assert "symlink" in proc.stderr, proc.stderr
    assert _order_path(repo).is_symlink(), "the writer replaced a symlink"
    assert (repo / "elsewhere.json").is_file()


def test_an_unreadable_decision_record_is_an_environment_fault(tmp_path):
    repo = _repo(tmp_path)
    record = repo / "noni" / "decisions" / f"{BASELINE_ID}.json"
    record.chmod(0o000)
    try:
        proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    finally:
        record.chmod(0o644)
    if proc.returncode != 3:  # pragma: no cover - root can read 000 files
        import pytest
        pytest.skip("the reading user can read a 000-mode file")
    assert "could not be read" in proc.stderr, proc.stderr
