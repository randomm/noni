"""What the freshness guard does with each STATE of the repository it reads.

The companion to ``tests/test_order_writer_probe.py``, which asks the probe about the
artifact's own path and about a guard that cannot answer. This file asks the three
questions the guard asks of the repository -- what HEAD holds, what the index holds,
and whether there is a HEAD at all -- because each has its own honest negative, and a
guard that mistakes one of them for the next either refuses the first committed order
of a fresh tree or commits over an order it never looked at.

Runs go through ``order_fixtures._order_inprocess`` (or the subprocess launcher where
the contract is the whole command) for the reason that module gives.
"""

import json
import subprocess

from _harness import _git
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
    _writer_git_call,
)
from order_probe_shared import STAGED, _no_commit_repo
from order_race_fixtures import (
    FILE_CHANGED,
    REFUSAL,
    RIVAL_STAMP,
    _head,
    _race_entry,
    interrupt_read,
)


def test_a_committed_order_is_written_when_the_file_is_already_in_the_working_tree(
        tmp_path):
    """A pre-existing file at the artifact path is not a committed order (issue #116).

    The state the lens review reported: a repository with no commit at all, and
    ``noni/direction/order.json`` already sitting in the working tree. There the answer
    git gives for ``show HEAD:<path>`` is NOT the phrase set the probe used to read as
    absence -- with a file of that name on disk it says "path '<rel>' exists on disk,
    but not in 'HEAD'", and the probe that matched English wording read that as a
    repository it could not read. The first committed order of such a repository is the
    quickstart's own first step, so it has to land.

    Driven as a subprocess with the bytes this writer itself renders, so the only thing
    under test is the probe's answer and not the artifact reader's canonical comparison.
    """
    repo = _no_commit_repo(tmp_path, "no-commit-file")
    target = _order_path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_canonical([_entry(11)]), encoding="utf-8")
    assert _committed_order(repo) is None, "the fixture must not have committed anything"

    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "changed since it was read" not in proc.stderr, proc.stderr
    assert _issues(repo) == [11, 7], _issues(repo)
    assert _committed_order(repo) == target.read_bytes()


def test_a_committed_order_is_written_when_a_staged_copy_is_the_only_change(tmp_path):
    """The quickstart's first committed order, with the file staged as well as written.

    A staged file that agrees with the working copy is not a rival: the writer's own
    ``git add`` re-stages the same path and the commit carries this run's plan, so the
    run has to land. This is also the state whose ``show HEAD:<path>`` answer swaps to
    git's "exists on disk, but not in 'HEAD'" sentence -- the wording a probe that
    sorted 128s by phrase read as a repository it could not read.
    """
    repo = _no_commit_repo(tmp_path, "no-commit-staged")
    target = _order_path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_canonical([_entry(11)]), encoding="utf-8")
    _git(repo, "add", ORDER_REL)
    assert _committed_order(repo) is None, "the fixture must not have committed anything"

    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "changed since it was read" not in proc.stderr, proc.stderr
    assert _issues(repo) == [11, 7], _issues(repo)
    assert _committed_order(repo) == target.read_bytes()
    assert _porcelain(repo, ORDER_REL) == "", (
        "the committed order left the artifact dirty: "
        f"{_porcelain(repo, ORDER_REL)!r}")


def test_a_file_that_is_not_in_the_history_is_nothing_committed_for_the_probe(tmp_path):
    """The second honest negative: a HEAD that exists and does not hold the path.

    ``git init`` with one commit that touched something else, and the artifact's path
    in neither the history nor the index. This is the state the phrase set of
    ``git show`` used to be matched against, and it is the state the guard's own
    ``ls-files`` arm has to answer for as absence and not as a fault.
    """
    helper = _gitwrite_module()
    repo = _bare_repo(tmp_path, subdir="no-path-in-history")
    assert _committed_order(repo) is None
    answer = helper.committed_bytes(repo, ORDER_REL)
    assert answer.data is None and answer.code is None, (
        f"a path no commit holds must read as nothing committed: {answer}")


def test_an_unborn_head_reads_as_nothing_committed_when_the_path_is_on_disk(tmp_path):
    """The helper-level pin of the same answer: absence, never a fault, never bytes.

    Asserted on the shape and not just on the absence of a fault: if the probe ever
    reads the worktree file and hands its bytes back as "what HEAD holds", a run
    whose plan differs from those bytes refuses at exit 4 for a rival that never
    ran, and a run whose plan matches them commits nothing while saying it committed.
    """
    helper = _gitwrite_module()
    repo = _no_commit_repo(tmp_path, "unborn-helper")
    target = _order_path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_canonical([_entry(11)]), encoding="utf-8")
    answer = helper.committed_bytes(repo, ORDER_REL)
    assert answer.data is None and answer.code is None, (
        f"an unborn HEAD holds no order even when the file is on disk: {answer}")


