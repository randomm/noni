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
    SEED_STAMP,
    STAMP,
    SUPERSEDING_ID,
    _assert_census_clean,
    _canonical,
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


# --- move --decision: a reorder under a new decision --------------------------

# A second live record, so a move has a decision to move *to* that is not the one
# the seeded entry already carries. The fixture's baseline is committed and decided;
# ``_commit_record`` gives the same shape under a second id.
ALT_ID = "2026-10-15-repriority"


def test_a_decision_only_move_keeps_every_position(tmp_path):
    """``move N --decision ID`` with no ``--to`` changes one field and nothing else.

    The case the pilot asked for: the reason for a position changed, so the entry
    keeps its place in the queue and takes the new citation. Every other entry keeps
    its position and its own stamp, and the reason one entry carries stays with that
    entry (``why`` belongs to ``add`` alone, so it is asserted on the entry that owns it).
    """
    repo = _repo(tmp_path)
    _commit_record(repo, ALT_ID, "decided", None)
    _seed(repo, {**_entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"), "why": "first"},
          _entry(2, BASELINE_ID, "2026-10-01T00:00:00Z"),
          _entry(3, BASELINE_ID, "2026-10-01T00:00:00Z"))
    proc = _order(repo, "move", "2", "--decision", ALT_ID, "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    entries = _read(repo)["entries"]
    assert [e["issue"] for e in entries] == [1, 2, 3], entries
    assert entries[1]["decision"] == ALT_ID, entries[1]
    assert entries[1]["confirmed"] == STAMP, entries[1]
    assert "why" not in entries[1], entries[1]
    assert entries[0]["why"] == "first", entries[0]
    assert entries[0]["decision"] == BASELINE_ID and entries[2]["decision"] == BASELINE_ID
    assert entries[0]["confirmed"] == "2026-10-01T00:00:00Z"
    assert entries[2]["confirmed"] == "2026-10-01T00:00:00Z"
    # The committed bytes are the canonical render, not a patched copy of the old file.
    assert _order_path(repo).read_text(encoding="utf-8") == _canonical(entries)
    assert list(entries[0]) == ["issue", "decision", "confirmed", "why"], entries[0]
    _assert_census_clean(repo, "a decision-only move")


def test_a_decision_move_with_to_changes_both(tmp_path):
    """``move N --decision ID --to P`` is one run that does both, and restamps once."""
    repo = _repo(tmp_path)
    _commit_record(repo, ALT_ID, "decided", None)
    _seed(repo, {**_entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"), "why": "first"},
          {**_entry(2, BASELINE_ID, "2026-10-01T00:00:00Z"), "why": "second"},
          _entry(3, BASELINE_ID, "2026-10-01T00:00:00Z"))
    proc = _order(repo, "move", "3", "--decision", ALT_ID, "--to", "1", "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    entries = _read(repo)["entries"]
    assert [e["issue"] for e in entries] == [3, 1, 2], entries
    assert entries[0]["decision"] == ALT_ID, entries[0]
    assert entries[0]["confirmed"] == STAMP, entries[0]
    assert entries[1]["confirmed"] == "2026-10-01T00:00:00Z", entries[1]
    # The entry that carried a reason keeps it and stays in the documented key order.
    assert list(entries[1]) == ["issue", "decision", "confirmed", "why"], entries[1]
    assert entries[1]["why"] == "first", entries[1]
    _assert_census_clean(repo, "a move that changed position and decision")


def test_a_move_refuses_a_superseded_decision_and_names_its_successor(tmp_path):
    """The citation rule is ``add``'s rule: exit 4, and the hint names the successor.

    The contrast that makes the test worth having: with the chain moved past it, the
    same command succeeds when it names the record that replaced the baseline, so the
    refusal is about the citation and not about the verb.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"),
          _entry(2, SUPERSEDING_ID, "2026-10-01T00:00:00Z"))
    _supersede_baseline(repo)
    before = _order_path(repo).read_bytes()
    proc = _order(repo, "move", "2", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert SUPERSEDING_ID in proc.stderr, proc.stderr
    assert f"--decision {SUPERSEDING_ID}" in proc.stderr, proc.stderr
    assert _order_path(repo).read_bytes() == before
    assert _porcelain(repo, ORDER_REL) == ""
    assert _order(repo, "move", "2", "--decision", SUPERSEDING_ID,
                  "--now", NOW).returncode == 0


def test_a_move_refuses_a_decision_that_matches_no_record(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"))
    before = _order_path(repo).read_bytes()
    proc = _order(repo, "move", "1", "--decision", "2026-10-09-ghost", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "matches no record" in proc.stderr or "is in the ledger" in proc.stderr, \
        proc.stderr
    assert _order_path(repo).read_bytes() == before


def test_a_move_refuses_an_unreadable_record_with_three(tmp_path):
    """"I could not read it" is exit 3 and not exit 4, for move as it is for add.

    The environment's code and the order's code answer two different questions, and a
    move that collapsed an unreadable ledger into "no record carries that id" would
    send the operator to the ledger when the tree is what is wrong.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"))
    _commit_record(repo, ALT_ID, "decided", None)
    record = repo / "noni" / "decisions" / f"{ALT_ID}.json"
    record.unlink()
    record.mkdir()
    before = _order_path(repo).read_bytes()
    proc = _order(repo, "move", "1", "--decision", ALT_ID, "--now", NOW)
    assert proc.returncode == 3, proc.stderr
    assert "not readable" in proc.stderr, proc.stderr
    assert _order_path(repo).read_bytes() == before


def test_a_move_refuses_an_absent_entry_before_reading_the_decision(tmp_path):
    """The entry question is asked first, and the ledger is never opened for it.

    The order of the refusals is what a caller acts on: an entry nobody listed is the
    order's own problem and is fixed by ``add``, while a record the ledger does not hold
    is fixed by naming another one. An empty ledger cannot tell those apart, because both
    answer exit 4, so the probe is a ledger whose records cannot be read: the citation
    question then answers exit 3, the environment's code for "I could not read it", so an
    exit 4 naming the order can only have come from the entry refusal that ran ahead of
    the lookup.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID))
    _commit_record(repo, ALT_ID, "decided", None)
    record = repo / "noni" / "decisions" / f"{ALT_ID}.json"
    record.unlink()
    record.mkdir()
    before = _order_path(repo).read_bytes()
    reached = _order(repo, "move", "1", "--decision", ALT_ID, "--now", NOW)
    assert reached.returncode == 3, reached.stderr
    assert "not readable" in reached.stderr, reached.stderr

    proc = _order(repo, "move", "99", "--decision", ALT_ID, "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "is not in the order" in proc.stderr, proc.stderr
    assert "readable" not in proc.stderr, proc.stderr
    assert _order_path(repo).read_bytes() == before


def test_a_move_that_changes_no_byte_commits_nothing(tmp_path):
    """A run whose planned bytes are the file's bytes commits nothing.

    The no-change shortcut already had a confirm test; this is the same rule reached
    through ``--decision``: the entry already cites the record the run was handed, so
    the only thing left to do is restamp a stamp the file already holds."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(1, BASELINE_ID, STAMP))
    head_before = _git_e2(repo, "rev-parse", "HEAD").stdout.strip()
    before = _order_path(repo).read_bytes()
    proc = _order(repo, "move", "1", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    assert "unchanged" in proc.stdout and "nothing to commit" in proc.stdout
    assert _order_path(repo).read_bytes() == before
    assert _git_e2(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert _porcelain(repo) == ""


def test_a_decision_only_move_commits_exactly_the_order_path(tmp_path):
    """One commit, one path, a clean tree: the run that changed only a citation is a
    run over the artifact and nothing else."""
    repo = _repo(tmp_path)
    _commit_record(repo, ALT_ID, "decided", None)
    _seed(repo, _entry(1, BASELINE_ID, "2026-10-01T00:00:00Z"))
    proc = _order(repo, "move", "1", "--decision", ALT_ID, "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    assert _head_paths(repo) == [ORDER_REL], _head_paths(repo)
    assert _porcelain(repo) == ""
    assert f"decision={ALT_ID}" in proc.stdout, proc.stdout
    subject = _git_e2(repo, "log", "-1", "--format=%s").stdout.strip()
    assert subject.startswith("direction: move 1 "), subject


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
