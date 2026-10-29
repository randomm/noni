"""Every shipped writer clears the inherited git variables (issue #39).

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
transport pins a caller legitimately sets). This file is the proof for each
writer that commits: decide, order, register, claim, close and release.

Each writer runs in two cases. The first sets ``GIT_DIR`` and ``GIT_WORK_TREE``
to a decoy repository under ``tmp_path``; the second sets only
``GIT_INDEX_FILE`` to a decoy index. Both then ask the same four questions, in
``_harness.assert_writers_clear_git_env``: the record is committed in the state
root, the decoy is byte-for-byte what it was, and the state root's own
``git status --porcelain`` is empty (so the record was committed and not merely
written). A third case sets the object-store and trace variables to paths under
``tmp_path`` and asks the same questions of those (see
``test_writers_ignore_a_hostile_object_store_and_trace_environment``).

The variables are set explicitly in the subprocess environment rather than
inherited: ``tests/conftest.py`` clears the location ones for every test, so a
launcher that relied on inheritance would have set nothing and passed no matter
what the writer did.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from _harness import (
    CLAIM,
    CLOSE,
    DECIDE,
    ORDER,
    REGISTER,
    RELEASE,
    _git,
    _git_env_with_identity,
    _init_repo,
    assert_writers_clear_git_env,
    decoy_git_index,
    decoy_git_repo,
    git_pin_date,
    subprocess_env,
)

from noni import gitenv

# The session file every sessions writer writes to, and the task they claim.
SID = "2026-10-01-aaaaaa"
SESSION_REL = f"noni/sessions/{SID}.md"
TASK = "#42"

# decide.py's own record and the ledger path it lands under, and order.py's
# artifact. All three are read back from HEAD by name, so each is a constant.
# The baseline record the fixture commits and the one decide.py writes differ in
# slug: decide.py refuses a record whose id is already in the ledger.
BASELINE_ID = "2026-10-01-gitenv-baseline"
DECISION_ID = "2026-10-01-gitenv-probe"
RECORD_REL = f"noni/decisions/{DECISION_ID}.json"
BASELINE_REL = f"noni/decisions/{BASELINE_ID}.json"
ORDER_REL = "noni/direction/order.json"

# The issue whose position order.py records, and the record that cites it. The
# artifact is asserted on these bytes, so both are constants.
ORDER_ISSUE = "7"


def _git_ok(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """A checking git call in ``repo`` (the fixture-side git, not the writer's)."""
    proc = _git(repo, *args)
    assert proc.returncode == 0, f"git {args} failed: {proc.stderr}"
    return proc


def _identity_env() -> dict[str, str]:
    """The harness's deterministic git identity, ready to extend with decoys.

    Every writer here commits, and the suite's autouse fixture clears the
    author/committer variables, so a launched writer needs the identity the other
    committing launchers supply — otherwise git refuses the commit for want of an
    author and the test measures the wrong fault.
    """
    return dict(_git_env_with_identity())


def _decoy_env(vars_: dict[str, str]) -> dict[str, str]:
    """The launching environment for one decoy case: identity plus ``vars_``.

    Explicit, because conftest has already cleared the four location variables
    from the parent environment: the decoy has to be put back on by hand.
    """
    env = subprocess_env()
    env.update(_identity_env())
    env.update(vars_)
    return env


def _session_body(identity: str = "dev", claims: list[str] | None = None) -> str:
    """A session register file in the shape register.py writes."""
    lines = [f"- identity: {identity}", "- host/worktree: ws",
             "- started: 2026-10-01T10:00:00Z", "- status: active", "- claims:"]
    for claim in claims or []:
        lines.append(f"  - claim: {claim}")
    return "\n".join(lines) + "\n"


def _sessions_repo(tmp_path: Path, subdir: str,
                   claims: list[str] | None = None) -> Path:
    """A state root holding one committed session file, claiming ``claims``."""
    repo = _init_repo(tmp_path / subdir)
    sessions = repo / "noni" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f"{SID}.md").write_text(_session_body("dev", claims), encoding="utf-8")
    _git_ok(repo, "add", SESSION_REL)
    git_pin_date(repo, "2026-10-01T10:00:00Z", "commit", "-q",
                 "-m", f"register: {SID}")
    return repo


