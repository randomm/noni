"""What the freshness probe does with each answer it can get.

The companion to ``tests/test_order_writer_race.py``, which races a rival commit
against the writer. This file asks the probe alone, because a guard that refuses the
wrong answer is as bad as a guard that is absent:

  nothing there   -- absence is a value and not a wildcard. The first add into a
                     fresh repository has ``before`` of ``None`` and must not be
                     refused for it.
  bytes it did not read -- a change, and a refusal, including the arm where the run
                     read no file at all and an order appeared behind its back.
  a call that could not answer -- exit 3, the environment's fault: a hang read as
                     "unchanged" would commit an order nobody checked, and a corrupt
                     object store read as "nothing there" would commit over an order
                     the run never saw.

Runs go through ``order_fixtures._order_inprocess`` for the reason that module gives.
"""

import os
import subprocess

import pytest

from order_fixtures import (
    BASELINE_ID,
    NOW,
    ORDER_REL,
    _bare_repo,
    _committed_order,
    _entry,
    _gitwrite_module,
    _issues,
    _order,
    _order_inprocess,
    _order_module,
    _order_path,
    _porcelain,
    _repo,
    _rival_commit,
    _seed,
)
from order_race_fixtures import (
    FILE_CHANGED,
    REFUSAL,
    RIVAL_STAMP,
    _head,
    interrupt_read,
)

# --- the probe's own answers --------------------------------------------------


def test_a_first_add_into_an_uncommitted_tree_is_not_a_refusal(tmp_path):
    """``before is None`` is decided explicitly: no committed bytes is not a change.

    The very first ``add`` has nothing to compare against, and a probe that read
    git's honest "path does not exist in 'HEAD'" as a moved order would refuse every
    fresh order in the product.
    """
    repo = _repo(tmp_path)
    code, _out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                       "--now", NOW)
    assert code == 0, err
    assert _issues(repo) == [7]
    assert _committed_order(repo) == _order_path(repo).read_bytes()


def test_an_unborn_head_reads_as_nothing_committed_for_the_probe(tmp_path):
    """A repository with no commit at all holds nothing, and says so honestly.

    ``git show HEAD:<path>`` under an unborn HEAD answers 128 with "invalid object
    name 'HEAD'.", which is git's way of saying there is no tree to look in. A probe
    that read that as a repository it could not read would refuse the first committed
    order with exit 3, and the quickstart's brand new private state repository could
    never hold an order.
    """
    helper = _gitwrite_module()
    repo = _bare_repo(tmp_path)
    answer = helper.committed_bytes(repo, ORDER_REL)
    assert answer.data is None and answer.code is None, (
        f"an unborn HEAD must read as nothing committed, not as a fault: {answer}")


def test_the_first_committed_order_of_a_fresh_repository_is_committed(tmp_path):
    """The same fault at the top of the writer: ``order add`` into a repo with no commit.

    Driven as a subprocess, because this is the route the quickstart tells the
    operator to take: ``git init`` a private state repository, then write the order
    into it. Exit 0 and one commit holding the entry is the whole contract, and exit
    3 here is a probe that mistook an empty history for a broken repository.
    """
    repo = _bare_repo(tmp_path)
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _issues(repo) == [7]
    assert _committed_order(repo) == _order_path(repo).read_bytes()
    assert _porcelain(repo) == "", "the first committed order left the tree dirty"


def test_a_first_add_is_refused_when_a_committed_order_appears_during_the_run(tmp_path):
    """The other arm of the same decision: bytes that appeared are a change.

    ``None`` is what the artifact read hands back for a path that does not exist, so
    it is the value the guard compares when the run read nothing. Read as a wildcard
    it matches an absent HEAD too and the run commits its one entry over an order it
    never saw; read as a value it refuses the moment HEAD answers with bytes.

    The rival's order is committed for real and nothing sits at the path, so the
    only asymmetry is the one under test: nothing read, HEAD holding an order.
    """
    repo = _repo(tmp_path)
    _rival_commit(repo, [_entry(55, BASELINE_ID, RIVAL_STAMP)])
    committed = _committed_order(repo)
    assert committed is not None, "the rival's order is not committed"

    code, out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                      "--now", NOW)
    assert code == 4, (code, out + err)
    assert REFUSAL in err, err
    assert not _order_path(repo).exists(), "a refused first add must not create the file"
    assert _committed_order(repo) == committed, "the rival's committed order did not stand"


