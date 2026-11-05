"""The add verb of order.py: one item, one commit, the census's answer.

Extracted from the order writer suite: appending an entry, the idempotence rule,
and the artifact's shape as the census reads it."""

import json
import shutil

from _harness import (
    _git_e2,
)
from order_fixtures import (
    BASELINE_ID,
    NOW,
    ORDER_REL,
    SUPERSEDING_ID,
    _assert_census_clean,
    _canonical,
    _census_ordering,
    _commit_record,
    _entry,
    _head_paths,
    _issues,
    _order,
    _order_path,
    _porcelain,
    _read,
    _repo,
    _schema_module,
    _seed,
    _supersede_baseline,
)
from ordering_shapes import (
    MALFORMED_SHAPES,
)


def test_add_creates_the_file_and_commits_only_that_path(tmp_path):
    repo = _repo(tmp_path)
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    assert _read(repo) == {"schema": "noni.order/1", "entries": [_entry(7, BASELINE_ID)]}
    assert _head_paths(repo) == [ORDER_REL], _head_paths(repo)
    assert _porcelain(repo) == ""
    subject = _git_e2(repo, "log", "-1", "--format=%s").stdout.strip()
    assert subject.startswith("direction: add 7 [") and subject.endswith("]"), subject
    _assert_census_clean(repo, "add")


def test_an_entry_whose_decision_is_null_is_refused_by_every_verb(tmp_path):
    """Every entry cites a decision (anti-fabrication, issue #97), so neither a
    hand-written ``"decision": null`` nor an entry that omits the key is a state
    the file may carry.

    Both states run the whole verb set: the rule is that no order writer verb
    opens such a file, and one enforced by four verbs and missed by the fifth is
    the gap this pins shut. The two states keep their own sentences -- the null
    is refused as a decision that is neither a record id nor null, the absent key
    as a missing field -- so a reader learns whether the repair is an id or a
    key. The refusal is the writer's own code 4 and it leaves the artifact
    untouched, because overwriting an order the operator committed is worse than
    refusing the run.
    """
    # Both shapes come from the shared table (``tests/ordering_shapes.py``), the
    # one list the census's ordering suite reads too, so neither half of the
    # contract can quietly drop a state.
    for label in ("decision null", "decision absent"):
        body, needle = MALFORMED_SHAPES[label]
        repo = _repo(tmp_path, f"decision-{label.replace(' ', '-')}")
        _order_path(repo).parent.mkdir(parents=True, exist_ok=True)
        _order_path(repo).write_text(body, encoding="utf-8")
        before = _order_path(repo).read_bytes()
        for verb in (("confirm",), ("confirm", "1"), ("move", "1", "--to", "1"),
                     ("remove", "2"), ("add", "9", "--decision", BASELINE_ID)):
            proc = _order(repo, *verb, "--now", NOW)
            assert proc.returncode == 4, f"{label} {verb}: {proc.returncode} {proc.stderr}"
            assert needle in proc.stderr, f"{label} {verb}: {proc.stderr}"
            assert "entry 1" in proc.stderr, \
                f"{label} {verb} must name the entry: {proc.stderr}"
        assert _order_path(repo).read_bytes() == before, \
            f"{label}: a refused run rewrote the artifact"
    # What the writer does write: the key present with a real id, in the
    # documented order, and the census content with it.
    repo = _repo(tmp_path, "decision-cited")
    _seed(repo, _entry(1, BASELINE_ID))
    assert _order(repo, "confirm", "--now", NOW).returncode == 0
    body = _order_path(repo).read_text(encoding="utf-8")
    assert '"decision": "2026-10-01-baseline"' in body, body
    assert list(json.loads(body)["entries"][0]) == ["issue", "decision", "confirmed"]
    _assert_census_clean(repo, "a cited decision")


def test_add_writes_the_canonical_bytes_the_docstring_documents(tmp_path):
    """The artifact is the documented shape: schema first, then entries, each
    entry issue/decision/confirmed, two-space indent, one trailing newline."""
    repo = _repo(tmp_path)
    assert _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW).returncode == 0
    assert _order(repo, "add", "12", "--decision", BASELINE_ID,
                  "--now", NOW).returncode == 0
    body = _order_path(repo).read_text(encoding="utf-8")
    # Every add names a --decision: an entry that cited nothing would not be an
    # artifact this writer writes at all.
    assert body == _canonical([_entry(7, BASELINE_ID), _entry(12, BASELINE_ID)]), repr(body)
    assert list(json.loads(body)) == ["schema", "entries"]
    assert list(json.loads(body)["entries"][0]) == ["issue", "decision", "confirmed"]
    assert body.endswith("\n") and not body.endswith("\n\n")
    assert '  "schema": "noni.order/1"' in body, body


def test_add_appends_at_the_end_and_at_the_named_position(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID), _entry(2, BASELINE_ID))
    assert _order(repo, "add", "9", "--decision", BASELINE_ID,
                    "--now", NOW).returncode == 0
    assert _issues(repo) == [1, 2, 9]
    assert _order(repo, "add", "8", "--at", "1", "--decision", BASELINE_ID,
                    "--now", NOW).returncode == 0
    assert _issues(repo) == [8, 1, 2, 9]
    _assert_census_clean(repo, "inserts")


