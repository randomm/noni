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
    _read,
    _repo,
    _rival_commit,
    _seed,
    _writer_git_call,
    git_input,
)
from order_probe_shared import (
    CONFLICTED,
    STAGED,
    _conflicted_repo,
    _no_commit_repo,
)
from order_race_fixtures import (
    FILE_CHANGED,
    IO_FAULT,
    REFUSAL,
    RIVAL_STAMP,
    _head,
    _race_entry,
    _rival_raced,
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
def test_a_rival_that_rewrites_the_file_under_an_unborn_head_is_refused(tmp_path):
    """The lost update, in a repository with no commit yet.

    The state the quickstart's first step is: ``git init`` a private state repository
    and write the order into it. The guard used to answer the whole question as soon as
    it saw there was no HEAD, because with no committed order there is nothing for a
    rival to have moved -- and in doing so it skipped the one comparison that still
    means something here: ``write_atomic`` replaces the bytes at the path whether or not
    HEAD exists, so a second writer that rewrote the artifact between this run's read
    and its write had its work silently replaced, exit 0, in exactly the repository
    where the writer is most likely to be run first.

    The HEAD comparison and the index arm stay skipped (there is no committed order and
    a path-restricted commit cannot record a first commit for a path the index does not
    hold); only the file comparison is owed, and its own wording.
    """
    module = _order_module()
    repo = _no_commit_repo(tmp_path, "unborn-rival")
    target = _order_path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_canonical([_race_entry(11)]), encoding="utf-8")
    # There is no commit at all: the guard's HEAD arm has nothing to compare.
    assert _head(repo) == "", "the fixture planted a commit"
    real_read = module.orderstate.read_order

    def read_then_rival(path):
        read = real_read(path)
        # A rival session writes its own order into the window between this run's read
        # and its write -- the same second-writer shape the committed race tests drive.
        path.write_text(_canonical([_entry(55, BASELINE_ID, RIVAL_STAMP)]),
                        encoding="utf-8")
        return read

    with interrupt_read(module, "read_order", read_then_rival):
        code, out, err = _order_inprocess(repo, "add", "44", "--decision", BASELINE_ID,
                                          "--now", NOW)
        rival_bytes = target.read_bytes()

    assert code == module.EXIT_REFUSAL, (code, out + err)
    assert FILE_CHANGED in err, err
    assert REFUSAL not in err, f"nothing was ever committed here: {err}"
    assert STAGED not in err, err
    # The refused run wrote nothing: the rival's bytes are still the file, and no order
    # of this run's made it into HEAD (which is still no order at all).
    assert target.read_bytes() == rival_bytes, "a refused run replaced the rival's file"
    assert _committed_order(repo) is None, "a refused run made the first commit"
    assert 44 not in _issues(repo), _issues(repo)
    assert "order.json (" not in out, out


def test_the_first_order_of_a_fresh_repository_still_lands_under_an_unborn_head(
        tmp_path):
    """The other half of the same arm: a clean unborn HEAD is still a pass.

    Adding the file comparison back under an unborn HEAD must not turn the quickstart's
    first ``order add`` into a refusal. Nothing moved in that run -- the file still
    holds the bytes it read -- so the guard has nothing to report and the commit lands.
    """
    repo = _no_commit_repo(tmp_path, "unborn-clean")
    target = _order_path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_canonical([_race_entry(11)]), encoding="utf-8")

    code, out, err = _order_inprocess(repo, "add", "44", "--decision", BASELINE_ID,
                                      "--now", NOW)
    assert code == 0, (code, out + err)
    assert FILE_CHANGED not in err, err
    assert sorted(_issues(repo)) == [11, 44], _issues(repo)
    assert _committed_order(repo) == target.read_bytes()