def test_the_probe_compares_bytes_and_not_a_decoded_or_rebuilt_form(tmp_path,
                                                                   monkeypatch):
    """What is compared is the byte sequence, with no decode and no re-render.

    ``git show`` answers with the committed bytes plus one trailing newline. A
    comparison that stripped, normalised line endings or re-rendered the parsed value
    would call that a match and commit over the rival; one that decoded would die on
    bytes no artifact should hold. The probe hands the bytes over verbatim and the
    writer refuses.
    """
    helper = _gitwrite_module()
    module = _order_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    committed = _committed_order(repo)
    assert committed is not None

    def show(*args):
        # The committed blob with one extra trailing newline: bytes the run did not
        # read, differing from them only in a byte a decoder would have dropped.
        # Text mode with errors="replace" would round-trip this to the very bytes
        # the run read and call a moved HEAD a match; a binary read cannot.
        return subprocess.CompletedProcess(["git", *args], 0, committed + b"\n\n", b"")

    monkeypatch.setattr(helper, "git_bytes", show)
    code, _out, _err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                        "--now", NOW)
    assert code == module.EXIT_REFUSAL, code


def test_the_probe_reads_the_committed_blob_as_raw_bytes(tmp_path, monkeypatch):
    """The comparison is made on bytes, and no decode stands between the two sides.

    A blob holding a byte no decoder can represent (a stray 0xFF in a position the
    artifact's JSON would never put) must reach the caller unchanged: decoded through
    text mode with ``errors="replace"`` it comes back as U+FFFD, and a run that
    compared that would call a moved HEAD and its own read the same bytes.
    """
    helper = _gitwrite_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    blob = b'{"schema": "noni.order/1", "entries": []}\n\xff\xfe'

    def show(repo_arg, *args):
        # Bound: the probe must have asked for the artifact's own path in HEAD, or
        # the comparison below is a fixed answer and proves nothing about scoping.
        assert args == ("show", f"HEAD:{ORDER_REL}"), args
        return subprocess.CompletedProcess(["git", *args], 0, blob, b"")

    monkeypatch.setattr(helper, "git_bytes", show)
    answer = helper.committed_bytes(repo, ORDER_REL)
    assert answer.data == blob, f"the blob was not handed over verbatim: {answer.data!r}"


def test_a_working_file_that_changed_while_head_stood_names_the_file(tmp_path):
    """The other cause of the guard's exit 4, told apart from a rival commit.

    Only a moved HEAD is fixed by re-running the same command. When the committed
    order never moved and the file no longer holds what this run read (a local edit
    that outlived the read, a stash), a re-run is refused again and again, and the
    concurrency hint -- "the order that was committed while it ran still stands" --
    would be a claim this run did not observe. So the refusal names the read that
    moved and gives the fix that settles it.

    The run is driven in-process with the artifact read interrupted after it parsed,
    which is the deterministic way to put the run in that window: no other fixture
    leaves HEAD holding what the run read while the file holds something else.
    """
    module = _order_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    head_before = _head(repo)
    committed_before = _committed_order(repo)
    real_read = module.orderstate.read_order

    def read_then_edit(path):
        read = real_read(path)
        path.write_bytes(path.read_bytes() + b"\n")
        return read

    with interrupt_read(module, "read_order", read_then_edit):
        code, out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                          "--now", NOW)
    assert code == module.EXIT_REFUSAL, (code, out + err)
    assert REFUSAL not in err, f"no rival committed here: {err}"
    assert FILE_CHANGED in err, err
    assert "still stands" not in err, err
    assert ORDER_REL in err and "checkout HEAD" in err, err
    assert _head(repo) == head_before, "a refused run advanced HEAD"
    assert _committed_order(repo) == committed_before, "a refused run rewrote HEAD"