def _ledger_repo(tmp_path: Path, subdir: str) -> Path:
    """A state root whose ledger holds one committed decided record.

    decide.py cites a decision id and order.py looks one up before it writes its
    artifact, so both writers need a real committed record to be run at all. The
    tree's own ``user.name`` is set because decide.py takes the record's ``by``
    from it and refuses the run when it is unset. The record is committed through
    ``git_pin_date`` (the harness's dated commit, which supplies its own identity)
    so the record's date is the one the citation and the ordering compare against.
    """
    repo = _init_repo(tmp_path / subdir)
    _git_ok(repo, "config", "user.name", "Replay")
    _git_ok(repo, "config", "user.email", "replay@fixture.invalid")
    record = {
        "id": BASELINE_ID,
        "date": "2026-10-01T10:00:00Z",
        "asked_by": "developer",
        "questions": [{"id": "q1", "text": "Probe?", "options": ["yes", "no"],
                       "answer": "yes"}],
        "by": "Replay",
        "scope": "release ordering",
        "status": "decided",
        "supersedes": None,
    }
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / f"{BASELINE_ID}.json").write_text(json.dumps(record, indent=2),
                                                encoding="utf-8")
    _git_ok(repo, "add", BASELINE_REL)
    git_pin_date(repo, "2026-10-01T10:00:00Z", "commit", "-q",
                 "-m", f"steering: {BASELINE_ID}")
    return repo


def _scratch_dir(repo: Path) -> Path:
    """A directory beside ``repo`` to launch from: never the checkout under test."""
    scratch = repo.parent / "launch-from"
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch


def _decoy_case(tmp_path: Path, name: str) -> tuple[dict[str, str], Path, dict[str, bytes]]:
    """The GIT_DIR / GIT_WORK_TREE case: (env entries, decoy tree, snapshot).

    Both variables name the decoy: git refuses the pair when the work tree does
    not match the directory it was handed, so a case that set only GIT_DIR would
    fail the run for the wrong reason.
    """
    tree, git_dir = decoy_git_repo(tmp_path, name=name)
    before = {p.relative_to(tree).as_posix(): p.read_bytes()
              for p in sorted(tree.rglob("*")) if p.is_file()}
    return {"GIT_DIR": str(git_dir), "GIT_WORK_TREE": str(tree)}, tree, before


def _index_case(tmp_path: Path, repo: Path,
                name: str) -> tuple[dict[str, str], Path, bytes]:
    """The GIT_INDEX_FILE case: (env entries, decoy index, its original bytes)."""
    index = decoy_git_index(repo, tmp_path, name=name)
    return {"GIT_INDEX_FILE": str(index)}, index, index.read_bytes()


def _run(script: Path, repo: Path, env: dict[str, str],
         *args: str) -> subprocess.CompletedProcess[str]:
    """One writer launched by path with an explicit environment.

    ``cwd`` is pinned to ``tmp_path``'s parent rather than inherited: the suite
    runs with the repository as pytest's working directory, and a writer whose
    ``--repo`` was retargeted by the decoy would otherwise resolve a relative
    path (or its own cwd-relative write) against the checkout it is being
    tested from. The cwd-isolation contract has its own tests; this launcher
    pins the environment and keeps the run out of the tree.
    """
    return subprocess.run([sys.executable, str(script), "--repo", str(repo), *args],
                          capture_output=True, text=True, env=env, timeout=120,
                          cwd=str(_scratch_dir(repo)))


# --- claim -----------------------------------------------------------------------