def test_an_unmerged_index_refuses_rather_than_reading_the_first_row(tmp_path):
    """A conflicted path answers THREE rows, and no id names it.

    ``git ls-files -s -- <path>`` prints one row per stage for a path the index holds in
    conflict (base, ours, theirs). The reader used to take the first row and hand back
    the blob of the merge base as "the bytes the index holds at that path" -- a single
    id that answers a question with three answers, and the one read of the guard the
    coming ``git commit --only -- <path>`` actually obeys. Refusing is the only honest
    answer: this run cannot name what its commit would write, and the remedy is to
    resolve or abort the merge, not to re-run.
    """
    module = _order_module()
    helper = _gitwrite_module()
    repo = _conflicted_repo(tmp_path, "unmerged-index")
    rows = helper.git_bytes(repo, "ls-files", "-s", "--", ORDER_REL).stdout.decode()
    stages = sorted(field.split()[2] for field in rows.splitlines() if field.strip())
    assert stages == ["1", "2", "3"], f"the fixture is not conflicted: {rows}"

    # The helper answers the conflict as its own value, never as the id of one stage.
    assert helper.index_blob_id(repo, ORDER_REL) == (helper.UNMERGED, "")

    head_before = _head(repo)
    committed_before = _committed_order(repo)
    code, out, err = _order_inprocess(repo, "add", "44", "--decision", BASELINE_ID,
                                      "--now", NOW)
    assert code == module.EXIT_REFUSAL, (code, out + err)
    assert CONFLICTED in err, err
    assert STAGED not in err, f"unstaging is not the fix for a conflict: {err}"
    assert REFUSAL not in err, err
    assert _head(repo) == head_before, "a refused run advanced HEAD"
    assert _committed_order(repo) == committed_before, "a refused run committed"
    assert 44 not in _issues(repo), "a refused run wrote its entry"


def test_a_head_that_names_no_object_is_a_fault_and_never_an_empty_history(
        tmp_path):
    """A deleted commit object must not read as "nothing is committed here".

    The path-level negative is what the guard trusts for an empty history: ``rev-parse
    --verify --quiet HEAD:<rel>`` exits 1 for "no such path in that tree", and the
    writer reads that as absence so the first committed order of a fresh repository can
    land. The same exit 1 is what git answers when there is no tree to look in -- the
    commit HEAD names is gone -- so without asking the cheaper question first ("is HEAD
    a commit object at all?") a repository whose object store the operator has to
    repair was reported as an empty one, and the run committed into it claiming an order
    nothing had ever checked.
    """
    module = _order_module()
    helper = _gitwrite_module()
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    head = _head(repo)
    committed_before = _committed_order(repo)
    loose = repo / ".git" / "objects" / head[:2] / head[2:]
    assert loose.is_file(), f"the commit is packed, so this fixture cannot delete it: {head}"
    loose.unlink()

    # The state itself, asserted from git and not from the guard's own answer: HEAD
    # resolves as a name and the object behind it is gone.
    assert _git(repo, "rev-parse", "--verify", "--quiet", "HEAD").returncode == 0
    assert helper.committed_bytes(repo, ORDER_REL).code is not None, (
        "a HEAD whose commit object is gone is a fault, never 'nothing committed'")

    code, out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                      "--now", NOW)
    assert code == module.EXIT_IO, (code, out + err)
    assert REFUSAL not in err, f"a corrupt repository is not a concurrent writer: {err}"
    assert FILE_CHANGED not in err, err
    assert STAGED not in err, err
    assert "re-run" in err, err
    assert 7 not in _issues(repo), "a run against a corrupt store wrote its entry"


def test_an_unmerged_index_is_refused_even_under_an_unborn_head(tmp_path):
    """The claim that keeps the two states apart: no committed order, conflicted index.

    Under an unborn HEAD the guard skips the HEAD comparison, and it skips the index
    arm on the argument that a path-restricted commit records no first commit for a
    path the index does not already hold -- so the state that arm exists for cannot
    arise. This test puts the index in the one shape that argument does not cover: the
    index DOES hold the path, in three stages, and the commit would obey a blob no run
    ever read. What is pinned is that no order reaches HEAD while the guard cannot name
    the bytes its commit would write (exit 4 from the guard, or exit 3 if the writer's
    own stage step refuses the conflicted path first -- either is a refusal, and a
    silent exit 0 is not).
    """
    module = _order_module()
    helper = _gitwrite_module()
    repo = _no_commit_repo(tmp_path, "unborn-conflicted")
    target = _order_path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_canonical([_race_entry(11)]), encoding="utf-8")
    # The blob HEAD would have held does not exist here (nothing is committed), so the
    # base stage of the conflict is one more stored order rather than HEAD's own.
    base = git_input(repo, "hash-object", "-w", "--stdin",
                     text=_canonical([_race_entry(11)]))
    _staged_conflict(repo, base)
    # The index rows are DATA and git lets them stand for a path it already tracks, so
    # the run cannot be steered away from the conflict by the state of the file: the
    # guard is asked with the index holding three rows and no answer. What is pinned is
    # that the run does not land its order while the bytes its commit would write are
    # the ones git's stage step picks out of a conflict (and, with the path conflicted,
    # the writer's own ``git add`` refuses it: "needs merge", an exit 3 fault).
    code, out, err = _order_inprocess(repo, "add", "44", "--decision", BASELINE_ID,
                                      "--now", NOW)
    assert code in (module.EXIT_REFUSAL, module.EXIT_IO), (code, out + err)
    assert 44 not in _issues(repo), "a run that could not name its commit wrote anyway"
    assert _committed_order(repo) is None, (
        "a run whose index read was unmerged made the first commit")


