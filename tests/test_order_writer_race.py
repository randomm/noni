"""The two-writer race of order.py: the lost update, and the refusal that ends it.

Before issue #116 the writer read ``noni/direction/order.json`` once, planned from
those entries, then wrote and committed with ``git commit --only -- <path>``. The
commit carries the bytes sitting in the working tree, so a second writer that
committed between the read and the commit had its entry dropped from HEAD with exit
0 -- and an ``add --at 1`` computed against the stale list landed at a position
nobody chose.

The fix is a re-read of the committed bytes immediately before the write, and an
exit-4 refusal when they moved. This module reproduces the race deterministically --
a rival commit placed before the losing run reaches its write, never two processes
racing a window of a few milliseconds -- and pins the four things that make the
refusal honest: it refuses, it writes nothing, the first writer's entry survives, and
a re-run of the same command succeeds with both entries.

Every run here goes through ``order_fixtures._order_inprocess``: the probe, a lying
``git show`` and the tripwire on ``write_atomic`` are patches on the package module,
and the writer only sees them by running *in that module*. The subprocess launcher
would spawn the installed package instead, and a guard test whose patch landed on a
different copy of the module reports success for a guard that was never installed --
the worst way for such a test to fail. The wrapper route stays covered by
``tests/test_console_routes.py``, which pairs it against ``noni order`` byte for byte.
"""


import pytest
from order_doc_readers import _skill_section
from order_fixtures import (
    BASELINE_ID,
    NOW,
    ORDER_REL,
    STAMP,
    _assert_census_clean,
    _committed_order,
    _entry,
    _gitwrite_module,
    _issues,
    _order_inprocess,
    _order_module,
    _order_path,
    _porcelain,
    _read,
    _repo,
    _seed,
)
from order_race_fixtures import (
    FILE_CHANGED,
    REFUSAL,
    _checkout_head,
    _head,
    _issues_in_head,
    _race_entry,
    _rival_raced,
    interrupt_read,
)

# --- the race itself ----------------------------------------------------------


def test_a_second_writer_between_the_read_and_the_commit_is_refused_and_the_first_entry_survives(
        tmp_path):
    """The repro of the descriptor, in one working copy.

    Writer A commits ``add 33 --at 1``. Writer B then runs ``add 44 --at 1`` while
    still planning from the entries it read before A landed. B is refused at exit 4
    with the wording that names the fix, and A's entry is still in HEAD -- which is
    the whole point: the pre-fix run exited 0 and A's #33 was gone.
    """
    repo = _repo(tmp_path)
    _seed(repo, _race_entry(11), _race_entry(22))
    assert _order_inprocess(repo, "add", "33", "--at", "1", "--decision", BASELINE_ID,
                            "--now", NOW)[0] == 0

    # B's read has already happened by the time the rival commits: this is the state
    # B's write phase would have found had the two processes interleaved.
    _rival_raced(repo, (55, BASELINE_ID))
    # The two states the rival leaves behind, named separately because the refused
    # run has to leave each of them alone: HEAD holds the rival's committed order
    # (which is not the file's bytes, and that disagreement *is* the race), and the
    # file still holds the order this run read.
    rival_head = _head(repo)
    rival_committed = _committed_order(repo)
    artifact_before = _order_path(repo).read_bytes()
    porcelain_before = _porcelain(repo)

    code, out, err = _order_inprocess(repo, "add", "44", "--at", "1",
                                      "--decision", BASELINE_ID, "--now", NOW)
    assert code == 4, (code, out + err)
    assert REFUSAL in err, err
    # A run that wrote nothing may not print the order it planned as if it were the
    # order that stood: the printed order is the success signal.
    assert "order.json (" not in out, out
    assert "committed" not in out, out

    # The first writer's entry survives, and B moved nothing at all.
    assert 33 in _issues_in_head(repo), "the first writer's entry was dropped from HEAD"
    assert _committed_order(repo) == rival_committed, "the refused run rewrote HEAD"
    assert _order_path(repo).read_bytes() == artifact_before
    assert 33 in _issues(repo), "the first writer's entry was dropped"
    assert _head(repo) == rival_head, "a refused run must not advance HEAD"
    # The tree is modified against HEAD before the run starts, by the race itself:
    # HEAD holds the rival's bytes and the file holds what this run read. So the
    # claim is that the refused run left the working area exactly as it found it,
    # not that the tree was clean.
    assert _porcelain(repo) == porcelain_before, (
        f"{_porcelain(repo)} != {porcelain_before}")


