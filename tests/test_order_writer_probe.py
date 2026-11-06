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

import subprocess

from order_fixtures import (
    BASELINE_ID,
    NOW,
    ORDER_REL,
    _committed_order,
    _entry,
    _gitwrite_module,
    _issues,
    _order_inprocess,
    _order_module,
    _order_path,
    _repo,
    _rival_commit,
    _seed,
)
from order_race_fixtures import (
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
        return subprocess.CompletedProcess(["git", *args], 0,
                                           committed.decode("utf-8") + "\n", "")

    monkeypatch.setattr(helper, "git", show)
    code, _out, _err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                        "--now", NOW)
    assert code == module.EXIT_REFUSAL, code


# --- a probe that cannot answer is an environment fault -----------------------


def _drive_add_with_probe(repo, monkeypatch, answer):
    """Run a committed ``add`` whose freshness probe answers ``answer``.

    Only the probe's own call is intercepted: the ``add`` and ``commit`` the writer
    makes afterwards run for real, so a probe read as "unchanged" really does land a
    commit and a probe read as a fault really does stop before one.
    """
    helper = _gitwrite_module()
    real_git = helper.git
    probes: list[tuple] = []

    def git(repo, *args):
        if args and args[0] == "show":
            probes.append(args)
            return answer(args)
        return real_git(repo, *args)

    # The repository is built first and the spy installed only for the run under
    # test: the spy answers every ``git show``, the fixture's own included, and the
    # harness commits through helpers that read HEAD as well, so a spy in place while
    # the tree is built makes the fixture die on a fault that belongs to nothing in
    # the scenario.
    monkeypatch.setattr(helper, "git", git)
    code, out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                      "--now", NOW)
    return code, out, err, probes


def _hung(args):
    """What the writer's own helper hands back for a call that cannot finish."""
    return subprocess.CompletedProcess(["git", "show", *args],
                                       _gitwrite_module().GIT_TIMEOUT_RC, "",
                                       "git show timed out")


def _failed(args):
    """128 for a reason that is not git's honest 'not in HEAD' answer."""
    return subprocess.CompletedProcess(["git", "show", *args], 128, "",
                                       "fatal: not a valid object name 'HEAD'")


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
    real_git = helper.git
    seen: list[tuple] = []

    def git(repo, *args):
        seen.append(args)
        return real_git(repo, *args)

    # The repository is built first and the spy installed only for the run under
    # test: the spy answers every ``git show``, the fixture's own included, and the
    # harness commits through helpers that read HEAD as well, so a spy in place while
    # the tree is built makes the fixture die on a fault that belongs to nothing in
    # the scenario.
    repo = _repo(tmp_path)
    _seed(repo, _entry(11, BASELINE_ID))
    monkeypatch.setattr(helper, "git", git)
    code, _out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                       "--now", NOW)
    assert code == 0, err
    assert ("show", f"HEAD:{ORDER_REL}") in seen, seen
    shows = [args for args in seen if args[0] == "show"]
    assert len(shows) == 1, f"the probe ran {len(shows)} git calls: {shows}"


# --- --no-commit keeps its contract ------------------------------------------