def _staged_conflict(repo, base: str) -> None:
    """Put the artifact's path in the index at stages 1/2/3 and no stage 0.

    A conflict cannot be planted with ``git merge`` in every scenario (a merge needs a
    commit to merge into), and it cannot be planted with ``update-index --cacheinfo``
    either: git reads that option's third field as a PATH and re-hashes the worktree
    bytes for it, so for a path the worktree holds it quietly restages the file at stage
    0 and the index answers a single id -- the read that is supposed to be ambiguous
    would never have happened. ``update-index --index-info`` writes rows as DATA, in the
    exact form ``ls-files -s`` prints them, and is the call git's own merge machinery
    uses; it must be git's last argument and reads its rows on stdin.

    ``base`` is the id of the merge base, passed in because only the caller knows
    whether the path is in HEAD at all. The other two blobs are stored orders, and the
    file is left holding "ours" on disk: git will not accept a staged row for a path
    whose worktree copy it cannot account for, and a conflicted checkout is what this
    state looks like on disk.
    """
    ours_text = _canonical([_entry(99, BASELINE_ID, RIVAL_STAMP)])
    ours_blob = git_input(repo, "hash-object", "-w", "--stdin", text=ours_text)
    theirs_blob = git_input(repo, "hash-object", "-w", "--stdin",
                            text=_canonical([_entry(55, BASELINE_ID, RIVAL_STAMP)]))
    _order_path(repo).write_text(ours_text, encoding="utf-8")
    rows = [f"100644 {blob} {stage}\t{ORDER_REL}"
            for stage, blob in ((1, base), (2, ours_blob), (3, theirs_blob))]
    git_input(repo, "update-index", "--index-info", text="\n".join(rows) + "\n")


