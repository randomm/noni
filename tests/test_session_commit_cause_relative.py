"""A relative ``--repo`` commit failure is classified by its pathspec, not its upstream.

``test_session_relative_repo.py`` pins what a refused relative-repo commit
*prints* to an operator. This file pins the two mechanics underneath that print,
because both did their damage where an exit code could not see it:

* ``stage_and_commit`` handed ``git reset``/``add``/``commit --only`` a pathspec
  built by joining the caller-cwd-relative ``--repo`` to the state path (AC2). The
  argv of the three steps is asserted at the module's own git seam rather than the
  verdict, because a doubled pathspec can still exit 0 on a clone that happens to
  hold that path -- argv is the only witness that says which path git was pointed
  at;
* ``_index_matches_head`` receives that same string as its pathspec and asks three
  probes of it, so a doubled rel probes a path whose committed bytes no run here
  changes, and the classifier reports "the file already holds the bytes this run
  wrote" about a file whose work-tree bytes plainly differ (AC6). The misread also
  costs the operator their clause: with the index reported clean, the line that
  came back blamed a missing upstream (AC8).

The classifier is driven directly here, with the pathspec handed in, because the
point is the classification of a given pathspec rather than the run that produced
one. Under the explicit-name contract a caller cannot hand the primitive a
``--repo`` component at all -- :func:`noni._session_git.relative_name` refuses a
name that is absolute or that leaves the root, and a caller builds its name with
:func:`noni._session_git.writer_name` -- so the doubled spelling is planted here
as the classifier's own pathspec argument. That is precisely the reading this
suite was written to catch: a pathspec that named the decoy instead of the run's
own file, which is what the old cwd-joining heuristic could still produce (no
such helper is in the package any more).

All cases run on the nested-state fixture (project, git-ignored clone, decoy
committed at the doubled path, origin holding ``main``) with the process cwd
inside the project, which is what makes the ``--repo`` a relative one.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from _harness import _git_env_with_identity, _git_ok
from session_git_support import (
    STATE_DIR,
    _committed_names,
    _nested_state,
)

from noni import _commit_cause, _session_git

SID = "2026-10-01-cccccc"
REL = f"noni/sessions/{SID}.md"
DOUBLED = f"{STATE_DIR}/noni/sessions/{SID}.md"

# git's own words for a pathspec naming a path the tree does not hold. That clause
# is the whole doubled-pathspec fault, so it is the needle at both ends: the honest
# line for the run's own file must not carry it, and the upstream clause must not
# stand in for it.
PATHSPEC_FAULT = "did not match any files"


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    """Pin a git identity, as the rest of the ``_session_git`` suites do.

    The suite's autouse conftest clears the author/committer variables, so a file
    that drives the helpers in-process has to pin one itself or git refuses every
    commit for want of an identity, and the test would observe that refusal
    instead of the path handling under test.
    """
    for name, value in _git_env_with_identity().items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def relative_state(tmp_path):
    """The private-state route with the process cwd moved inside the project.

    The cwd is the whole of the difference between this fixture and a plain one:
    with it, ``Path(STATE_DIR)`` is the caller's spelling of the state root, the
    one argparse hands the writers, and a path built from it carries the ``st/``
    component a doubled pathspec is made of.
    """
    project, state, session = _nested_state(tmp_path, SID, name="cause-project")
    cwd_before = os.getcwd()
    os.chdir(project)
    try:
        yield project, state, session
    finally:
        os.chdir(cwd_before)


def _move_status_line(session: Path) -> Path:
    """Move the session's status line, the way close.py does before it commits.

    Without a real change in the tree every verdict below would be about the
    absence of a diff rather than about the pathspec.
    """
    session.write_text(
        session.read_text(encoding="utf-8").replace("- status: active",
                                                    "- status: closed"),
        encoding="utf-8")
    return session


def _asking_the_primitive():
    """A ``(sink, restore)`` pair wrapping the module's own git seam.

    The seam is replaced rather than ``subprocess.run``, which the hardened helper
    resolves through its own module; the captured reference is what lets the
    wrapper call it without recursing into itself.
    """
    asked: list[tuple[str, ...]] = []
    real = _session_git.git

    def recording(repo, *args):
        asked.append(tuple(str(part) for part in args))
        return real(repo, *args)

    _session_git.git = recording

    def restore() -> list[tuple[str, ...]]:
        _session_git.git = real
        return asked

    return asked, restore


def _pathspecs_of(asked, verb):
    """The pathspec the named verb was handed, or the assertion that it wasn't."""
    call = [argv for argv in asked if argv[0] == verb]
    assert len(call) == 1, (verb, asked)
    return call[0][call[0].index("--") + 1:]


