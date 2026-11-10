"""The closed question a run could not ask is a verdict, not a sentence (#148).

The pilot's CI stayed green for days over an order whose issues had all been
closed. The census had an answer to "was the closed class asked" -- a ``note:``
line and the summary row's ``not_evaluated`` field -- and no step read either,
because a step gates on the exit code and the exit code carried no trace of the
skipped check. The fix makes the same fact a row of the class it describes:
``ordering-closed``, ``warn``, the class's own 46 under ``--strict``.

Each case below is the smallest tree that separates the fix from the bug it
replaces, and every one of them passes on the pre-fix tool only if the assertion
is about the note. That is what makes the suite the regression: a change that
turns the row back into a sentence reddens it.

The opposite half matters as much and is pinned here too. The row is an ordinary
finding of its class, so a tree that ordered nothing, an order that names no
issue, a run given a state map, and a run that skipped the class by name all
print no row and no code. A fix that simply always fired would be a worse bug
than the one it replaced: it would fault a project for a layer it never used.
"""

from __future__ import annotations

import json
import re

from _harness import _commit_file
from ordering_fixtures import (
    BASELINE_ID,
    ORDER_REL,
    _entry,
    _human,
    _repo,
    _run,
    _seed,
    _state,
)

NOW = "2026-10-27T12:00:00Z"

# The row's opening words, read from the product rather than copied: a reworded
# row must stop these filters matching, not quietly stop being asserted on.
def _unasked_prefix() -> str:
    from noni import census_ordering_closed

    return census_ordering_closed.CLOSED_STATE_UNASKED.split(":", 1)[0]


def _is_unasked(row: dict) -> bool:
    return (row["check"] == "ordering-closed"
            and row["message"].startswith(_unasked_prefix()))


def _unasked(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_unasked(r)]


def _order_of(repo, entries: list[dict]) -> None:
    """An order committed with the given entries, bypassing the writer's rules."""
    _commit_file(repo, ORDER_REL,
                 json.dumps({"schema": "noni.order/1", "entries": entries}, indent=2))


def _tree(tmp_path, name: str, entries: list[dict] | None):
    repo = _repo(tmp_path, name)
    if entries:
        _seed(repo, *[_entry(**e) for e in entries])
    elif entries == []:
        _order_of(repo, [])
    return repo


ISSUE = [{"issue": 7, "decision": BASELINE_ID, "confirmed": "2026-10-26T00:00:00Z"}]


def test_an_unasked_closed_check_is_a_warn_row_at_exit_zero(tmp_path):
    """The bug, stated as a test: an order of issues and no map is a finding.

    Before the fix this run printed rows nothing gated on and exited 0, and the
    only sentence saying why was a ``note:`` line below the rows. The row is
    pinned to the artifact as its subject, never an issue number: the fact is
    about the run and not about any one ordered issue, and a row whose subject
    were an issue would be the census answering a question it never asked.
    """
    repo = _tree(tmp_path, "unasked", ISSUE)
    code, rows, out, err = _run(repo)
    assert code == 0, (code, rows, err)
    assert [(r["check"], r["severity"], r["subject"]) for r in _unasked(rows)] == [
        ("ordering-closed", "warn", ORDER_REL)], rows
    assert len(_unasked(rows)) == 1, rows


def test_the_unasked_closed_check_earns_its_own_code_under_strict(tmp_path):
    """The half the CI step reads: ``--strict`` gives the row its 46.

    Exit 0 with a warning is what the pilot's pipeline saw, and exit 0 is not a
    failure a step can gate on. Under ``--strict`` the run must return the
    class's code -- not 0, not the hygiene class's 50, and not a code invented
    for the occasion, since the issue's contract is the existing class.
    """
    repo = _tree(tmp_path, "strict", ISSUE)
    code, rows, _out, err = _run(repo, "--strict")
    assert code == 46, (code, rows, err)
    assert [r["severity"] for r in _unasked(rows)] == ["fail"], rows
    assert _unasked(rows)[0]["code"] == 46, rows


def test_the_verdict_line_names_the_class_that_was_not_checked(tmp_path):
    """A CI step grepping the report's last line learns it too.

    The note sits below the rows and the verdict is the line a person or a
    ``tail -1`` reads, so the clause lives there. It is keyed on the row rather
    than on the note alone, because the note is owed by trees that asked nothing
    -- the two counter-cases at the end are what stop the clause being a stamp.
    """
    repo = _tree(tmp_path, "verdict", ISSUE)
    code, out, err = _human(repo)
    assert code == 0, (code, out, err)
    last = out.splitlines()[-1]
    assert last.startswith("summary:"), last
    assert "clean" not in last, last
    assert "ordering-closed not checked" in last, last
    assert last.endswith("verdict ok"), last

    # Given the map, the question was asked: the verdict is the plain one.
    asked = _tree(tmp_path, "verdict-asked", ISSUE)
    code, out, err = _human(asked, "--issue-state", _state(asked, {"7": "open"}))
    assert code == 0, (code, out, err)
    assert "not checked" not in out.splitlines()[-1], out.splitlines()[-1]

    # Skipped by name: a class the operator asked away is not an unchecked one.
    skipped = _tree(tmp_path, "verdict-skipped", ISSUE)
    code, out, err = _human(skipped, "--skip", "ordering-closed")
    assert code == 0, (code, out, err)
    assert "not checked" not in out.splitlines()[-1], out.splitlines()[-1]
    assert "was not evaluated" not in out, out


