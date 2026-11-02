"""The commit-failure classifier's honesty rules, driven against real trees.

The classifier in ``_commit_cause`` is the half of a refused commit an operator
reads, so the properties that matter are the negative ones: a probe the timeout
killed is never read as an answer, a quote of git's own text is never re-formatted,
and a state is named only where a git call measured it. The fixtures are real
trees rather than hand-written ``CompletedProcess`` values wherever the point is
that the probes ran.
"""

from __future__ import annotations

import subprocess

import pytest
from _harness import _git_env_with_identity, _git_ok, build_bare_origin
from session_commit_cause_support import (
    _HARDENED_GIT,
    _git_refusing,
    _git_via,
    _hung_probe_git,
)
from session_git_support import (
    _pushable_clone,
    _repo,
    _seed_ahead,
    _tracked_session,
)

from noni import _commit_cause, _session_git


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    """Pin a git identity, as the rest of the ``_session_git`` suites do.

    The suite's autouse conftest clears the author/committer variables, so a
    file that drives the helpers in-process has to pin one itself or git refuses
    every commit for want of an identity, and the test would observe that
    refusal instead of the state it built.
    """
    for name, value in _git_env_with_identity().items():
        monkeypatch.setenv(name, value)


def _pushable_clone_with_change(tmp_path):
    """A pushable clone whose tracked session file carries an uncommitted change.

    The tree is the one the generic-cause test needs: committable (``main``
    tracks a branch origin still holds), and holding a real change (the close
    run's bytes are on disk and not in HEAD) -- the state in which a refused
    commit matches none of the named causes and only the generic clause fits.
    """
    origin = tmp_path / "nc-origin.git"
    clone = tmp_path / "nc-clone"
    build_bare_origin(origin, [clone])
    target = _tracked_session(clone)
    target.write_text("- status: closed\n", encoding="utf-8")
    return origin, clone, target


def test_a_killed_probe_leaves_the_line_to_gits_own_words(tmp_path, monkeypatch):
    """A probe the timeout killed answered nothing, so this classifies nothing.

    The upstream probe is the call that could invent a state here: on a tree
    whose origin is gone, a classifier that read a killed ``rev-parse`` as 'this
    ref does not resolve' would print UPSTREAM_GONE and send the operator to a
    remote they cannot reach. Hanging that call must give the unfounded clause
    up -- the line falls back to git's own words.
    """
    origin, clone = _pushable_clone(tmp_path, name="no-answer-clone")
    _tracked_session(clone)
    target = clone / "noni" / "sessions" / "2026-10-01-dddddd.md"
    target.write_text("- status: closed\n", encoding="utf-8")
    run = _hung_probe_git({"rev-parse"})
    monkeypatch.setattr(_session_git, "git", _git_via(run))
    monkeypatch.setattr(_commit_cause, "_git", _git_via(run))
    refused = subprocess.CompletedProcess([], 1, "", "fatal: nothing was answered")

    assert _commit_cause.commit_failure_cause(clone, refused) is None
    assert target.is_file()
    assert "rev-parse" in run.asked, run.asked
    assert _commit_cause.commit_failed(clone, refused) == \
        "git could not commit: fatal: nothing was answered"
    assert origin.is_dir() or clone.is_dir()


def test_a_killed_upstream_probe_is_never_read_as_the_gone_clause(tmp_path,
                                                                  monkeypatch):
    """The specific lie this guard exists for, on a tree that can still commit.

    ``rev-parse`` is the verb every upstream probe runs, so hanging it hangs each
    question the classifier asks about the upstream -- on a branch that is
    configured against one. A classifier that read a killed call as 'this ref
    does not resolve' would print UPSTREAM_GONE and send the operator to fix a
    state nobody measured. The writer's own reset/add/commit keep answering, so
    the commit lands and nothing is claimed about the upstream.
    """
    origin, clone = _pushable_clone(tmp_path, name="killed-upstream")
    target = _tracked_session(clone)
    target.write_text("- status: closed\n", encoding="utf-8")
    run = _hung_probe_git({"rev-parse"})
    monkeypatch.setattr(_session_git, "git", _git_via(run))
    monkeypatch.setattr(_commit_cause, "_git", _git_via(run))

    ok, why = _session_git.stage_and_commit(clone, target, "close: d")

    assert ok, why  # the commit is git's to take; nothing is claimed about it
    assert why == ""
    assert _commit_cause.UPSTREAM_GONE not in why
    assert run.asked, "no probe was asked at all, so nothing was tested"
    assert origin.is_dir()


def test_a_quiet_git_failure_reports_no_invented_cause(tmp_path):
    """A failed commit whose git output was empty on both streams is unclassified.

    There is no state to name (the tree is healthy, the upstream resolves) and
    nothing to quote, so the honest line is the one that says so. The name names
    what the classifier refuses to do: invent a cause for a fault it was not
    told about.
    """
    origin, clone = _pushable_clone(tmp_path, name="quiet-cause")
    _tracked_session(clone)
    silent = subprocess.CompletedProcess([], 1, "", "")
    assert _commit_cause.commit_failure_cause(clone, silent) is None
    assert _commit_cause.commit_failed(clone, silent) == \
        "git could not commit: no reason given"
    assert origin.is_dir()


