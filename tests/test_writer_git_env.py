"""The ledger and ordering writers clear the inherited git variables (issue #39).

The same contract ``tests/test_session_writer_git_env.py`` proves for the session
writers, for the two writers that commit a JSON artifact: ``decide.py`` (a ledger
record) and ``order.py`` (the ordering artifact). ``--repo`` is the only thing
that names the state root, but git reads a body of variables from the environment
before it ever consults the ``-C`` path its caller passed — the four that
relocate the repository outright, plus the object store, the trace sinks and the
ref namespace that ``noni.gitenv.child_env`` also strips.

Each writer runs in two cases. The first sets ``GIT_DIR`` and ``GIT_WORK_TREE``
to a decoy repository under ``tmp_path``; the second sets only ``GIT_INDEX_FILE``
to a decoy index. Both then ask the same four questions, in
``_harness.assert_writers_clear_git_env``: the record is committed in the state
root, the decoy is byte-for-byte what it was, and the state root's own
``git status --porcelain`` is empty. A third case per writer sets the object-store
and trace variables to paths under ``tmp_path`` and asks the same questions of
those (the objects a commit needs must not land in the decoy, and a trace file
must never appear).

The variables are set explicitly in the subprocess environment rather than
inherited: ``tests/conftest.py`` clears the location ones for every test, so a
launcher that relied on inheritance would have set nothing and passed no matter
what the writer did.
"""

from __future__ import annotations

import os

from _harness import assert_writers_clear_git_env
from writer_git_env_support import (
    ORDER_ISSUE,
    ORDER_REL,
    RECORD_REL,
    _assert_object_store_untouched,
    _decide_run,
    _decoy_case,
    _decoy_env,
    _index_case,
    _ledger_repo,
    _object_store_case,
    _order_run,
)

from noni import gitenv

# --- decide ---------------------------------------------------------------------


def test_decide_commits_in_the_state_root_with_a_decoy_git_dir(tmp_path):
    """The record is committed in the state root, not the GIT_DIR decoy."""
    repo = _ledger_repo(tmp_path, "decide-dir")
    env, decoy, before = _decoy_case(tmp_path, "decide-decoy-dir")
    proc = _decide_run(repo, _decoy_env(env))
    assert_writers_clear_git_env(proc, repo, RECORD_REL, decoy, before,
                                 None, None, '"status": "decided"')


def test_decide_commits_in_the_state_root_with_a_decoy_git_index_file(tmp_path):
    repo = _ledger_repo(tmp_path, "decide-idx")
    env, index, before = _index_case(tmp_path, repo, "decide-decoy-index")
    proc = _decide_run(repo, _decoy_env(env))
    assert_writers_clear_git_env(proc, repo, RECORD_REL, None, {}, index, before,
                                 '"status": "decided"')


# --- order ---------------------------------------------------------------------


def test_order_commits_in_the_state_root_with_a_decoy_git_dir(tmp_path):
    """The ordering artifact is committed in the state root, not the decoy."""
    repo = _ledger_repo(tmp_path, "order-dir")
    env, decoy, before = _decoy_case(tmp_path, "order-decoy-dir")
    proc = _order_run(repo, _decoy_env(env))
    assert_writers_clear_git_env(proc, repo, ORDER_REL, decoy, before,
                                 None, None, f'"issue": {ORDER_ISSUE}')


def test_order_commits_in_the_state_root_with_a_decoy_git_index_file(tmp_path):
    repo = _ledger_repo(tmp_path, "order-idx")
    env, index, before = _index_case(tmp_path, repo, "order-decoy-index")
    proc = _order_run(repo, _decoy_env(env))
    assert_writers_clear_git_env(proc, repo, ORDER_REL, None, {}, index, before,
                                 f'"issue": {ORDER_ISSUE}')


# --- the object store and the trace sink ------------------------------------------


