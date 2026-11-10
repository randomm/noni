"""Shared fixture builders for the writers'-git-environment suites.

Every writer here commits, so every case needs the same three trees: a state
root whose ledger holds one
committed decided record, and a decoy for the variable under test. The record is
committed through ``git_pin_date`` (the harness's dated commit) because decide.py
cites a decision id and order.py looks one up before it writes its artifact, and
both compare against the record's date.

The launcher pins ``cwd`` beside the repository rather than inheriting pytest's
working directory: a writer whose ``--repo`` had been retargeted by a decoy would
otherwise resolve a relative path (or its own cwd-relative write) against the
checkout it is being tested from.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from _harness import (
    DECIDE,
    ORDER,
    _git,
    _git_env_with_identity,
    _init_repo,
    decoy_git_index,
    decoy_git_repo,
    git_pin_date,
    subprocess_env,
)

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


def _order_run(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _run(ORDER, repo, env, "add", ORDER_ISSUE, "--decision", BASELINE_ID,
                "--now", "2026-10-02T00:00:00Z")


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
