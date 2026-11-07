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
from pathlib import Path

import pytest
from _harness import _git, _git_e2
from order_fixtures import (
    BASELINE_ID,
    NOW,
    ORDER_REL,
    _bare_repo,
    _canonical,
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
    _seed,
)
from order_probe_shared import _no_commit_repo
from order_race_fixtures import (
    FILE_CHANGED,
    REFUSAL,
    RIVAL_STAMP,
    _head,
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
    """A path no commit has ever held holds nothing, and says so honestly.

    ``git show HEAD:<path>`` for a path the history never held answers 128 with
    "does not exist in 'HEAD'.", and under a HEAD with no commit at all it answers
    "invalid object name 'HEAD'.". Both are git's way of saying there is nothing to
    look at. A probe that read either as a repository it could not read would refuse
    the first committed order with exit 3, and the quickstart's brand new private
    state repository could never hold an order.
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


def test_a_path_with_an_embedded_null_is_a_fault_and_not_a_traceback(tmp_path):
    """A NUL in the path is the filesystem declining to answer, so it is exit 3.

    ``os.lstat`` raises ``ValueError`` for such a path and ``ValueError`` is no
    ``OSError``, so a classifier that catches only the latter lets the guard die with
    a traceback in the middle of a commit. The package already answers that question
    (:func:`noni._path_kind.inspected_file_kind`); the guard asks it.
    """
    module = _order_module()
    probe = module.order_probe
    answer = probe.file_bytes(Path("noni\x00direction/order.json"))
    assert answer.code == probe.NO_FAULT + 1, f"a declined lstat is a fault: {answer}"
    assert answer.data is None, answer
    assert answer.why, "a fault has to name what the filesystem said"


def test_a_regular_file_that_fails_to_read_is_a_fault_and_never_absence(tmp_path):
    """The shape is fine and the read failed: exit 3, not the exit-4 "re-run".

    ``lstat`` answered "regular", so nothing about the path is wrong and only the
    read itself failed (a file replaced by a dangling link between the two calls, an
    I/O error, a permission the operator has to undo). Reading it as absence would
    compare ``None`` against the bytes this run read, blame a concurrent writer that
    never ran and tell the operator to re-run a command that refuses forever.
    """
    module = _order_module()
    probe = module.order_probe
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    target = _order_path(repo)
    real_read_bytes = type(target).read_bytes

    def refusing(self):
        raise OSError("Input/output error")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(type(target), "read_bytes", refusing, raising=False)
    try:
        answer = probe.file_bytes(target)
    finally:
        monkey.undo()
    assert answer.code == probe.NO_FAULT + 1, f"a failed read is a fault: {answer}"
    assert answer.data is None, answer
    assert "could not be read" in answer.why, answer
    assert real_read_bytes is type(target).read_bytes


def test_the_guard_reads_the_index_under_an_unborn_head_only_to_refuse_a_conflict(
        tmp_path, monkeypatch):
    """Under a HEAD that names no object the index is consulted for ONE question.

    The HEAD comparison and the staged-copy arm stay skipped: there is no committed
    order to lose, and ``git commit --only -- <path>`` records no first commit for a
    path the index does not already hold, so a guard that compared the staged bytes
    here would refuse every run of a repository whose next commit git also refuses.
    The one index question that IS owed is the conflicted index: the index DOES hold
    the path, in three stages, and no blob answers what the commit would write. So a
    normal run under an unborn HEAD still lands, and the index is asked exactly once
    and only for that unmerged-stage check.

    The pinned case is the one the phrase-matching probe got wrong: with the artifact
    already sitting in the index and nothing committed, git changes the wording it
    uses for absence, so absence is read as a return code and never as a sentence.
    """
    helper = _gitwrite_module()
    repo = _no_commit_repo(tmp_path, "unborn-index-asked-once")
    target = _order_path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_canonical([_entry(99, BASELINE_ID, RIVAL_STAMP)]),
                      encoding="utf-8")
    _git(repo, "add", ORDER_REL)
    target.unlink()

    # The state itself, asserted from git and not from the guard's own answer: HEAD
    # names nothing, and the index DOES hold a blob -- a staged copy that is neither
    # HEAD's (there is none) nor this run's plan, which is exactly the state the live
    # HEAD case refuses. Under an unborn HEAD it must not: no commit is at stake.
    assert helper.committed_bytes(repo, ORDER_REL).data is None
    assert helper.index_blob_id(repo, ORDER_REL)[0] is not None

    calls: list[tuple] = []
    real_git_bytes = helper.git_bytes

    def spy(repo_arg, *args, input_text=None):
        calls.append(args)
        return real_git_bytes(repo_arg, *args, input_text=input_text)

    monkeypatch.setattr(helper, "git_bytes", spy)
    code, out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                      "--now", NOW)
    assert code == 0, (code, out + err)
    asked = [args for args in calls if args[0] == "ls-files"]
    assert len(asked) == 1, f"the index was asked {len(asked)} times: {calls}"
    assert asked[0] == ("ls-files", "-s", "--", ORDER_REL), calls
    # The artifact's own path enters the history as the WRITER wrote it: what the index
    # held before the run is the operator's file, not this run's entry, so asserting the
    # committed bytes against the writer's render is the claim that survives.
    assert _committed_order(repo) == _order_path(repo).read_bytes()
    assert 7 in _issues(repo), _issues(repo)


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

    def git_bytes(repo, *args, input_text=None):
        if args and args[0] == "show":
            probes.append(args)
            return answer(args)
        return real_git(repo, *args, input_text=input_text)

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
    """A path git says no commit holds is absence; a 128 for any other reason is a fault.

    Both arms of the probe are pinned so an implementation cannot collapse them, which
    is how a corrupt object store would otherwise read as "no committed bytes" and let
    the run commit over an order it never saw. The honest answer is now a return code
    rather than a sentence, so the fault arm is a code that is not that one code -- the
    ``bad object`` of a store git could not read, which no wording set has to name.
    """
    module = _order_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    code, _out, err, probes = _drive_add_with_probe(repo, monkeypatch, _failed)
    assert code == module.EXIT_IO, code
    assert len(probes) == 1, probes
    assert "git show failed" in err, err
    assert REFUSAL not in err, err
    assert 7 not in _issues(repo), "the unwritten order must not have been written"


def _head_blob(repo, rel=ORDER_REL):
    """The id HEAD holds at ``rel``, asked of git directly and not of the writer.

    The probe is being pinned against its own answers, so the expected blob id has to
    come from outside it: here it is what git answers for the same rev through the
    harness's own git runner, and that is the id the probe must then read back.
    """
    asked = _git_e2(repo, "rev-parse", "--verify", "--quiet", f"HEAD:{rel}")
    assert asked.returncode == 0, asked.stderr
    return asked.stdout.strip()


def test_the_probe_is_one_hardened_git_call_of_the_writer_s_own_helper(tmp_path,
                                                                       monkeypatch):
    """The probe reuses the writer's own git helper: one runner, hardened, bounded.

    The argv is what carries the hardening (no signing, no hooks, no external
    transports, no fsmonitor) and the scoped path, so the assertion is on the command
    lines the probe built. It asks two of them: existence first, as
    ``rev-parse --verify --quiet HEAD:<rel>``, which answers a return code rather than
    a sentence; then the bytes, as ``show <blob>``, of the very id the first call
    printed. The second call deliberately does not name the path again -- re-resolving
    the rev would let a second lookup decide what "unchanged" means -- and no other
    read asks about anything else. Both go through the writer's own helper, so there
    is no second runner of its own to drift from the first.
    """
    helper = _gitwrite_module()
    real_git_bytes = helper.git_bytes
    seen: list[tuple] = []

    def git_bytes(repo, *args, input_text=None):
        seen.append(args)
        return real_git_bytes(repo, *args, input_text=input_text)

    # The repository is built first and the spy installed only for the run under
    # test: the spy answers every git call, the fixture's own included, and the
    # harness commits through helpers that read HEAD as well, so a spy in place while
    # the tree is built makes the fixture die on a fault that belongs to nothing in
    # the scenario.
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    blob = _head_blob(repo, ORDER_REL)
    monkeypatch.setattr(helper, "git_bytes", git_bytes)
    code, _out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                       "--now", NOW)
    assert code == 0, err
    assert ("rev-parse", "--verify", "--quiet", f"HEAD:{ORDER_REL}") in seen, seen
    assert ("show", blob) in seen, seen
    # The only git reads of the probe are the HEAD existence check, the type of HEAD
    # itself, and the one blob read above; none of them names a path that is not the
    # artifact's own.
    assert not [args for args in seen if args[0] == "show" and args[1] != blob], seen

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
