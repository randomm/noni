"""An unreadable ledger is reported by one identifier, never named by its host path.

The ordering group's read faults alone (the probe's own read is pinned in
``tests/test_census_ledger_probe.py``), so a directory the run could not enumerate
cannot answer for the entries the artifact cites.

Split out of ``tests/test_census_ordering.py``; the builders are in
``tests/ordering_fixtures.py``.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
from ordering_fixtures import (
    _entry,
    _listing_faults,
    _listing_faults_all_reads,
    _ordering_record_read_faults,
    _repo,
    _run,
    _run_in_process,
    _seed,
)

BASELINE_ID = "2026-10-01-baseline"

ORDER_REL = "noni/direction/order.json"

def test_an_unreadable_ledger_does_not_blame_every_entry(tmp_path):
    """A ledger the census cannot list answers nothing, so no entry's decision
    may be reported as matching no file: the ordering group stays silent and
    leaves the ledger's own classes to report the tree."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(3, BASELINE_ID))
    shutil.rmtree(repo / "noni" / "decisions")
    (repo / "noni" / "decisions").write_text("not a directory", encoding="utf-8")
    code, rows, out, err = _run(repo)
    assert code == 0, (code, out, err)
    assert rows == [], rows


def test_an_unlistable_ledger_is_reported_and_never_reads_as_clean(tmp_path):
    """A ledger whose listing itself faults answers nothing, and silence about
    that is a clean verdict on a run that checked no citation at all.

    The census lists the ledger with ``Path.glob``. When that call faults while an
    entry cites a decision, the group adds one whole-artifact row naming the
    fault, so the run is never clean: the row is a fail-class one, it exits 15 on
    its own and under ``--strict`` alike, and whole-artifact is what keeps it
    through every ``--only``/``--skip`` set (see ``keep`` in census.py).

    Distinguished from ``test_an_unreadable_ledger_does_not_blame_every_entry``:
    there the ledger path is not a directory, so the listing never runs and the
    ledger's own classes own the report. Here the path is a real directory whose
    listing faults -- an I/O fault of this tree, which no other class of the run
    can see, and the artifact is the one both sides gate on.

    The census runs in-process for this one (``_run_in_process``): the fault is
    inside the interpreter, and a subprocess would not see it."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(3, BASELINE_ID))
    with _listing_faults(repo / "noni" / "decisions"):
        code, rows, out, err = _run_in_process(repo)
        # ordering-malformed is a fail class, so the run is not clean with or
        # without --strict: the row is the whole point of the test.
        assert code == 15, (code, out, err)
        assert [r["check"] for r in rows] == ["ordering-malformed"], rows
        assert rows[0]["severity"] == "fail", rows[0]
        assert rows[0]["subject"] == ORDER_REL, rows[0]
        assert "noni/decisions" in rows[0]["message"], rows[0]
        # The OSError's own text reaches the row. It goes through the census's
        # machine-local-path scrubbing, which is anchored so that it stops at
        # absolute and home paths and leaves this errno text whole; the
        # assertions are written by substring, not by the whole phrase, so they
        # hold whichever way the scrub lands.
        assert "OSError" in rows[0]["message"], rows[0]
        assert "input" in rows[0]["message"], rows[0]
        # A whole-artifact row survives a filter that named none of its classes.
        for extra in (("--only", "ordering-stale", "--strict"),
                      ("--only", "ordering-closed", "--strict"),
                      ("--skip", "ordering-malformed", "--strict")):
            strict, strict_rows, s_out, s_err = _run_in_process(repo, *extra)
            assert strict == 15, f"{extra}: exit {strict} rows={strict_rows} {s_err}"
            assert [r["check"] for r in strict_rows] == ["ordering-malformed"], strict_rows
        strict, strict_rows, out, err = _run_in_process(repo, "--strict")
        assert strict == 15, (strict, out, err)


def test_an_unlistable_ledger_without_a_citation_adds_no_row(tmp_path):
    """Nothing was looked up, so nothing was left unchecked: an entry with no
    ``decision`` cannot have had its citation silently skipped, and the run
    stays clean. The row reports a check the run could not perform, not a fault
    of the ledger in general -- that is the ledger group's own report."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(3, None))
    with _listing_faults(repo / "noni" / "decisions"):
        code, rows, out, err = _run_in_process(repo, "--strict")
        assert code == 0, (code, out, err)
        assert rows == [], rows


