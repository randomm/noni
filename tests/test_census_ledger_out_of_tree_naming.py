"""Every ledger-group row names an out-of-tree ``--ledger`` by its last segment.

The census promises never to print a machine-local path, and a ``--ledger``
override is the one input that can hand it one: when the ledger does not sit
under ``--repo`` the census's own rooting helper cannot root it and hands the
path back verbatim, so each row that names the ledger has to ask for the
census's identifier (``census_ledger.ledger_name``) rather than interpolate the
path. ``tests/test_census_ledger_name.py`` pins the rule itself and
``tests/test_census_ledger_probe_rows.py`` pins it for the listing-fault row;
this file pins it for the rest of the group's rows, one row type per case,
because the rule is per-row and a leak in any one of them breaks the promise
the other rows keep. What this file does *not* cover is the deleted-vs-cannot-tell
pair of a faulted listing: that is the deletion contract, not the naming one, and
it lives in ``tests/test_census_ledger_deleted_directory.py``.

The override reaches these rows through ``--repo`` and ``--ledger`` only. The
host directory is a path under ``/tmp`` built at runtime, so the assertion is
about the row and not about a literal this file happens to hold.
"""

from __future__ import annotations

import json
from pathlib import Path

from _harness import _commit_file, _init_repo
from census_ledger_fixtures import _rows, _valid_record
from census_run import _run_census


def _code(repo: Path, *args: str) -> int:
    """The exit code of a pinned-time run of ``repo``.

    Local to this file rather than imported from the probe fixtures: the ledger
    rows here are asserted on their exit code as well as their text, and the
    runner here is the one that takes ``--skip hygiene`` as an argument like the
    rows above.
    """
    _rc, _out, _err = _run_census(repo, *args)
    return _rc


def _out_of_tree(tmp_path: Path) -> tuple[Path, Path]:
    """A repo and a ledger directory that does not live under it.

    The ledger is a sibling of the repo rather than a child, which is exactly the
    case ``_rel_to_root`` cannot answer: it holds records, so the group's record,
    chain and deletion passes all have something to say about it.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "README.md", "# repo\n")
    ledger = tmp_path / "ledger-home" / "decisions"
    ledger.mkdir(parents=True)
    return repo, ledger


def _assert_no_host_path(rows: list[dict], needles: tuple[str, ...]) -> None:
    """No row of the run carries any part of the host directory the ledger lives in.

    Checked over the whole row rather than one field: the identifier is rendered
    in ``subject``, ``artifact`` and the message, and the leak this file exists
    for was in a field no earlier test looked at.
    """
    for row in rows:
        rendered = json.dumps(row)
        for needle in needles:
            assert needle not in rendered, (
                f"host path part {needle!r} leaked into a "
                f"{row['check']} row: {rendered}")


def test_the_chain_rows_name_an_out_of_tree_ledger_by_its_last_segment(tmp_path):
    """``ledger-chain`` names the ledger in ``artifact`` for every row of the
    chain class (duplicate, dangling, orphan, cycle, zero-live, multi-live).

    A broken chain is planted by two records rather than asserted for one shape:
    a superseded record nobody supersedes and a dangling ``supersedes`` are two
    rows from two different reporters in the same pass, and the whole class is
    checked rather than the one that happened to fire.
    """
    repo, ledger = _out_of_tree(tmp_path)
    (ledger / "2026-10-01-alpha.json").write_text(
        json.dumps(_valid_record("2026-10-01-alpha", "superseded")), encoding="utf-8")
    (ledger / "2026-10-02-beta.json").write_text(
        json.dumps(_valid_record("2026-10-02-beta", "decided", "no-such-record")),
        encoding="utf-8")

    found = _rows(repo, "--skip", "hygiene", "--ledger", str(ledger))
    chain = [r for r in found if r["check"] == "ledger-chain"]
    assert chain, f"expected the chain class to report: {found}"
    assert {r["artifact"] for r in chain} == {"decisions"}, (
        f"every chain row names the ledger by its last segment: {chain}")
    _assert_no_host_path(found, (str(tmp_path), "ledger-home"))


def test_the_chain_rows_keep_a_root_relative_ledger_in_tree(tmp_path):
    """The other arm of the identifier rule, so the test above cannot be
    satisfied by a reporter that shortens every path.

    For the default in-tree ledger the chain rows name the directory
    root-relative: that path is the census's own and the operator acts on it, so
    a rule that reduced it to ``decisions`` would destroy the thing the row is
    telling them to look at.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "README.md", "# repo\n")
    ledger = repo / "noni" / "decisions"
    ledger.mkdir(parents=True)
    (ledger / "2026-10-01-alpha.json").write_text(
        json.dumps(_valid_record("2026-10-01-alpha", "superseded")), encoding="utf-8")
    (ledger / "2026-10-02-beta.json").write_text(
        json.dumps(_valid_record("2026-10-02-beta", "decided", "no-such-record")),
        encoding="utf-8")

    chain = [r for r in _rows(repo, "--skip", "hygiene") if r["check"] == "ledger-chain"]
    assert chain, "expected the chain class to report"
    assert {r["artifact"] for r in chain} == {"noni/decisions"}, chain


