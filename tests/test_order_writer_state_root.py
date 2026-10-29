"""order.py runs from a separate state root: the cwd is not the target.

Extracted from the order writer suite: the writer driven from a decoy cwd so a
path leak into the working directory shows up as a refusal, never as a write."""

import subprocess
from pathlib import Path

from _harness import (
    ORDER,
    _git,
    _init_repo,
    run_from,
)
from order_fixtures import (
    BASELINE_ID,
    NOW,
    ORDER_CWD_DIR,
    ORDER_DECOY_DIR,
    ORDER_DECOY_ISSUE,
    ORDER_REL,
    ORDER_STATE_DIR,
    _assert_census_clean,
    _canonical,
    _entry,
    _head_paths,
    _issues,
    _order_path,
    _repo,
)
from ordering_shapes import (
    commit_artifact,
)


def _order_state_root(tmp_path: Path) -> Path:
    """The state repository: a git repo with an identity and the baseline
    record ``add --decision`` cites, and no order file yet."""
    root = _repo(tmp_path, ORDER_STATE_DIR)
    _git(root, "config", "user.name", "Replay")
    _git(root, "config", "user.email", "replay@fixture.invalid")
    return root


def _order_decoy(tmp_path: Path) -> Path:
    """A decoy state root beside the cwd: a git repo holding one committed
    ordering artifact, so a cwd-driven run would have had an order to overwrite.

    A git repository for the same reason as decide.py's decoy: a plain directory
    would make the writer's own path probes answer first, and the test would
    measure the probe rather than the resolution.
    """
    decoy = _init_repo(tmp_path / ORDER_DECOY_DIR)
    _git(decoy, "config", "user.name", "Replay")
    _git(decoy, "config", "user.email", "replay@fixture.invalid")
    commit_artifact(decoy, _canonical([_entry(ORDER_DECOY_ISSUE, BASELINE_ID)]))
    return decoy


def _order_case(tmp_path: Path) -> tuple[Path, Path, Path]:
    """The three trees of one order state-root run: (state root, decoy, cwd)."""
    root = _order_state_root(tmp_path)
    decoy = _order_decoy(tmp_path)
    cwd = tmp_path / ORDER_CWD_DIR
    cwd.mkdir(parents=True, exist_ok=True)
    return root, decoy, cwd


def _order_from(cwd: Path, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """order.py launched from ``cwd``, with ``--repo`` naming the state root."""
    return run_from(cwd, ORDER, "--repo", str(repo), *args)


def test_order_writes_the_state_root_and_nothing_beside_the_cwd(tmp_path):
    """The ordering artifact lands under the state root; the decoy order beside
    the cwd keeps its bytes and no ``noni/`` appears under the cwd."""
    root, decoy, cwd = _order_case(tmp_path)
    decoy_bytes = _order_path(decoy).read_bytes()

    proc = _order_from(cwd, root, "add", "7", "--decision", BASELINE_ID, "--now", NOW)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"

    assert _order_path(root).is_file(), "the artifact did not land in the state root"
    assert _issues(root) == [7]
    assert _head_paths(root) == [ORDER_REL], _head_paths(root)
    assert _order_path(decoy).read_bytes() == decoy_bytes, (
        "the run overwrote the decoy order beside its cwd, so the artifact path "
        "resolved from somewhere other than --repo"
    )
    assert not (cwd / "noni").exists(), "the run created noni/ under the cwd"
    _assert_census_clean(root, "an add from a foreign cwd")


def test_order_reads_the_state_roots_own_order_from_a_foreign_cwd(tmp_path):
    """The other half of the pair: an entry listed in the state root is the one
    ``move`` reorders, while a different entry sits in the decoy.

    Without this, the test above could be satisfied by a writer that created a
    fresh file wherever it liked: a run that read nothing would still pass a
    write-side assertion.
    """
    root, decoy, cwd = _order_case(tmp_path)
    seed = _canonical([_entry(3, BASELINE_ID), _entry(7, BASELINE_ID)])
    commit_artifact(root, seed)
    decoy_bytes = _order_path(decoy).read_bytes()

    proc = _order_from(cwd, root, "move", "7", "--to", "1", "--now", NOW)
    assert proc.returncode == 0, f"{proc.returncode}: {proc.stderr}"
    assert _issues(root) == [7, 3], (
        "the writer reordered something other than the state root's own list"
    )
    assert _order_path(decoy).read_bytes() == decoy_bytes
    assert ORDER_DECOY_ISSUE not in _issues(root), (
        "the decoy's entry leaked into the state root's order"
    )
    assert not (cwd / "noni").exists()


def test_order_refuses_a_repo_that_is_not_a_directory(tmp_path):
    """A --repo naming no directory is refused with the state-root refusal code
    (2) that names the state root, and the decoy order beside the cwd is
    untouched.

    2 and not merely non-zero: order.py's other refusals are 3 (an environment
    fault) and 4 (a refusal of the order), and a test that accepted any non-zero
    code would pass on a run that crashed or faulted for an unrelated reason.
    """
    _root, decoy, cwd = _order_case(tmp_path)
    decoy_bytes = _order_path(decoy).read_bytes()
    missing = tmp_path / "no-such-state-root"

    proc = _order_from(cwd, missing, "add", "7", "--decision", BASELINE_ID,
                       "--now", NOW)
    assert proc.returncode == 2, (
        f"a missing state root is the writer's usage refusal (2), got "
        f"{proc.returncode}: {proc.stderr}"
    )
    assert "no-such-state-root" in (proc.stderr + proc.stdout), (
        f"the refusal must name the state root it was given: {proc.stderr}"
    )
    assert _order_path(decoy).read_bytes() == decoy_bytes, (
        "a refused run wrote the decoy order beside its cwd"
    )
    assert not (cwd / "noni").exists(), "a refused run created noni/ under the cwd"