def test_an_unlistable_ledger_is_reported_by_the_ledger_group_too(tmp_path):
    """Both groups read the ledger through the one listing, and both say so.

    Since the ledger group, the ordering group and the probe share
    ``census_ledger.listing_helper``, an injected readdir fault is visible to
    both classes at once. Each reports it in its own class: the ordering group's
    row says which check it could not perform, and the ledger group's says the
    append-only question went unanswered. The point of this test is that the
    ordering arm's fault -- injected at the ordering group's own seam by
    ``_listing_faults`` -- does not stand in for the ledger group's, which is
    why this one faults ``Path.iterdir``: the read every group shares.

    Run unfiltered (no ``--only`` at all), so no group's rows are dropped by a
    filter: the fault row of each group is whole-artifact and survives on its own
    merits. ``--skip hygiene`` is named because hygiene always reports, and its
    "deny-list class inactive" row belongs to no ledger or ordering contract."""
    repo = _repo(tmp_path)
    _seed(repo, _entry(3, BASELINE_ID))
    with _listing_faults_all_reads(repo / "noni" / "decisions"):
        code, rows, out, err = _run_in_process(repo, "--skip", "hygiene")
        checks = sorted(r["check"] for r in rows)
        assert checks == ["ledger-edited", "ordering-malformed"], (checks, out, err)
        ledger_rows = [r for r in rows if r["check"] == "ledger-edited"]
        assert len(ledger_rows) == 1, rows
        assert ledger_rows[0]["subject"] == "noni/decisions", ledger_rows[0]
        assert "input/output error" in [
            r["message"] for r in rows if r["check"] == "ordering-malformed"][0]
        # Both classes are fail classes here: the ordering row is a fail class
        # outright, and --strict promotes the ledger group's cannot-tell warn.
        assert code == 15, (code, out, err)


def _ordering_host_faults() -> list[tuple[OSError, tuple[str, ...]]]:
    """The faults whose filename the scrubber keeps losing, and their parts.

    Built at runtime, never literals: a tracked file carrying one of these paths
    would trip the census's own hygiene class. A non-ASCII component with a space
    in it, and the bare home of a service account -- the two shapes the path arms
    of ``census_text._stripped`` cannot be relied on to catch, which is why the
    row is built without the filename rather than scrubbed after it.
    """
    return [
        (OSError(13, "Permission denied", "/home/someone/\u00fcn\u00ef c\u00f6de/my dir/"),
         ("someone", "\u00fcn\u00ef", "c\u00f6de", "my dir")),
        (OSError(13, "Permission denied", "~deploy"), ("deploy",)),
    ]


@contextlib.contextmanager
def _listing_fault(ledger: Path, fault: OSError):
    """Fault the ordering group's read of ``ledger`` with one given exception.

    ``_listing_faults`` raises a bare ``OSError(text)``, which is the shape every
    other test here wants. This one takes the exception itself, for the test that
    needs the filename a real fault carries.
    """
    ordering = importlib.import_module("noni.census_ordering")
    readers = importlib.import_module("noni.census_ordering_readers")
    real_check = ordering.check_ordering
    real_helper = readers.listing_helper
    target = Path(ledger)

    def check_without_names(*args, **kwargs):
        kwargs["names"] = None
        return real_check(*args, **kwargs)

    def boom(path):
        if Path(path) == target:
            raise fault
        return real_helper(path)

    ordering.check_ordering = check_without_names
    readers.listing_helper = boom
    try:
        yield
    finally:
        ordering.check_ordering = real_check
        readers.listing_helper = real_helper


@pytest.mark.parametrize("case", range(2))
def test_the_listing_fault_row_carries_no_part_of_the_filename(tmp_path, case):
    """The ordering group's row for an unlistable ledger names the fault, never a path.

    The same rule the ledger group's row obeys, pinned at this group's own seam:
    the fault text is built from the exception's class and its ``strerror``, so a
    filename the scrubber would have missed never reaches the row. The words and
    the ledger still have to appear -- a row that lost them to stay clean would
    fail here, not just the leak assertions.
    """
    repo = _repo(tmp_path, f"fault-no-filename-{case}")
    _seed(repo, _entry(3, BASELINE_ID))
    fault, parts = _ordering_host_faults()[case]
    with _listing_fault(repo / "noni" / "decisions", fault):
        code, rows, out, err = _run_in_process(repo)
    assert code == 15, (code, out, err)
    assert [r["check"] for r in rows] == ["ordering-malformed"], rows
    row = rows[0]
    for field in ("subject", "artifact", "message"):
        for part in parts:
            assert part not in row[field], f"{part!r} leaked into {field}: {row[field]!r}"
        assert "/home/someone" not in row[field], row[field]
    assert "Permission denied" in row["message"], row["message"]
    assert "PermissionError" in row["message"], row["message"]


