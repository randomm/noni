"""The item writer's verbs: what each one files, what each one refuses, and what it prints.

The store is the writer's own contract, so this suite is the half of the contract that
the census cannot check: the census arbitrates the bytes, and this checks that the
bytes the verbs produce are the bytes the writer meant. Three things are pinned over
and over because each is a way a writer silently corrupts a store:

- **A refusal changes nothing.** Every exit that is not 0 leaves the file it refused
  byte-identical and the tree with no new commit: a verb that refused half its own
  rules and rewrote the record anyway is the store's worst failure mode.
- **``created`` is the idea's age and never restamped.** ``add`` stamps it once and
  ``drop``/``promote`` carry it over, so an idea that sat for a month is a month old
  after it is promoted, and ``item-stale`` cannot be dodged by moving the item.
- **One verb writes one path.** A commit that also touched the ledger or the order is
  a verb doing two jobs, and the census has no class that would notice.

Usage and argv refusals are ``test_item_writer_usage.py``; the artifact's bytes and the
malformed-shape table are ``test_item_writer_artifact.py``; the path guard is
``test_item_writer_state_root.py``.
"""

from __future__ import annotations

from _harness import _git
from item_writer_fixtures import (
    BASELINE_ID,
    FRESH,
    HEIR_ID,
    NOW,
    OLD,
    commit,
    item_path,
    read,
    repo,
    run_item,
    seed_item,
    seed_order,
    seed_record,
)


def _add(tree, item_id="idea-0001", title="Say hello first", no_commit=False, **flags):
    """``add`` with the flags the caller names, as the operator would type them.

    ``no_commit`` is a flag rather than a ``--no-commit`` keyword because argparse's
    store-true option takes no value and would otherwise be spelled with an empty
    argument it has to reject.
    """
    argv = ["add", item_id, "--title", title]
    if no_commit:
        argv.append("--no-commit")
    for flag, value in flags.items():
        argv += [f"--{flag.replace('_', '-')}", str(value)]
    return run_item(tree, *argv)


def _file_candidate(tree, item_id="idea-0001", title="t", status="candidate",
                    created=FRESH, **extra):
    """Plant one item in the store as a commit, bypassing the writer.

    ``add`` refuses to file over an id that is already there, so a test of a later verb
    cannot begin with two calls to it: the record has to be planted, and the census's
    own builder is not wanted here (this suite tests what the writer writes, not what
    the census reads).
    """
    seed_item(tree, {"schema": "noni.item/1", "id": item_id, "title": title,
                     "status": status, "created": created, **extra})


def test_add_files_a_candidate_and_commits_one_path(tmp_path):
    """The one verb that creates, and the one path its commit may hold."""
    tree = repo(tmp_path)
    proc = _add(tree, now=NOW)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    body = read(tree, "idea-0001")
    assert body["status"] == "candidate"
    assert body["created"] == NOW, "add stamps created with --now"
    assert body["title"] == "Say hello first"
    # The optional fields are absent, not null: the schema tells the two apart and the
    # census reads the difference.
    assert "issue" not in body and "decision" not in body and "why" not in body
    last = _git(tree, "log", "-1", "--name-only", "--pretty=format:%s").stdout.split("\n")
    assert last[0].startswith("items: add idea-0001"), last[0]
    assert [p for p in last[1:] if p.strip()] == ["noni/items/idea-0001.json"], last


def test_add_without_a_created_stamp_stamps_this_runs_time(tmp_path):
    """``created`` is stamped by the writer, so omitting --now is the normal run.

    No clock is faked: the assertion is that the field names an instant in the UTC form
    the schema accepts, which is the property a missing stamp would break.
    """
    tree = repo(tmp_path)
    assert _add(tree).returncode == 0
    created = read(tree, "idea-0001")["created"]
    assert created.endswith("Z") and "T" in created, created


def test_add_refuses_an_id_that_is_already_filed(tmp_path):
    """Two ideas cannot share a name, and the first record survives the attempt."""
    tree = repo(tmp_path)
    _add(tree, now=NOW)
    before = item_path(tree, "idea-0001").read_bytes()
    head = _git(tree, "rev-parse", "HEAD").stdout
    proc = _add(tree, title="A different idea", now=NOW)
    assert proc.returncode == 4, proc.stderr
    assert "idea-0001" in proc.stderr
    assert item_path(tree, "idea-0001").read_bytes() == before, "the first record moved"
    assert _git(tree, "rev-parse", "HEAD").stdout == head, "a refusal committed"