def test_the_staged_refusal_is_reached_only_after_head_and_the_file_are_clean(tmp_path):
    """Each refusal line is a claim about the reads it did NOT report, so each is pinned.

    Three sentences, three causes. The staged line claims "HEAD and the file still hold
    what this run read"; the file line claims the committed order did not move; the HEAD
    line is the one a rival commit earns and whose remedy is a bare re-run. Asked in the
    wrong order each line is printed for a run whose true cause was something else, and
    the operator is sent to the wrong remedy -- a run whose HEAD had ALSO moved told to
    unstage an index copy, when re-running was the fix.

    So each step moves exactly the one thing its sentence names and proves, from the
    writer's own reads of the tree (asked of git with the guard's own helpers, so the
    fixture is not asserting its own handiwork), that the two reads the line says are
    clean really are. The three steps are three repository STATES of one tree rather
    than three trees: step 2's rival commit is undone by committing the baseline back
    through the product's own writer, which is the only way to move HEAD without
    rewinding history -- and history is the one thing this test must not touch, because
    the rival commit it is undoing is the point of the step above it.
    """
    module = _order_module()
    helper = _gitwrite_module()

    def reads(name, expect, tree=None):
        """The guard's three reads, taken from the tree and not from what this test meant.

        A step whose "clean" read was secretly moved would pass by asserting the
        fixture's own writes, so each read is asked of git and of the file through the
        very helpers the guard calls, and compared against THIS RUN's baseline: the bytes
        sitting at the artifact path when the run starts, which is what the guard will
        compare all three against. ``expect`` is which of the two git reads the step
        claims is clean and which it blames -- and the blamed one must be moved, or the
        sentence this step pins has no cause at all.
        """
        tree = repo if tree is None else tree
        committed = helper.committed_bytes(tree, ORDER_REL)
        assert committed.code is None, committed.why
        on_disk = _path_kind_file_bytes(_order_path(tree))
        assert on_disk.code == 0, on_disk.why
        staged, fault = helper.index_blob_id(tree, ORDER_REL)
        assert not fault, fault
        head_blob, fault = helper.blob_id(repo, committed.data)
        assert not fault, fault
        read_bytes = _order_path(tree).read_bytes()
        assert on_disk.data == read_bytes, f"{name}: the file read is not the file"
        if expect == "head":
            assert committed.data != read_bytes, (
                f"{name}: HEAD did not move, so the HEAD arm has no cause")
        else:
            # HEAD is compared against the FILE, not against a snapshot frozen at the top
            # of this test. Step 3 restores HEAD by committing, so HEAD's bytes legitimately
            # differ from the seed by then; a stale baseline would blame HEAD for the
            # fixture's own restore, which is the opposite of the claim this step makes.
            assert committed.data == read_bytes, (
                f"{name}: HEAD moved too, so this is not {name} alone")
        # The index of a run that has not staged anything answers HEAD's own bytes, and
        # nothing else, because the fixture's own commits staged them. That is the
        # precondition every non-index arm needs -- a staged copy left behind by an
        # earlier step would answer the index with something foreign and hand the run an
        # index refusal it was not built to test -- so it is asserted rather than assumed.
        if expect == "staged":
            assert staged not in (head_blob, None), (
                f"{name}: the staged copy did not move, so the staged arm has no cause")
        else:
            # The index must answer with what HEAD holds. It is allowed to be MISSING: the
            # ``git add -- <path>`` the writer makes a moment before its commit fills an
            # absent row from the working copy, which is the file compared just above, and
            # a missing row is therefore not a third state to refuse. A row holding
            # something NEITHER HEAD nor this run's plan contains is the other thing
            # altogether -- a copy some earlier step staged and nobody cleaned up -- and it
            # would hand the run the index refusal this step was not built to test.
            assert staged in (head_blob, None), (
                f"{name}: the index holds a foreign copy, so the {name} arm is not alone")
        if expect == "file":
            assert on_disk.data != committed.data, (
                f"{name}: the file did not move, so the file arm has no cause")
        elif expect == "file-clean":
            assert on_disk.data == committed.data, (
                f"{name}: the file moved too, so this is not {name} alone")
        if expect == "staged":
            assert staged not in (head_blob, None), (
                f"{name}: the staged copy did not move, so the staged arm has no cause")

    repo = _repo(tmp_path)
    _seed(repo, _race_entry(11), _race_entry(22))
    target = _order_path(repo)
    committed_before = _committed_order(repo)
    assert committed_before is not None and target.read_bytes() == committed_before

    # --- the index alone has moved -------------------------------------------------
    # The staged copy is an order no run read, and HEAD and the file both still hold the
    # committed bytes -- which ``reads`` asks of git rather than trusting.
    target.write_text(_canonical([_entry(99, BASELINE_ID, RIVAL_STAMP)]),
                      encoding="utf-8")
    _git(repo, "add", ORDER_REL)
    target.write_bytes(committed_before)
    reads("staged", "staged")
    code, out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                      "--now", NOW)
    assert code == module.EXIT_REFUSAL, (code, out + err)
    assert STAGED in err, err
    assert FILE_CHANGED not in err, err
    assert REFUSAL not in err, err

    # --- HEAD has moved, and only HEAD ---------------------------------------------
    # The plain concurrent writer, in a tree of its own. The step above staged a foreign
    # copy on purpose, and a second step in the same tree would spend all its effort
    # undoing the first -- an undo is itself a change to a read whose sentence claims it
    # clean, which is how a test of arm order ends up pinning the undo instead of the arm.
    # Here exactly one read has moved: HEAD, to the rival's order. The file and the staged
    # copy both answer the bytes this run reads (the rival fixture restores the file to
    # what the run read, then rehashes the index row against it), which is the claim the
    # HEAD line does NOT make and the reason the run gets the bare re-run rather than a
    # trip to the index or a checkout.
    rival = _repo(tmp_path, "head-alone")
    _seed(rival, _race_entry(11), _race_entry(22))
    _rival_raced(rival, (55, BASELINE_ID))
    reads("head", "head", rival)
    code, out, err = _order_inprocess(rival, "add", "8", "--decision", BASELINE_ID,
                                      "--now", NOW)
    assert code == module.EXIT_REFUSAL, (code, out + err)
    assert REFUSAL in err, err
    assert STAGED not in err, f"HEAD moved too, and that is the arm to report: {err}"
    assert FILE_CHANGED not in err, f"the file did not move here: {err}"

    # --- the file alone has moved --------------------------------------------------
    # HEAD is put back to the order this run reads, and with the index behind it, by
    # committing that order through the product's own writer: a real second commit, which
    # is the only honest way to move HEAD here (a fixture must not rewind history to undo
    # the commit the step above exists to make, and a refused run never moves HEAD --
    # that claim is pinned elsewhere and stands). The file then moves to bytes neither
    # HEAD nor the index holds, and ``reads`` confirms that the two the file line says
    # are clean are.
    #
    # The move is an EXTRA ENTRY and not a restamp: this run's own plan is to stamp every
    # entry with --now, so a file restamped to what that verb was going to write renders
    # the very bytes it read, and the writer decides nothing is left to add and exits 0
    # before any guard. That shortcut is pinned by its own test, and a step that landed on
    # it would be measuring the shortcut instead of this arm.
    _rival_commit(repo, _read(repo)["entries"],
                  message="direction: head put back to the order the run reads")
    _git(repo, "checkout", "HEAD", "--", ORDER_REL)
    _git(repo, "add", "--", ORDER_REL)
    target.write_text(_canonical(json.loads(committed_before)["entries"]
                                 + [_entry(77, BASELINE_ID, RIVAL_STAMP)]),
                      encoding="utf-8")
    reads("file", "file")
    code, out, err = _order_inprocess(repo, "confirm", "--now", NOW)
    assert code == module.EXIT_REFUSAL, (code, out + err)
    assert FILE_CHANGED in err, err
    assert REFUSAL not in err, f"HEAD moved as well, which is the other arm: {err}"
    assert STAGED not in err, f"the index moved too, and that is the other arm: {err}"