def test_both_groups_name_an_unreadable_ledger_with_one_identifier(tmp_path):
    """One unreadable ledger, two rows, one name for it.

    The ledger group's row and the ordering group's row both report a ledger this
    run could not list, and an operator reading the report joins them by that
    name. The ordering group used to derive it by running the census's own
    root-relative path through the scrubber, which is the wrong tool for a path
    the census wrote itself: scrub a root-relative path and what comes back is a
    marker, not the directory. Both rows take the name from
    ``census_ledger.ledger_name`` instead, which is the census's one answer to
    "what do I call a ledger I could not read".

    The out-of-tree ``--ledger`` is the case that decides it: there the path is
    not rootable, so the identifier is a bare last segment and a scrubber handed
    the same path would have printed a host directory instead. Both groups read
    the ledger through the run's one listing, so faulting that listing is what
    leaves the two of them without an answer -- and the run is in-process because
    the fault lives in this interpreter.
    """
    repo = _repo(tmp_path, "shared-ledger-identifier")
    _seed(repo, _entry(3, BASELINE_ID))
    outside = tmp_path / "ledger-home" / "decisions"
    outside.mkdir(parents=True)
    (outside / f"{BASELINE_ID}.json").write_text(
        json.dumps({"id": BASELINE_ID, "date": "2026-10-01T00:00:00Z", "asked_by": "developer",
                    "questions": [{"id": "q1", "text": "Order?", "options": ["a", "b"],
                                   "answer": "a"}], "by": "Replay",
                    "scope": "release ordering", "status": "decided", "supersedes": None},
                   indent=2) + "\n",
        encoding="utf-8")
    with _listing_faults_all_reads(outside, "input/output error"):
        # ``--only ordering-malformed`` rather than the helper's default set: that
        # one confines the run to the ordering group, whose whole-artifact fault
        # row survives whatever it names, and the ledger group's own row for the
        # same fault is wanted here too -- which is what makes the two rows' name
        # for the ledger comparable.
        code, rows, out, err = _run_in_process(repo, "--ledger", str(outside),
                                               "--only", "ordering-malformed")
    assert code == 15, (code, out, err)
    by_check = {r["check"]: r for r in rows}
    assert sorted(by_check) == ["ledger-edited", "ordering-malformed"], rows
    ledger_row, ordering_row = by_check["ledger-edited"], by_check["ordering-malformed"]
    # The identifier the ledger group uses, in the ordering group's prose too.
    assert ledger_row["subject"] == "decisions", ledger_row
    assert "the decision ledger (decisions)" in ordering_row["message"], ordering_row["message"]
    for field in ("subject", "artifact", "message"):
        assert str(outside) not in ordering_row[field], ordering_row[field]


def test_no_ordering_row_names_an_out_of_tree_ledger_by_its_host_directory(tmp_path):
    """Every row of the group names the ledger the one way, out-of-tree included.

    An out-of-tree ``--ledger`` cannot be rooted, so ``rel_to_root`` hands back the
    machine-local absolute path -- and a row that interpolates that value directly
    prints the directory the host keeps the ledger in. There are two places the
    group names the ledger in prose (the listing-fault row and the per-entry
    citation row), and both take the identifier from ``ledger_name``: the group has
    no identity default to fall back on, so a caller that forgets the argument does
    not get a path printed by default.
    """
    repo = _repo(tmp_path, "out-of-tree-ledger-rows")
    _seed(repo, _entry(3, BASELINE_ID), _entry(4, "no-such-record"))
    outside = tmp_path / "ledger-home" / "decisions"
    outside.mkdir(parents=True)
    (outside / f"{BASELINE_ID}.json").write_text(
        json.dumps({"id": BASELINE_ID, "date": "2026-10-01T00:00:00Z", "asked_by": "developer",
                    "questions": [{"id": "q1", "text": "Order?", "options": ["a", "b"],
                                   "answer": "a"}], "by": "Replay",
                    "scope": "release ordering", "status": "decided", "supersedes": None},
                   indent=2) + "\n",
        encoding="utf-8")

    with _ordering_record_read_faults(outside, "input/output error"):
        code, rows, out, err = _run_in_process(repo, "--ledger", str(outside),
                                              "--only", "ordering-malformed")
    assert code == 15, (code, out, err)
    citation_rows = [r for r in rows if "matches no record file" in r["message"]]
    assert citation_rows, rows
    for row in citation_rows:
        for field in ("subject", "artifact", "message"):
            assert str(outside.parent) not in row[field], f"{field}: {row[field]!r}"
            assert "ledger-home" not in row[field], f"{field}: {row[field]!r}"
        assert "(decisions)" in row["message"], row["message"]

    with _listing_faults(outside):
        code, rows, out, err = _run_in_process(repo, "--ledger", str(outside),
                                              "--only", "ordering-malformed")
    assert code == 15, (code, out, err)
    listing_rows = [r for r in rows if "could not be listed" in r["message"]]
    assert listing_rows, rows
    for row in listing_rows:
        for field in ("subject", "artifact", "message"):
            assert str(outside.parent) not in row[field], f"{field}: {row[field]!r}"
            assert "ledger-home" not in row[field], f"{field}: {row[field]!r}"
        assert "the decision ledger (decisions)" in row["message"], row["message"]