def test_a_committed_change_still_names_the_concurrent_writer(tmp_path):
    """The two arms stay distinguishable: a moved HEAD keeps the pinned wording.

    The deletion test above proves the file arm does not print the concurrency
    sentence; this proves the reverse, so the split cannot be a single message with
    a hint that happens to mention the wrong cause in one of the two cases.
    """
    module = _order_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    committed = _committed_order(repo)
    real_read = module.orderstate.read_order

    def read_then_move_head(path):
        read = real_read(path)
        # HEAD moves after the read and the file stays put: the concurrent writer,
        # with no working-tree change mixed in.
        _rival_commit(repo, [_entry(11, BASELINE_ID), _entry(55, BASELINE_ID,
                                                             RIVAL_STAMP)])
        return read

    with interrupt_read(module, "read_order", read_then_move_head):
        code, _out, err = _order_inprocess(repo, "add", "7", "--decision",
                                           BASELINE_ID, "--now", NOW)
    assert code == 4, (code, err)
    assert REFUSAL in err, err
    assert FILE_CHANGED not in err, err
    assert _committed_order(repo) != committed, "the rival's commit did not land"


# --- a probe that cannot answer is an environment fault -----------------------


def test_a_path_that_became_a_symlink_is_a_fault_not_a_concurrent_writer(tmp_path):
    """The guard's second read names what it actually found at the path.

    The file arm of the guard and the HEAD arm have different remedies: a rival
    commit is fixed by a re-run, a path that is no longer a plain readable file is
    fixed by putting the file back. Telling the operator to re-run against a symlink
    would send them chasing a writer that was never there, and the writer never
    follows a link, so the run stops at exit 3 with the shape it found.
    """
    module = _order_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    outside = tmp_path / "outside-order.json"
    outside.write_bytes(_order_path(repo).read_bytes())
    _order_path(repo).unlink()
    _order_path(repo).symlink_to(outside)
    head_before = _head(repo)

    code, out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                      "--now", NOW)
    assert code == module.EXIT_IO, (code, out + err)
    assert REFUSAL not in err, f"a symlink is not a concurrent writer: {err}"
    assert "symlink" in err, err
    assert "re-run" in err, err
    assert _head(repo) == head_before, "a faulted probe must not commit"
    assert _order_path(repo).is_symlink(), "a refused run replaced the operator's link"


def test_a_path_that_became_a_directory_is_a_fault_not_a_concurrent_writer(tmp_path):
    """The same arm, other shape: a directory where the artifact was read.

    The two shapes the reader refuses before the guard is ever reached cannot reach
    it from a run that read bytes, so this is the state the guard's own second read
    has to answer for, and it answers as the environment's fault rather than as
    absence (which would read as a change and blame a writer that never ran).
    """
    module = _order_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    target = _order_path(repo)
    target.unlink()
    target.mkdir()
    code, out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                      "--now", NOW)
    assert code == module.EXIT_IO, (code, out + err)
    assert REFUSAL not in err, err
    assert "directory" in err, err


def _drive_add_with_probe(repo, monkeypatch, answer):
    """Run a committed ``add`` whose freshness probe answers ``answer``.

    Only the probe's own call is intercepted: the ``add`` and ``commit`` the writer
    makes afterwards run for real, so a probe read as "unchanged" really does land a
    commit and a probe read as a fault really does stop before one. The intercepted
    call is ``git_bytes``, the binary half of the helper the probe reads the blob
    through -- the write half, ``git``, stays the real one.
    """
    helper = _gitwrite_module()
    real_git = helper.git_bytes
    probes: list[tuple] = []

    def git_bytes(repo, *args):
        if args and args[0] == "show":
            probes.append(args)
            return answer(args)
        return real_git(repo, *args)

    # The repository is built first and the spy installed only for the run under
    # test: the spy answers every ``git show``, the fixture's own included, and the
    # harness commits through helpers that read HEAD as well, so a spy in place while
    # the tree is built makes the fixture die on a fault that belongs to nothing in
    # the scenario.
    monkeypatch.setattr(helper, "git_bytes", git_bytes)
    code, out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                      "--now", NOW)
    return code, out, err, probes


def _hung(args):
    """What the writer's own helper hands back for a call that cannot finish."""
    return subprocess.CompletedProcess(["git", "show", *args],
                                       _gitwrite_module().GIT_TIMEOUT_RC, b"",
                                       b"git show timed out")


def _failed(args):
    """128 for a reason that is not git's honest 'not in HEAD' answer."""
    return subprocess.CompletedProcess(["git", "show", *args], 128, b"",
                                       b"fatal: bad object HEAD")