def test_the_refused_run_writes_no_file_and_stages_nothing(tmp_path, monkeypatch):
    """The refusal is raised before ``write_atomic`` is ever entered.

    The atomic writer is replaced by a tripwire, so a run that reached the write
    phase fails here rather than leaving bytes to be compared afterwards; the
    artifact keeps the bytes it had and no temp file appears in its directory, which
    is the same temp-file honesty ``tests/test_order_writer_arbiter.py`` pins for the
    other refusals.
    """
    helper = _gitwrite_module()
    module = _order_module()
    written: list = []

    def tripwire(path, data):
        written.append(path)
        raise AssertionError("the refused run reached the write phase")

    monkeypatch.setattr(helper, "write_atomic", tripwire)
    repo = _repo(tmp_path)
    _seed(repo, _race_entry(11), _race_entry(22))
    _rival_raced(repo, (55, BASELINE_ID))
    artifact_before = _order_path(repo).read_bytes()

    code, _out, _err = _order_inprocess(repo, "add", "44", "--at", "1",
                                        "--decision", BASELINE_ID, "--now", NOW)
    assert code == module.EXIT_REFUSAL, code
    assert written == [], f"the run wrote {written}"
    assert _order_path(repo).read_bytes() == artifact_before
    assert sorted(p.name for p in _order_path(repo).parent.iterdir()) == ["order.json"]


