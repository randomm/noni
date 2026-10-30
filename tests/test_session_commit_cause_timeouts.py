"""The classifier's timeout honesty: a killed probe is never read as an answer.

Split from ``test_session_commit_cause`` (the 500-line source limit) along the
classifier's own honesty rule: every probe asks ``_answered`` before it reads a
returncode, because ``GIT_TIMEOUT_RC`` is a non-zero exit that reports a kill and
not a verdict. Each test here kills one class of git call -- or hands back the
sentinel directly -- on a tree that can still commit, and asserts the classifier
names no state at all rather than the one an unwary reading of that exit would
print. The fixtures are real trees, built with the helpers the main suite uses.
"""

from __future__ import annotations

import subprocess

import pytest
from _harness import _git_env_with_identity
from session_commit_cause_support import _git_via, _hung_probe_git
from session_git_support import _pushable_clone, _tracked_session

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


def test_a_killed_probe_that_prints_gits_words_is_still_no_answer(tmp_path,
                                                                  monkeypatch):
    """A probe carrying the timeout sentinel answers nothing, even when it quotes text.

    Three of this classifier's probes -- the branch name, the upstream's
    configured ref, and the fetch refspec list -- read a *non-zero* exit as the
    healthy answer, so a probe killed by the timeout would not be read as a
    refusal but as 'this branch has no upstream configured': the one clause this
    classifier prints whatever git said. The guard is one predicate that compares
    the returncode against the sentinel before any caller reads an answer, and
    the sentinel is a value this module does not own. Re-deriving it from
    ``_session_git.GIT_TIMEOUT_RC`` here would be the same expression the code
    already has, so the test pins the behaviour instead of the constant: a
    timeout-shaped call must classify nothing even when it carries the text an
    unwary reader would act on. Both call shapes are driven -- the ``None`` a
    helper hands back for a probe that could not run, and the sentinel a killed
    call comes back as.
    """
    origin, clone = _pushable_clone(tmp_path, name="sentinel-answered")
    _tracked_session(clone)
    killed = subprocess.CompletedProcess(
        ["git", "config"], _session_git.GIT_TIMEOUT_RC, "",
        f"git config timed out after {_session_git.GIT_TIMEOUT}s")

    assert _commit_cause._answered(None) is False
    assert _commit_cause._answered(killed) is False
    assert _commit_cause._answered(
        subprocess.CompletedProcess(["git", "config"], 1, "", "no such key")) is True

    monkeypatch.setattr(_commit_cause, "_config_value", lambda repo, key: None)
    refused = subprocess.CompletedProcess([], 1, "", "fatal: rejected")
    assert _commit_cause.commit_failure_cause(clone, refused) is None

    monkeypatch.setattr(_commit_cause, "_git", lambda repo, *a: killed)
    assert _commit_cause.commit_failure_cause(clone, refused) is None
    assert _commit_cause.commit_failed(clone, refused) == \
        "git could not commit: fatal: rejected"
    assert origin.is_dir()


def test_a_killed_branch_probe_is_not_read_as_the_no_upstream_clause(tmp_path,
                                                                    monkeypatch):
    """A killed config call is not evidence that the branch has no upstream.

    The no-upstream clause is the one this classifier prints whatever git said, so
    the probe that reaches it has to have answered: a config call killed by the
    timeout on a branch that *is* configured against origin must give the clause
    up rather than send the operator to configure an upstream already there.
    """
    origin, clone = _pushable_clone(tmp_path, name="killed-config")
    _tracked_session(clone)
    run = _hung_probe_git({"config"})
    monkeypatch.setattr(_session_git, "git", _git_via(run))
    monkeypatch.setattr(_commit_cause, "_git", _git_via(run))
    refused = subprocess.CompletedProcess([], 1, "", "fatal: nothing was answered")

    assert _commit_cause.commit_failure_cause(clone, refused) is None
    assert "config" in run.asked, run.asked
    assert origin.is_dir()


def test_a_killed_resolve_probe_never_becomes_the_gone_clause(tmp_path, monkeypatch):
    """The ref-verification probe, killed, gives the gone clause up.

    ``rev-parse --verify --quiet`` returning non-zero is how the classifier learns
    an upstream ref is gone; the same non-zero exit from a call the timeout killed
    means nobody measured anything, so the line must not tell the operator to fix
    a remote-tracking ref that may be perfectly present.
    """
    origin, clone = _pushable_clone(tmp_path, name="killed-verify")
    _tracked_session(clone)
    monkeypatch.setattr(_commit_cause, "_resolves", lambda repo, ref: None)
    refused = subprocess.CompletedProcess([], 1, "", "fatal: rejected")
    assert _commit_cause.commit_failure_cause(clone, refused) is None
    assert origin.is_dir()


def test_a_killed_abbreviation_probe_never_becomes_the_gone_clause(tmp_path,
                                                                  monkeypatch):
    """The unambiguous-name probe, killed, gives the gone clause up too.

    Two probes answer the same question (``--verify --quiet`` and ``--no-abbrev
    --verify``) and hanging only the second is the only way to show the second is
    honoured on its own rather than riding along with the first.
    """
    origin, clone = _pushable_clone(tmp_path, name="killed-noabbrev")
    _tracked_session(clone)
    monkeypatch.setattr(_commit_cause, "_abbreviates_to_head",
                        lambda repo, upstream: None)
    refused = subprocess.CompletedProcess([], 1, "", "fatal: rejected")
    assert _commit_cause.commit_failure_cause(clone, refused) is None
    assert origin.is_dir()


def test_a_killed_index_probe_is_never_read_as_nothing_to_commit(tmp_path,
                                                                monkeypatch):
    """A killed work-tree probe does not become 'this run wrote nothing new'.

    The nothing-to-commit clause tells the operator their file already holds these
    bytes. That claim rests on two diff probes and an untracked listing; if any of
    the three died, the classifier has not measured the tree and the clause is
    withheld.
    """
    origin, clone = _pushable_clone(tmp_path, name="killed-index")
    _tracked_session(clone)
    monkeypatch.setattr(_commit_cause, "_index_matches_head",
                        lambda repo, rel: None)
    refused = subprocess.CompletedProcess([], 1, "", "fatal: rejected")
    assert _commit_cause.commit_failure_cause(clone, refused) is None
    assert origin.is_dir()




def test_a_result_that_was_never_waited_on_names_no_cause(tmp_path):
    """``returncode=None`` is not a refusal, so it gets no cause.

    ``CompletedProcess`` allows a returncode of ``None`` -- it is the shape of a
    call that was launched and never waited on -- and every guard in this module
    reads that field. Read naively, ``None != 0`` is true, so an unwaited call
    would be classified as a failure git made and printed as a cause the operator
    could chase for an hour. Both halves of the guard are pinned here: the
    classifier names no state, and the probe predicate calls the answer no answer
    at all, so no probe downstream can read it either.
    """
    origin, clone = _pushable_clone(tmp_path, name="none-returncode")
    _tracked_session(clone)
    never_waited = subprocess.CompletedProcess(["git", "commit"], None, "", "")
    assert _commit_cause.commit_failure_cause(clone, never_waited) is None
    assert _commit_cause._answered(never_waited) is False
    # The line a caller prints for it stays git's own words, not a state.
    line = _commit_cause.commit_failed(clone, never_waited)
    assert "no reason given" in line or "could not commit" in line, line
    assert origin.is_dir()
