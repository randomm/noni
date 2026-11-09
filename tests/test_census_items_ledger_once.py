"""The ledger is read once per run, whatever the store holds.

``_successor`` answers one question -- which live record supersedes the record this item
cites -- and it once answered it by re-reading and re-parsing *every* file of the ledger
for *each* citing item. Eight items citing one superseded record meant eight walks over
a directory the run had already listed (the probe's ``names``) and parsed once
(``_ledger_status``): quadratic in the store, for an answer the first walk already held.

The rule this suite holds: the group opens each ledger record once, and the count of
opens does not grow with the number of citing items. The spy wraps the seam the group is
handed (``census_items_run._item_read_record``) and the run is driven *in process* rather
than as a subprocess, because a counter in this process cannot observe reads a child made
-- a spy that silently counts nothing is the failure mode that would let the quadratic
path back in while the test stayed green.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from _harness import _init_repo
from census_items_group_support import commit, item, record
from items_fixtures import NOW

DECISIONS = "noni/decisions"
CITED = "2026-10-01-old"
HEIR = "2026-11-01-heir"


def _tree(tmp_path, name: str):
    """A fresh git tree, so two sizes of the same fixture cannot share a commit."""
    tree = tmp_path / name
    if tree.exists():
        shutil.rmtree(tree)
    return _init_repo(tree)


def _run_census_counting_ledger_reads(monkeypatch, tree, *extra):
    """Rows and exit code of an in-process census run, plus the ledger files it opened.

    The census is imported through ``importlib`` for the same reason the sibling suites
    do (the package re-exports the run, and a stale module would answer for another
    tree). The spy replaces the items group's own reader seam, so what it counts is this
    group's reads and no other group's; it delegates to the real reader, so the rows are
    the rows an unspied run would have produced.
    """
    from noni import census as census_mod
    from noni import census_items_run

    real = census_items_run._item_read_record
    seen: list[str] = []

    def spy(path):
        if DECISIONS in str(path):
            seen.append(str(path).rsplit("/", 1)[-1])
        # The ledger's records reach this seam for one reason only: the citation class
        # could not answer from the map the ledger group built, so it is reading the
        # record for itself. Counting here is the honest measurement -- spying on
        # ``Path.read_bytes`` instead would spy on the ledger group's own read and turn
        # the census's own sharing into a "read" the items group never took.
        return real(path)

    monkeypatch.setattr(census_items_run, "_item_read_record", spy)

    # A guard on the census's own ledger probe: a run whose probe could not classify the
    # ledger shares no parsed records with the items group, and a test that let that
    # happen silently would be measuring a census that never shared anything at all. The
    # assertion is what makes "the ledger was read once" mean the read was *shared*.
    from noni import census as census_module

    real_probe = census_module._ledger_probe

    def probe(path):
        answer = real_probe(path)
        if DECISIONS in str(path):
            assert answer.state == "ok", (
                f"the ledger probe answered {answer.state!r} for {path}, so the run "
                "shared no parsed records with the items group and this test would be "
                "measuring the wrong run")
        return answer

    monkeypatch.setattr(census_module, "_ledger_probe", probe)
    rows, findings = _capture(census_mod, str(tree), *extra)
    return rows, findings, seen


def _capture(census_mod, repo_arg: str, *extra):
    """``main`` with its NDJSON captured rather than printed."""
    import io
    from contextlib import redirect_stdout

    import pytest

    buf = io.StringIO()
    argv = ["--repo", repo_arg, "--now", NOW, "--json", *extra]
    with redirect_stdout(buf):
        code = census_mod.main(argv)
    lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    try:
        rows = [__import__("json").loads(line) for line in lines]
    except ValueError:
        pytest.fail(f"the census printed non-NDJSON under --json: {lines}")
    return code, [r for r in rows if r.get("kind") == "finding"]


def _plant_citing_items(tree, count: int, cited: str) -> None:
    """``count`` dropped items, all citing one superseded record."""
    for index in range(count):
        item(tree, item_id=f"idea-{index:04d}", status="dropped",
             decision=cited, why="superseded by a later call")


def test_the_ledger_is_read_once_whatever_the_store_holds(tmp_path, monkeypatch):
    """N citing items cost one read of each ledger record, not N of them.

    Two runs over two tree sizes, one comparison: how many times the items group opened
    each record. A run that re-walks the ledger per item shows the count multiplying; a
    run that reads it once shows it flat.
    """
    counts = {}
    for size in (2, 8):
        tree = _tree(tmp_path, f"ledger-once-{size}")
        record(tree, CITED, status="superseded")
        record(tree, HEIR, status="decided", supersedes=CITED)
        _plant_citing_items(tree, size, CITED)
        commit(tree, f"items: {size} citing")
        code, findings, seen = _run_census_counting_ledger_reads(
            monkeypatch, tree, "--only", "item-reference-unresolved")
        assert code == 55, (code, findings)
        citing = [row for row in findings
                  if row["check"] == "item-reference-unresolved"]
        assert len(citing) == size, (size, citing)
        for row in citing:
            assert HEIR in row["message"], f"no successor named: {row['message']}"
        counts[size] = seen

    small, large = counts[2], counts[8]
    for name in (f"{CITED}.json", f"{HEIR}.json"):
        assert small.count(name) <= 1, \
            f"{name} opened {small.count(name)} times at 2 items: {small}"
        assert large.count(name) <= 1, \
            f"{name} opened {large.count(name)} times at 8 items: {large}"
    assert len(large) == len(small), (
        f"the ledger was opened {len(small)} times for 2 items and {len(large)} for "
        f"8: {small} vs {large}")


def test_the_walk_names_the_last_link_of_a_two_step_chain(tmp_path):
    """The unit of the walk on its own, before the run is asked to agree with it.

    Two questions, kept apart on purpose: *does the walk follow a two-step chain to its
    live end*, and *does the census report say so*. Only the second can be reached through
    the census, and a fixture that fails the first would silently make the second a test
    of something else. The chain is the one the ledger's own writers produce (see
    :func:`census_items_group_support.record`): each link names the decision it replaced,
    dated after it, one link left live.
    """
    from noni import census_items_citations as citations
    from noni.census_json import load_json_strict

    tree = _tree(tmp_path, "ledger-chain-unit")
    # "X supersedes Y" is stored as X.supersedes = Y, so the chain first -> second -> heir
    # is written by each later record naming the one it replaced.
    record(tree, "2026-08-01-first", status="superseded")
    record(tree, "2026-09-01-second", status="superseded",
           supersedes="2026-08-01-first")
    record(tree, HEIR, status="decided", supersedes="2026-09-01-second")
    ledger = tree / DECISIONS

    def read_record(path):
        try:
            return Path(path).read_bytes(), None
        except OSError as exc:
            return None, exc

    names = tuple(sorted(path.name for path in ledger.glob("*.json")))
    assert names == ("2026-08-01-first.json", "2026-09-01-second.json",
                     f"{HEIR}.json"), names
    # The middle link of the chain is itself gone, so the record the operator has to be
    # pointed at is the live one at the end of it -- and the ledger's own rule that a
    # chain has one live record is what makes the two the same question.
    assert citations._successor(
        ledger, "2026-08-01-first", ledger_names=names, records={},
        read_record=read_record, load_json_strict=load_json_strict) == HEIR
    # The link that already holds: its replacement is nothing, and the class says so by
    # naming no successor rather than inventing one.
    assert citations._successor(
        ledger, HEIR, ledger_names=names, records={},
        read_record=read_record, load_json_strict=load_json_strict) is None


def test_the_successor_still_names_the_live_record_of_a_chain(tmp_path, monkeypatch):
    """The answer the sharing must not lose: the heir, two steps along a chain.

    Deduplicating a read is only correct if the answer is the same answer, so the case
    that motivated the second walk in the first place is pinned here rather than left to
    the counts above: a record superseded by a record that was itself superseded is
    reported against the *live* link, not the first one the scan met.
    """
    tree = _tree(tmp_path, "ledger-chain-heir")
    # A chain written the way the ledger's own writers write it: each link's
    # ``supersedes`` names the decision it replaced (the direction ``decide.py`` stores
    # and ``orderstate._successor`` reads), each link dated after the one it replaced, and
    # exactly one record left live. A fixture whose middle link stayed live, or whose
    # names sorted out of chain order, would be a ``ledger-chain`` ledger the arbiter
    # refuses, and the citation class would be asked for the last word of a chain that
    # has no single last word.
    record(tree, "2026-08-01-first", status="superseded")
    record(tree, "2026-09-01-second", status="superseded",
           supersedes="2026-08-01-first")
    record(tree, HEIR, status="decided", supersedes="2026-09-01-second")
    item(tree, status="dropped", decision="2026-08-01-first",
         why="superseded twice")
    commit(tree, "items: chain citation")
    code, findings, _seen = _run_census_counting_ledger_reads(
        monkeypatch, tree, "--only", "item-reference-unresolved")
    assert code == 55, (code, findings)
    assert [row["check"] for row in findings] == ["item-reference-unresolved"], findings
    assert HEIR in findings[0]["message"], findings[0]["message"]


def test_an_item_that_cites_nothing_costs_no_ledger_read_at_all(tmp_path, monkeypatch):
    """A store with no citation to answer does not walk the ledger either.

    The group's own cheap case: with nothing to resolve there is nothing to read, and a
    run that listed and parsed the ledger anyway would be paying for a question no item
    asked.
    """
    tree = _tree(tmp_path, "ledger-unasked")
    record(tree, "2026-10-01-baseline")
    item(tree)
    commit(tree, "items: a candidate")
    code, findings, seen = _run_census_counting_ledger_reads(
        monkeypatch, tree, "--only", "item-reference-unresolved")
    assert code == 0, (code, findings)
    assert findings == [], findings
    assert seen == [], f"the ledger was read for no citation: {seen}"