def _claim_run(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _run(CLAIM, repo, env, "--session-id", SID, "--task", TASK)


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


def _close_run(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _run(CLOSE, repo, env, "--session-id", SID)


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


def _release_run(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _run(RELEASE, repo, env, "--session-id", SID, "--task", TASK)


def _assert_row_released(repo: Path) -> None:
    """The committed register no longer carries the task's row.

    ``git cat-file`` rather than ``git show``: show runs the tree's clean/smudge
    filters over what it prints, and a blob that is plainly there can come back
    empty. The assertion below is about content, so it reads the stored blob.
    """
    shown = _git_ok(repo, "cat-file", "-p", f"HEAD:{SESSION_REL}")
    assert f"- claim: {TASK}" not in shown.stdout, "the row was not released"


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


def _register_run(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _run(REGISTER, repo, env, "--identity", "developer")


def _registered_rel(proc: subprocess.CompletedProcess[str]) -> str:
    """The session file register.py's success line names, as a repo-relative path.

    The id is allocated by the writer, so the path the assertion reads back from
    HEAD is taken from the run's own words rather than guessed.
    """
    line = proc.stdout.strip()
    assert "registered session " in line, f"no registration line: {proc.stderr}"
    session_id = line.split("registered session ")[1].split(" ->")[0].strip()
    return f"noni/sessions/{session_id}.md"


def test_register_commits_in_the_state_root_with_a_decoy_git_dir(tmp_path):
    """A fresh registration commits its file in the state root it was named."""
    repo = _init_repo(tmp_path / "register-dir")
    env, decoy, before = _decoy_case(tmp_path, "register-decoy-dir")
    proc = _register_run(repo, _decoy_env(env))
    assert_writers_clear_git_env(proc, repo, _registered_rel(proc), decoy, before,
                                 None, None, "- identity: developer")


def test_register_commits_in_the_state_root_with_a_decoy_git_index_file(tmp_path):
    repo = _init_repo(tmp_path / "register-idx")
    env, index, before = _index_case(tmp_path, repo, "register-decoy-index")
    proc = _register_run(repo, _decoy_env(env))
    assert_writers_clear_git_env(proc, repo, _registered_rel(proc), None, {},
                                 index, before, "- identity: developer")


# --- decide ---------------------------------------------------------------------


def _decide_argv() -> list[str]:
    """The arguments for one decide.py record, minus ``--repo``.

    ``--date`` is pinned so the record id is deterministic: the assertion reads
    the committed file back by name, and a date taken from the clock would make
    that path a different string every run.
    """
    return ["--asked-by", "developer", "--slug", "gitenv-probe",
            "--date", "2026-10-01", "--scope", "release ordering",
            "--question", "q1=Adopt the probe?", "--option", "q1=yes",
            "--option", "q1=no", "--answer", "q1=yes"]


def _decide_run(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _run(DECIDE, repo, env, *_decide_argv())


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


def _order_run(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _run(ORDER, repo, env, "add", ORDER_ISSUE, "--decision", BASELINE_ID,
                "--now", "2026-10-02T00:00:00Z")


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
#
# The four location variables name a repository. These do not, so the earlier
# clearing left them alone, and clearing only those four is how a writer keeps
# committing somewhere the caller never pointed at: GIT_OBJECT_DIRECTORY and
# GIT_ALTERNATE_OBJECT_DIRECTORIES relocate the object store, so the objects a
# commit needs land in a decoy directory while the state root's refs still look
# fine (a staged-but-uncommitted writer, which is the failure the assertion
# below catches), and GIT_TRACE2_EVENT makes the child append its trace to any
# file the caller names. One writer from each helper runs the same three.


def _object_store_case(tmp_path: Path, name: str) -> tuple[dict[str, str], Path, Path]:
    """The object-store and trace case: (env entries, decoy objects dir, trace file).

    Both object variables point at the same decoy directory so the case cannot
    pass by reading an alternate while writing to the real store, and
    GIT_TRACE2_EVENT names a file that must not exist afterwards: git creates a
    trace file the moment the child runs with it set, so its absence is the
    evidence that the variable never reached the child.
    """
    objects = tmp_path / name
    objects.mkdir(parents=True, exist_ok=True)
    trace = tmp_path / f"{name}-trace.jsonl"
    return ({"GIT_OBJECT_DIRECTORY": str(objects),
             "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(objects),
             "GIT_TRACE": str(trace),
             "GIT_TRACE2": str(trace),
             "GIT_TRACE2_EVENT": str(trace),
             "GIT_NAMESPACE": "refs/noni-hostile",
             "GIT_CEILING_DIRECTORIES": str(tmp_path),
             # A lower-case lookalike is not one of git's: the filter is
             # case-sensitive because git reads these names in upper case, and a
             # non-git variable must not be dropped along with them.
             "git_config_global": "not-a-git-config"},
            objects, trace)


def _assert_object_store_untouched(vars_: dict[str, str], objects: Path,
                                   trace: Path) -> None:
    """The decoy object store holds nothing and no trace file was written."""
    strays = sorted(p.name for p in objects.iterdir())
    assert strays == [], f"objects were written to the GIT_OBJECT_DIRECTORY decoy: {strays}"
    assert not trace.exists(), (
        "a trace variable reached the child, which wrote its trace to "
        f"{trace}"
    )
    # The writer resolves its identity from the allowlisted GIT_AUTHOR_* pair
    # the harness supplies, so a run that committed proved the filter kept
    # those; a run that dropped them could not have committed at all.
    assert vars_["git_config_global"] == "not-a-git-config"


def test_session_writer_commits_with_a_hostile_object_store_and_trace(tmp_path):
    """claim.py commits into the state root while the object store is pointed away."""
    repo = _sessions_repo(tmp_path, "claim-objstore")
    vars_, objects, trace = _object_store_case(tmp_path, "claim-decoy-objects")
    proc = _claim_run(repo, _decoy_env(vars_))
    assert_writers_clear_git_env(proc, repo, SESSION_REL, None, {}, None, None,
                                 f"- claim: {TASK}")
    _assert_object_store_untouched(vars_, objects, trace)


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