def test_a_tree_that_ordered_nothing_owes_no_row(tmp_path):
    """The fix must not fault a project for a layer it never used.

    Three states and one assertion: an absent order, an order with no entries,
    and an order whose entries name no issue. All three leave nothing for the
    closed class to ask, and a row in any of them would be a finding the run
    invented -- worse than the silence it replaced, because it would fire on a
    correctly-configured project.
    """
    absent = _repo(tmp_path, "absent")
    code, rows, out, err = _run(absent)
    assert code == 0, (code, rows, err)
    assert _unasked(rows) == [], rows

    empty = _tree(tmp_path, "empty", [])
    code, rows, out, err = _run(empty)
    assert code == 0, (code, rows, err)
    assert _unasked(rows) == [], rows
    assert "was not evaluated" in out, (
        "the note stays: the class belonged to the run and no map came")

    nameless = _repo(tmp_path, "nameless")
    _order_of(nameless, [{"issue": None, "decision": BASELINE_ID,
                          "confirmed": "2026-10-26T00:00:00Z"}])
    code, rows, out, err = _run(nameless)
    assert _unasked(rows) == [], rows


def test_the_row_is_an_ordinary_finding_of_its_class(tmp_path):
    """``--skip`` and ``--only`` hold the row the way they hold any other.

    The row reports a question the run chose not to ask, not a read that failed,
    so it earns none of the whole-artifact exemption the probe-honesty rows carry
    (``census_run.keep``). If it did, a warn row would be unsilenceable, and the
    one rule every other class obeys would have an exception nobody asked for.
    """
    repo = _tree(tmp_path, "filters", ISSUE)
    skipped = _run(repo, "--skip", "ordering-closed")
    assert _unasked(skipped[1]) == [], skipped[1]
    assert "was not evaluated" not in skipped[2], (
        "a class asked away by name is not a class that went unasked")

    other = _run(repo, "--only", "hygiene")
    assert _unasked(other[1]) == [], other[1]

    named = _run(repo, "--only", "ordering-closed")
    assert len(_unasked(named[1])) == 1, named[1]
    assert named[0] == 0, (named[0], named[1])


def test_the_headline_separates_the_clause_from_the_counts_it_qualifies(tmp_path):
    """The clause is appended to a count, so it has to open with a separator.

    The first cut of the clause carried no leading space and the headline printed
    it flush against the count, which rendered as one garbled token
    (``2 finding(s)ordering-closed not checked``). A test that only asked whether
    the class was *named* passed on that output, so what is pinned here is the
    shape of the line: the counts stay their own two tokens and the clause is a
    third, separated, with the class named once and not twice.
    """
    repo = _tree(tmp_path, "separator", ISSUE)
    code, out, err = _human(repo)
    assert code == 0, (code, out, err)
    first = out.splitlines()[0]
    # The counts are the ordering group's own (the human helper confines the run to
    # it); what matters below is their shape, not their number.
    assert re.match(r"^census: \d+ warning\(s\), \d+ finding\(s\)", first), first
    assert "finding(s)ordering" not in first.replace(" ", ""), first
    assert first.endswith("ordering-closed not checked"), first
    assert first.count("ordering-closed") == 1, first


def test_the_row_never_invents_a_closed_issue(tmp_path):
    """A run that answered the class about issues is not this run.

    The row's subject is the artifact and the class's per-issue rows carry issue
    numbers, so one tree that does both separates them: the closed row from the
    map and the not-evaluated row must not be confusable, and a fix that made
    the unasked case claim an issue would fail here rather than read as a pass.
    """
    repo = _tree(tmp_path, "both", ISSUE)
    code, rows, out, err = _run(repo, "--issue-state", _state(repo, {"7": "closed"}))
    assert code == 0, (code, rows, err)
    assert _unasked(rows) == [], (
        f"a run that read the map has nothing unasked to report: {rows}")
    assert [(r["check"], r["subject"]) for r in rows] == [
        ("ordering-closed", "#7")], rows


def test_the_row_survives_a_malformed_state_file_without_double_reporting(tmp_path):
    """A given-but-broken map is the malformed class's answer, not this one.

    The flag was passed, so the class was asked; the file refused to answer, and
    the group already says that as an ``ordering-malformed`` row. Adding the
    not-evaluated row too would report one fault as two verdicts of two classes.
    """
    repo = _tree(tmp_path, "broken-map", ISSUE)
    bad = repo / "bad-state.json"
    bad.write_text("{ not json", encoding="utf-8")
    code, rows, out, err = _run(repo, "--issue-state", str(bad))
    assert code == 15, (code, rows, err)
    assert _unasked(rows) == [], rows
    assert [r["check"] for r in rows] == ["ordering-malformed"], rows


def test_the_row_carries_no_machine_local_path(tmp_path):
    """The row names its artifact as the census names every artifact.

    The tree is built under a home-shaped path and the row's subject must be the
    root-relative identifier: a row that printed the tree's real location would
    put a machine-local path in the report the public-repo hygiene class exists
    to keep free of them.
    """
    repo = _repo(tmp_path / "home-someone" / "checkout", "path")
    _seed(repo, _entry(7, BASELINE_ID))
    code, rows, out, err = _run(repo)
    assert code == 0, (code, rows, err)
    row = _unasked(rows)[0]
    assert row["subject"] == ORDER_REL, row
    assert row["artifact"] == ORDER_REL, row
    assert str(tmp_path) not in json.dumps(row), row
    assert "/home/" not in row["message"], row["message"]