def test_a_head_with_no_commit_at_all_reads_as_nothing_committed(tmp_path):
    """No commit has ever been made: there is no tree, so HEAD holds no order.

    The state the lens review reported, and the one no phrase set may be relied on
    to describe: with the artifact already on disk git swaps the sentence it uses for
    absence, and a probe that sorts 128s by wording reads that swap as a broken
    repository and refuses the first committed order of a fresh tree at exit 3.
    """
    helper = _gitwrite_module()
    repo = _no_commit_repo(tmp_path, "no-commit")
    target = _order_path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_canonical([_entry(11)]), encoding="utf-8")
    answer = helper.committed_bytes(repo, ORDER_REL)
    assert answer.data is None and answer.code is None, (
        f"a HEAD that names no object holds no order: {answer}")


def test_the_first_committed_order_of_a_repository_with_no_commit_at_all_is_committed(
        tmp_path):
    """The same state at the top of the writer, driven as a subprocess.

    The quickstart's route end to end: ``git init`` a private state repository, put a
    file at the artifact's path, and have the first committed ``add`` land. Exit 0
    with the entry in HEAD is the whole contract; exit 3 or 4 here is a probe that
    mistook an empty history for a repository it could not read.
    """
    repo = _no_commit_repo(tmp_path, "no-commit-writer")
    target = _order_path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_canonical([_entry(11)]), encoding="utf-8")
    proc = _order(repo, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "changed since it was read" not in proc.stderr, proc.stderr
    assert _issues(repo) == [11, 7], _issues(repo)
    assert _committed_order(repo) == target.read_bytes()


def test_the_guard_refuses_a_staged_copy_that_is_neither_heads_nor_the_plan(tmp_path):
    """The index is the third thing to ask, because it is what the commit obeys.

    ``git commit --only -- <path>`` takes the path from the INDEX, so the bytes that
    land in HEAD are the bytes the index held a moment before, whether or not this run
    ever saw them. A path staged with content that is neither HEAD's nor this run's
    plan would therefore reach HEAD holding an order nobody read: the same lost update
    the guard exists to stop, answered by neither of the two reads it had.

    The working copy is put back to HEAD's bytes, so the file read stays honest and
    only the index moved: this is the index arm alone, with its own wording, and not
    the file arm or the HEAD arm in disguise.
    """
    module = _order_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    head_before = _head(repo)
    committed_before = _committed_order(repo)
    target = _order_path(repo)
    target.write_text(_canonical([_entry(99, BASELINE_ID, RIVAL_STAMP)]),
                      encoding="utf-8")
    _git(repo, "add", ORDER_REL)
    target.write_bytes(committed_before)

    code, out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                      "--now", NOW)
    assert code == module.EXIT_REFUSAL, (code, out + err)
    assert STAGED in err, err
    assert REFUSAL not in err, f"HEAD never moved here: {err}"
    assert FILE_CHANGED not in err, f"the file still holds what the run read: {err}"
    assert _head(repo) == head_before, "a refused run advanced HEAD"
    assert _committed_order(repo) == committed_before, "a refused run committed the index"
    assert 7 not in _issues(repo), "a refused run must not have written its entry"


def test_an_unstaged_or_staged_absent_path_is_not_the_index_arm(tmp_path):
    """What the index read must NOT refuse, or the guard would refuse every run.

    Two states answer "the index does not hold this path" and git spells them
    identically (no row, exit 0): a path nobody has staged, and a path another hand
    took out of the index with ``git rm --cached``. Neither is a claim about the
    coming commit, because the writer's own ``git add -- <path>`` fills the index from
    the working copy moments before it, and the working copy is the file read, compared
    against this run's plan two arms below. A guard that read a missing row as a
    foreign staged order would refuse every ordinary run of the writer.
    """
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    head_before = _head(repo)

    # A path nobody staged: the ordinary state of every run in this suite.
    code, out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                      "--now", NOW)
    assert code == 0, (code, out + err)
    assert STAGED not in err, err
    assert _head(repo) != head_before, "the ordinary run was refused"

    # The same index answer, reached by taking the path out of the index. The file
    # still holds what HEAD holds, so no arm of the guard has anything to report.
    _git(repo, "rm", "--cached", "--quiet", "--", ORDER_REL)
    code, out, err = _order_inprocess(repo, "confirm", "--now", NOW)
    assert code == 0, (code, out + err)
    assert STAGED not in err, err


