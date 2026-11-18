"""The deny-list's absent state: a note, not a warn row (issue #194).

A tree with no deny-list configured is the ordinary state of a fresh attach, so
the default run says it in one `note:` line and reports no row for that half of
the scan. The row stays for the states that mean somebody meant to use a list and
cannot -- ``corrupt`` and ``present but empty``, pinned in
``tests/test_census_hygiene.py`` -- and ``--strict`` keeps the absent one's row
too, so the gate a team opts into is not weakened by the note.

Split from ``tests/test_census_hygiene.py`` along the seam its 500-line cap chose;
the builders are in ``tests/census_fixtures.py``, the runners in
``tests/census_run.py`` and the deny-list planting in ``tests/census_denylist.py``.
"""

from __future__ import annotations

import json

from _harness import _commit_file, _init_repo
from census_fixtures import _ndjson_rows, _valid_record
from census_run import _run_census


class TestAbsentDenylist:
    def test_absent_denylist_is_a_note_and_not_a_warn_row(self, tmp_path, monkeypatch):
        """No deny-list configured at all is said in a note, not warned on every run.

        The default run reports no hygiene row for the deny-list half, counts no
        warning for it, and prints one note saying the check is off, that names
        and hostnames went unchecked, and how to switch it on. A row here made
        every unconfigured tree carry a warning, and teams answered it by pointing
        NONI_SCRUB_DENYLIST at another repository's list, which turned the row into
        a lie. ``corrupt`` and ``present but empty`` keep their rows below.
        """
        import census_hygiene
        from census_denylist import _with_no_denylist

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                     json.dumps(_valid_record(), indent=2))
        _with_no_denylist(monkeypatch, tmp_path)
        rc, out, err = _run_census(repo, json_out=True)
        assert rc == 0, f"no deny-list is still not a failure, got {rc}\n{err}"
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
        assert rows == [], f"an absent deny-list must not emit a row: {rows}"
        summary = [r for r in _ndjson_rows(out) if r.get("kind") == "summary"][0]
        assert "hygiene" not in summary["counts"], f"summary counted a row: {summary}"
        assert census_hygiene.HYGIENE_DENYLIST_NOTE in summary["not_evaluated"], summary
        note = summary["not_evaluated"][[i for i, n in enumerate(summary["not_evaluated"])
                                         if n == census_hygiene.HYGIENE_DENYLIST_NOTE][0]]
        # Same sentence in both modes, and no path in it: the census never prints
        # a machine-local absolute path.
        _rc, human, _err = _run_census(repo)
        assert f"note: {census_hygiene.HYGIENE_DENYLIST_NOTE}" in human, human
        for route in ("NONI_SCRUB_DENYLIST", ".noni-scrub-denylist"):
            assert route in note, note
            assert route in human, human
        assert str(repo) not in out and str(repo) not in human, (
            f"the note leaked a host path: {out!r}{human!r}")

    def test_absent_denylist_under_strict_keeps_the_row_and_the_exit(
            self, tmp_path, monkeypatch):
        """The strict gate is not weakened by the note: the absent state still fails.

        Same class and same code as the configured-list path, asserted at the
        level a caller runs it (``--only hygiene --strict`` over a tree with no
        deny-list at all), and no note: a run that failed the check has said it.
        """
        from census_denylist import _with_no_denylist

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                     json.dumps(_valid_record(), indent=2))
        _with_no_denylist(monkeypatch, tmp_path)
        rc, out, err = _run_census(repo, "--only", "hygiene", "--strict")
        assert rc == 50, f"--strict must still fail an absent deny-list, got {rc}\n{out}{err}"
        assert "deny-list" in out, f"the strict run must carry the row: {out}"
        assert "note:" not in out, f"a failing run must not soften into a note: {out}"
        _rc, json_out, _err = _run_census(repo, "--only", "hygiene", "--strict",
                                         json_out=True)
        rows = [r for r in _ndjson_rows(json_out) if r.get("kind") == "finding"]
        assert [r["subject"] for r in rows] == ["deny-list"], rows
        assert rows[0]["check"] == "hygiene" and rows[0]["code"] == 50, rows
        assert "(absent)" in rows[0]["message"], rows[0]
        assert "not a hygiene-clean guarantee" in rows[0]["message"], rows[0]

    def test_a_note_is_not_emitted_for_a_class_the_run_did_not_run(
            self, tmp_path, monkeypatch):
        """A run that took the hygiene class away prints no deny-list note.

        The ordering-closed note is suppressed the same way for ``--skip``: a
        class the operator asked away is not an unchecked one. Without the
        filter the same tree owes the note, which is the half that keeps this
        from passing by never printing anything at all.
        """
        import census_hygiene
        from census_denylist import _with_no_denylist

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                     json.dumps(_valid_record(), indent=2))
        _with_no_denylist(monkeypatch, tmp_path)
        for argv in (("--skip", "hygiene"), ("--only", "ledger-empty")):
            _rc, out, err = _run_census(repo, *argv)
            assert census_hygiene.HYGIENE_DENYLIST_NOTE not in out, (
                f"{argv} took the class out of the run: {out}{err}")
        _rc, out, _err = _run_census(repo)
        assert census_hygiene.HYGIENE_DENYLIST_NOTE in out, (
            f"the unfiltered run owes the note: {out}")
