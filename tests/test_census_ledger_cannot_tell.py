"""The cannot-tell row a recordless ledger owes when git cannot answer.

``_check_ledger`` (``src/noni/census_ledger_checks.py``) asks the git-backed
deletion check its append-only question and, when that check could not put the
question to git at all and the ledger reads as "empty", adds one cannot-tell row
beside the ``ledger-empty`` warn. "Empty" is the one state that can mean
"committed records were deleted", and the deletion check is the only signal for
that, so a run that got no answer from git must say so rather than leave the
operator with a dismissible warn (probe honesty, issue #33).

The state is reached two ways, and both are pinned here: a run whose ``Git`` view
could not read the history (the double of ``tests/census_probe_doubles.py``, put
on the census seam the run itself asks), and a tree with no git at all, where the
census builds no view in the first place. Both pair the default exit with the
``--strict`` escalation, because a cannot-tell that never escalates is a row
nobody has to act on.
"""

from __future__ import annotations

from _harness import _commit_file, _init_repo
from census_fixtures import _ndjson_rows
from census_probe_doubles import _UnreadableGit
from census_run import _run_census


def _assert_cannot_tell_beside_the_warn(repo):
    """The two rows, their codes and severities, then the escalation.

    Shared by both shapes of "git cannot answer": the pair of rows is the
    contract and it must not depend on how git was made unable to answer.
    """
    rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
    assert rc == 0, (
        f"the cannot-tell row is a warn: expected exit 0, got {rc}\n"
        f"stderr: {err}\n{out}"
    )
    rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
    assert [r["check"] for r in rows] == ["ledger-edited", "ledger-empty"], (
        f"expected the ledger-empty row plus the cannot-tell row: {rows}"
    )
    empty = [r for r in rows if r["check"] == "ledger-empty"][0]
    assert empty["severity"] == "warn" and empty["code"] == 42, empty
    assert "(empty)" in empty["message"], f"state word kept: {empty['message']}"
    row = [r for r in rows if r["check"] == "ledger-edited"][0]
    assert row["subject"] == "cannot-tell", row
    assert row["code"] == 12, f"stays in the ledger-edited class: {row}"
    assert row["severity"] == "warn", f"cannot-tell is a warn: {row}"
    assert "could not run" in row["message"], (
        f"the row must say the deletion check could not run: {row['message']}"
    )

    rc_strict, out_strict, err = _run_census(repo, "--strict", skip_hygiene=True)
    assert rc_strict == 12, (
        f"--strict escalates the cannot-tell to ledger-edited's code, got "
        f"{rc_strict}\nstderr: {err}\n{out_strict}"
    )


def test_recordless_ledger_whose_git_view_cannot_answer_says_the_check_could_not_run(
    tmp_path, monkeypatch
):
    """A recordless ``decisions/`` whose git history the census could not read
    must not read as a plain "empty" warn.

    The seam is the one the run asks: ``census_run._run`` builds the run's single
    ``Git`` view through ``census.Git``, so patching that name on the census
    module is how the history read is taken away without breaking the tree in
    some unrelated way. The fixture is a committed ``noni/decisions/.gitkeep`` —
    a tree whose probe genuinely answers "empty", so nothing here patches the
    probe's state: the cannot-tell row is the run's own addition.
    """
    import census

    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/.gitkeep", "")
    monkeypatch.setattr(census, "Git", lambda top: _UnreadableGit())
    _assert_cannot_tell_beside_the_warn(repo)


def test_recordless_ledger_in_a_plain_directory_reports_the_cannot_tell_too(tmp_path):
    """The same finding in a genuinely non-git directory: there is no history
    anywhere, so the deletion question is just as unanswered and the row must
    still appear.

    The other no-git trees of the empty class carry states the probe itself
    answers (absent, symlink, not a directory), not "empty" with a directory
    present, so this is the shape where the missing row would be invisible
    anywhere else. No seam here: ``_git_top`` answers None for a plain directory
    and the run builds no view at all.
    """
    plain = tmp_path / "plain"
    (plain / "noni" / "decisions").mkdir(parents=True)
    _assert_cannot_tell_beside_the_warn(plain)
