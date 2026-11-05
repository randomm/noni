"""The census's hygiene class over a tree holding a FIFO: prompt, silent, no hang.

Issue #91, at the level a caller actually runs. ``census --repo <tree> --json
--only hygiene`` hung with no row and no exit over a tree whose tracked path was
a named pipe, and the class's own ``except Exception`` ("report, never crash")
could do nothing: a blocked read raises nothing, so the honesty guard that turns
an unreadable tree into a *did-not-run* row never fired.

Two rules shape this file, both of them about how a hanging test would hide the
bug rather than report it:

- **The census runs in a child process** (``sys.executable -c``, a hard
  ``timeout=``, an elapsed assertion), the shape ``tests/test_session_walk_bounded.py``
  and ``tests/test_census_intent_cited_record.py`` use. The suite's in-process
  runner, ``tests/census_run.py``'s ``_run_census``, calls ``census.main`` with no
  bound of any kind, so a regression there would wedge the pytest worker and the
  suite would report nothing -- the product's failure mode reproduced one layer up.
- **The skip is silent.** A non-regular path holds no stored content, so there is
  nothing to scan and no row is emitted for it: no new warn row, no new artifact
  class. What is asserted instead is the *absence* of a row for the pipe beside
  the presence of every row the run owes the caller -- and, for the tree with no
  deny-list, the one inactive-class row the class always reports.

The FIFO fixtures are the repo's one builder (``tests/harness_faults.py``), shared
with the scrub level and the gate-CLI level so the three cannot mean three
different things by "a tracked pipe".
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from _harness import (
    SRC,
    _commit_file,
    _git,
    _home_path_violation,
    _init_repo,
    _mkfifo_available,
    _plant_fifo,
    _plant_fifo_symlink,
    _plant_untracked_fifo,
    _secret_violation,
)
from census_denylist import DENYLIST_ENV_VAR
from census_fixtures import _valid_record

# Comfortable against a census run that finishes in well under a second, short
# enough that the regression this test exists for -- a run that never returns --
# fails in seconds rather than inheriting the absence of any suite-wide timeout.
BOUND_SECONDS = 30

pytestmark = pytest.mark.skipif(
    not _mkfifo_available(),
    reason="os.mkfifo is POSIX-only, so this host cannot plant a named pipe",
)

# The census exits 0 for a warn-only hygiene finding and 50 for the same finding
# under --strict; both are answers. Anything else, or no answer at all, is the bug.
CENSUS_CLEAN_EXIT = 0
CENSUS_WARN_EXIT = 50


def _census_rows_in_time(repo: Path, *args: str) -> tuple[int, list[dict], str]:
    """``census.main`` over ``repo`` in a child that cannot stall the suite.

    The hygiene class is requested explicitly (``--only hygiene``) so the ledger
    and session classes cannot decide the exit code of a run that is answering a
    question about the scan. Returns the exit code, the NDJSON rows and stderr.
    """
    argv = ["--repo", str(repo), "--json", "--only", "hygiene", *args]
    # ``noni.census`` rather than the bare ``census`` alias the in-process suite
    # imports: the alias is registered as a side effect of the test harness, which
    # does not run in this child.
    script = (
        "import sys; sys.path.insert(0, {src!r})\n"
        "import noni.census as census\n"
        "sys.exit(census.main({argv!r}))\n"
    ).format(src=str(SRC), argv=argv)
    started = time.monotonic()
    proc = subprocess.run([sys.executable, "-B", "-c", script],
                          capture_output=True, text=True, timeout=BOUND_SECONDS,
                          env=os.environ.copy())
    elapsed = time.monotonic() - started
    assert proc.returncode in (CENSUS_CLEAN_EXIT, CENSUS_WARN_EXIT), (
        f"the census exited {proc.returncode}, not a verdict: {proc.stderr}")
    # A run that reached the bound would have tripped subprocess's own timeout,
    # so this is the assertion that says the class returned on its own.
    assert elapsed < BOUND_SECONDS, f"the census run took {elapsed:.1f}s"
    rows = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip()]
    return proc.returncode, rows, proc.stderr


def _hygiene_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("check") == "hygiene"]


def _non_git_repo(tmp_path: Path, name: str = "plain") -> Path:
    """A directory that is not a git repo, for the not-run control."""
    plain = tmp_path / name
    plain.mkdir()
    (plain / "note.txt").write_text("hello\n", encoding="utf-8")
    return plain


def test_a_tracked_fifo_under_a_clean_active_deny_list_reports_nothing(tmp_path):
    """AC1, end to end: the hygiene class over a pipe returns at its own exit.

    The deny-list is active so the class has no reason to report at all: the run
    must come back at exit 0 with zero hygiene rows. Before the guard it returned
    nothing, ever -- no row, no exit, no timeout.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    _plant_fifo(repo, "pipe.md")
    _with_env_denylist(tmp_path, "synthetic-project-name")
    try:
        code, rows, err = _census_rows_in_time(repo)
    finally:
        _clear_env_denylist()
    assert code == CENSUS_CLEAN_EXIT, f"expected 0, got {code}\n{err}"
    assert _hygiene_rows(rows) == [], (
        f"a silent skip must not become a row: {_hygiene_rows(rows)}")


