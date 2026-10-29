"""Shared fixtures for the E1-E5 hardening half of the decide.py writer suite.

The hardening round's tests share the in-process writer seam (a spy on the
writer's git calls, and stand-ins for its one atomic write) and the target-
shaped fixtures (a committed target whose bytes are whatever a fixture plants).
The in-process seam itself lives in ``decide_inprocess_fixtures`` and is
imported from there; this module holds the census-shim cases and the
target-shaped fixtures. Pure moves from the file that covered all of them: no
behaviour here changed.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable

from _harness import _git, _git_e2, git_pin_date, subprocess_env
from decide_fixtures import (
    BASELINE_DATE,
    BASELINE_ID,
    NEW_ID,
    _baseline_repo,
    _porcelain,
    _record_json,
    _record_path,
    _supersede,
)
from decide_inprocess_fixtures import (  # noqa: F401  (re-export: tests import these from here)
    _decide_in_process,
    _decide_module,
    _git_spy,
    _gitwrite_module,
    _supersede_in_process,
)

# The three trees of a census.sh state-root run; see _census_sh_case.
CENSUS_SH_STATE_DIR = "census-sh-state-root"
CENSUS_SH_CWD_DIR = "census-sh-cwd"
CENSUS_SH_DECOY_DIR = "census-sh-decoy"


def _census_sh_from(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """census.sh launched from ``cwd`` with the arguments given verbatim.

    Verbatim, because the point of these tests is the absence of an argument:
    a helper that always passed a ledger could not express the run that gives
    the shim nothing.
    """
    from decide_fixtures import CENSUS_SH

    return subprocess.run(
        ["bash", str(CENSUS_SH), *args],
        capture_output=True, text=True, env=subprocess_env(),
        cwd=str(cwd), timeout=120,
    )


def _census_sh_snapshot(tree: Path) -> dict[str, str]:
    """Every file under ``tree`` as path -> bytes, so a claim of 'untouched'
    names what moved rather than only that something did."""
    return {str(p.relative_to(tree)): p.read_bytes()
            for p in sorted(tree.rglob("*")) if p.is_file()}


def _census_sh_case(tmp_path: Path) -> tuple[Path, Path, Path]:
    """The three trees of one census-sh state-root run: (state root, decoy, cwd).

    Both ledgers hold one committed decided record, so both are censusable: a
    run that resolved its ledger from the cwd would answer on the decoy's
    bytes, and the assertion can tell that from a run that read the state
    root's. The decoy is a real git repo for the same reason the decide decoy
    is one — a decoy the tool could not have worked in is not a decoy.
    """
    root = _baseline_repo(tmp_path, CENSUS_SH_STATE_DIR)
    decoy = _baseline_repo(tmp_path, CENSUS_SH_DECOY_DIR)
    cwd = tmp_path / CENSUS_SH_CWD_DIR
    cwd.mkdir(parents=True, exist_ok=True)
    return root, decoy, cwd


def _canonical_body(target_id: str, status: str = "decided") -> str:
    """``target_id``'s record in the writer's canonical bytes (the _render form).

    The record is built by the fixture helper and rendered by the writer's own
    _render, so the bytes a canonical fixture commits are exactly the bytes this
    writer would have written for that record.
    """
    record = json.loads(_record_json(target_id, status, "yes", None))
    return _decide_module()._render(record)


def _non_canonical_target_repo(
    tmp_path: Path, body: str, name: str = "odd", target_id: str | None = None
) -> tuple[Path, str, str]:
    """A repo whose committed target is ``body`` verbatim.

    ``target_id`` is the record's id and defaults to ``<BASELINE date>-<name>``;
    a fixture that builds its bytes from another id passes it so the record's
    own ``id`` field and its filename agree. The commit bypasses
    ``_commit_tree``'s identical-bytes guard on purpose: these fixtures commit
    bytes the writer itself would not have produced, and the whole point is
    that HEAD holds them exactly as given.
    """
    repo = _baseline_repo(tmp_path, f"target-{name}")
    target_id = target_id or f"{BASELINE_ID[:10]}-{name}"
    rel = f"noni/decisions/{target_id}.json"
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", rel)
    git_pin_date(repo, BASELINE_DATE, "commit", "-q", "-m", f"fixture: odd target {name}")
    return repo, rel, target_id


def _refused_target_repo(tmp_path: Path, name: str, raw: str) -> tuple[Path, str]:
    """A repo whose committed supersede target is ``raw``, the bytes verbatim.

    ``raw`` is given as text so a fixture can plant a shape no flag of this
    writer can produce (``NaN`` as a bare token, a quoted date, a numeric
    answer): the commit goes in raw so HEAD holds exactly those characters,
    which is what the writer is asked to read.
    """
    target_id = f"{BASELINE_ID[:10]}-{name}"
    repo, rel, _id = _non_canonical_target_repo(tmp_path, raw, name, target_id)
    return repo, target_id


def _refuse_raw_target(tmp_path: Path, name: str, raw: str) -> tuple[str, Path, str]:
    """The stderr of the standard supersede of a planted target, plus its paths.

    The run is the launched one (no in-process spy), so it reads the committed
    bytes the way a real run does. The assertion every caller makes is exit 4
    with the target and the tree untouched: a refusal is only worth having if
    it refuses rather than rewrites.
    """
    repo, target_id = _refused_target_repo(tmp_path, name, raw)
    rel = f"noni/decisions/{target_id}.json"
    committed = _git_e2(repo, "show", f"HEAD:{rel}").stdout
    proc = _supersede(repo, target_id)
    assert proc.returncode == 4, f"{name}: expected exit 4, got {proc.returncode}: {proc.stderr}"
    assert _porcelain(repo) == "", f"{name}: a refused run must leave the tree alone"
    assert not _record_path(repo, f"{BASELINE_ID[:10]}-scheduler").exists(), name
    assert _git_e2(repo, "show", f"HEAD:{rel}").stdout == committed, (
        f"{name}: the refused target's committed bytes must be exactly what they were"
    )
    return proc.stderr, repo, rel


def _planted_body(target_id: str, **overrides: object) -> str:
    """A canonical record body for ``target_id`` with ``overrides`` applied.

    The record is built by the fixture helper and rendered by the writer's own
    ``_render``, so the bytes are canonical except for the one field under test --
    which is what routes the refusal to the rule being probed rather than to the
    canonical-form check or the id/name match. A caller that mutates a nested
    value (``questions``) applies its own patch and passes no override for it.
    """
    record = json.loads(_canonical_body(target_id))
    record.update(overrides)
    return _decide_module()._render(record)


def _refused_path_repo(tmp_path: Path, name: str, plant: Callable[[Path], str]) -> tuple[Path, str]:
    """A repo whose committed target is whatever ``plant`` leaves at the target path.

    ``plant`` receives the target path and returns the single line describing the
    shape it made (``symlink -> elsewhere``, ``<dir>``), which the caller asserts
    back after the commit: git stores a link as a link and a directory as its
    files, so a fixture that planted one and lost it would assert a refusal that
    git had quietly un-planted. The commit is the writer's own route (add, then
    commit at the pinned date), so HEAD really holds the path under the target's
    name and only the file kinds are unusual.
    """
    target_id = f"{BASELINE_ID[:10]}-{name}"
    repo = _baseline_repo(tmp_path, f"target-{name}")
    rel = f"noni/decisions/{target_id}.json"
    target = repo / rel
    described = plant(target)
    _git(repo, "add", rel)
    git_pin_date(repo, BASELINE_DATE, "commit", "-q", "-m", f"fixture: odd target {name}")
    assert described == _describe_path(target), (
        f"{name}: the planted shape is not what is on disk ({described!r} vs "
        f"{_describe_path(target)!r})"
    )
    return repo, target_id


def _describe_path(path: Path) -> str:
    """One line naming what ``path`` actually is, read without following a link."""
    if not os.path.lexists(path):
        return "<absent>"
    if path.is_symlink():
        return f"symlink -> {os.readlink(path)}"
    if path.is_dir():
        return "<dir>"
    if path.is_file():
        return "<file>"
    return "<other>"


def _assert_wrote_nothing(repo: Path, *expected_untracked: str) -> None:
    """A refused run touches neither the ledger nor the index.

    ``expected_untracked`` names the repo-relative paths the fixture itself left
    untracked (a planted symlink's body, say): the assertion is that this run
    staged and wrote nothing, not that the fixture repo was pristine, and
    spelling out what may be untracked is what keeps a record this run did write
    from being mistaken for fixture noise.
    """
    new_record = f"noni/decisions/{NEW_ID}.json"
    listed = [line.strip() for line in _porcelain(repo).splitlines() if line.strip()]
    assert not any(new_record in line for line in listed), (
        f"a refused run wrote {new_record}: {listed}"
    )
    assert not any(line.startswith("A ") or line.startswith("M ") or line.startswith("D ")
                   for line in listed), f"a refused run staged something: {listed}"
    allowed = set(expected_untracked)
    for line in listed:
        path = line[3:]
        assert path in allowed, f"unexpected path after a refused run: {line!r} (allowed: {sorted(allowed)})"