def test_add_at_the_last_position_of_the_new_list_is_accepted(tmp_path):
    """``--at`` ranges over the list this run produces, so the new length is a
    legal position and one past it is not."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    assert _order(repo, "add", "5", "--at", "2", "--decision", BASELINE_ID,
                    "--now", NOW).returncode == 0
    assert _issues(repo) == [1, 5]
    assert _order(repo, "add", "6", "--at", "4", "--now", NOW).returncode == 2
    assert _issues(repo) == [1, 5]


def test_add_stamps_confirmed_with_the_run_time_when_now_is_omitted(tmp_path):
    """Without --now the stamp is this run's UTC second, which the file must
    carry in the one shape the census parses."""
    repo = _repo(tmp_path)
    assert _order(repo, "add", "7", "--decision", BASELINE_ID).returncode == 0
    stamp = _read(repo)["entries"][0]["confirmed"]
    assert len(stamp) == 20 and stamp.endswith("Z") and stamp[10] == "T", stamp
    assert _schema_module().parse_confirmed(stamp) is not None


def test_add_without_a_decision_refuses_with_two(tmp_path):
    repo = _repo(tmp_path)
    proc = _order(repo, "add", "7", "--now", NOW)
    assert proc.returncode == 2
    assert "--decision" in proc.stderr
    assert not _order_path(repo).exists()


def test_add_of_an_already_listed_issue_refuses_with_four_and_changes_nothing(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(7, BASELINE_ID))
    before = _order_path(repo).read_bytes()
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 4
    assert "already in the order at position 1" in proc.stderr
    assert _order_path(repo).read_bytes() == before
    assert _porcelain(repo, ORDER_REL) == ""


def test_add_refuses_a_decision_that_matches_no_record(tmp_path):
    repo = _repo(tmp_path)
    proc = _order(repo, "add", "7", "--decision", "2026-10-09-ghost", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "is in the ledger" in proc.stderr or "matches no record" in proc.stderr, proc.stderr
    assert not _order_path(repo).exists()
    code, rows, _ = _census_ordering(repo)
    assert code == 0 and not rows, rows


def test_add_refuses_a_superseded_decision_and_names_its_successor(tmp_path):
    repo = _repo(tmp_path)
    _supersede_baseline(repo)
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert SUPERSEDING_ID in proc.stderr, proc.stderr
    assert f"--decision {SUPERSEDING_ID}" in proc.stderr, proc.stderr
    assert not _order_path(repo).exists()
    # The successor itself sets a position without complaint.
    assert _order(repo, "add", "7", "--decision", SUPERSEDING_ID, "--now", NOW).returncode == 0


def test_add_refuses_a_record_whose_status_is_not_one_of_the_three(tmp_path):
    """A hand-edited status answers nothing about the chain, so it is refused
    like a missing record rather than trusted as a live decision."""
    repo = _repo(tmp_path)
    _commit_record(repo, "2026-10-15-rogue", "settled", None)
    proc = _order(repo, "add", "7", "--decision", "2026-10-15-rogue", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "settled" in proc.stderr, proc.stderr


def test_an_empty_ledger_answers_that_the_id_is_not_there(tmp_path):
    """A ledger directory that holds no records is a readable answer, and it is
    the same answer as no file with that name: exit 4, the refusal is about the
    ordering, and the caller fixes it by naming a record that exists."""
    repo = _repo(tmp_path)
    shutil.rmtree(repo / "noni" / "decisions")
    (repo / "noni" / "decisions").mkdir()
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "is in the ledger" in proc.stderr, proc.stderr


def test_a_record_that_is_not_a_regular_file_cannot_set_a_position(tmp_path):
    """Something that is not a record sitting where the record should be cannot
    have decided anything: the writer refuses the citation (exit 4) and says the
    path is not readable, so the caller repairs the ledger rather than hunting
    for a record that was never missing."""
    repo = _repo(tmp_path)
    record = repo / "noni" / "decisions" / f"{BASELINE_ID}.json"
    record.unlink()
    record.mkdir()
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 3, proc.stderr
    assert "not readable" in proc.stderr, proc.stderr


def test_a_ledger_that_is_not_a_directory_cannot_be_looked_in(tmp_path):
    """The contrast: the ledger path itself holds something that is not a
    directory, so nothing was looked at. That is 'I could not look' (exit 3),
    not the absence the previous test reports."""
    repo = _repo(tmp_path)
    shutil.rmtree(repo / "noni" / "decisions")
    (repo / "noni" / "decisions").write_text("not a directory", encoding="utf-8")
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 3, proc.stderr
    assert "could not be looked in" in proc.stderr, proc.stderr


def test_add_creates_the_direction_directory_for_the_first_entry(tmp_path):
    repo = _repo(tmp_path)
    assert not (repo / "noni" / "direction").exists()
    assert _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW).returncode == 0
    assert _order_path(repo).is_file()
