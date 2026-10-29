"""Every session writer clears the inherited git variables (issue #39).

``--repo`` is the only thing that names the state root, but git reads a body of
variables from the environment before it ever consults the ``-C`` path its
caller passed. Four of them relocate the repository outright — ``GIT_DIR`` and
``GIT_COMMON_DIR`` name a different repository directory, ``GIT_WORK_TREE`` a
different working tree, ``GIT_INDEX_FILE`` a different index to stage and commit
through — and they are not the whole hazard. ``GIT_OBJECT_DIRECTORY`` and
``GIT_ALTERNATE_OBJECT_DIRECTORIES`` move the object store itself, so a commit
is written into (or read from) a tree the caller never named while the state
root's own refs look untouched; ``GIT_TRACE``, ``GIT_TRACE2`` and
``GIT_TRACE2_EVENT`` make the child write its trace to any file the caller
picks; ``GIT_NAMESPACE`` silently redirects every ref name. A writer that handed
its child the ambient environment therefore wrote somewhere other than the state
root while still printing the success line for the tree it was pointed at.

``noni.gitenv.child_env`` is the fix, and it is fail-closed: the child gets
every variable the process has except the ones whose name starts with ``GIT_``
and that are not in the allowlist the writers need (identity, and the config and
transport pins a caller legitimately sets). This file is the proof for the four
session writers that commit: register, claim, close and release.

Each writer runs in two cases. The first sets ``GIT_DIR`` and ``GIT_WORK_TREE``
to a decoy repository under ``tmp_path``; the second sets only
``GIT_INDEX_FILE`` to a decoy index. Both then ask the same four questions, in
``_harness.assert_writers_clear_git_env``: the record is committed in the state
root, the decoy is byte-for-byte what it was, and the state root's own
``git status --porcelain`` is empty (so the record was committed and not merely
written). A third case sets the object-store and trace variables to paths under
``tmp_path`` and asks the same questions of those.

The variables are set explicitly in the subprocess environment rather than
inherited: ``tests/conftest.py`` clears the location ones for every test, so a
launcher that relied on inheritance would have set nothing and passed no matter
what the writer did.
"""

from __future__ import annotations

from _harness import assert_writers_clear_git_env
from writer_git_env_support import (
    SESSION_REL,
    TASK,
    _assert_object_store_untouched,
    _assert_row_released,
    _claim_run,
    _close_run,
    _decoy_case,
    _decoy_env,
    _index_case,
    _object_store_case,
    _register_repo,
    _register_run,
    _registered_rel,
    _release_run,
    _sessions_repo,
)

# --- claim -----------------------------------------------------------------------


def test_claim_commits_in_the_state_root_with_a_decoy_git_dir(tmp_path):
    """An inherited GIT_DIR/GIT_WORK_TREE must not take the claim elsewhere."""
    repo = _sessions_repo(tmp_path, "claim-dir")
    env, decoy, before = _decoy_case(tmp_path, "claim-decoy-dir")
    proc = _claim_run(repo, _decoy_env(env))
    assert_writers_clear_git_env(proc, repo, SESSION_REL, decoy, before,
                                 None, None, f"- claim: {TASK}")


def test_claim_commits_in_the_state_root_with_a_decoy_git_index_file(tmp_path):
    """An inherited GIT_INDEX_FILE must not be the index the claim is staged through."""
    repo = _sessions_repo(tmp_path, "claim-idx")
    env, index, before = _index_case(tmp_path, repo, "claim-decoy-index")
    proc = _claim_run(repo, _decoy_env(env))
    assert_writers_clear_git_env(proc, repo, SESSION_REL, None, {}, index, before,
                                 f"- claim: {TASK}")


# --- close -----------------------------------------------------------------------


def test_close_commits_in_the_state_root_with_a_decoy_git_dir(tmp_path):
    """The status line lands in the state root's register, not the decoy's."""
    repo = _sessions_repo(tmp_path, "close-dir")
    env, decoy, before = _decoy_case(tmp_path, "close-decoy-dir")
    proc = _close_run(repo, _decoy_env(env))
    assert_writers_clear_git_env(proc, repo, SESSION_REL, decoy, before,
                                 None, None, "- status: closed")


def test_close_commits_in_the_state_root_with_a_decoy_git_index_file(tmp_path):
    repo = _sessions_repo(tmp_path, "close-idx")
    env, index, before = _index_case(tmp_path, repo, "close-decoy-index")
    proc = _close_run(repo, _decoy_env(env))
    assert_writers_clear_git_env(proc, repo, SESSION_REL, None, {}, index, before,
                                 "- status: closed")


# --- release ---------------------------------------------------------------------


def test_release_commits_in_the_state_root_with_a_decoy_git_dir(tmp_path):
    """The row is removed from the state root's register and committed there."""
    repo = _sessions_repo(tmp_path, "release-dir", claims=[TASK])
    env, decoy, before = _decoy_case(tmp_path, "release-decoy-dir")
    proc = _release_run(repo, _decoy_env(env))
    _assert_row_released(repo)
    assert_writers_clear_git_env(proc, repo, SESSION_REL, decoy, before,
                                 None, None, "- identity: dev")


def test_release_commits_in_the_state_root_with_a_decoy_git_index_file(tmp_path):
    repo = _sessions_repo(tmp_path, "release-idx", claims=[TASK])
    env, index, before = _index_case(tmp_path, repo, "release-decoy-index")
    proc = _release_run(repo, _decoy_env(env))
    _assert_row_released(repo)
    assert_writers_clear_git_env(proc, repo, SESSION_REL, None, {}, index, before,
                                 "- identity: dev")


# --- register ---------------------------------------------------------------------


def test_register_commits_in_the_state_root_with_a_decoy_git_dir(tmp_path):
    """A fresh registration commits its file in the state root it was named."""
    repo = _register_repo(tmp_path, "register-dir")
    env, decoy, before = _decoy_case(tmp_path, "register-decoy-dir")
    proc = _register_run(repo, _decoy_env(env))
    assert_writers_clear_git_env(proc, repo, _registered_rel(proc), decoy, before,
                                 None, None, "- identity: developer")


def test_register_commits_in_the_state_root_with_a_decoy_git_index_file(tmp_path):
    repo = _register_repo(tmp_path, "register-idx")
    env, index, before = _index_case(tmp_path, repo, "register-decoy-index")
    proc = _register_run(repo, _decoy_env(env))
    assert_writers_clear_git_env(proc, repo, _registered_rel(proc), None, {},
                                 index, before, "- identity: developer")


# --- the object store and the trace sink ------------------------------------------


def test_session_writer_commits_with_a_hostile_object_store_and_trace(tmp_path):
    """claim.py commits into the state root while the object store is pointed away."""
    repo = _sessions_repo(tmp_path, "claim-objstore")
    vars_, objects, trace = _object_store_case(tmp_path, "claim-decoy-objects")
    proc = _claim_run(repo, _decoy_env(vars_))
    assert_writers_clear_git_env(proc, repo, SESSION_REL, None, {}, None, None,
                                 f"- claim: {TASK}")
    _assert_object_store_untouched(vars_, objects, trace)
