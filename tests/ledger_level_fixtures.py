"""Fixtures for the ledger schema level: a project that declares one, and one that does not.

``tests/test_ledger_schema_level_skew.py`` and
``tests/test_ledger_schema_level_census.py`` drive the same drift from the two ends
that can hold it apart -- the writer that is ahead of its project's census, and the
census that is behind its project's writer -- and both need the same three trees.
The shapes live here so the pair cannot disagree about what "an attached project"
means, which is the same failure mode the shared schema in
``tests/ledger_schema_fixtures.py`` exists to prevent.

Every tree is a real git repository built with the harness's own helpers, and every
census the tests run over them is pinned with ``--now`` and offline: no network, no
real accounts, no tracker.
"""

from __future__ import annotations

import json
from pathlib import Path

from _harness import _commit_file, _git, _init_repo
from census_fixtures import _ndjson_rows
from census_run import _run_census
from ledger_schema_fixtures import _baseline, _census_verdicts

from noni import ledger_level

# The declaration's path, read from the product rather than restated here: a test
# that spelled the path out would keep passing on the day the module moved it.
DECLARATION = ledger_level.SCHEMA_LEVEL_REL

# The field a record carries when the point is that an older census does not declare
# it. Deliberately outside the closed set in ``ledger_schema`` -- see
# ``tests/ledger_schema_fixtures._with_skew_field``.
SKEW_FIELD = "decided_by_next_era"

# The note a ``--json`` census of these trees carries, and the only one it may carry.
# Stated rather than read back from the run: the claim the tests make is "no NEW
# note", and a list built from the same run could not show a new sentence had joined
# it. An attached project holds ``noni/``, so it is not the no-state-root case and the
# ordering-closed note (no ``--issue-state`` file is passed) is the sole occupant.
KNOWN_NOTES = ("ordering-closed was not evaluated",)

# The wording the census's cause clause adds, and nothing else. The "unknown
# field(s)" fault has to survive beside it, so a rewording that dropped the fault and
# kept the cause would break every consumer that matched the fault.
CAUSE_PHRASES = ("newer", "census pin", "schema_level")


def _plant_declaration(repo: Path, body: str) -> Path:
    """Commit the declaration file with ``body`` as its bytes, verbatim.

    Committed, because the file is a maintainer's artifact and a census that reads
    the working tree should meet it the way an attached project's CI does. Written
    verbatim so a test can plant ``"{"`` as well as a well-formed document.
    """
    path = repo / DECLARATION
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    _git(repo, "add", DECLARATION)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "chore: declare the census level")
    return path


def _attached_project(tmp_path: Path, name: str, declaration: str | None = None) -> Path:
    """An attached project: a git tree, one committed record, maybe a declaration.

    Built the way ``tests/test_census_ledger_empty.py`` builds its trees
    (``_init_repo`` plus committed files under ``noni/``), so the census has a real
    state root to audit rather than a bare ledger directory beside it.
    """
    repo = _init_repo(tmp_path / name)
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_baseline(), indent=2) + "\n")
    if declaration is not None:
        _plant_declaration(repo, declaration)
    return repo


def _bare_repo(tmp_path: Path, name: str) -> Path:
    """A committed code repository that holds no ``noni/`` at all.

    The tree docs/PRODUCT.md 7 describes as the wrong ``--repo``, and the one the
    refusal-ordering test needs: a tree a run must refuse before it allocates.
    """
    repo = _init_repo(tmp_path / name)
    _commit_file(repo, "README.md", "# a code repository\n")
    assert not (repo / "noni").exists(), "the fixture shipped a noni/"
    return repo


def _census_rows(repo: Path) -> list[dict]:
    """One ``--json`` census over ``repo``, as rows; a non-zero exit is a failure.

    ``skip_hygiene`` is what the ledger and session fixtures pass for the same
    reason: an isolated tree has no deny-list, and the hygiene class always reports
    its absence, so leaving it in would put a row no test here is about in every
    finding list the pair asserts on.
    """
    rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
    assert rc == 0, f"{rc}\n{out}\n{err}"
    return _ndjson_rows(out)


def _findings(rows: list[dict]) -> list[dict]:
    """The finding rows of a census report -- the rows a claim is made about.

    Asserted on rows rather than on the exit code because a warn and a clean run
    share 0, and the claim these tests make is about which rows appeared.
    """
    return [r for r in rows if r.get("kind") == "finding"]


def _census_verdicts_for(root: Path, record: dict, *, subdir: str) -> dict[str, tuple[int, str]]:
    """Both entry points' (code, output) over a ledger holding ``record``.

    Re-exported from :mod:`tests.ledger_schema_fixtures` under the name this pair of
    files uses, so the shim and the unified script are driven by one owner and a
    verdict cannot be asserted on one route and quietly skipped on the other.
    """
    return _census_verdicts(root, record, subdir=subdir)


def _writer_level() -> int:
    """The writer's own level, read from the product rather than copied here."""
    return ledger_level.LEDGER_SCHEMA_LEVEL


def _older_level() -> int:
    """A declared level below the writer's: the level of yesterday's closed field set.

    The census at that level is the one the drift is about -- a project that pinned
    a noni commit whose ledger carried fewer fields than this writer emits. Zero is a
    real answer for it (a census pinned before the level existed at all), so it is
    admitted, and the assertion here is only that the writer has a level to be ahead
    of: a product that declared none could outrun nothing, and every skew test would
    pass vacuously.
    """
    assert isinstance(_writer_level(), int) and _writer_level() >= 1, _writer_level()
    return _writer_level() - 1