def test_the_ledger_empty_rows_name_an_out_of_tree_ledger_by_its_last_segment(tmp_path):
    """``ledger-empty`` puts the ledger in ``subject``, ``artifact`` and its own
    prose, so all three are checked, for an absolute and a relative override alike.

    The two forms are different leaks: an absolute override hands the row a host
    directory, and a relative one hands it a walk out of the tree (``../x/y``),
    whose leading segments are somebody else's directories. Both are paths the
    caller spelled, so both reduce to the last segment; an in-tree override keeps
    the path the census wrote.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "README.md", "# repo\n")

    absolute = tmp_path / "ledger-home" / "decisions"
    absolute.mkdir(parents=True)
    found = _rows(repo, "--skip", "hygiene", "--ledger", str(absolute))
    empty = [r for r in found if r["check"] == "ledger-empty"]
    assert len(empty) == 1, f"expected one ledger-empty row: {found}"
    assert empty[0]["subject"] == "decisions", empty[0]
    assert empty[0]["artifact"] == "decisions", empty[0]
    _assert_no_host_path(found, (str(tmp_path), "ledger-home"))

    # The relative override, run with the process standing beside the repo so
    # the path really does walk out of the audited tree.
    home = repo.parent / "relative-home"
    (home / "decisions").mkdir(parents=True)
    import os

    previous = os.getcwd()
    os.chdir(repo.parent)
    try:
        found = _rows(repo, "--skip", "hygiene", "--ledger", "../relative-home/decisions")
    finally:
        os.chdir(previous)
    empty = [r for r in found if r["check"] == "ledger-empty"]
    assert len(empty) == 1, f"expected one ledger-empty row: {found}"
    assert empty[0]["subject"] == "decisions", empty[0]
    assert empty[0]["artifact"] == "decisions", empty[0]
    _assert_no_host_path(found, (str(repo.parent), "relative-home"))


def test_the_ledger_empty_row_keeps_the_root_relative_path_it_used_to_carry(tmp_path):
    """The in-tree counterpart: a default ledger is named root-relative in
    ``subject`` and ``artifact``, exactly as before.

    Those two fields are what the operator joins on and what the row's ``fix``
    tells them to create, so a rule that shortened them to ``decisions`` would
    destroy the thing the row is for. The prose of this particular state words
    the finding as "no record to census" and has never carried the path, so it
    is not what the naming rule is about here.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/README.md", "noni lives here\n")

    empty = [r for r in _rows(repo, "--skip", "hygiene") if r["check"] == "ledger-empty"]
    assert len(empty) == 1, empty
    row = empty[0]
    assert row["subject"] == "noni/decisions", row
    assert row["artifact"] == "noni/decisions", row
    assert "noni/" in row["message"], row


def test_the_out_of_tree_deletion_cannot_tell_names_the_ledger_by_its_last_segment(
    tmp_path,
):
    """The one row of the group whose reason quotes the ledger path verbatim.

    The append-only question cannot be put to git for an override outside the
    audited tree, and the cannot-tell that says so names the path it could not
    root — which for an out-of-tree override is the host directory. The row is
    the group's only word about the override, so the naming rule applies to its
    prose as well as to ``subject`` and ``artifact``.

    Both spellings are driven because they leak differently (an absolute one
    puts ``/…`` in the sentence, a relative one a ``../`` walk), and the run
    stays a warn either way: an out-of-tree override is a normal configuration,
    not a violation.
    """
    repo, ledger = _out_of_tree(tmp_path)

    found = _rows(repo, "--skip", "hygiene", "--ledger", str(ledger))
    row = _deletion_cannot_tell(found)
    assert "the ledger path (decisions)" in row["message"], row["message"]
    _assert_no_host_path(found, (str(tmp_path), "ledger-home"))
    assert _code(repo, "--skip", "hygiene", "--ledger", str(ledger)) == 0

    home = repo.parent / "relative-home"
    (home / "decisions").mkdir(parents=True)
    import os

    previous = os.getcwd()
    os.chdir(repo.parent)
    try:
        found = _rows(repo, "--skip", "hygiene", "--ledger", "../relative-home/decisions")
    finally:
        os.chdir(previous)
    row = _deletion_cannot_tell(found)
    assert "the ledger path (decisions)" in row["message"], row["message"]
    _assert_no_host_path(found, (str(repo.parent), "relative-home"))