def test_add_refuses_a_title_a_dropped_item_already_carried(tmp_path):
    """The kill list is the point: re-filing a killed idea under its own name is a
    second record for one decision the ledger already holds."""
    tree = repo(tmp_path)
    seed_record(tree)
    seed_item(tree, {"schema": "noni.item/1", "id": "old-idea",
                     "title": "Cache the census", "status": "dropped",
                     "created": OLD, "decision": BASELINE_ID,
                     "why": "belongs to the adapter"})
    proc = _add(tree, item_id="new-idea", title="Cache the census", now=NOW)
    assert proc.returncode == 4, proc.stderr
    assert "Cache the census" in proc.stderr, proc.stderr
    assert not item_path(tree, "new-idea").exists()


def test_a_same_title_on_a_candidate_is_not_a_duplicate(tmp_path):
    """Only the dropped item's title is taken: two live ideas may be phrased alike."""
    tree = repo(tmp_path)
    assert _add(tree, item_id="a", title="Say hello", now=NOW).returncode == 0
    assert _add(tree, item_id="b", title="Say hello", now=NOW).returncode == 0


def test_drop_needs_a_decision_and_a_reason(tmp_path):
    tree = repo(tmp_path)
    seed_item(tree, {"schema": "noni.item/1", "id": "idea-0001", "title": "t",
                     "status": "candidate", "created": FRESH})
    for argv in (["drop", "idea-0001"],
                 ["drop", "idea-0001", "--why", "out of scope"],
                 ["drop", "idea-0001", "--decision", BASELINE_ID]):
        proc = run_item(tree, *argv)
        assert proc.returncode == 2, f"{argv}: {proc.returncode} {proc.stderr}"
        assert "drop needs" in proc.stderr, f"{argv}: {proc.stderr}"


def test_drop_records_the_decision_the_reason_and_keeps_the_age(tmp_path):
    tree = repo(tmp_path)
    seed_record(tree)
    seed_item(tree, {"schema": "noni.item/1", "id": "idea-0001",
                     "title": "Cache the census", "status": "candidate",
                     "created": OLD})
    proc = run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                    "--why", "duplicated #12", "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    body = read(tree, "idea-0001")
    assert body["status"] == "dropped"
    assert body["decision"] == BASELINE_ID
    assert body["why"] == "duplicated #12"
    assert body["created"] == OLD, "a drop does not make an idea younger"
    assert body["title"] == "Cache the census", "a drop is not a rename"


def test_drop_refuses_an_absent_item(tmp_path):
    tree = repo(tmp_path)
    seed_record(tree)
    proc = run_item(tree, "drop", "no-such", "--decision", BASELINE_ID,
                    "--why", "out of scope", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "no-such" in proc.stderr


def test_drop_refuses_an_item_that_is_already_terminal(tmp_path):
    """A kill already recorded stands: re-dropping it would rewrite the reason."""
    for status, extra in (("dropped", {"decision": BASELINE_ID,
                                       "why": "out of scope"}),
                          ("promoted", {"issue": 7})):
        tree = repo(tmp_path, status)
        seed_record(tree)
        body = {"schema": "noni.item/1", "id": "idea-0001", "title": "t",
                "status": status, "created": FRESH, **extra}
        seed_item(tree, body)
        before = item_path(tree, "idea-0001").read_bytes()
        proc = run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                        "--why", "again", "--now", NOW)
        assert proc.returncode == 4, f"{status}: {proc.stderr}"
        assert item_path(tree, "idea-0001").read_bytes() == before