def _path_kind_file_bytes(path):
    """The probe module's own file read, reached through the guard that uses it.

    The fixture asks the guard's three questions and must ask them with the guard's own
    helpers, so a read this step does not name cannot be quietly different from the one
    the run makes. The file read lives on the probe module rather than the git helper
    module, because it reads a path and not a repository.
    """
    return _order_module().order_probe.file_bytes(path)


def _rival_behind_a_staged_copy(repo):
    """Move HEAD to a rival's order while the index keeps a foreign copy.

    Three reads must disagree here -- HEAD (the rival's), the file (what this run will
    read) and the index (a third order) -- so that the ORDER of the guard's arms is what
    decides which refusal the run gets, rather than one arm happening to be clean.
    """
    _rival_raced(repo, (55, BASELINE_ID))
    # The rival's fixture restores the working copy; re-stage the foreign bytes the
    # scenario needs, so all three reads disagree and the order of arms is what decides.
    target = _order_path(repo)
    target.write_text(_canonical([_entry(99, BASELINE_ID, RIVAL_STAMP)]),
                      encoding="utf-8")
    _git(repo, "add", ORDER_REL)


def _restore_head(repo):
    """Restore the file from HEAD so HEAD and the file agree, and hand back HEAD's bytes.

    The scenario has already moved HEAD (a rival commit), and the writer's contract is
    that a refused run never moves it -- so a fixture must not rewind history to undo
    that, and the next run must plan from what HEAD holds now. The documented remedy
    does exactly that and nothing more: ``git checkout HEAD -- <path>`` (the sync the
    skill tells the operator to do after a refusal) restores the working copy AND the
    index from HEAD, so HEAD is unmoved and all three reads agree before the caller
    moves the file.

    The result is read back and asserted rather than trusted: a "restored" that left
    HEAD's order elsewhere would put the next refusal in the wrong arm, and the test
    would be pinning the wrong comparison.
    """
    _git(repo, "checkout", "HEAD", "--", ORDER_REL)
    head_bytes = _committed_order(repo)
    assert head_bytes == _order_path(repo).read_bytes(), (
        "the file does not hold HEAD's order, so the next refusal is the wrong arm")
    return head_bytes