def _deletion_cannot_tell(rows: list[dict]) -> dict:
    """The group's cannot-tell row for an override outside the audited tree."""
    matches = [r for r in rows
               if r["check"] == "ledger-edited" and r["subject"] == "cannot-tell"
               and "outside the audited git tree" in r["message"]]
    assert len(matches) == 1, f"expected one out-of-tree cannot-tell row: {rows}"
    return matches[0]


# The ledger-group rows that name the ledger, as the census skill documents them.
# One entry per row type: the class word as the census spells it, and the field
# the ledger's name goes in. A row type added to the group without an entry here
# is a row type whose naming nobody pinned, and a documented rule that no test
# checks is a rule the next refactor drops (the pre-fix state of this file's
# subject: the skill stated the rule for one row and the code broke it for four).
_DOCUMENTED_LEDGER_ROWS: tuple[tuple[str, str], ...] = (
    ("ledger-edited", "cannot-tell of a faulted listing"),
    ("ledger-empty", "the no-ledger row"),
    ("ledger-record", "a malformed record"),
    ("ledger-chain", "a broken supersede chain"),
    ("ledger-edited", "cannot-tell of an out-of-tree override"),
)


def test_the_skill_states_the_last_segment_rule_once_for_every_ledger_row():
    """The census skill states the last-segment naming rule for the group, in one
    place, and covers every ledger-group row that names the ledger.

    The rule used to be written inside the unreadable-ledger bullet, which is why
    four of the five rows leaked while the documentation read as though the rule
    were group-wide: a reader who met a leaking row found no sentence that said
    it should not. So the test asks for one section that names the rule and for
    each row type of the group to appear in it, rather than for any particular
    sentence to be repeated five times.
    """
    from _harness import REPO

    text = (REPO / "skills" / "census" / "SKILL.md").read_text(encoding="utf-8")
    heading = "### Every ledger row names the ledger the same way"
    assert text.count(heading) == 1, (
        f"the last-segment rule belongs in exactly one section of the skill: "
        f"{text.count(heading)} copies of {heading!r}")
    section = text.split(heading, 1)[1].split("\n## ", 1)[0]
    lowered = section.lower()
    assert "last segment" in lowered, (
        f"the naming section does not state the last-segment rule: {section[:200]!r}")
    assert "root-relative" in lowered, (
        "the section must state which form the rule keeps for an in-tree ledger")
    assert "machine-local" in lowered, (
        "the section must say why the rule exists: the report prints no host path")
    for check, _what in _DOCUMENTED_LEDGER_ROWS:
        assert f"`{check}`" in section, (
            f"the naming section does not cover the {check} row the group adds")
    # The row that names a record rather than the directory is deliberately not
    # in the table; the skill says so, so the omission is a decision and not a
    # gap a reader has to discover by being surprised.
    assert "deleted" in lowered, (
        "the section should say which ledger row the rule does not reach, and why")


def test_a_record_row_of_an_out_of_tree_ledger_names_no_host_directory(tmp_path):
    """The record pass roots its artifact through the census's one rooting helper,
    so the path a row carries is composed here rather than quoted from the run.

    A malformed record's row keys ``subject`` on the name and puts the record
    path in ``artifact``, and the path it composes is ``<ledger>/<name>`` — for
    an out-of-tree override, a host directory plus the record's name. The naming
    rule is a property of the whole group, so the one row that names a file
    inside the ledger gets the same identifier in front of the name; which form
    the rooting happens to answer with is not something the row may depend on.
    """
    repo, ledger = _out_of_tree(tmp_path)
    (ledger / "2026-10-01-bad.json").write_text("{not json", encoding="utf-8")

    found = _rows(repo, "--skip", "hygiene", "--ledger", str(ledger))
    records = [r for r in found if r["check"] == "ledger-record"]
    assert len(records) == 1, f"expected the malformed record to report: {found}"
    assert records[0]["subject"] == "2026-10-01-bad.json", records[0]
    assert records[0]["artifact"] == "decisions/2026-10-01-bad.json", records[0]
    _assert_no_host_path(found, (str(tmp_path), "ledger-home"))


def test_a_record_row_of_the_default_ledger_keeps_its_root_relative_path(tmp_path):
    """The in-tree half of the row above: a malformed record of the default ledger
    is still ``noni/decisions/<name>.json``, which is the path the operator opens.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/README.md", "noni lives here\n")
    ledger = repo / "noni" / "decisions"
    ledger.mkdir()
    (ledger / "2026-10-01-bad.json").write_text("{not json", encoding="utf-8")

    records = [r for r in _rows(repo, "--skip", "hygiene") if r["check"] == "ledger-record"]
    assert len(records) == 1, records
    assert records[0]["artifact"] == "noni/decisions/2026-10-01-bad.json", records[0]
