"""The confirm, drop and list verbs of order.py.

Extracted from the order writer suite: the verbs that move an item along or
read the artifact, as opposed to ``add``."""

import os

import pytest
from _harness import (
    _git,
    _git_e2,
)
from order_fixtures import (
    BASELINE_ID,
    NOW,
    ORDER_REL,
    OTHER_ID,
    SEED_STAMP,
    STAMP,
    SUPERSEDING_ID,
    _assert_census_clean,
    _commit_record,
    _entry,
    _head_paths,
    _issues,
    _order,
    _order_inprocess,
    _order_module,
    _order_path,
    _porcelain,
    _read,
    _repo,
    _seed,
    _spied_git,
    _supersede_baseline,
)
from order_race_fixtures import REFUSAL, RIVAL_STAMP
from order_rival_commit import _rival_commit


def test_move_replaces_the_entry_and_restamps_it(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"),
          _entry(2, BASELINE_ID, "2026-10-01T00:00:00Z"),
          _entry(3, BASELINE_ID, "2026-10-01T00:00:00Z"))
    proc = _order(repo, "move", "3", "--to", "1", "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    entries = _read(repo)["entries"]
    assert [e["issue"] for e in entries] == [3, 1, 2]
    assert entries[0]["confirmed"] == STAMP, entries[0]
    assert entries[0]["decision"] == BASELINE_ID, entries[0]
    assert entries[1]["confirmed"] == "2026-10-01T00:00:00Z", entries[1]
    _assert_census_clean(repo, "move")


def test_move_with_a_decision_keeps_every_position_and_takes_the_new_id(tmp_path):
    """``move N --decision ID`` re-cites one entry and places nothing.

    The pilot's case: the reason for an entry's priority changed, so the record that
    set it is no longer the record the entry should cite. Position in the list IS the
    order, so a re-citation that shuffled the queue would be a different operation --
    and the entry the run did not touch keeps both its place and its own stamp.
    """
    repo = _repo(tmp_path)
    _commit_record(repo, OTHER_ID, "decided", None)
    _seed(repo, _entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"),
          _entry(2, BASELINE_ID, "2026-10-01T00:00:00Z"),
          _entry(3, BASELINE_ID, "2026-10-01T00:00:00Z"))
    proc = _order(repo, "move", "2", "--decision", OTHER_ID, "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    entries = _read(repo)["entries"]
    assert [e["issue"] for e in entries] == [1, 2, 3], entries
    assert entries[1]["decision"] == OTHER_ID, entries[1]
    assert entries[1]["confirmed"] == STAMP, entries[1]
    assert entries[0]["decision"] == BASELINE_ID, entries[0]
    assert entries[0]["confirmed"] == "2026-10-01T00:00:00Z", entries[0]
    assert entries[2]["decision"] == BASELINE_ID, entries[2]
    assert entries[2]["confirmed"] == "2026-10-01T00:00:00Z", entries[2]
    _assert_census_clean(repo, "a decision-only move")


def test_move_with_a_decision_and_to_changes_both_at_once(tmp_path):
    """The one run does both things the pilot asked of it: new citation, new place.

    ``--to`` ranges over the list this run produces, which the entry left behind --
    the same bound a position-only move obeys, asserted here for the verb form that
    also rewrites the decision.
    """
    repo = _repo(tmp_path)
    _commit_record(repo, OTHER_ID, "decided", None)
    _seed(repo, _entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"),
          _entry(2, BASELINE_ID, "2026-10-01T00:00:00Z"),
          _entry(3, BASELINE_ID, "2026-10-01T00:00:00Z"))
    proc = _order(repo, "move", "3", "--to", "1", "--decision", OTHER_ID, "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    entries = _read(repo)["entries"]
    assert [e["issue"] for e in entries] == [3, 1, 2], entries
    assert entries[0]["decision"] == OTHER_ID, entries[0]
    assert entries[0]["confirmed"] == STAMP, entries[0]
    assert [e["decision"] for e in entries[1:]] == [BASELINE_ID, BASELINE_ID]
    _assert_census_clean(repo, "a move that changed both")


def test_move_refuses_a_decision_that_resolves_to_no_live_record(tmp_path):
    """The same live-record rule ``add --decision`` obeys, on the same codes.

    A position that rests on a superseded record is not a position the operator chose,
    and the refusal names the successor the way add's does (exit 4); a ledger this run
    could not look in is the environment's fault (exit 3), never read as an absence.
    """
    repo = _repo(tmp_path)
    _commit_record(repo, OTHER_ID, "decided", None)
    _seed(repo, _entry(1, BASELINE_ID), _entry(2, BASELINE_ID))
    before = _order_path(repo).read_bytes()
    # Read after the supersede, which is itself two commits: the three refusals below
    # commit nothing, so HEAD has to still be this line when they are done, and a
    # baseline taken before the supersede would name a commit the tree has left behind.
    _supersede_baseline(repo)
    head_before = _git_e2(repo, "rev-parse", "HEAD").stdout.strip()

    proc = _order(repo, "move", "1", "--decision", "2026-10-09-ghost", "--now", NOW)
    assert proc.returncode == 4, f"{proc.returncode}: {proc.stderr}"
    assert "is in the ledger" in proc.stderr or "matches no record" in proc.stderr, \
        proc.stderr

    proc = _order(repo, "move", "1", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 4, f"{proc.returncode}: {proc.stderr}"
    assert SUPERSEDING_ID in proc.stderr, proc.stderr
    assert f"--decision {SUPERSEDING_ID}" in proc.stderr, proc.stderr

    # The ledger this run cannot read: the environment's code (3), never the exit-4
    # sentence about a record nobody committed. Same shape as the add suite's unreadable
    # record: a 000 record the read itself cannot open -- and the same caveat, that a
    # reader who can read any mode cannot plant it. The id is already cited by no entry,
    # so the only thing this run can answer with is the fault.
    record = repo / "noni" / "decisions" / f"{OTHER_ID}.json"
    record.chmod(0o000)
    try:
        proc = _order(repo, "move", "1", "--decision", OTHER_ID, "--now", NOW)
        if proc.returncode != 3:  # pragma: no cover - root reads any mode
            if os.geteuid() == 0:
                pytest.skip("root reads any mode, so the ledger fault cannot be planted")
            raise AssertionError(f"{proc.returncode}: {proc.stderr}")
        assert "could not be read" in proc.stderr, proc.stderr
        assert "is in the ledger" not in proc.stderr, proc.stderr
    finally:
        record.chmod(0o644)

    assert _order_path(repo).read_bytes() == before, "a refused run rewrote the artifact"
    assert _git_e2(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert _porcelain(repo) == "", _porcelain(repo)


def test_move_with_a_decision_of_an_unlisted_issue_refuses_with_four(tmp_path):
    """A subject the queue does not hold is refused the way move already refuses it.

    The decision lookup must not turn a missing entry into a success or into a
    different refusal: same code, same sentence, artifact byte-identical.
    """
    repo = _repo(tmp_path)
    _commit_record(repo, OTHER_ID, "decided", None)
    _seed(repo, _entry(1, BASELINE_ID))
    before = _order_path(repo).read_bytes()
    proc = _order(repo, "move", "99", "--decision", OTHER_ID, "--now", NOW)
    assert proc.returncode == 4, f"{proc.returncode}: {proc.stderr}"
    assert "not in the order" in proc.stderr, proc.stderr
    assert _order_path(repo).read_bytes() == before


def test_a_move_that_changes_no_byte_commits_nothing(tmp_path):
    """Re-citing the record the entry already holds is a run with nothing to write.

    The no-change shortcut ``confirm`` already obeys, driven by the verb that rewrites
    a decision: no commit, no --allow-empty commit, HEAD unmoved and the tree clean.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID, STAMP), _entry(2, BASELINE_ID, STAMP))
    head_before = _git_e2(repo, "rev-parse", "HEAD").stdout.strip()
    before = _order_path(repo).read_bytes()
    proc = _order(repo, "move", "1", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    assert "unchanged" in proc.stdout and "nothing to commit" in proc.stdout, proc.stdout
    assert _order_path(repo).read_bytes() == before
    assert _git_e2(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert _porcelain(repo) == "", _porcelain(repo)


def _commit_subject(repo) -> str:
    """The subject of HEAD's commit, for the runs that owe a legible log line."""
    return _git_e2(repo, "log", "-1", "--format=%s").stdout.strip()


def test_a_decision_only_move_commits_exactly_the_order_path(tmp_path):
    """The commit of a re-citation carries one path, and a foreign staged file stays
    staged, uncommitted and unstaged by this run.

    The commit subject is the second half of the assertion: it is the line a reader of
    ``git log`` works out what the run did from, so it names the verb, the subject and
    the record the entry now cites, and ends in the digest the writer appends."""
    repo = _repo(tmp_path)
    _commit_record(repo, OTHER_ID, "decided", None)
    _seed(repo, _entry(1, BASELINE_ID), _entry(2, BASELINE_ID))
    (repo / "README.md").write_text("staged by someone else\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    proc = _order(repo, "move", "1", "--decision", OTHER_ID, "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    assert _head_paths(repo) == [ORDER_REL], _head_paths(repo)
    assert _porcelain(repo) == "A  README.md", _porcelain(repo)
    subject = _commit_subject(repo)
    assert subject.startswith(f"direction: move 1 to decision {OTHER_ID} [")
    assert subject.endswith("]"), subject
    _assert_census_clean(repo, "a decision-only move that committed")


def test_move_without_to_is_a_usage_error(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    proc = _order(repo, "move", "1", "--now", NOW)
    assert proc.returncode == 2
    assert "--to" in proc.stderr


def test_move_with_to_and_no_decision_restamps_the_moved_entry(tmp_path):
    """The counter-case to the decision arm: ``--to`` alone keeps the old citation.

    Without this, a move that rewrote the decision on every reorder would look like a
    passing move. It is the same call with one flag missing, which is what makes the
    pair a mutation test rather than two happy paths.
    """
    repo = _repo(tmp_path)
    _commit_record(repo, OTHER_ID, "decided", None)
    _seed(repo, _entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"),
          _entry(2, OTHER_ID, "2026-10-01T00:00:00Z"))
    proc = _order(repo, "move", "2", "--to", "1", "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    entries = _read(repo)["entries"]
    assert [e["issue"] for e in entries] == [2, 1], entries
    assert entries[0]["decision"] == OTHER_ID, entries[0]
    assert entries[0]["confirmed"] == STAMP, entries[0]
    _assert_census_clean(repo, "a position-only move")


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
    _seed(repo, _entry(1, BASELINE_ID), _entry(2, BASELINE_ID))
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
    _seed(repo, _entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"),
          _entry(2, BASELINE_ID, "2026-10-01T00:00:00Z"))
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
    _seed(repo, _entry(1, BASELINE_ID), _entry(2, BASELINE_ID))
    proc = _order(repo, "remove", "1", "--now", NOW)
    lines = proc.stdout.splitlines()
    assert any("order.json" in line and "1 entr" in line for line in lines), lines
    assert any(line.strip().startswith("1. #2") for line in lines), lines
    # The decision column carries the citation the entry holds -- never a dash:
    # since issue #97 every entry cites a record, so the printed order always
    # names it, and the line stays the operator's view of what the order rests on.
    assert f"decision={BASELINE_ID}" in proc.stdout, proc.stdout
    assert "confirmed=" in proc.stdout, proc.stdout
    assert "decision=-" not in proc.stdout, proc.stdout


def test_a_decision_move_prints_the_new_decision_for_the_moved_entry(tmp_path):
    """The printed order is the operator's view of what the queue now rests on, so the
    re-cited entry prints the record it now cites -- not the one it cited before.

    The column is the only place a run tells the operator which record an entry names,
    and a move that printed the old id while committing the new one would report the
    order it read rather than the order it wrote."""
    repo = _repo(tmp_path)
    _commit_record(repo, OTHER_ID, "decided", None)
    _seed(repo, _entry(1, BASELINE_ID), _entry(2, BASELINE_ID))
    proc = _order(repo, "move", "1", "--decision", OTHER_ID, "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    entry_lines = [line for line in proc.stdout.splitlines() if "decision=" in line]
    assert len(entry_lines) == 2, proc.stdout
    assert f"decision={OTHER_ID}" in entry_lines[0], entry_lines
    assert f"decision={BASELINE_ID}" in entry_lines[1], entry_lines
    assert "decision=-" not in proc.stdout, proc.stdout


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
    # The line names the path as the caller can reach it: ``--repo`` joined to
    # the artifact's path under the state root, not a state-root-relative tail
    # (issue #77, AC2).
    assert f"{repo / ORDER_REL}" in line, line
    assert sum("uncommitted" in row for row in printed) == 1, proc.stdout


def test_no_commit_is_exempt_from_the_freshness_probe(tmp_path):
    """The exemption has an arm, not just a paragraph.

    AC6 of issue #116 is that ``--no-commit`` keeps its contract: exit 0, the file
    written, and no git call. The probe's own tests cover what it does when it
    runs; nothing pinned that this route never reaches it. So this test plants the
    state that refuses the committed route -- HEAD moved past the bytes the run
    read -- and requires the ``--no-commit`` run to come out 0 anyway.

    Both halves run in-process, which is the only way to reach the guard at all (see
    ``order_fixtures._order_inprocess``). The probe is replaced with one that raises,
    so a leak is loud rather than an exit code a test has to interpret, and the git
    spy records every call the writer makes -- the probe's own ``git show`` would
    appear there if it leaked into this route.
    """
    order = _order_module()
    real_probe = order.order_probe.probe
    real_git = order.gitwrite.git
    calls: list[list[str]] = []
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID, SEED_STAMP))
    _rival_commit(repo, [_entry(1, BASELINE_ID, SEED_STAMP),
                         _entry(9, BASELINE_ID, RIVAL_STAMP)])
    head_before = _git_e2(repo, "rev-parse", "HEAD").stdout.strip()

    def tripwire(*args, **kwargs):
        raise AssertionError(f"--no-commit reached the freshness probe: {args}")

    order.order_probe.probe = tripwire
    order.gitwrite.git = _spied_git(real_git, calls)
    try:
        code, out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                          "--now", NOW, "--no-commit")
    finally:
        order.order_probe.probe = real_probe
        order.gitwrite.git = real_git

    assert code == 0, err
    assert _issues(repo) == [1, 7], _issues(repo)
    assert "uncommitted" in out, out
    assert _git_e2(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert calls == [], f"--no-commit called git: {calls}"


def test_the_committed_route_reaches_the_probe_where_no_commit_does_not(tmp_path):
    """The other half of the exemption: same repo, same rival, no flag, and the run
    is refused.

    Without this the exemption test above could be passing because the probe were
    simply never called by anyone -- an empty log proves nothing on its own. The
    probe is only watched here, never replaced, so the refusal this run prints is
    the product's own wording.
    """
    order = _order_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID, SEED_STAMP))
    _rival_commit(repo, [_entry(1, BASELINE_ID, SEED_STAMP),
                         _entry(9, BASELINE_ID, RIVAL_STAMP)])

    calls: list[tuple] = []
    real_probe = order.order_probe.probe

    def spy(*args, **kwargs):
        calls.append(args)
        return real_probe(*args, **kwargs)

    order.order_probe.probe = spy
    try:
        code, _out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                           "--now", NOW)
    finally:
        order.order_probe.probe = real_probe

    assert code == 4, err
    assert REFUSAL in err, err
    assert len(calls) == 1, f"the committed route called the probe {len(calls)} times"
    assert _issues(repo) == [1], _issues(repo)


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