def test_a_refused_add_then_a_rerun_lands_both_entries_at_the_position_asked(tmp_path):
    """AC3's second half and the ``--at N`` symptom of the descriptor.

    The remedy is a re-run of the same command, so the re-run has to be the whole
    fix: exit 0, and #44 at position 1 of an order that still carries the rival's
    #55. The position is resolved against the entries the second run read -- not
    against the stale list the refused run planned from, which is how the pre-fix
    run put #44 somewhere nobody had asked for.

    The rival here is a second writer that got its own entry committed, so the
    order on disk is what a re-run reads once the race has settled: the first run
    is refused for planning against bytes HEAD no longer holds, and the re-run
    re-reads, sees the rival's #55, and lands #44 in front of it.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID), _entry(22, BASELINE_ID))
    assert _order_inprocess(repo, "add", "33", "--at", "1", "--decision", BASELINE_ID,
                            "--now", NOW)[0] == 0
    _rival_raced(repo, (55, BASELINE_ID))

    code, _out, err = _order_inprocess(repo, "add", "44", "--at", "1",
                                       "--decision", BASELINE_ID, "--now", NOW)
    assert code == 4, code
    assert REFUSAL in err, err

    # The race has settled: the working copy is brought back to what HEAD holds, so
    # the re-run reads the rival's committed order and has no stale baseline left to
    # be refused for. This is what the operator does after a refusal -- sync the
    # checkout and run again -- and it is why the remedy is a re-run and not a flag.
    _checkout_head(repo)
    code, out, err = _order_inprocess(repo, "add", "44", "--at", "1",
                                      "--decision", BASELINE_ID, "--now", NOW)
    assert code == 0, err
    assert sorted(_issues(repo)) == [11, 22, 33, 44, 55], _issues(repo)
    entries = _read(repo)["entries"]
    assert [e["issue"] for e in entries].index(44) == 0, entries
    assert entries[0]["confirmed"] == STAMP, entries[0]
    assert "committed" in out, out


def _flat(text):
    """``text`` with every run of whitespace down to one space (the page wraps)."""
    return " ".join(text.split())


def test_a_rerun_on_a_stale_checkout_is_refused_rather_than_claimed_unchanged(tmp_path):
    """The remedy the skill documents has to be the whole remedy, in both states.

    After a refusal the operator re-runs the same command. A checkout synced to HEAD
    re-plans from the rival's entries and commits (pinned by
    ``test_a_refused_add_then_a_rerun_lands_both_entries_at_the_position_asked``).
    A checkout still holding the refused run's own bytes used to be the hole: the
    run's plan reproduced the bytes on disk, so it took the writer's no-change
    shortcut, printed "is unchanged; nothing to commit" and exited 0 while HEAD still
    lacked the entry the operator had just confirmed -- no probe, no commit, no
    warning. The shortcut is issue #76's idempotent repeat and stays, so instead it is
    now guarded by the same committed-bytes read: a shortcut is only taken when HEAD
    agrees with the file it is compared against.
    """
    repo = _repo(tmp_path)
    _seed(repo, _race_entry(11), _race_entry(22))
    assert _order_inprocess(repo, "add", "33", "--at", "1", "--decision", BASELINE_ID,
                            "--now", NOW)[0] == 0
    _rival_raced(repo, (55, BASELINE_ID))
    refused = _order_inprocess(repo, "add", "44", "--at", "1",
                               "--decision", BASELINE_ID, "--now", NOW)
    assert refused[0] == 4, refused

    # No sync: the file still holds what the refused run read, and the same command
    # now plans to exactly those bytes. It must be refused, not reported as a no-op.
    code, out, err = _order_inprocess(repo, "add", "44", "--at", "1",
                                      "--decision", BASELINE_ID, "--now", NOW)
    assert code == 4, (code, out + err)
    assert REFUSAL in err, err
    assert "unchanged; nothing to commit" not in out, out
    assert 44 not in _issues_in_head(repo), _issues_in_head(repo)

    # The synced re-run is still the fix, and the page says the checkout has to agree
    # with HEAD before the re-run settles anything.
    _checkout_head(repo)
    code, out, err = _order_inprocess(repo, "add", "44", "--at", "1",
                                      "--decision", BASELINE_ID, "--now", NOW)
    assert code == 0, (code, out + err)
    assert "committed" in out, out
    assert 44 in _issues_in_head(repo), _issues_in_head(repo)

    page = _flat(_skill_section("Writing the order"))
    assert "checkout" in page or "sync" in page, (
        "SKILL.md's re-run remedy promises both entries without saying the working "
        "copy has to agree with HEAD first")


def test_the_refused_run_leaves_the_ordering_census_clean(tmp_path):
    """A refusal is not a census class.

    The census is the arbiter, and the order that survives a refused run is
    well-formed and committed, so the three ordering classes stay at exit 0 with no
    rows: the guard adds no signal for the arbiter to report.
    """
    repo = _repo(tmp_path)
    _seed(repo, _race_entry(11))
    _rival_raced(repo, (55, BASELINE_ID))
    assert _order_inprocess(repo, "confirm", "--now", NOW)[0] == 4
    _assert_census_clean(repo, "the refused run")


# --- every writing verb -------------------------------------------------------


def _refused_by_a_rival_commit(tmp_path, name, *argv):
    """One verb, raced: the rival commits first and this verb must refuse at 4.

    The four verbs share the writer's single write phase, so they share the guard.
    Each case asserts the post-conditions of an honest refusal -- exit 4 with the
    wording that names the fix, the order not printed as if committed, HEAD and the
    artifact unmoved, nothing staged -- and no verb is covered by a loop over shapes
    it never drives: ``confirm`` here is the whole-order form, which restamps every
    entry and so is the verb with the largest blast radius if the guard missed it.
    """
    repo = _repo(tmp_path, f"race-{name}")
    _seed(repo, _race_entry(11), _race_entry(22))
    _rival_raced(repo, (55, BASELINE_ID))
    # HEAD holds the rival's order and the file holds what this run read: the
    # refused run must leave both exactly where the rival left them.
    head_before = _head(repo)
    committed_before = _committed_order(repo)
    artifact_before = _order_path(repo).read_bytes()
    # The tree is already modified before the run starts -- HEAD holds the rival's
    # order and the file holds what this run read, so they differ by design. What
    # the refusal has to preserve is that exact state, staged or unstaged, which is
    # why the working area is compared and not `_porcelain` against empty.
    porcelain_before = _porcelain(repo)

    code, out, err = _order_inprocess(repo, *argv, "--now", NOW)
    assert code == 4, f"{name}: exit {code}: {err}"
    assert REFUSAL in err, f"{name}: {err}"
    assert "order.json (" not in out, f"{name}: {out}"
    assert _committed_order(repo) == committed_before, f"{name}: HEAD's order moved"
    assert _order_path(repo).read_bytes() == artifact_before, f"{name}: the file moved"
    assert _head(repo) == head_before, f"{name}: a refused run advanced HEAD"
    assert _porcelain(repo) == porcelain_before, (
        f"{name}: {_porcelain(repo)} != {porcelain_before}")
    return repo


# AC2, for every verb that writes. The four cases share the writer's write phase and
# therefore the guard, so the shapes are driven from one table rather than four
# near-identical bodies, and each of the guard's two causes is driven per verb: a
# moved HEAD (the concurrent writer a re-run fixes) and a changed working file with
# HEAD unmoved (a local state no re-run fixes, and the reason the two refusals are
# worded differently).
_WRITE_VERBS = [
    ("add", ("add", "44", "--at", "1", "--decision", BASELINE_ID)),
    ("move", ("move", "22", "--to", "1")),
    ("remove", ("remove", "22")),
    ("confirm", ("confirm",)),
]


@pytest.mark.parametrize("name,argv", _WRITE_VERBS)
def test_every_writing_verb_refuses_a_committed_order_that_moved(tmp_path, name, argv):
    """AC2: add, move, remove and confirm each refuse the rival's commit at exit 4."""
    repo = _refused_by_a_rival_commit(tmp_path, name, *argv)
    if name == "add":
        # The rival's order is the one that still stands, and this run added nothing
        # to it: HEAD holds the rival's committed entries and the run wrote no file.
        assert _issues_in_head(repo) == [11, 22, 55], _issues_in_head(repo)


