"""Exit-code tests of the unified census: one test per code in the contract.

Moved out of ``tests/test_census_exit_codes.py`` so each file stays at or under
the size ratchet; the tests, their docstrings and their assertions are main's,
verbatim. The module-private builders and runners they use are held in
``tests/census_exit_codes_builders.py``.
"""

from __future__ import annotations

import json

import census
from _harness import (
    _commit_file,
    _fault_the_ledger_listing,
    _init_repo,
)
from census_exit_codes_builders import (
    _HOME_PATH,
    _rows,
    _run,
    _valid_record,
)


def test_exit_0_clean(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json", json.dumps(_valid_record(), indent=2))
    assert _run(repo) == 0


def test_exit_10_schema_violation(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    bad = _valid_record()
    del bad["status"]
    _commit_file(repo, "noni/decisions/2026-10-01-bad.json", json.dumps(bad, indent=2))
    assert _run(repo) == 10


def test_recordless_ledger_dir_is_ledger_empty_warn(tmp_path):
    """An existing decisions/ directory with no *.json record is the
    ledger-empty warn (operator decision on issue #33, which reverses the
    exit-10 ruling of issue #23): a freshly attached project with no decisions
    yet must census clean, so this run exits 0 and 42 under --strict."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/.gitkeep", "")
    assert _run(repo, "--skip", "hygiene") == 0
    assert _run(repo, "--skip", "hygiene", "--strict") == 42
    assert _run(repo, "--only", "ledger-empty", "--strict") == 42


def test_unreadable_ledger_dir_is_cannot_tell_not_empty(tmp_path, monkeypatch):
    """A decisions/ directory that exists and cannot be listed is not the
    recordless tree: it is a probe fault, reported as a ledger-edited
    cannot-tell row -- a warn that leaves the run at 0 and --strict lifts to
    the class's 12, the same pair every other cannot-tell row keeps.

    The pair sits beside test_recordless_ledger_dir_is_ledger_empty_warn on
    purpose: the two trees differ only in whether the census could read them,
    and their codes differ (0/12 against 0/42) so an operator can tell a
    project that has never steered anything apart from a ledger that went
    unreadable."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json",
                 json.dumps(_valid_record(), indent=2))
    _fault_the_ledger_listing(monkeypatch, repo / "noni" / "decisions")

    assert _run(repo, "--skip", "hygiene") == 0
    assert _run(repo, "--skip", "hygiene", "--strict") == 12
    assert _run(repo, "--only", "ledger-edited", "--strict") == 12
    rows = [r for r in _rows(repo, "--skip", "hygiene") if r.get("kind") == "finding"]
    assert [r["check"] for r in rows] == ["ledger-edited"], (
        f"an unreadable ledger answers no state word, so ledger-empty adds "
        f"nothing of its own: {rows}"
    )
    assert rows[0]["severity"] == "warn" and rows[0]["code"] == 12, rows[0]
    assert "readdir" in rows[0]["message"] and "denied" in rows[0]["message"], (
        f"the OSError text must reach the operator: {rows[0]['message']}"
    )
    assert not rows[0]["subject"].startswith("/"), (
        f"no machine-local path in the row: {rows[0]}"
    )


def test_the_unreadable_ledger_row_survives_a_filter_that_named_no_ledger_class(
    tmp_path, monkeypatch
):
    """The filter must not be able to buy back the clean verdict.

    ``--only`` drops rows of classes it does not name, and the fault row is a
    ``ledger-edited`` row like any other. What it is also is a whole-artifact
    row: the group's own filter keeps it, and the group runs even when the
    filter named none of its classes -- a run that could not read the ledger
    and said nothing would report the same clean as a run that read it and
    found nothing."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json",
                 json.dumps(_valid_record(), indent=2))
    _fault_the_ledger_listing(monkeypatch, repo / "noni" / "decisions")

    for extra in (("--only", "hygiene"), ("--skip", "ledger-edited"),
                  ("--only", "ledger-empty", "--strict")):
        # hygiene is skipped explicitly rather than left in: its always-on
        # "deny-list inactive" row would sit beside the fault row without
        # changing this assertion's meaning.
        rows = _rows(repo, "--skip", "hygiene", *extra)
        found = [r for r in rows if r.get("kind") == "finding"]
        assert [r["check"] for r in found] == ["ledger-edited"], (
            f"{extra}: the unreadable ledger must still be reported: {found}"
        )
        assert "readdir" in found[0]["message"], found[0]
        # warn by default, 12 under --strict, whichever filter was used.
        expected = 12 if "--strict" in extra else 0
        assert _run(repo, "--skip", "hygiene", *extra) == expected, f"{extra}: expected {expected}"


def test_exit_10_not_valid_json(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-bad.json", "{bad")
    assert _run(repo) == 10


def test_exit_12_edited_after_commit(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json", json.dumps(_valid_record(), indent=2))
    (repo / "noni/decisions/2026-10-01-a.json").write_text(
        json.dumps(_valid_record(status="open"), indent=2)
    )
    assert _run(repo) == 12


def test_exit_20_dangling_supersedes(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-root.json", json.dumps(_valid_record("2026-10-01-root"), indent=2))
    dangling = _valid_record("2026-10-22-d", "decided", "2026-10-99-missing")
    _commit_file(repo, "noni/decisions/2026-10-22-d.json", json.dumps(dangling, indent=2))
    assert _run(repo) == 20


def test_exit_20_cycle(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    a = _valid_record("2026-10-01-a", "decided", "2026-10-02-b")
    b = _valid_record("2026-10-02-b", "decided", "2026-10-01-a")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json", json.dumps(a, indent=2))
    _commit_file(repo, "noni/decisions/2026-10-02-b.json", json.dumps(b, indent=2))
    assert _run(repo) == 20


def test_exit_42_ledger_empty(tmp_path):
    """noni/ present with no decisions/ directory is the warn ledger-empty
    class: exit 0 without --strict, exit 42 under --strict. The register side
    is clean, so this class alone decides the code."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/README.md", "noni lives here\n")
    assert _run(repo) == 0
    assert _run(repo, "--only", "ledger-empty", "--strict") == 42