def test_a_quiet_failure_on_a_tree_with_no_upstream_names_that_state(tmp_path):
    """The one case where a quiet git failure does have a state to name.

    A private state repository that was never pushed is committable and healthy
    by every probe git answers, so a refusal there is the no-upstream state and
    the clause is worth printing even when git quoted nothing.
    """
    repo = _repo(tmp_path)  # no remote at all: nothing was ever pushed
    _tracked_session(repo)
    silent = subprocess.CompletedProcess([], 1, "", "")
    assert _commit_cause.commit_failure_cause(repo, silent) == _commit_cause.NO_UPSTREAM
    assert _commit_cause.commit_failed(repo, silent).startswith(
        f"git could not commit -- {_commit_cause.NO_UPSTREAM}")


def test_the_failure_line_quotes_gits_words_without_reading_them_as_slots(tmp_path):
    """git's text is quoted verbatim, never re-formatted.

    These bytes can originate with the remote or a credential helper, so a
    payload that reads as a format placeholder must print as the text it is
    rather than raise out of the writer's failure path.
    """
    repo = _repo(tmp_path)
    _tracked_session(repo)
    hostile = subprocess.CompletedProcess(
        [], 1, "", "fatal: {0!r} {quoted!x} {missing} {quoted}")
    line = _commit_cause.commit_failed(repo, hostile)
    assert "{0!r}" in line, line
    assert "{missing}" in line, line
    assert "git could not commit -- " in line, line


def test_a_commit_the_upstream_rejected_names_the_generic_cause(tmp_path,
                                                                monkeypatch):
    """The upstream resolves and the tree carries a real change, so none of the
    three named states holds: the honest answer is git's own fault clause with
    git's words after it, not a state the classifier guessed at.

    The refusal is forced at the seam instead of by taking git's identity away.
    Stripping ``GIT_AUTHOR_EMAIL``/``GIT_COMMITTER_EMAIL`` was the wrong lever:
    git reads an identity from four sources and the env vars rank *below* the
    tree's own ``.git/config``, so a CI checkout that set ``user.name`` and
    ``user.email`` repo-locally (what ``actions/checkout`` does) supplied one
    anyway and the commit landed -- green on the developer's machine, red on the
    runner. The forcing must not depend on ambient config, so the refusal is
    made at the seam the writers' helper calls through: exactly the commit call
    comes back refused (with git's own 'no identity' text, the answer this tree
    would have given) while reset, add and every classifier probe run for real
    against the tree that produced the refusal.
    """
    origin, clone, target = _pushable_clone_with_change(tmp_path)
    _seed_ahead(origin, tmp_path, "rejected", {"other.md": "moved\n"})
    monkeypatch.setattr(_session_git, "git",
                        _git_refusing("commit", "Author identity unknown"))

    ok, why = _session_git.stage_and_commit(clone, target, "close: d")

    assert ok is False, why
    assert _commit_cause.GIT_REFUSED in why, why
    assert "git said:" in why, why
    assert "Author identity unknown" in why, why


def test_a_detached_tree_is_left_to_gits_own_words(tmp_path):
    """A tree with no branch name has no upstream to classify, so nothing is named.

    Every clause this module can print is a claim about a branch's upstream. On a
    detached HEAD there is no branch to have an upstream, and the probes that
    follow would answer about whatever commit happens to be checked out -- so the
    classifier stops at the branch name and the line carries git's words alone.
    """
    origin, clone = _pushable_clone(tmp_path, name="detached")
    _tracked_session(clone)
    _git_ok(clone, "checkout", "-q", "--detach")
    refused = subprocess.CompletedProcess([], 1, "", "fatal: detached")
    assert _commit_cause.commit_failure_cause(clone, refused) is None
    assert _commit_cause.commit_failed(clone, refused) == \
        "git could not commit: fatal: detached"
    assert origin.is_dir()