@pytest.mark.parametrize("name,argv", _WRITE_VERBS)
def test_every_writing_verb_refuses_a_working_file_it_no_longer_recognises(
        tmp_path, name, argv):
    """AC2's other arm, per verb: the file moved and HEAD did not.

    The second comparison of the guard exists for this case alone, and a verb that
    consulted only HEAD would write over bytes it never read. Same post-conditions as
    the rival case, different wording: the file refusal names the file.
    """
    module = _order_module()
    repo = _repo(tmp_path, f"filed-{name}")
    _seed(repo, _race_entry(11), _race_entry(22))
    head_before = _head(repo)
    committed_before = _committed_order(repo)
    real_read = module.orderstate.read_order

    def read_then_edit(path):
        read = real_read(path)
        path.write_bytes(path.read_bytes() + b"\n")
        return read

    with interrupt_read(module, "read_order", read_then_edit):
        code, out, err = _order_inprocess(repo, *argv, "--now", NOW)
    assert code == module.EXIT_REFUSAL, f"{name}: exit {code}: {err}"
    assert FILE_CHANGED in err, f"{name}: {err}"
    assert REFUSAL not in err, f"{name}: {err}"
    assert _head(repo) == head_before, f"{name}: a refused run advanced HEAD"
    assert _committed_order(repo) == committed_before, f"{name}: HEAD's order moved"


# --- --no-commit keeps its contract ------------------------------------------

def test_no_commit_still_writes_the_file_and_moves_no_head_when_the_order_moved(tmp_path):
    """The pinned ``--no-commit`` contract survives the guard.

    That route runs no git at all, so there is nothing to compare against and no
    commit to lose: it writes the file, exits 0 and leaves HEAD where it was, even
    with a rival commit behind it. A guard that compared HEAD here would refuse every
    run of Route B in the quickstart, where a whole train of writers runs before the
    first commit.

    The order it writes is built from the entries on disk, which the race leaves at
    the baseline: #44 joins 11 and 22, and the rival's entry stays in HEAD alone.
    That is the point of the exemption -- Route B is the route that has no committed
    state to be honest about, so what it writes is what it read plus what it was told
    to add, and a later committed run is the one that has to face the rival.
    """
    repo = _repo(tmp_path)
    _seed(repo, _race_entry(11), _race_entry(22))
    _rival_raced(repo, (55, BASELINE_ID))
    head_before = _head(repo)
    code, _out, err = _order_inprocess(repo, "add", "44", "--at", "1",
                                       "--decision", BASELINE_ID, "--now", NOW,
                                       "--no-commit")
    assert code == 0, err
    assert REFUSAL not in err, err
    assert _issues(repo) == [44, 11, 22], _issues(repo)
    assert _head(repo) == head_before
    # Both the file and the index moved against HEAD: the writer put its own bytes
    # on disk and left them unstaged, exactly as --no-commit is contracted to.
    assert _porcelain(repo, ORDER_REL) == f"MM {ORDER_REL}", _porcelain(repo, ORDER_REL)


def test_no_commit_asks_git_nothing_at_all(tmp_path, monkeypatch):
    """No ``git add``, no ``git commit``, and no probe either.

    The exemption is structural, not a comparison that happens to pass: the
    --no-commit route makes no git call of any kind, so there is no code path on
    which it could be refused for a committed change it cannot see. Both halves of
    the writer's git helper are watched, the text one that stages and commits and
    the binary one the probe reads the committed blob through.
    """
    helper = _gitwrite_module()
    calls: list[tuple] = []

    def no_git(repo, *args):
        calls.append(args)
        raise AssertionError(f"--no-commit made a git call: {args}")

    monkeypatch.setattr(helper, "git", no_git)
    monkeypatch.setattr(helper, "git_bytes", no_git)
    repo = _repo(tmp_path)
    _seed(repo, _race_entry(11), _race_entry(22))
    _rival_raced(repo, (55, BASELINE_ID))
    code, _out, err = _order_inprocess(repo, "add", "44", "--decision", BASELINE_ID,
                                       "--now", NOW, "--no-commit")
    assert code == 0, err
    assert calls == [], calls