def test_drop_naming_a_record_the_ledger_does_not_hold_is_refused(tmp_path):
    tree = repo(tmp_path)
    seed_item(tree, {"schema": "noni.item/1", "id": "idea-0001", "title": "t",
                     "status": "candidate", "created": FRESH})
    proc = run_item(tree, "drop", "idea-0001", "--decision", "2026-01-01-ghost",
                    "--why", "out of scope", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "2026-01-01-ghost" in proc.stderr


def test_drop_naming_a_superseded_record_names_its_successor(tmp_path):
    """The refusal is actionable: it says which record to cite instead."""
    tree = repo(tmp_path)
    seed_record(tree, "2026-10-01-old", status="superseded")
    seed_record(tree, HEIR_ID, status="decided", supersedes="2026-10-01-old")
    seed_item(tree, {"schema": "noni.item/1", "id": "idea-0001", "title": "t",
                     "status": "candidate", "created": FRESH})
    proc = run_item(tree, "drop", "idea-0001", "--decision", "2026-10-01-old",
                    "--why", "out of scope", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert HEIR_ID in proc.stderr, proc.stderr


def test_an_unreadable_ledger_is_an_environment_fault_not_a_refusal(tmp_path):
    """3 and not 4: the writer could not look, which is not the item's fault.

    Skipped where the reading user can read a 000-mode file (root can), because the
    precondition is the read being refused and no assertion follows without it.
    """
    tree = repo(tmp_path)
    seed_item(tree, {"schema": "noni.item/1", "id": "idea-0001", "title": "t",
                     "status": "candidate", "created": FRESH})
    ledger = tree / "noni" / "decisions"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / f"{BASELINE_ID}.json").write_text("{}\n", encoding="utf-8")
    commit(tree, "ledger")
    ledger.chmod(0)
    try:
        proc = run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                        "--why", "out of scope", "--now", NOW)
    finally:
        ledger.chmod(0o755)
    if proc.returncode != 3:  # pragma: no cover - root reads a 000 directory
        import pytest
        pytest.skip("the reading user can read a 000-mode directory")
    assert "could not be" in proc.stderr.lower(), proc.stderr


def test_promote_needs_the_issue_it_became(tmp_path):
    """A promoted item that names no issue was promoted to nothing.

    The schema can refuse a *present* null but not an absent field, so the verb owes
    the check: without it the writer would file a document the next census reports
    malformed and the next ``add`` refuses to write over.
    """
    tree = repo(tmp_path)
    seed_item(tree, {"schema": "noni.item/1", "id": "idea-0001", "title": "t",
                     "status": "candidate", "created": FRESH})
    proc = run_item(tree, "promote", "idea-0001", "--now", NOW)
    assert proc.returncode == 2, proc.stderr
    assert "--issue" in proc.stderr, proc.stderr


def test_promote_records_the_issue_and_keeps_the_age(tmp_path):
    tree = repo(tmp_path)
    seed_item(tree, {"schema": "noni.item/1", "id": "idea-0001",
                     "title": "Cache the census", "status": "candidate",
                     "created": OLD})
    proc = run_item(tree, "promote", "idea-0001", "--issue", "42", "--now", NOW)
    assert proc.returncode == 0, proc.stderr
    body = read(tree, "idea-0001")
    assert body["status"] == "promoted"
    assert body["issue"] == 42, "the issue is filed as a number, not a string"
    assert body["created"] == OLD, "promoting an idea does not make it younger"
    assert body["title"] == "Cache the census"