def test_a_tracked_fifo_is_never_reported_as_a_violation_or_a_did_not_run(tmp_path):
    """The pipe yields neither a violation row nor a did-not-run row.

    Both are wrong and each is a plausible implementation: a violation row would
    call a pipe a hygiene problem, and a did-not-run row would tell the operator
    the scan could not do its job when it did. The skip is silent, exactly as a
    binary file's is, so the assertion is the absence of both -- while the run's
    exit code still says the class ran.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    _plant_fifo(repo, "pipe.md")
    _with_env_denylist(tmp_path, "synthetic-project-name")
    try:
        _code, rows, _err = _census_rows_in_time(repo)
        strict_code, _rows, _err = _census_rows_in_time(repo, "--strict")
    finally:
        _clear_env_denylist()

    hygiene = _hygiene_rows(rows)
    assert hygiene == [], hygiene
    text = json.dumps(rows)
    assert "pipe.md" not in text, f"the skipped path reached a row: {rows}"
    assert "did not run" not in text, f"a pipe is not a scan that failed: {rows}"
    assert strict_code == CENSUS_CLEAN_EXIT, (
        f"--strict lifted a run that reported nothing: exit {strict_code}")


def test_a_violation_beside_a_tracked_fifo_is_still_reported(tmp_path):
    """The guard is narrow: the class still finds, names and exits for a real one.

    Without this control, a class that skipped the whole scan -- or read the pipe
    as the empty file its EOF hands back -- would look identical to one that
    correctly skipped only the non-regular path. The row is asserted in full:
    subject, artifact, message and the warn code the class documents.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    _plant_fifo(repo, "pipe.md")
    _commit_file(repo, "note.md", "token " + _secret_violation() + "\n")
    _with_env_denylist(tmp_path, "synthetic-project-name")
    try:
        code, rows, err = _census_rows_in_time(repo)
        strict_code, _o, _e = _census_rows_in_time(repo, "--strict")
    finally:
        _clear_env_denylist()

    assert code == CENSUS_CLEAN_EXIT, f"hygiene is warn: expected 0, got {code}\n{err}"
    hygiene = _hygiene_rows(rows)
    assert len(hygiene) == 1, f"expected the one violation row, pipe included: {hygiene}"
    row = hygiene[0]
    assert row["code"] == CENSUS_WARN_EXIT and row["severity"] == "warn"
    assert "note.md" in row["subject"] and "note.md" in row["artifact"], row
    assert "public hygiene" in row["message"], row
    assert strict_code == CENSUS_WARN_EXIT, (
        f"--strict must lift the real violation: exit {strict_code}")


