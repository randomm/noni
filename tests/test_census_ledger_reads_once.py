"""One readdir of the ledger per census run, and every citation still checked when it faults.

Split out of ``tests/test_census_ledger_probe.py``; the builders are in
``tests/census_ledger_fixtures.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from _harness import (
    SRC,
    _commit_file,
    _fault_the_ledger_listing,
    _harness_source,
    _init_repo,
)
from census_ledger_fixtures import _code, _rows, _valid_record
from ordering_fixtures import rows_without_unasked_closed

CENSUS = Path(__file__).resolve().parent.parent / "skills" / "census" / "scripts" / "census.py"

def _iterdir_counter(monkeypatch, ledger: Path):
    """Patch ``Path.iterdir`` once, counting the listings of ``ledger`` it sees.

    Returns ``(state, plant)``: ``state["n"]`` is the count, and ``plant(k)``
    makes the (k + 1)-th listing of ``ledger`` raise. The single patch is the
    point — a fixture that patches twice over its own previous patch chains two
    counters, the outer one never reaches its guard, and the test silently stops
    faulting anything. One patch, one counter, and the fault position is a
    parameter a test resets between the runs it compares.

    The patch goes on ``census.Path``, the name the census and its ledger module
    share (see ``_fault_the_ledger_listing`` in ``tests/_harness.py``), so it is
    visible to every reader of the ledger and to no other interpreter.
    """
    import census

    real_iterdir = Path.iterdir
    target = Path(ledger)
    state = {"n": 0, "fault_after": 10 ** 9}

    def boom(self):
        if self == target:
            state["n"] += 1
            if state["n"] > state["fault_after"]:
                raise OSError("readdir faulted after the probe")
        return real_iterdir(self)

    monkeypatch.setattr(census.Path, "iterdir", boom)

    def plant(fault_after: int) -> dict:
        state["n"] = 0
        state["fault_after"] = fault_after
        return state

    return state, plant


def test_the_run_lists_the_ledger_once(tmp_path, monkeypatch):
    """One readdir of the ledger per run, whoever downstream wants its names.

    The probe is the run's only listing: the record pass and the ordering readers
    read the ``names`` it carries instead of walking the directory again. The
    fault is planted after the first successful readdir, which is the shape no
    single-fault test can reach: the probe's read answered, and the tree has
    turned hostile only by the time the record pass asks the same question. A
    run that re-listed died there with an ``OSError`` traceback out of
    ``census.main``; a run that reads the probe's names says the same thing the
    unfaulted run says and exits like it.

    The seam is ``Path.iterdir`` with a counter, so the assertion is about the
    count and not about which helper happened to be called: the census's own
    git calls, the session register and the artifact reads all list other paths,
    and only a guard that lets the first readdir of the ledger through reaches
    the arm under test. The patch is installed once, by ``_iterdir_counter``,
    and the fault position reset between runs: a fixture that patched twice over
    its own previous patch would chain the counters and fault nothing.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    _commit_file(repo, "noni/decisions/2026-10-02-beta.json",
                 json.dumps(_valid_record(rec_id="2026-10-02-beta"), indent=2))
    ledger = repo / "noni" / "decisions"
    state, plant = _iterdir_counter(monkeypatch, ledger)

    # The run with every listing honest is the control: the same tree, the same
    # verdict the faulted run must reproduce.
    plant(10 ** 9)
    rows = _rows(repo, "--skip", "hygiene")
    code = _code(repo, "--skip", "hygiene")
    assert code == 0, f"a run that read the ledger once stays clean: {code} {rows}"
    assert rows == [], f"the unfaulted run reports nothing: {rows}"

    # The counter is the mechanism: pin that this run listed the ledger once.
    plant(10 ** 9)
    code = _code(repo, "--skip", "hygiene")
    assert code == 0, (code, state)
    assert state["n"] == 1, f"the ledger was listed {state['n']} times, expected one"

    # And the second readdir faulting is what used to kill the run.
    plant(1)
    rows = _rows(repo, "--skip", "hygiene")
    code = _code(repo, "--skip", "hygiene")
    assert code == 0, f"the run must complete, not raise: {code} {rows}"
    assert rows == [], f"the faulted run reports the same rows as the clean one: {rows}"