def test_recordless_ledger_dir_reports_the_empty_state(tmp_path):
    """The recordless decisions/ directory reports the same state word as a
    missing decisions/: the warn row names 'empty' either way, and the run is
    clean without --strict."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/.gitkeep", "")
    assert _run(repo, "--skip", "hygiene") == 0
    rows = [r for r in _rows(repo, "--skip", "hygiene") if r.get("check") == "ledger-empty"]
    assert len(rows) == 1, f"expected one ledger-empty row: {rows}"
    assert "(empty)" in rows[0]["message"], f"state word missing: {rows[0]['message']}"


def test_exit_42_ledger_absent(tmp_path):
    """A repo with no noni/ at all is ledger-empty, not a silent clean: one
    row, exit 0 without --strict, exit 42 under --strict. hygiene is skipped
    so the class under test is the one that decides the code."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "README.md", "# empty\n")
    assert _run(repo) == 0
    assert _run(repo, "--only", "ledger-empty", "--strict") == 42


def test_exit_50_hygiene(tmp_path):
    """A tracked file with a home path / secret shape is the warn hygiene
    class: exit 0 without --strict, 50 under --strict. The deny-list is made
    active so the row fires on the violation and not on the inactive class."""
    import public_safety

    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "note.md", _HOME_PATH + "\n")
    denylist = tmp_path / "denylist.txt"
    denylist.write_text("synthetic-project-name\n", encoding="utf-8")
    import os

    os.environ[public_safety.DENYLIST_ENV_VAR] = str(denylist)
    try:
        assert _run(repo, "--only", "hygiene") == 0
        assert _run(repo, "--only", "hygiene", "--strict") == 50
    finally:
        del os.environ[public_safety.DENYLIST_ENV_VAR]


def test_lowest_code_wins(tmp_path):
    """When exit 10 (schema) and 20 (dangling supersedes) both fire, 10 wins."""
    repo = _init_repo(tmp_path / "repo")
    bad = _valid_record()
    del bad["id"]
    _commit_file(repo, "noni/decisions/2026-10-01-bad.json", json.dumps(bad, indent=2))
    _commit_file(repo, "noni/decisions/2026-10-02-a.json",
                 json.dumps(_valid_record("2026-10-02-a", "decided",
                                          "2026-10-09-missing"), indent=2))
    assert _run(repo) == 10