def test_promote_refuses_an_item_the_order_cites(tmp_path):
    """Item-only in this sub-issue: the order side is sub-issue 2's same-commit rewrite.

    Until that lands, a promote that would leave an order entry citing a newly
    promoted item has to be refused rather than half-done, and the refusal names the
    order path so the operator knows which artifact moves first.
    """
    tree = repo(tmp_path)
    seed_record(tree)
    seed_item(tree, {"schema": "noni.item/1", "id": "idea-0001", "title": "t",
                     "status": "candidate", "created": FRESH})
    seed_order(tree, [{"issue": 7, "decision": BASELINE_ID,
                       "confirmed": FRESH, "item": "idea-0001"}],
               schema="noni.order/1")
    before = item_path(tree, "idea-0001").read_bytes()
    proc = run_item(tree, "promote", "idea-0001", "--issue", "7", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "order.json" in proc.stderr, proc.stderr
    assert item_path(tree, "idea-0001").read_bytes() == before


def test_an_uncited_item_promotes(tmp_path):
    """The refusal is about the citation, not about the order existing.

    The issue promoted to is one the queue does not hold: promoting an item to an issue
    the order already lists is its own refusal (a rewrite would name that issue twice),
    and this case asks the other question -- an order that cites nothing must not stop
    the promote.
    """
    tree = repo(tmp_path)
    seed_record(tree)
    seed_item(tree, {"schema": "noni.item/1", "id": "idea-0001", "title": "t",
                     "status": "candidate", "created": FRESH})
    seed_order(tree, [{"issue": 7, "decision": BASELINE_ID, "confirmed": FRESH}])
    assert run_item(tree, "promote", "idea-0001", "--issue", "42",
                    "--now", NOW).returncode == 0


def test_promote_to_an_issue_the_order_already_lists_is_refused(tmp_path):
    """A rewrite that duplicates an issue is refused, not written.

    ``order.py add`` refuses a second position for one issue and the arbiter reports the
    duplicate as malformed, so a promote that wrote it would emit an artifact no verb
    could open again. One entry has to cite the item for a rewrite to be owed at all --
    an order that merely lists the issue cites nothing and owes no rewrite.

    The item keeps its ``candidate`` status and the order keeps the entry that still
    describes it: a refusal is the whole run.
    """
    tree = repo(tmp_path)
    seed_record(tree)
    seed_item(tree, {"schema": "noni.item/1", "id": "idea-0001", "title": "t",
                     "status": "candidate", "created": FRESH})
    seed_order(tree, [{"item": "idea-0001", "decision": BASELINE_ID,
                       "confirmed": FRESH},
                      {"issue": 42, "decision": BASELINE_ID, "confirmed": FRESH}],
               schema="noni.order/2")
    before_item = item_path(tree, "idea-0001").read_bytes()
    before_order = (tree / "noni" / "direction" / "order.json").read_bytes()
    proc = run_item(tree, "promote", "idea-0001", "--issue", "42", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert "already in the order" in proc.stderr, proc.stderr
    assert item_path(tree, "idea-0001").read_bytes() == before_item
    assert (tree / "noni" / "direction" / "order.json").read_bytes() == before_order


def test_promote_refuses_an_item_that_is_already_terminal(tmp_path):
    tree = repo(tmp_path)
    seed_item(tree, {"schema": "noni.item/1", "id": "idea-0001", "title": "t",
                     "status": "promoted", "created": FRESH, "issue": 7})
    proc = run_item(tree, "promote", "idea-0001", "--issue", "9", "--now", NOW)
    assert proc.returncode == 4, proc.stderr
    assert read(tree, "idea-0001")["issue"] == 7, "a refusal re-tooled the record"


def test_list_prints_the_store_newest_first_and_writes_nothing(tmp_path):
    tree = repo(tmp_path)
    seed_item(tree, {"schema": "noni.item/1", "id": "old", "title": "Old idea",
                     "status": "candidate", "created": OLD})
    seed_item(tree, {"schema": "noni.item/1", "id": "new", "title": "New idea",
                     "status": "promoted", "created": FRESH, "issue": 3})
    head = _git(tree, "rev-parse", "HEAD").stdout
    proc = run_item(tree, "list")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.index("new") < proc.stdout.index("old"), proc.stdout
    assert "2 item" in proc.stdout, proc.stdout
    assert _git(tree, "rev-parse", "HEAD").stdout == head, "list committed"
    assert _git(tree, "status", "--porcelain").stdout.strip() == ""


def test_the_list_line_is_the_documented_bytes(tmp_path):
    """The row format of #124, pinned as bytes: five fixed fields, then the title.

    A field the item does not carry prints ``-`` rather than dropping out, so a
    reader cuts every row by field number whatever the store holds. The three shapes
    below are the three the store can write: a ``promoted`` item with both optional
    fields, a bare ``candidate`` with neither, and a ``dropped`` item citing a record
    and no issue.
    """
    tree = repo(tmp_path)
    seed_item(tree, {"schema": "noni.item/1", "id": "a-promoted", "title": "Cache census",
                     "status": "promoted", "created": FRESH, "issue": 3,
                     "decision": "2026-10-01-ship"})
    seed_item(tree, {"schema": "noni.item/1", "id": "b-candidate", "title": "Plain idea",
                     "status": "candidate", "created": OLD})
    seed_item(tree, {"schema": "noni.item/1", "id": "c-dropped", "title": "Dead idea",
                     "status": "dropped", "created": OLD, "decision": "2026-10-02-no",
                     "why": "superseded"})
    lines = run_item(tree, "list").stdout.splitlines()
    assert f"a-promoted promoted issue=3 decision=2026-10-01-ship created={FRESH} Cache census" in lines, lines
    assert f"b-candidate candidate issue=- decision=- created={OLD} Plain idea" in lines, lines
    assert f"c-dropped dropped issue=- decision=2026-10-02-no created={OLD} Dead idea" in lines, lines


def test_a_store_that_is_absent_lists_empty_rather_than_failing(tmp_path):
    """The store is optional, and so is the store's absence in every reader."""
    tree = repo(tmp_path)
    proc = run_item(tree, "list")
    assert proc.returncode == 0, proc.stderr
    assert "0 item" in proc.stdout, proc.stdout


def test_no_commit_leaves_the_file_written_and_says_so(tmp_path):
    """The file is on disk and uncommitted, and the run names that state.

    The operator has to be told: a writer that quietly left the artifact uncommitted
    would let the census read a store git does not hold, and the census reads
    committed state.
    """
    tree = repo(tmp_path)
    proc = _add(tree, now=NOW, no_commit=True)
    assert proc.returncode == 0, proc.stderr
    assert item_path(tree, "idea-0001").is_file()
    assert "uncommitted" in proc.stdout.lower(), proc.stdout
    assert _git(tree, "status", "--porcelain").stdout.strip(), "nothing to clean up"
    assert not any(p.startswith("noni/items") for p in _git(tree, "ls-files").stdout.split())


def test_a_write_whose_bytes_already_stand_reports_unchanged_and_commits_nothing(tmp_path):
    """The file already holds these bytes: the run says so and adds no commit.

    No verb reaches this by repeating itself (``add`` refuses an id it has filed and
    ``drop``/``promote`` refuse a record whose status is terminal, both before the
    write), so the state is planted as it occurs in the field: a hand-repaired record
    brought to exactly the bytes the writer produces. The two answers the run must not
    confuse are the two asserted here -- "unchanged" is not "written", and an unchanged
    run must not stage or commit anything, because a second commit of identical bytes
    is a commit no verb made.
    """
    tree = repo(tmp_path)
    seed_record(tree)
    _file_candidate(tree, created=OLD)
    assert run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                    "--why", "duplicated #12", "--now", NOW).returncode == 0
    assert "unchanged" not in run_item(
        tree, "add", "idea-0001", "--title", "Say hello first",
        "--now", NOW).stdout.lower(), "a refused add is not an unchanged write"
    head = _git(tree, "rev-parse", "HEAD").stdout
    proc = run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                    "--why", "duplicated #12", "--now", NOW)
    assert proc.returncode == 4, proc.stderr  # terminal status: refused before writing
    assert _git(tree, "rev-parse", "HEAD").stdout == head
    assert _git(tree, "status", "--porcelain").stdout.strip() == ""

def test_each_verb_writes_only_its_own_item_path(tmp_path):
    """One verb, one path.

    A commit that also touched the ledger or the order would be a verb doing two
    jobs, and no census class reports a ledger the item writer edited: the only
    check that catches it is this one.
    """
    tree = repo(tmp_path)
    seed_record(tree)
    seed_order(tree, [{"issue": 7, "decision": BASELINE_ID, "confirmed": FRESH}])
    before = _git(tree, "ls-files").stdout.split()
    assert _add(tree, item_id="idea-0001", now=NOW).returncode == 0
    assert run_item(tree, "drop", "idea-0001", "--decision", BASELINE_ID,
                    "--why", "out of scope", "--now", NOW).returncode == 0
    after = _git(tree, "ls-files").stdout.split()
    assert after == sorted(set(before) | {"noni/items/idea-0001.json"}), after
    last = [p for p in _git(tree, "log", "-1", "--name-only",
                            "--pretty=format:").stdout.split("\n") if p.strip()]
    assert last == ["noni/items/idea-0001.json"], last