def test_the_index_probes_ask_about_this_writers_own_path_only(tmp_path, monkeypatch):
    """The nothing-to-commit question is asked of one path, never of the tree.

    Two reasons the probes carry a pathspec, both measured here: a whole-tree
    diff re-stats every file to answer a question about one, and it would report
    somebody else's dirty file as a reason this run's own write had something to
    commit. The writer passes the one path it owns down through
    :func:`commit_failed`, so the argv of each of the three probes is asserted to
    name that path -- not just the verdict they lead to.
    """
    origin, clone = _pushable_clone(tmp_path, name="pathspec")
    _tracked_session(clone)  # the one path this writer owns, committed baseline
    rel = "noni/sessions/2026-10-01-dddddd.md"
    silent = subprocess.CompletedProcess([], 1, "", "fatal: rejected")
    asked: list[tuple[str, ...]] = []

    def recording_git(repo, *args):
        asked.append(tuple(str(part) for part in args))
        return _HARDENED_GIT(repo, *args)

    monkeypatch.setattr(_commit_cause, "_git", recording_git)
    # The path is handed in, which is the whole of the difference between this
    # call and the one a caller that named no path makes.
    assert _commit_cause.commit_failure_cause(clone, silent, rel) == \
        _commit_cause.NOTHING_TO_COMMIT

    diffs = [argv for argv in asked if argv[0] == "diff"]
    assert len(diffs) == 2, asked
    for argv in diffs:
        assert "--" in argv, argv
        assert argv[argv.index("--") + 1:] == (rel,), argv
    listing = [argv for argv in asked if argv[0] == "ls-files"]
    assert len(listing) == 1, asked
    assert listing[0][listing[0].index("--") + 1:] == (rel,), asked

    # The other half of the guarantee: a file this run does not own is dirty and
    # still does not make this run's own write look like a change. The index
    # probe would answer differently if it were asked of the whole tree.
    (clone / "elsewhere.md").write_text("not mine\n", encoding="utf-8")
    asked.clear()
    assert _commit_cause.commit_failure_cause(clone, silent, rel) == \
        _commit_cause.NOTHING_TO_COMMIT
    assert [argv for argv in asked if argv[0] == "diff"], asked
    assert origin.is_dir()

    # And the whole-tree form is still the whole-tree form: a caller that named
    # no path gets the question asked of everything, which is what it asked for.
    # Here that answer differs, because somebody else's file is the dirty one.
    asked.clear()
    assert _commit_cause.commit_failure_cause(clone, silent) == \
        _commit_cause.GIT_REFUSED
    whole = [argv for argv in asked if argv[0] == "diff"]
    assert len(whole) == 2, asked
    for argv in whole:
        assert argv[argv.index("--") + 1:] == (".",), argv


def test_a_branch_configured_against_a_local_remote_names_no_gone_state(tmp_path):
    """A branch whose remote is this clone itself has no origin to have lost it.

    ``remote "."`` is git's own way of tracking another branch in the same
    repository, so the gone clause would be wrong here: no remote ever held the
    ref. This is one of the states the module documents as a 'nothing to compare
    against' answer, reached by config rather than by a missing remote.
    """
    repo = _repo(tmp_path)
    _tracked_session(repo)
    _git_ok(repo, "checkout", "-q", "-b", "feature")
    _git_ok(repo, "config", "remote..origin", ".")
    _git_ok(repo, "config", "branch.feature.remote", ".")
    _git_ok(repo, "config", "branch.feature.merge", "refs/heads/main")
    silent = subprocess.CompletedProcess([], 1, "", "")
    assert _commit_cause.commit_failure_cause(repo, silent) == _commit_cause.NO_UPSTREAM


def test_a_branch_with_no_fetch_refspec_for_its_remote_is_a_none_state(tmp_path):
    """A remote that fetches nothing leaves a ref this clone can never hold.

    With no ``remote.<name>.fetch`` line there is no way the upstream ref could
    exist locally, and git's own wording cannot tell this apart from a branch
    origin deleted -- so the honest clause is the no-upstream one. The branch
    still names the remote (the one line a clone cannot lose without losing its
    upstream outright), and its merge line is the kind this classifier answers
    from config alone, so only the refspec probe stands between this tree and the
    gone clause. That probe is what the test drives to nothing.
    """
    origin, clone = _pushable_clone(tmp_path, name="no-refspec")
    _tracked_session(clone)
    _git_ok(clone, "config", "--unset-all", "remote.origin.fetch")
    _git_ok(clone, "config", "--unset-all", "branch.main.remote")
    _git_ok(clone, "config", "branch.main.merge", "refs/tags/not-a-head")
    silent = subprocess.CompletedProcess([], 1, "", "")
    assert _commit_cause.commit_failure_cause(clone, silent) == _commit_cause.NO_UPSTREAM
    assert origin.is_dir()


def test_a_branch_whose_merge_line_is_not_a_head_line_falls_back_to_its_name(tmp_path):
    """A merge line git would never follow leaves the branch's own name as upstream.

    git honours a merge ref under refs/heads/ only; the classifier does not trust
    a ref git would not follow, and falls back to the remote plus the branch's own
    name. That ref resolves on a freshly pushed clone, so the tree classifies as
    a real refusal rather than one of the named states.
    """
    origin, clone = _pushable_clone(tmp_path, name="odd-merge")
    target = _tracked_session(clone)
    target.write_text("- status: closed\n", encoding="utf-8")
    _git_ok(clone, "config", "branch.main.merge", "refs/tags/nope")
    refused = subprocess.CompletedProcess([], 1, "", "fatal: rejected")
    assert _commit_cause.commit_failure_cause(clone, refused) == _commit_cause.GIT_REFUSED
    assert origin.is_dir()