def test_a_probe_that_hangs_is_exit_three_naming_the_call(tmp_path, monkeypatch):
    """A hung ``git show`` is an environment fault, never "unchanged, go ahead".

    Reading a timeout as a match would commit an order whose state nobody checked --
    the same class of lie as the lost update -- so the run stops at exit 3, names the
    call that could not answer, and never reaches the write or the commit.
    """
    module = _order_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    head_before = _head(repo)
    committed_before = _committed_order(repo)
    code, out, err, probes = _drive_add_with_probe(repo, monkeypatch, _hung)
    assert code == module.EXIT_IO, code
    assert len(probes) == 1, probes
    assert "timed out" in err, err
    assert str(_gitwrite_module().GIT_TIMEOUT) in err, err
    assert REFUSAL not in err, f"a hung probe is not a concurrent writer: {err}"
    assert "committed" not in out, out
    assert _head(repo) == head_before, "a refused run committed"
    assert _committed_order(repo) == committed_before, "a refused run moved the order"
    assert 7 not in _issues(repo), "a refused run must not have written its entry"


def test_a_probe_that_failed_for_a_reason_that_told_us_nothing_is_exit_three(
        tmp_path, monkeypatch):
    """128 with git's "not in HEAD" wording is absence; 128 for any other reason is a
    fault. Both arms of the probe are pinned so an implementation cannot collapse
    them, which is how a corrupt object store would otherwise read as "no committed
    bytes" and let the run commit over an order it never saw."""
    module = _order_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    code, _out, err, probes = _drive_add_with_probe(repo, monkeypatch, _failed)
    assert code == module.EXIT_IO, code
    assert len(probes) == 1, probes
    assert "git show failed" in err, err
    assert REFUSAL not in err, err
    assert 7 not in _issues(repo), "the unwritten order must not have been written"


def test_the_probe_is_one_hardened_git_call_of_the_writer_s_own_helper(tmp_path,
                                                                       monkeypatch):
    """The probe reuses the writer's own ``git()``: one git runner, hardened, bounded.

    The argv is what carries the hardening (no signing, no hooks, no external
    transports, no fsmonitor) and the scoped path, so the assertion is on the command
    line the probe built -- one ``show`` of the artifact's path, and no second runner
    of its own to drift from the first.
    """
    helper = _gitwrite_module()
    real_git = helper.git_bytes
    seen: list[tuple] = []

    def git_bytes(repo, *args):
        seen.append(args)
        return real_git(repo, *args)

    # The repository is built first and the spy installed only for the run under
    # test: the spy answers every ``git show``, the fixture's own included, and the
    # harness commits through helpers that read HEAD as well, so a spy in place while
    # the tree is built makes the fixture die on a fault that belongs to nothing in
    # the scenario.
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    monkeypatch.setattr(helper, "git_bytes", git_bytes)
    code, _out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                       "--now", NOW)
    assert code == 0, err
    assert ("show", f"HEAD:{ORDER_REL}") in seen, seen
    shows = [args for args in seen if args[0] == "show"]
    assert len(shows) == 1, f"the probe ran {len(shows)} git calls: {shows}"

def test_a_file_that_cannot_be_read_is_a_fault_naming_the_reason(tmp_path):
    """The read arm that is neither absence nor a readable file: an unreadable file.

    ``lstat`` answers "regular", so the shape is not the problem and the read itself
    must fail. The run then reports the environment's fault (exit 3) with the reason
    it got, never the exit-4 "re-run" a concurrent writer gets: a chmod the operator
    has to undo is not a rival commit, and re-running would refuse forever.

    The FIFO shape is covered beside it by ``tests/test_order_writer_arbiter.py``,
    which is where this suite parks its unreadable-path fixtures.
    """
    module = _order_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    target = _order_path(repo)
    os.chmod(target, 0o000)
    try:
        code, out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                          "--now", NOW)
    finally:
        os.chmod(target, 0o644)
    if os.geteuid() == 0:
        pytest.skip("root reads any mode, so the permission fault cannot be planted")
    assert code == module.EXIT_IO, (code, out + err)
    assert REFUSAL not in err, err
    assert FILE_CHANGED not in err, err
    assert "could not be read" in err, err
    assert "re-run" in err, err
