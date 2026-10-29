"""The confirm, drop and list verbs of order.py.

Extracted from the order writer suite: the verbs that move an item along or
read the artifact, as opposed to ``add``."""

from _harness import (
    _git,
    _git_e2,
)
from order_fixtures import (
    BASELINE_ID,
    NOW,
    ORDER_REL,
    STAMP,
    _assert_census_clean,
    _entry,
    _head_paths,
    _issues,
    _order,
    _order_path,
    _porcelain,
    _read,
    _repo,
    _seed,
)


def test_move_replaces_the_entry_and_restamps_it(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"),
          _entry(2, None, "2026-10-01T00:00:00Z"),
          _entry(3, BASELINE_ID, "2026-10-01T00:00:00Z"))
    proc = _order(repo, "move", "3", "--to", "1", "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    entries = _read(repo)["entries"]
    assert [e["issue"] for e in entries] == [3, 1, 2]
    assert entries[0]["confirmed"] == STAMP, entries[0]
    assert entries[0]["decision"] == BASELINE_ID, entries[0]
    assert entries[1]["confirmed"] == "2026-10-01T00:00:00Z", entries[1]
    _assert_census_clean(repo, "move")


def test_move_without_to_is_a_usage_error(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    proc = _order(repo, "move", "1", "--now", NOW)
    assert proc.returncode == 2
    assert "--to" in proc.stderr


def test_move_of_an_unlisted_issue_refuses_with_four(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    before = _order_path(repo).read_bytes()
    proc = _order(repo, "move", "99", "--to", "1", "--now", NOW)
    assert proc.returncode == 4
    assert "not in the order" in proc.stderr
    assert _order_path(repo).read_bytes() == before


def test_remove_shortens_the_list_and_leaves_the_others(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID), _entry(2, None))
    proc = _order(repo, "remove", "1", "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    assert _issues(repo) == [2]
    assert _read(repo)["entries"][0]["confirmed"] == STAMP, "remove must not restamp"
    _assert_census_clean(repo, "remove")


def test_remove_of_an_unlisted_issue_refuses_with_four(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    proc = _order(repo, "remove", "5", "--now", NOW)
    assert proc.returncode == 4
    assert "not in the order" in proc.stderr


def test_confirm_restamps_one_entry_and_then_the_whole_order(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, None, "2026-10-01T00:00:00Z"),
          _entry(2, None, "2026-10-01T00:00:00Z"))
    assert _order(repo, "confirm", "1", "--now", NOW).returncode == 0
    entries = _read(repo)["entries"]
    assert entries[0]["confirmed"] == STAMP and entries[1]["confirmed"] == "2026-10-01T00:00:00Z"
    assert _order(repo, "confirm", "--now", "2026-10-28T09:00:00Z").returncode == 0
    entries = _read(repo)["entries"]
    assert [e["confirmed"] for e in entries] == ["2026-10-28T09:00:00Z"] * 2
    _assert_census_clean(repo, "confirm")


def test_confirm_of_an_unlisted_issue_refuses_with_four(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    proc = _order(repo, "confirm", "5", "--now", NOW)
    assert proc.returncode == 4
    assert "not in the order" in proc.stderr


def test_a_run_that_changes_no_byte_commits_nothing(tmp_path):
    """Confirming an entry already stamped at the given time has nothing to
    commit: no --allow-empty commit, and the file keeps its bytes."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID, STAMP))
    head_before = _git_e2(repo, "rev-parse", "HEAD").stdout.strip()
    before = _order_path(repo).read_bytes()
    proc = _order(repo, "confirm", "1", "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    assert "unchanged" in proc.stdout and "nothing to commit" in proc.stdout
    assert _order_path(repo).read_bytes() == before
    assert _git_e2(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert _porcelain(repo) == ""


# --- the printed order --------------------------------------------------------


def test_every_run_prints_the_resulting_order_one_line_per_entry(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID), _entry(2, None))
    proc = _order(repo, "remove", "1", "--now", NOW)
    lines = proc.stdout.splitlines()
    assert any("order.json" in line and "1 entr" in line for line in lines), lines
    assert any(line.strip().startswith("1. #2") for line in lines), lines
    assert "decision=-" in proc.stdout and "confirmed=" in proc.stdout, proc.stdout


# --- --no-commit and the staged-file rule -------------------------------------


def test_no_commit_writes_the_file_and_moves_no_head(tmp_path):
    repo = _repo(tmp_path)
    head_before = _git_e2(repo, "rev-parse", "HEAD").stdout.strip()
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW, "--no-commit")
    assert proc.returncode == 0, proc.stderr
    assert _issues(repo) == [7]
    assert _git_e2(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert _porcelain(repo, ORDER_REL) == f"?? {ORDER_REL}", _porcelain(repo, ORDER_REL)
    printed = proc.stdout.splitlines()
    line = next(row for row in printed if "uncommitted" in row)
    assert ORDER_REL in line, line
    assert sum("uncommitted" in row for row in printed) == 1, proc.stdout


def test_a_file_somebody_else_staged_is_neither_committed_nor_unstaged(tmp_path):
    """The commit carries exactly the path this run wrote: a foreign staged file
    survives the run staged and uncommitted, and never appears in HEAD."""
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("staged by someone else\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    assert _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW).returncode == 0
    assert _head_paths(repo) == [ORDER_REL], _head_paths(repo)
    assert _porcelain(repo, "README.md") == "A  README.md", _porcelain(repo, "README.md")


def test_the_written_file_is_readable_not_owner_only(tmp_path):
    """mkstemp's 0600 must not land: an order the census cannot read is an
    order nobody can trust."""
    repo = _repo(tmp_path)
    assert _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW).returncode == 0
    mode = _order_path(repo).stat().st_mode & 0o777
    assert mode & 0o044, f"the artifact is {oct(mode)}; the census must be able to read it"