def test_a_staged_removal_of_the_path_leaves_the_order_to_the_file_read(tmp_path):
    """A path out of the index is not a foreign staged order; the file is the check.

    Taking the path out of the index leaves the index agreeing with HEAD, so nothing
    the index arm can see has moved. What would actually lose an order is the working
    copy no longer holding what this run read, and that is the file arm's refusal, in
    its own wording.

    The file is moved inside the window rather than before the run, for the reason the
    race fixtures give: the run reads the artifact first, so a file edited beforehand
    is simply the file it read, and the only asymmetry left to test is the index. The
    edit is a restamp rather than a new entry, because a file the artifact reader
    refuses for its form never reaches the guard at all.
    """
    module = _order_module()
    repo = _repo(tmp_path)
    # Seeded at SEED_STAMP so the run's own stamp is a real change: a run that would
    # write no byte takes the writer's no-change shortcut and never reaches the guard.
    _seed(repo, _race_entry(11))
    head_before = _head(repo)
    committed_before = _committed_order(repo)
    _git(repo, "rm", "--cached", "--quiet", "--", ORDER_REL)
    real_read = module.orderstate.read_order

    def read_then_edit(path):
        read = real_read(path)
        entries = json.loads(path.read_bytes())["entries"]
        entries[0]["confirmed"] = RIVAL_STAMP
        path.write_text(_canonical(entries), encoding="utf-8")
        return read

    with interrupt_read(module, "read_order", read_then_edit):
        code, out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                         "--now", NOW)
    assert code == module.EXIT_REFUSAL, (code, out + err)
    assert FILE_CHANGED in err, err
    assert STAGED not in err, f"the index agreed with HEAD here: {err}"
    assert _head(repo) == head_before, "a refused run advanced HEAD"
    assert _committed_order(repo) == committed_before, "a refused run rewrote HEAD"


def test_the_guard_asks_the_index_once_and_by_the_path_derived_from_order_path(
        tmp_path, monkeypatch):
    """The three reads name ONE file, and the index read is a comparison, not a checkout.

    Two things are pinned at once. Every probe call is asked of the artifact path
    derived from the ``order_path`` the writer was handed, so a run whose repo and
    artifact are not the pair the constants assume cannot ask HEAD about one file and
    the file about another. And ``ls-files`` is asked with ``-s``, which answers with
    the blob id: the two shapes that do NOT answer the question are
    ``--error-unmatch`` (exit 1 for a path the index does not hold, a code the writer's
    fault arm cannot tell from a genuine fault) and ``diff --cached --quiet`` (exit 1
    for any staged change, including this writer's own ``git add``).

    The tree is seeded and committed, because under no commit at all the guard returns
    before the index read: a first commit has no order in HEAD to lose, and git cannot
    record one through a path-restricted commit anyway.
    """
    helper = _gitwrite_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    seen: list[tuple] = []
    real_git_bytes = helper.git_bytes

    def spy(repo_arg, *args, input_text=None):
        seen.append(args)
        return real_git_bytes(repo_arg, *args, input_text=input_text)

    monkeypatch.setattr(helper, "git_bytes", spy)
    code, _out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                       "--now", NOW)
    assert code == 0, err
    assert ("show", f"HEAD:{ORDER_REL}") in seen, seen
    assert ("ls-files", "-s", "--", ORDER_REL) in seen, seen
    assert not [args for args in seen if args[0] == "show"
                and args[1] != f"HEAD:{ORDER_REL}"], seen


def test_the_guard_refuses_a_run_whose_order_path_is_not_under_the_repo(tmp_path):
    """A path git cannot name is refused as a fault, not asked of git and misread.

    The guard takes ``order_path`` from its caller and cannot assume the pair it was
    handed: a path outside the repository has no git path, and a probe that built one
    anyway would ask HEAD about a file no commit could hold and call that "nothing
    committed", which is the pass rather than the refusal.
    """
    module = _order_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    outside = tmp_path / "elsewhere" / "order.json"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(_order_path(repo).read_bytes())
    rel, refusal = module.order_probe._artifact_rel(repo, outside)
    assert rel == "" and refusal is not None, (rel, refusal)
    assert "--repo" in refusal[1], refusal


def test_the_probe_reads_the_committed_state_with_no_git_location_variable(tmp_path,
                                                                            monkeypatch):
    """``--repo`` alone names the repository the guard reads, whatever the caller exported.

    The commit half already runs under ``gitenv.child_env()``, which drops every
    ``GIT_*`` name but the identity, config and transport allowlist. The read half
    adds ``LC_ALL=C`` on top of it, and an implementation that built its environment
    from ``os.environ`` would keep the four that relocate a repository: an inherited
    ``GIT_DIR`` sends the guard's ``git show`` to another repository, which answers
    "nothing committed", and the run commits over an order it never looked at.
    """
    decoy = _bare_repo(tmp_path, subdir="decoy-repo")
    _seed(decoy, _entry(999, BASELINE_ID, RIVAL_STAMP))
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    real_run = subprocess.run
    observed: list[dict] = []

    def spy(cmd, **kwargs):
        if _writer_git_call(cmd, repo):
            observed.append(dict(kwargs.get("env") or {}))
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    for name in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_COMMON_DIR",
                 "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
        monkeypatch.setenv(name, str(decoy))

    code, _out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                       "--now", NOW)
    assert code == 0, err
    assert observed, "the run made no git call of its own to inspect"
    for env in observed:
        for name in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_COMMON_DIR",
                     "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
            assert name not in env, f"{name} travelled to a git child: {sorted(env)}"
    assert 7 in _issues(repo), "the decoy repository answered for the state root"