def test_decide_commits_with_a_hostile_object_store_and_trace(tmp_path):
    """decide.py's record is committed in the state root, not the decoy store."""
    repo = _ledger_repo(tmp_path, "decide-objstore")
    vars_, objects, trace = _object_store_case(tmp_path, "decide-decoy-objects")
    proc = _decide_run(repo, _decoy_env(vars_))
    assert_writers_clear_git_env(proc, repo, RECORD_REL, None, {}, None, None,
                                 '"status": "decided"')
    _assert_object_store_untouched(vars_, objects, trace)


def test_order_commits_with_a_hostile_object_store_and_trace(tmp_path):
    """order.py's artifact is committed in the state root, not the decoy store."""
    repo = _ledger_repo(tmp_path, "order-objstore")
    vars_, objects, trace = _object_store_case(tmp_path, "order-decoy-objects")
    proc = _order_run(repo, _decoy_env(vars_))
    assert_writers_clear_git_env(proc, repo, ORDER_REL, None, {}, None, None,
                                 f'"issue": {ORDER_ISSUE}')
    _assert_object_store_untouched(vars_, objects, trace)


# --- the helper itself -------------------------------------------------------------


def test_child_env_drops_every_git_variable_but_the_allowlist(monkeypatch):
    """Everything GIT_* goes; the allowlist and the rest of the environment stay.

    Fail-closed is the point: an unknown variable that changes what a writer's
    git does (an object store, a trace sink, a namespace) is refused without
    having to be named here. Removing too much would be the worse bug, so the
    same run pins what must survive: the identity variables, the config pins and
    the transport variables the allowlist names, plus a non-git variable.
    """
    for name in gitenv.GIT_LOCATION_VARS:
        monkeypatch.setenv(name, "/hostile/" + name.lower())
    for name in ("GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                 "GIT_TRACE", "GIT_TRACE2", "GIT_TRACE2_EVENT", "GIT_TRACE2_PERF",
                 "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES", "GIT_INDEX_VERSION",
                 "GIT_DIR_HOLDER", "GIT_PUSH_OPTION_COUNT"):
        monkeypatch.setenv(name, "/hostile/" + name.lower())
    for name in gitenv.CHILD_ENV_GIT_ALLOWLIST:
        monkeypatch.setenv(name, "pinned-by-test")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Replay")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("PATH", os.environ["PATH"])

    env = gitenv.child_env()

    for name in gitenv.GIT_LOCATION_VARS:
        assert name not in env, f"{name} survived child_env()"
    for name in env:
        if name.startswith("GIT_"):
            assert name in gitenv.CHILD_ENV_GIT_ALLOWLIST, (
                f"{name} reached the child without being on the allowlist"
            )
    for name in ("GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                 "GIT_TRACE", "GIT_TRACE2", "GIT_TRACE2_EVENT", "GIT_NAMESPACE",
                 "GIT_CEILING_DIRECTORIES"):
        assert name not in env, f"{name} survived child_env()"
    assert env["GIT_AUTHOR_NAME"] == "Replay"
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_SSH_COMMAND"] == "pinned-by-test"
    assert env["PATH"] == os.environ["PATH"]
    assert env is not os.environ, "child_env handed out the live environment"


def test_the_allowlist_is_the_documented_set():
    """The set the writers are built on, pinned in neither direction.

    A name added here silently widens what an inherited environment may still
    steer (an object store, a hooks path, a fsmonitor helper all begin GIT_ and
    none of them is identity or transport); a name dropped reopens the hole the
    allowlist exists to leave open, and the writers would fail for want of an
    author. Pinning the tuple is cheaper than trusting a reader.
    """
    assert gitenv.CHILD_ENV_GIT_ALLOWLIST == (
        "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
        "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE",
        "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM",
        "GIT_SSH", "GIT_SSH_COMMAND", "GIT_ASKPASS", "GIT_TERMINAL_PROMPT",
    )