def test_the_three_git_steps_name_the_repo_relative_pathspec(relative_state):
    """AC2: reset, add and commit --only each name ``noni/sessions/<sid>.md``.

    The argv is the assertion, not the verdict: a fix that made the commit succeed
    while still handing git the doubled string would exit 0 on a clone that
    happened to hold that path, and this test would still see which path git was
    pointed at.
    """
    _project, state, session = relative_state
    _move_status_line(session)
    _asked, restore = _asking_the_primitive()
    try:
        ok, why = _session_git.stage_and_commit(Path(STATE_DIR), REL, "close: x")
    finally:
        asked = restore()

    assert ok, why
    for verb in ("reset", "add", "commit"):
        assert _pathspecs_of(asked, verb) == (REL,), verb
    assert _committed_names(state) == [REL], "the commit moved more than the one path"
    assert "- status: closed" in _git_ok(state, "show", f"HEAD:{REL}").stdout


def test_a_refused_commit_on_a_relative_repo_clone_names_the_refusal(relative_state):
    """AC8 on the tree a reader builds: a refused commit is not called an upstream fault.

    The refusal is reached the way an operator reaches it -- a run that wrote the
    bytes HEAD already holds, so ``commit --only`` refuses and every probe is
    asked for real against this clone. The clone has an origin and a pushed
    ``main``, which is what makes the upstream clause a falsifiable claim rather
    than an unfalsifiable one: a tree with no remote at all really would answer
    "no upstream configured", and the writer suites already cover that shape.
    Here every upstream probe resolves, so the honest line is git's own refusal,
    quoted and not paraphrased.
    """
    _project, state, _session = relative_state
    # The fixture committed the session as it stands on disk, so writing the same
    # bytes back is the state release.py and close.py hit when the row or status
    # they were asked to set was already set: staged, staged-and-HEAD equal, and
    # git refusing the empty commit.
    ok, why = _session_git.stage_and_commit(Path(STATE_DIR), REL, "close: x")

    assert ok is False, "precondition: git must refuse the empty commit"
    assert _commit_cause.NO_UPSTREAM not in why, (
        f"a clone whose branch tracks a branch origin holds was told it has no "
        f"upstream: {why}"
    )
    assert PATHSPEC_FAULT not in why, (
        f"a pathspec that matched the run's own file was reported as a pathspec "
        f"fault: {why}"
    )
    assert DOUBLED not in why, why
    assert "git said:" in why, why


def test_the_index_probe_reads_one_path_and_its_own(relative_state):
    """AC6: one tree, two readings, two verdicts.

    The doubled rel names the decoy path, whose committed bytes no run here
    changes, so all three nothing-to-commit probes answer "unchanged" and the
    classifier reports that the file already holds what this run wrote -- about a
    file whose work-tree bytes plainly differ. The repo-relative rel asks about the
    path that does carry the change and gets the honest verdict. Both are asserted
    on one identical tree, which is what makes the pair more than two independent
    claims.
    """
    _project, state, session = relative_state
    _move_status_line(session)
    refused = subprocess.CompletedProcess([], 1, "", "fatal: rejected")

    assert _commit_cause.commit_failure_cause(state, refused, DOUBLED) == \
        _commit_cause.NOTHING_TO_COMMIT, (
        "the doubled pathspec must still misread this tree, or the pair below "
        "measures nothing"
    )
    assert _commit_cause.commit_failure_cause(state, refused, REL) == \
        _commit_cause.GIT_REFUSED, (
        "the repo-relative pathspec must see the change the run actually made"
    )


def test_the_honest_line_never_blames_a_missing_upstream(relative_state):
    """AC8: what the classifier says about the run's own path on this tree.

    The clause the base produced here was "this branch has no upstream
    configured", which is a state this clone is not in -- its ``main`` tracks a
    branch origin holds -- and was reached only because the doubled index probe
    reported a clean tree. With the repo-relative pathspec the line names the
    refusal git actually gave, carries no path beginning with the --repo
    component, and never reaches for an upstream clause or a pathspec fault it
    never met.
    """
    _project, state, session = relative_state
    _move_status_line(session)
    refused = subprocess.CompletedProcess([], 1, "", "fatal: rejected")

    line = _commit_cause.commit_failed(state, refused, REL)

    assert _commit_cause.GIT_REFUSED in line, line
    assert "git said:" in line, line
    assert "fatal: rejected" in line, line
    assert "no upstream configured" not in line, line
    assert PATHSPEC_FAULT not in line, line
    assert DOUBLED not in line, line
    assert "- status: closed" in session.read_text(encoding="utf-8")
