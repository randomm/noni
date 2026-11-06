"""The order writer's state-root tests that spy on the writer's own git calls.

Companion of ``tests/test_order_writer_state.py``, split out so each file stays under
the line limit in AGENTS.md. These are the tests whose claim is what the guard's own
helper runs: the argv it builds, and the environment it hands its git children.
"""

from __future__ import annotations

import subprocess

from _harness import _git_e2
from order_fixtures import (
    BASELINE_ID,
    NOW,
    ORDER_REL,
    _bare_repo,
    _entry,
    _gitwrite_module,
    _order_inprocess,
    _repo,
    _seed,
    _writer_git_call,
)
from order_race_fixtures import RIVAL_STAMP


def _head_blob(repo, rel=ORDER_REL):
    """The id HEAD holds at ``rel``, asked of git directly and not of the writer.

    The probe is pinned against its own answers, so the blob id it must read back has
    to come from outside it: this is what git answers for the same rev through the
    harness's own git runner.
    """
    asked = _git_e2(repo, "rev-parse", "--verify", "--quiet", f"HEAD:{rel}")
    assert asked.returncode == 0, asked.stderr
    return asked.stdout.strip()


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
    blob = _head_blob(repo, ORDER_REL)
    seen: list[tuple] = []
    real_git_bytes = helper.git_bytes

    def spy(repo_arg, *args, input_text=None):
        seen.append(args)
        return real_git_bytes(repo_arg, *args, input_text=input_text)

    monkeypatch.setattr(helper, "git_bytes", spy)
    code, _out, err = _order_inprocess(repo, "add", "7", "--decision", BASELINE_ID,
                                       "--now", NOW)
    assert code == 0, err
    # HEAD is asked twice, both times by the writer's own helper: first whether the
    # path is in that tree at all (a return code, not a sentence), then for the bytes
    # of the object git named for it. The second call names the id and not the path, so
    # nothing re-resolves the rev after the first answer. The index is asked once, and
    # with the -s that answers a blob id.
    assert ("rev-parse", "--verify", "--quiet", f"HEAD:{ORDER_REL}") in seen, seen
    assert ("show", blob) in seen, seen
    assert ("ls-files", "-s", "--", ORDER_REL) in seen, seen
    assert not [args for args in seen if args[0] == "show"
                and args[1] != blob], seen


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
