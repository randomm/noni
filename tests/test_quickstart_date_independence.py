"""The quickstart's Route B runs on any date, not just the day it was reviewed.

The record id the page's ordering line cites is dated by the writer: ``decide``
builds it as ``<date>-<slug>`` from today's UTC clock
(``src/noni/_decide_flags.py``'s ``parse_date`` and ``src/noni/decide.py``). The
first harness filled ``<record-id>`` from a literal, so the page passed on the one
day the literal named and failed every day after with the ordering writer's
exit-4 refusal, "no decision record ... is in the ledger". This module is the
regression pair for that bug.

The proof is the shape the bug actually had, so it is the shape the fix must be
observed in: the date goes on the decide line's argv, appended by
:func:`quickstart_runner.date_arg` after the golden comparison, where the
harness's other two moves are applied. In-process monkeypatching is not a proof
here -- the writers run as subprocesses, so a patch on the test's own ``datetime``
reaches nothing that names a record.

Two dates, because one half of the bug is invisible to the other. The fixed date
below pins the id: a reader (or a harness) that copies an id from another day is
refused, so a run on that date that collected nothing would have nothing to
compare and the assertion would pass on the absence of a record. The second test
uses no date at all, which is the host's own today, so a future run cannot be told
apart from the one that went red: a literal planted again turns this test red on
whatever day it is, not on one scheduled day.

The control that keeps the first test honest is the ``--date`` token itself: the
test compares the record on disk against what the *page's* line printed, not
against a fixture's expectation, so a harness that ignored the appended argument
would collect the host's date and fail the equality.
"""

from __future__ import annotations

import re
from pathlib import Path

from quickstart_runner import World, date_arg, git, run_route_b, substitute

# A date the host clock will not reach for a long time, and one the page never
# named. The point is only that it is not today, so the record the writer files is
# a record no literal could have predicted.
OTHER_DATE = "2027-01-15"


def test_route_b_runs_on_a_date_other_than_the_host_clock(world: World) -> None:
    """The whole Route B walk exits 0 on a date the host is not on.

    This is the exact walk the two failing tests drive, with one addition: the
    world names a date, and the harness appends it to the page's decide line. The
    record the collector read back is then named by that date and nothing else, and
    the ordering line that follows -- which is the command that exited 4 -- carries
    the same id.
    """
    world.decide_date = OTHER_DATE
    commands = run_route_b(world)

    decide = next(argv for argv in commands if argv[:2] == ["noni", "decide"])
    assert date_arg(world, decide)[-2:] == ["--date", OTHER_DATE], (
        f"the decide line the launcher ran did not carry the requested date: "
        f"{date_arg(world, decide)}")

    records = sorted((world.state / "noni" / "decisions").glob("*.json"))
    assert len(records) == 1, (
        f"the decide line wrote {len(records)} records under the state clone: "
        f"{[p.name for p in records]}")
    assert records[0].stem == f"{OTHER_DATE}-release-scope", (
        f"decide did not honour the date the harness passed on its argv, so the "
        f"collector is reading the host clock: {records[0].name!r}")
    collected = world.placeholders.get("<record-id>")
    assert collected == records[0].stem, (
        f"the id handed to the ordering line is not the record on disk: "
        f"{collected!r} vs {records[0].name!r}")

    order = next(argv for argv in commands if argv[:2] == ["noni", "order"])
    filled = substitute(order, world.placeholders)
    assert filled[7] == f"{OTHER_DATE}-release-scope", filled


def test_route_b_runs_on_the_host_clock_with_no_date_pinned(world: World) -> None:
    """The same walk with no date set: today's date is whatever today is.

    The date-free half of the pair. Nothing here knows what day it runs, so a
    harness that fell back to a literal would fail on the day after that literal
    and stay red ever after -- the failure this module exists to keep loud. The id
    is checked against the file the writer actually committed, and against the
    commit the page's own decide step made, so the collected value is not merely
    present, it is the one the state route carries.
    """
    assert world.decide_date is None, "the fixture's world must not pre-set a date"
    run_route_b(world)

    records = sorted((world.state / "noni" / "decisions").glob("*.json"))
    assert len(records) == 1, (
        f"expected one record under the state clone, got "
        f"{[p.name for p in records]}")
    collected = world.placeholders.get("<record-id>")
    assert collected == records[0].stem, (
        f"the collector did not read the id off disk: collected {collected!r}, "
        f"on disk {records[0].name!r}")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-release-scope", collected or ""), (
        f"the collected id is not the form the ordering writer accepts: "
        f"{collected!r}")
    committed = _committed_record_names(world)
    assert collected in committed, (
        f"the record the ordering line names is not committed on the state "
        f"branch: {collected!r} not in {committed}")


def _committed_record_names(world: World) -> list[str]:
    """The record names the state branch's own history carries.

    Read from the clone's own checked-out branch (``world.branch``, the tree the
    fixture seeded) with the launch env, the same way the route's other git
    assertions read it: the page's decide line commits the record it wrote, so a
    collected id that only exists in the working tree is not the promise the page
    makes.
    """
    listed = git(world.state, "ls-tree", "-r", "--name-only", world.branch, "--",
                 "noni/decisions", env=world.env)
    assert listed.returncode == 0, (
        f"git ls-tree on the state clone failed: {listed.returncode} "
        f"{listed.stdout!r} {listed.stderr!r}")
    return [Path(line).stem for line in listed.stdout.splitlines() if line.strip()]


def test_the_date_argument_is_added_only_to_the_decide_line() -> None:
    """The date control touches one command, and never a page it reviews.

    ``date_arg`` runs after the golden comparison, so the page and
    ``tests/quickstart_golden.py`` keep the line a reader copies. That is only
    safe while the appended argument cannot leak onto another command or appear
    twice, which is what this pins: a golden decide line that gained ``--date``
    would mean the page prints it, and the harness would be duplicating a flag.
    """
    world = World(Path("/scratch"), Path("/venv"), Path("/clone"))
    world.decide_date = OTHER_DATE
    decide = ["noni", "decide", "--repo", ".noni-state", "--slug", "release-scope"]
    assert date_arg(world, decide) == [*decide, "--date", OTHER_DATE]
    for argv in (["noni", "order", "--repo", ".noni-state", "add", "12",
                  "--decision", "<record-id>"],
                 ["noni", "census", "--repo", ".noni-state"],
                 ["git", "-C", ".noni-state", "push", "-u", "origin", "HEAD"]):
        assert date_arg(world, argv) == argv, f"a non-decide line gained --date: {argv}"
    world.decide_date = None
    assert date_arg(world, decide) == decide, "a world with no date set passed --date"