def test_a_tracked_symlink_to_a_fifo_is_skipped_by_the_census_too(tmp_path):
    """The link case at the census level: followed by nobody, blocked on nothing.

    A pre-open ``lstat`` skip of the top-level path would pass the pipe case above
    and still block here, which is why AC2 names the same-descriptor check as the
    accepted design. The class must still return promptly and report nothing.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    _plant_fifo(repo, "pipe.md")
    _plant_fifo_symlink(repo, "link.md", "pipe.md")
    _with_env_denylist(tmp_path, "synthetic-project-name")
    try:
        code, rows, _err = _census_rows_in_time(repo)
    finally:
        _clear_env_denylist()
    assert code == CENSUS_CLEAN_EXIT
    assert _hygiene_rows(rows) == [], rows


def test_an_untracked_fifo_is_inert_and_the_class_still_reports_a_violation(tmp_path):
    """The untracked pipe is the control that pins the listing.

    ``git ls-files`` lists index entries only, so nothing here turns on the guard:
    the assertions are that git omits the path, and that the scan still reports the
    violation in the regular tracked file beside it. Together they say the run
    reached the file that mattered and never touched the pipe.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    _plant_untracked_fifo(repo, "loose-pipe.md")
    _commit_file(repo, "note.md", _home_path_violation() + "\n")
    _with_env_denylist(tmp_path, "synthetic-project-name")
    try:
        _code, rows, _err = _census_rows_in_time(repo)
    finally:
        _clear_env_denylist()

    assert "loose-pipe.md" not in _git(repo, "ls-files").stdout.split(), (
        "git lists the untracked pipe, so this case is no longer the control")
    hygiene = _hygiene_rows(rows)
    assert len(hygiene) == 1 and "note.md" in hygiene[0]["subject"], hygiene


def test_a_fifo_at_the_deny_list_path_leaves_the_class_reporting_itself_inactive(tmp_path):
    """The other blocking open, at the census level.

    A pipe at the env-named deny-list path hung the run before its tracked-file
    loop started -- and the census had no row to print because the read raised
    nothing. The class must answer the same thing it answers for a corrupt file:
    one inactive row, naming the state, and never a hygiene-clean claim.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    pipe = tmp_path / "denylist-pipe.txt"
    os.mkfifo(pipe)
    os.environ[DENYLIST_ENV_VAR] = str(pipe)
    try:
        code, rows, err = _census_rows_in_time(repo)
    finally:
        _clear_env_denylist()

    assert code == CENSUS_CLEAN_EXIT, f"expected 0 (warn), got {code}\n{err}"
    hygiene = _hygiene_rows(rows)
    assert len(hygiene) == 1, f"expected the one inactive-class row: {hygiene}"
    assert hygiene[0]["subject"] == "deny-list", hygiene[0]
    assert "inactive" in hygiene[0]["message"], hygiene[0]
    assert "hygiene-clean" not in hygiene[0]["message"].replace(
        "not a hygiene-clean", ""), hygiene[0]["message"]


def test_a_non_git_tree_still_reports_the_scan_did_not_run(tmp_path):
    """The control on the control: a scan that genuinely cannot run still says so.

    The pipe test above asserts there is no did-not-run row; this asserts the row
    still appears when the reason is real, so the absence asserted there is a
    statement about pipes and not a suppression of the honesty row.
    """
    code, rows, err = _census_rows_in_time(_non_git_repo(tmp_path))
    assert code == CENSUS_CLEAN_EXIT, f"expected 0 (warn), got {code}\n{err}"
    hygiene = _hygiene_rows(rows)
    assert len(hygiene) == 1 and "did not run" in hygiene[0]["message"], hygiene


def _with_env_denylist(tmp_path: Path, *entries: str) -> None:
    """Activate the deny-list class for a census run launched in a child.

    ``tests/census_denylist.py``'s helper writes the same file and sets the same
    variable for an in-process run; the child inherits the parent's environment,
    so setting it here is what makes it active there. The file sits under
    ``tmp_path`` so no host deny-list can decide the verdict.
    """
    path = tmp_path / "census-fifo-denylist.txt"
    path.write_text("\n".join(entries) + "\n", encoding="utf-8")
    os.environ[DENYLIST_ENV_VAR] = str(path)


def _clear_env_denylist() -> None:
    """Undo :func:`_with_env_denylist` (conftest re-clears the variable per test)."""
    os.environ.pop(DENYLIST_ENV_VAR, None)
