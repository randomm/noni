"""The listing fault's gate is the read, and the readable paths stay as they were.

A register reached through a symlink cannot read clean, a committed listable
register censuses clean as before, and a missing register is still clean.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py`` and the runners in ``tests/census_run.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from _harness import (
    _commit_file,
    _fault_the_sessions_listing,
    _git,
    _init_repo,
)
from census_fixtures import (
    _ndjson_rows,
    _session_body,
    _sessions_fixture,
    _valid_record,
)
from census_run import _run_census

from noni import orderschema
from noni.census_report import ORDERING_CHECKS, SESSION_CHECKS

# The clock the coexistence fixture is censused against. Its ordering entry is
# confirmed on the same day, so the run is a statement about the claim classes
# and not about a stale artifact: ``--now`` is the one input the ordering group's
# staleness class measures against (``check_ordering``).
COEXISTENCE_NOW = "2026-10-01T12:00:00Z"
COEXISTENCE_CONFIRMED = "2026-10-01T00:00:00Z"
ORDER_REL = "noni/direction/order.json"

# The classes a coexisting team expects to hear nothing from: the sessions
# group's claim classes, read from the census's own set rather than typed here so
# a class added to the group is a class this test asks about, and the ordering
# group, which the fixture's committed artifact keeps in the run.
_CLAIM_CLASSES: tuple[str, ...] = tuple(sorted(
    check for check in SESSION_CHECKS if check != "probe"))
_ORDERING_CLASSES: tuple[str, ...] = tuple(sorted(ORDERING_CHECKS))


class TestSessionsListingFault:
    """A ``noni/sessions/`` that cannot be listed is a fault, not a clean register.

    ``Path.glob`` swallows the ``OSError`` readdir raises and yields nothing, so
    while the register was listed with ``glob`` a directory the run could not
    read reported the same verdict as a project that had never opened a session.
    The register is listed with ``iterdir`` now, and these are the rows that
    fault earns — the sessions-side twin of ``TestLedgerStateVocabulary``'s
    ledger-listing tests, kept to the same contract and the same fault-injection
    seam for the same reason (a chmod fixture is vacuous on a root-equivalent
    runner, and patching ``glob`` would fault nothing).

    The three cases each hold one of the listing's three answers. A register the
    run could not list faults, a register it listed reads as its names, and a
    register that is not there is a state of the tree rather than a fault of the
    read. The whole register's absence is what a team running a driver of its own
    is in, and ``test_a_tree_with_direction_and_no_register_is_clean`` is the
    whole-tree pin for that state: it runs the census unfiltered, so the row an
    absent register would earn is absent from a run that could have printed it
    from any group, not merely from a filtered one.
    """

    def test_a_symlinked_override_outside_the_tree_reports_the_fault(
        self, tmp_path, monkeypatch
    ):
        """The gate is the read, so a register reached through a link cannot read clean.

        The path the census classifies and the path it lists are the one the
        caller gave it. Here a register of the audited tree is reached through a
        symlink under ``noni/``, so the classification follows the link to a
        directory and the readdir faults: exactly the pair the fault row exists
        for. A gate that classified the directory first and reached the listing
        only when the classification looked listable would be a second read
        entitled to disagree with the first, and this is the case it would get
        wrong -- a clean run for a register nobody read.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                     json.dumps(_valid_record(), indent=2))
        register = tmp_path / "real-register"
        register.mkdir()
        (register / "2026-10-01-aaaaaa.md").write_text(_session_body("developer"),
                                                       encoding="utf-8")
        (tmp_path / "repo" / "noni" / "linked").symlink_to(register)
        _fault_the_sessions_listing(monkeypatch, register)

        rc, out, err = _run_census(repo, "--sessions", str(register), json_out=True,
                                   skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out)
                if r.get("kind") == "finding" and r.get("check") == "session-deleted"]
        assert len(rows) == 1, (
            f"the symlinked register the run could not list must be reported: {rows}"
        )
        assert "could not be listed" in rows[0]["message"], rows[0]
        assert rc == 0, f"the fault row is a warn, got {rc}\nstderr: {err}"

    def test_a_readable_register_behaves_exactly_as_before(self, tmp_path):
        """The fix must not disturb the paths that already worked.

        A committed, listable register with two active sessions censuses clean
        (the deletion check finds nothing missing), and the same repo with one
        file removed still reports that deletion: the group's normal reads go
        through the same call now and must answer as they did on the base commit.
        """
        repo = _sessions_fixture(tmp_path)
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, f"a readable register censuses clean, got {rc}\nstderr: {err}\n{out}"
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert rows == [], f"a committed ledger and a readable register are clean: {rows}"
        (repo / "noni/sessions/2026-10-01-bbbbbb.md").unlink()
        rc, out, err = _run_census(repo, "--only", "session-deleted",
                                   json_out=True, skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "session-deleted"]
        assert len(rows) == 1 and rows[0]["subject"] == "2026-10-01-bbbbbb.md", rows
        assert rc == 0, f"warn class exits 0, got {rc}\nstderr: {err}"

    def test_a_missing_sessions_dir_is_still_clean(self, tmp_path):
        """No register at all is a state of the tree, not a fault of this read.

        The acceptance criterion names it explicitly: a missing ``noni/sessions/``
        keeps its old behaviour, which is silence. The fault row exists precisely
        to separate "could not look" from "nothing to see", so the second of
        those must stay wordless or the first is worth nothing.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "README.md", "# repo\n")
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, f"no sessions dir is clean, got {rc}\nstderr: {err}\n{out}"
        rows = [r for r in _ndjson_rows(out)
                if r.get("kind") == "finding" and r.get("artifact") == "noni/sessions"]
        assert rows == [], (
            f"a missing register adds no row of its own: {rows}"
        )

    def test_a_tree_with_direction_and_no_register_is_clean(self, tmp_path):
        """The coexistence state, censused whole: direction present, no register.

        docs/QUICKSTART.md's *Using noni alongside a driver that keeps its own
        claims* section tells a team whose work driver keeps its own claim state
        to run the direction layer and never create ``noni/sessions/``, because
        an absent register is the state the sessions group answers with silence
        while a register that exists and cannot be listed earns a ``cannot-tell``
        row of code 44. That sentence describes a state no other test in this
        suite builds: every whole-run clean-tree fixture either holds no
        direction layer at all (``tests/test_census_reporting.py``, which counts
        the ``ledger-empty`` warn its absence earns) or holds a committed
        register (``test_a_readable_register_behaves_exactly_as_before``, above).

        So the tree is the one the section sells: one committed ledger record,
        one committed ``noni/direction/order.json`` whose entry cites that record
        and stays inside the ordering group's own staleness threshold at
        ``--now``, and no ``noni/sessions/`` written at any point -- which is why
        ``noni/sessions`` names no committed path in ``git ls-files`` below. The
        census runs whole first, with no ``--only`` and no ``--skip`` of a claim
        class, so a finding row of any group is a finding this run was free to
        print.

        ``hygiene`` is the one class that whole run skips, and the harness flag is
        what says so rather than the assertion quietly tolerating a row: an
        isolated fixture tree has no deny-list, so hygiene always reports its
        inactive row, and an operator's own deny-list would decide this test from
        outside the tree.

        A whole run that printed nothing is also a run that could have printed
        nothing without reading the register at all, so each class is then asked
        on its own under ``--only``: the group is entered, its read happens, and
        the row it would have earned is the assertion's subject rather than an
        absent key in an aggregate. (The summary's ``counts`` are the fired
        classes only -- ``census_report._render`` drops the zeros -- so a zero
        there would prove nothing about whether a class ran.)
        """
        repo = _coexistence_fixture(tmp_path)
        tracked = _git(repo, "ls-files", "noni/sessions").stdout.split()
        assert tracked == [], (
            f"the fixture committed a register path, so the run below is not the "
            f"state the section documents: {tracked}"
        )

        rc, out, err = _run_census(repo, "--now", COEXISTENCE_NOW, json_out=True,
                                   skip_hygiene=True)
        rows = _ndjson_rows(out)
        findings = [r for r in rows if r.get("kind") == "finding"]
        assert rc == 0, (
            f"a tree with the direction layer and no register exits clean, got "
            f"{rc}\nstderr: {err}\n{out}"
        )
        assert findings == [], (
            f"the census found claim rows in a tree that keeps no claims: {findings}"
        )
        summaries = [r for r in rows if r.get("kind") == "summary"]
        assert len(summaries) == 1, f"the --json stream must carry one summary: {rows}"
        summary = summaries[0]
        assert summary.get("exit") == 0 and summary.get("ok") is True, summary
        for claim_class in _CLAIM_CLASSES:
            only = _run_census(repo, "--now", COEXISTENCE_NOW, "--only",
                               claim_class, json_out=True)
            assert only[0] == 0, (
                f"the {claim_class} run exited {only[0]} on a tree that keeps no "
                f"register\nstderr: {only[2]}\n{only[1]}"
            )
            rows = [r for r in _ndjson_rows(only[1]) if r.get("kind") == "finding"]
            assert rows == [], (
                f"the {claim_class} class reported in a tree that keeps no "
                f"register: {rows}"
            )
        for ordering_class in _ORDERING_CLASSES:
            only = _run_census(repo, "--now", COEXISTENCE_NOW, "--only",
                               ordering_class, json_out=True)
            assert only[0] == 0, (
                f"the {ordering_class} run exited {only[0]} on a committed artifact "
                f"that cites a record the ledger holds\nstderr: {only[2]}\n{only[1]}"
            )
            rows = [r for r in _ndjson_rows(only[1]) if r.get("kind") == "finding"]
            assert rows == [], (
                f"the {ordering_class} class reported for a committed artifact "
                f"that cites a record the ledger holds: {rows}"
            )


def _coexistence_fixture(tmp_path) -> Path:
    """The tree docs/QUICKSTART.md's driver-coexistence section sells, minus its register.

    One committed steering record, one committed ordering artifact whose single
    entry cites that record, and no ``noni/sessions/`` -- not an empty directory,
    which the section tells the reader never to create. ``tests/census_fixtures``
    builds neither the ordering artifact nor a register history, so the one line
    that is not a bare file commit lives here rather than in the shared builders,
    whose other callers expect the shapes they already build.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    entry = orderschema.entry(12, "2026-10-01-alpha", COEXISTENCE_CONFIRMED)
    _commit_file(repo, ORDER_REL,
                 json.dumps({"schema": orderschema.ORDER_SCHEMA,
                             "entries": [entry]}, indent=2))
    return repo
