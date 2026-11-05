"""A committed ``noni/decisions/`` directory that no longer exists is still reported.

Whole-directory deletion, with and without a commit, and the cannot-tell rows when
git cannot answer for the history.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py`` and the runners in ``tests/census_run.py``.

The last two cases are a pair about one line of ``_check_ledger``: the early
return taken when the ledger's listing faulted, which skips every check below it
and so silences git's deletion answer as well as the group's own read. They build
the same tree twice, once with the listing faulted and once without, because
neither half means anything alone.
"""

from __future__ import annotations

import json
import shutil

from _harness import _commit_file, _fault_the_ledger_listing, _git, _init_repo
from census_fixtures import _ndjson_rows, _valid_record
from census_ledger_fixtures import _code, _rows
from census_run import _run_census


class TestLedgerWholeDirectoryDeletion:
    """A committed ``noni/decisions/`` directory that no longer exists is still
    a deletion: records are append-only, so the whole-directory case must reach
    exit 12 the way the loss of a single file already does.

    The distinction these cases hold is between git *answering* "history never
    held a record" and git being unable to answer at all: the first is the lone
    ledger-empty warn, the second the cannot-tell row. The fixtures wipe the
    directory with ``git rm -r`` rather than the file-deletion helper, which
    iterates a directory that has to exist to be iterated."""

    def test_exit_12_deleted_whole_directory_committed(self, tmp_path):
        """Records committed, then the whole ``noni/decisions/`` deleted and the
        deletion committed: one ledger-edited "deleted" row per record, exit 12,
        with the ledger-empty warn present alongside them."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "noni/decisions/2026-10-02-beta.json",
                      json.dumps(_valid_record("2026-10-02-beta"), indent=2))
        _git(repo, "rm", "-r", "-q", "noni/decisions")
        _git(repo, "commit", "-q", "-m", "delete the ledger directory")
        assert not (repo / "noni" / "decisions").exists()
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 12, f"expected exit 12, got {rc}\nstderr: {err}\n{out}"
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        deleted = [r for r in rows if r["check"] == "ledger-edited"]
        assert [r["subject"] for r in deleted] == [
            "2026-10-01-alpha.json", "2026-10-02-beta.json"], (
            f"one deleted row per committed record: {deleted}"
        )
        for row in deleted:
            assert "deleted" in row["message"], row["message"]
            assert row["severity"] == "fail" and row["code"] == 12, row
        assert [r["check"] for r in rows if r["check"] == "ledger-empty"] == ["ledger-empty"], (
            f"the gone directory is still the ledger-empty warn too: {rows}"
        )

    def test_exit_12_deleted_whole_directory_uncommitted(self, tmp_path):
        """The same wipe with the deletion left uncommitted: the working tree is
        not the source of the question, git history is, so the rows and the
        exit code match the committed case."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        shutil.rmtree(repo / "noni" / "decisions")
        assert not (repo / "noni" / "decisions").exists()
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 12, f"expected exit 12, got {rc}\nstderr: {err}\n{out}"
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        deleted = [r for r in rows if r["check"] == "ledger-edited"]
        assert [r["subject"] for r in deleted] == ["2026-10-01-alpha.json"], rows
        assert "deleted" in deleted[0]["message"], deleted[0]["message"]

    def test_record_history_that_never_existed_is_only_the_warn(self, tmp_path):
        """The counterpart the fix must not break: git answered, and history
        never held a record under the path. Whether ``noni/decisions/`` is an
        empty directory or gone entirely, that tree is exactly one
        ledger-empty warn and exit 0 -- cannot-tell is for the run that got no
        answer, not for the answer "there was never anything here"."""
        kept = _init_repo(tmp_path / "kept")
        _commit_file(kept, "noni/decisions/.gitkeep", "")
        _commit_file(kept, "noni/README.md", "noni lives here\n")
        rc, out, err = _run_census(kept, json_out=True, skip_hygiene=True)
        assert rc == 0, f"expected exit 0, got {rc}\nstderr: {err}\n{out}"
        assert [r["check"] for r in _ndjson_rows(out) if r.get("kind") == "finding"] == [
            "ledger-empty"], out

        # gone: a tree whose history DID answer, and answered "this directory
        # was never added" -- the commits hold only noni/README.md, so
        # `rev-parse` resolves and the deletion check puts its question, and
        # finds no addition under the prefix to report as deleted. An
        # uncommitted empty decisions/ on disk is the answer "there was never
        # anything here", which is the warn alone.
        gone = _init_repo(tmp_path / "gone")
        _commit_file(gone, "noni/README.md", "noni lives here\n")
        (gone / "noni" / "decisions").mkdir()
        rc, out, err = _run_census(gone, json_out=True, skip_hygiene=True)
        assert rc == 0, f"expected exit 0, got {rc}\nstderr: {err}\n{out}"
        checks = [r["check"] for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert checks == ["ledger-empty"], (
            f"an uncommitted empty directory that history never held is the "
            f"warn alone, no deleted row: {checks}"
        )

    def test_record_history_and_deleted_dir_with_no_git_answer_says_cannot_tell(
        self, tmp_path
    ):
        """When git cannot answer, the cannot-tell row applies unchanged: a
        whole-directory wipe on a tree whose history the census could not read
        must not read as the honest "nothing was ever deleted" verdict.

        The tree is built the way the criterion describes it -- records
        committed, then the whole ``noni/decisions/`` directory removed -- and
        git is made unable to answer by taking the history away from the
        reading tool (the ``.git`` directory is deleted after the commits, so
        ``rev-parse`` fails for real). Nothing patches the probe's state: the
        probe answers "empty" for a tree that genuinely holds no record, and
        the cannot-tell row is what the run owes the operator on top of the
        warn. Patching the probe here would only ever prove the reporter.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "noni/decisions/2026-10-02-beta.json",
                      json.dumps(_valid_record("2026-10-02-beta"), indent=2))
        shutil.rmtree(repo / "noni" / "decisions")
        assert not (repo / "noni" / "decisions").exists()
        # git made unable to answer, by the tree rather than by a stub: no
        # history left for `rev-parse` to resolve.
        shutil.rmtree(repo / ".git")
        rc, out, err = _run_census(repo, json_out=True, skip_hygiene=True)
        assert rc == 0, f"cannot-tell is a warn: expected exit 0, got {rc}\n{err}"
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert sorted(r["check"] for r in rows) == ["ledger-edited", "ledger-empty"], rows
        empty = [r for r in rows if r["check"] == "ledger-empty"][0]
        assert empty["severity"] == "warn" and empty["code"] == 42, empty
        assert "(empty)" in empty["message"], empty["message"]
        row = [r for r in rows if r["check"] == "ledger-edited"][0]
        assert row["subject"] == "cannot-tell", row
        assert row["severity"] == "warn" and row["code"] == 12, row
        assert "could not run" in row["message"], row["message"]
        rc_strict, _out, err = _run_census(repo, "--strict", skip_hygiene=True)
        assert rc_strict == 12, (
            f"--strict escalates the cannot-tell to ledger-edited's code, got "
            f"{rc_strict}\nstderr: {err}"
        )

    def test_deleted_dir_with_no_git_answer_says_cannot_tell_under_a_ledger_filter(
        self, tmp_path
    ):
        """The same verdict through a filter that named only the ledger classes.

        The cannot-tell row of a ledger the deletion check could not put to git
        is not whole-artifact (``_append_cannot_tell`` composes it), so it is
        kept only because the filter named its class. A run filtered to the
        ledger classes must still report it; that is the contract SKILL.md
        states for the whole-directory case, and this pins it for the filter
        an operator is most likely to use when the ledger went missing.
        """
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        shutil.rmtree(repo / "noni" / "decisions")
        shutil.rmtree(repo / ".git")
        rc, out, err = _run_census(repo, "--only", "ledger-edited",
                                   "--only", "ledger-empty", "--strict",
                                   json_out=True, skip_hygiene=True)
        rows = [r for r in _ndjson_rows(out) if r.get("kind") == "finding"]
        assert sorted(r["check"] for r in rows) == ["ledger-edited", "ledger-empty"], rows
        assert rc == 12, f"expected 12, got {rc}\n{err}\n{out}"


def _records_deleted_but_directory_kept(tmp_path):
    """A repo whose history holds two records and whose working tree holds neither.

    ``noni/decisions/`` is emptied with ``git rm`` of the records alone, so the
    directory itself stays on disk and stays listable: a listing fault can only
    be planted on a directory that exists, and the deletion row needs history to
    have held the records. It is also the shape the pair below needs -- a tree
    whose history held no record would owe no deletion row whether or not the
    listing faulted, and the pair would prove nothing.
    """
    repo = _init_repo(tmp_path / "repo")
    _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                 json.dumps(_valid_record("2026-10-01-alpha"), indent=2))
    _commit_file(repo, "noni/decisions/2026-10-02-beta.json",
                 json.dumps(_valid_record("2026-10-02-beta"), indent=2))
    _commit_file(repo, "noni/decisions/KEEP.txt", "keeps the directory on disk\n")
    _git(repo, "rm", "-q", "noni/decisions/2026-10-01-alpha.json",
         "noni/decisions/2026-10-02-beta.json")
    _git(repo, "commit", "-q", "-m", "delete the records, keep the directory")
    assert (repo / "noni" / "decisions").is_dir()
    return repo


def test_a_committed_deletion_behind_a_faulted_listing_says_cannot_tell(
    tmp_path, monkeypatch
):
    """One half of the suppression: a faulted listing is the group's whole answer.

    ``_check_ledger`` returns as soon as the probe reports a faulted listing, and
    every check below that return is skipped -- including the git-backed deletion
    check, which is the one check of the group that does not need the listing at
    all. So a committed deletion whose directory is still on disk, in a tree git
    can answer for perfectly well, is reported only by the cannot-tell row, at the
    warn severity of a read that failed, and never as the clean verdict of a run
    that found no deletion. Exit 0 by default, the class's 12 under --strict.
    """
    repo = _records_deleted_but_directory_kept(tmp_path)

    _fault_the_ledger_listing(monkeypatch, repo / "noni" / "decisions")
    found = _rows(repo, "--skip", "hygiene")
    assert [r["check"] for r in found] == ["ledger-edited"], (
        f"a faulted listing is the group's only answer: {found}")
    row = found[0]
    assert row["subject"] == "noni/decisions", row
    assert "could not be listed" in row["message"], row["message"]
    assert row["severity"] == "warn" and row["code"] == 12, row
    # git could answer here -- history does hold the two records -- and the run
    # still says it cannot tell, because the row that would have named them was
    # never reached.
    assert "cannot-tell" in row["message"], row["message"]
    assert _code(repo, "--skip", "hygiene") == 0
    assert _code(repo, "--skip", "hygiene", "--strict") == 12


def test_the_same_tree_without_the_fault_reports_the_deletions_it_was_owed(tmp_path):
    """The other half: same tree, no fault planted, and git's answer comes through.

    One ``deleted`` row per committed record at exit 12, plus the ``ledger-empty``
    warn the recordless directory earns. Without this half the faulted run above
    proves nothing: it would read identically on a tree whose history never held a
    record, and a fault that silently swallowed a whole fail class would look like
    a clean run rather than a suppressed one.
    """
    repo = _records_deleted_but_directory_kept(tmp_path)

    found = _rows(repo, "--skip", "hygiene")
    deleted = [r for r in found if r["check"] == "ledger-edited"]
    assert [r["subject"] for r in deleted] == [
        "2026-10-01-alpha.json", "2026-10-02-beta.json"], (
        f"one deleted row per committed record: {deleted}")
    for row in deleted:
        assert "deleted" in row["message"], row["message"]
        assert row["severity"] == "fail" and row["code"] == 12, row
    assert [r["check"] for r in found if r["check"] == "ledger-empty"] == ["ledger-empty"], (
        f"the recordless directory is the ledger-empty warn too: {found}")
    assert _code(repo, "--skip", "hygiene") == 12