def test_a_run_that_cannot_relist_the_ledger_still_checks_every_citation(
    tmp_path, monkeypatch
):
    """One listing must not cost the run its checks.

    The run faults its second readdir of the ledger while an entry cites a
    record the ledger does not hold. A run that answered "no records" from the
    fault would report the citation as matching no file, which is the dishonesty
    the ordering group's fault row exists to prevent; a run that reads the
    probe's names makes the same finding it makes without the fault. Both rows
    are pinned by class and subject, so an implementation that dropped either
    half fails here."""
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record(), indent=2))
    order = {
        "schema": "noni.order/1",
        "entries": [{"issue": 7, "decision": "2026-10-01-alpha",
                     "confirmed": "2026-10-26T00:00:00Z"},
                    {"issue": 8, "decision": "2026-10-09-ghost",
                     "confirmed": "2026-10-26T00:00:00Z"}],
    }
    _commit_file(repo, "noni/direction/order.json", json.dumps(order, indent=2))
    state, plant = _iterdir_counter(monkeypatch, repo / "noni" / "decisions")
    plant(1)
    rows = _rows(repo, "--skip", "hygiene")
    assert state["n"] == 1, f"the ledger was listed {state['n']} times, expected one"
    # The run's own not-evaluated row (issue #148) is the fixture's -- no
    # --issue-state was given -- and it is not a second read of the ledger: the
    # listing count above already answers that question, and it is answered once.
    fault_rows = rows_without_unasked_closed(rows)
    assert sorted(r["check"] for r in fault_rows) == ["ordering-malformed"], rows
    assert [r["subject"] for r in fault_rows] == ["#8"], rows
    assert "2026-10-09-ghost" in fault_rows[0]["message"], rows
    assert _code(repo, "--skip", "hygiene") == 15


def test_the_run_probes_the_ledger_once(tmp_path, monkeypatch):
    """One classification per run: ``main`` asks the probe once and reuses it.

    The listing is the expensive read of the ledger group, and a second probe is
    a second chance to disagree with the first (the tree can change between two
    reads). ``main`` builds the one ``LedgerProbe``, decides the group from its
    ``listing_fault``, and hands that same probe to ``_check_ledger``. The
    counter proves the group ran and the count proves it read once.

    The seam is ``census._ledger_probe``, the name the census owns and the one
    its tests patch. The source pins at the end state the same rule on the
    wiring, so restoring a second-probe path fails there as well as here.
    """
    import census

    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json",
                 json.dumps(_valid_record(), indent=2))

    calls: list[str] = []
    real_probe = census._ledger_probe

    def counting_probe(ledger):
        calls.append(str(ledger))
        return real_probe(ledger)

    monkeypatch.setattr(census, "_ledger_probe", counting_probe)
    assert _code(repo, "--skip", "hygiene") == 0
    assert len(calls) == 1, f"the ledger probed {len(calls)} times: {calls}"

    # The faulted run probes once too: the filter decision and the row both use
    # the one probe, so a fault must not cost a second read.
    calls.clear()
    _fault_the_ledger_listing(monkeypatch, repo / "noni" / "decisions")
    assert _code(repo, "--skip", "hygiene") == 0
    assert len(calls) == 1, f"a faulted listing probed {len(calls)} times: {calls}"

    source = _harness_source(CENSUS)
    # The run moved to census_run.py (issue #52); the wiring the pin asks about
    # is the run's, so it is read from the file that holds it now. The census's
    # own source is still read for the rule that a second probe path is back: the
    # probe seam itself stays a name of the census.
    run_source = (SRC / "noni" / "census_run.py").read_text(encoding="utf-8")
    # The seam is resolved once per helper body now (`census = _census()`), so the
    # pin names the call through that local binding rather than the inline form.
    assert "ledger_probe = census._ledger_probe(ledger)" in run_source
    assert "ledger_probe.listing_fault" in run_source
    assert "census._check_ledger(ledger, git, root, findings, args.strict," in run_source
    assert "_ledger.listing_fault(" not in source, \
        "a second probe path is back: main must read the fault off its one probe"


def test_a_filter_that_named_no_ledger_class_at_all_still_reports_the_fault(
    tmp_path, monkeypatch
):
    """The filter bypass, with a filter that names a class of no ledger group.

    ``--only hygiene`` names neither ``ledger-edited`` nor ``ledger-empty``, so
    without the probe-driven group run this run would report nothing about the
    ledger at all: the group runs because the probe could not read its input, and
    the row survives because it is whole-artifact. Both halves are needed to stop
    a caller buying back the clean verdict with a filter that never mentioned the
    ledger.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-a.json",
                 json.dumps(_valid_record(), indent=2))
    _fault_the_ledger_listing(monkeypatch, repo / "noni" / "decisions")

    rows = _rows(repo, "--only", "hygiene")
    # hygiene is the class the filter named, and it always reports (an isolated
    # fixture repo has no active deny-list). The row under test is the ledger one.
    ledger_rows = [r for r in rows if r["check"] != "hygiene"]
    assert [r["check"] for r in ledger_rows] == ["ledger-edited"], (
        f"a run that could not list the ledger must say so under a filter that "
        f"named only hygiene: {rows}"
    )
    assert "readdir" in ledger_rows[0]["message"], ledger_rows[0]
    assert _code(repo, "--only", "hygiene") == 0
    # --strict promotes both the fault row (ledger-edited -> 12) and the
    # always-reporting hygiene warn (-> 50); either code is a promoted warn.
    assert _code(repo, "--only", "hygiene", "--strict") in (12, 50)
