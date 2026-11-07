"""The committed allowlist as the census's hygiene class sees it.

The scan's own exemption rules -- what an entry exempts, what it may never exempt, how a
file is classified -- are pinned in ``tests/test_public_safety_allowlist.py`` and the gate's
exit codes with them. What lives here is the census contract over the same states: that an
exemption produces no row, that a finding the allowlist itself earns produces a row a caller
can act on, and that an allowlist the scan could not read produces the not-run row rather
than a clean. Split out of ``tests/test_census_hygiene.py`` for the 500-line cap, which has
no override; the builders are shared with it (``tests/census_fixtures.py``,
``tests/census_run.py``, ``tests/census_denylist.py``, ``tests/census_allowlist.py``).
"""

from __future__ import annotations

import json

from _harness import _commit_file, _init_repo, _secret_violation
from census_allowlist import _allowlist_line, _with_allowlist, _with_committed_allowlist
from census_denylist import _clear_denylist, _with_denylist
from census_fixtures import _ndjson_rows, _valid_record
from census_hygiene_target import _hygiene_target
from census_run import _run_census

# The label and the token as file content, assembled from the product's own tables: a
# test file that typed a token literal would need an allowlist entry to pass the check
# it is testing.
_SECRET_LINE = f"token {_secret_violation()}"
_TOKEN_FIXTURE = _SECRET_LINE + "\n"
TOKEN_LABEL = "GitHub classic token"

class TestCommittedAllowlist:
    """The committed allowlist as the census sees it: exempted, stale, or unusable.

    The scan's own exemption rules are pinned in ``tests/test_public_safety_allowlist.py``.
    What lives here is the census contract: that an exemption produces no row, that a
    finding the allowlist itself earns produces a row a caller can act on, and that an
    allowlist the scan could not read produces the not-run row rather than a clean.
    """

    def _repo(self, tmp_path, name="repo"):
        """A tree with a valid record, so the only hygiene rows are the scan's."""
        repo = _init_repo(tmp_path / name)
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        return repo

    def test_a_stale_entry_is_reported_as_a_row(self, tmp_path):
        """An entry that matches nothing is a finding the census must print.

        The dangerous direction is the quiet one: a fixture renamed away from its
        exemption leaves the entry standing, and the next file to land on that path
        inherits a review nobody re-did. A row is the only way the census can say so --
        there is no exit code for a warning, and silence reads as clean.
        """
        repo = self._repo(tmp_path)
        _with_committed_allowlist(repo, _allowlist_line("fixtures/gone.txt", TOKEN_LABEL))
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"hygiene is warn: expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, f"expected exactly one stale-entry row: {rows}"
            row = rows[0]
            assert "matches nothing" in row["message"], row
            assert "fixtures/gone.txt" in row["message"], (
                f"a stale row must name the entry it is about: {row}")
            # The row is attributed to the allowlist file, not to a line of the tree:
            # the finding is about the exemption, and a caller has to open that file.
            import public_safety

            assert row["artifact"] == public_safety.ALLOWLIST_FILENAME, row
        finally:
            _clear_denylist()

    def test_a_live_entry_produces_no_row(self, tmp_path):
        """The control, and the point of the mechanism: the exempted fixture is silent.

        Without this the test above would pass on a scan that exempted nothing and
        reported every entry as stale, and the feature would ship broken.
        """
        repo = self._repo(tmp_path, "live")
        _commit_file(repo, "fixtures/token.txt", _TOKEN_FIXTURE)
        _with_committed_allowlist(repo, _allowlist_line("fixtures/token.txt", TOKEN_LABEL))
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert rows == [], f"an exempted fixture must produce no row: {rows}"
        finally:
            _clear_denylist()

    def test_the_same_fixture_without_the_entry_still_reports(self, tmp_path):
        """The exemption is what silenced the row above, not the fixture being inert.

        Identical tree, no allowlist: this is the assertion that makes the preceding
        test say something. A fixture the pattern never matched would make both tests
        pass and the feature meaningless.
        """
        repo = self._repo(tmp_path, "unexempted")
        _commit_file(repo, "fixtures/token.txt", _TOKEN_FIXTURE)
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, f"expected the planted violation: {rows}"
            assert rows[0]["artifact"] == "fixtures/token.txt", rows[0]
            assert TOKEN_LABEL in rows[0]["message"], rows[0]
        finally:
            _clear_denylist()

    def test_a_malformed_allowlist_is_the_not_run_row(self, tmp_path):
        """A file the scan refused is the gate-could-not-run state, told as a row.

        The census has no exit 3 to give, so the not-run row is this entry point's
        answer -- the same verdict the CI gate tells with its code. The wording matters:
        "not a hygiene-clean guarantee" is the phrase a caller greps for, and a row that
        said only "malformed allowlist" would not join the family of rows that all mean
        *this run did not check what you think it checked*.
        """
        repo = self._repo(tmp_path, "malformed")
        _with_committed_allowlist(repo, "this line is not an entry")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0 (warn) without --strict, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, f"expected exactly one not-run row: {rows}"
            row = rows[0]
            assert row["subject"] == "hygiene scan", (
                f"a refused allowlist is the whole scan, not one file: {row}")
            assert "did not run" in row["message"], row
            assert "allowlist" in row["message"], (
                f"the row must name the file at fault: {row}")
            assert "hygiene-clean guarantee" in row["message"], row
            # The artifact stays the scan's, as every "hygiene scan" row does -- a caller
            # that filtered on the violating file would never see this row. The file to
            # fix is named in the message, which is what a reader of a whole-scan row acts
            # on.
            import census_hygiene
            import public_safety

            assert row["artifact"] == census_hygiene.HYGIENE_SCAN_ARTIFACT, row
            assert public_safety.ALLOWLIST_FILENAME in row["message"], row
        finally:
            _clear_denylist()

    def test_a_malformed_allowlist_prints_nothing_on_stderr(self, tmp_path):
        """The scan's own refusal notice stays off the census's stderr.

        ``load_allowlist`` warns on stderr, quoting the file it tried to use -- which on
        the env route is an absolute host path. The census reports that state as a row,
        so the banner is both a duplicate and a leak: ``census --json`` is documented to
        leave stderr for this run's own usage and tool faults (issue #77, AC3), and the
        row is the machine-readable half.
        """
        repo = self._repo(tmp_path, "stderr")
        _with_committed_allowlist(repo, "this line is not an entry")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0, got {rc}\n{err}"
            assert "allowlist" not in err, (
                f"the scan's refusal banner reached the census's stderr: {err!r}")
            assert out.strip(), "the run must still report the row on stdout"
        finally:
            _clear_denylist()

    def test_a_malformed_allowlist_outranks_the_only_filter(self, tmp_path):
        """``--only`` must not be able to hide the not-run row.

        The filtered runs that decide whether a tree is publishable are the ones that
        must still see it: a filter that could drop the state of the scan would let
        ``--only sessions`` report an empty hygiene class as a clean one.
        """
        repo = self._repo(tmp_path, "filtered")
        _with_committed_allowlist(repo, "this line is not an entry")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, "--only", "hygiene", json_out=True)
            assert rc == 0, f"expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1 and "did not run" in rows[0]["message"], rows
        finally:
            _clear_denylist()

    def test_a_malformed_allowlist_lifts_the_exit_under_strict(self, tmp_path):
        """--strict turns the not-run row into its code, like any other warn row.

        The exit code is what CI acts on: the same state the gate answers with 3 must
        not be green under --strict here, or the two entry points would disagree about
        whether the tree is publishable.
        """
        repo = self._repo(tmp_path, "strict")
        _with_committed_allowlist(repo, "this line is not an entry")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, _out, err = _run_census(repo, "--only", "hygiene", "--strict")
            assert rc == 50, f"expected 50 under --strict, got {rc}\n{err}"
        finally:
            _clear_denylist()

    def test_an_unreadable_allowlist_is_also_the_not_run_row(self, tmp_path, monkeypatch):
        """Bytes that will not decode are the same verdict as a line refused.

        Asserted through the loader's seam because it is the census-side half of the
        rule: the census reads ``allowlist.status`` and must not care *why* the file
        gave no verdict. The scan's own classification of the two states is pinned in
        ``tests/test_public_safety_allowlist.py``.
        """
        public_safety = _hygiene_target()
        repo = self._repo(tmp_path, "unreadable")
        unreadable = tmp_path / "allowlist.bin"
        unreadable.write_bytes(b"\xff\xfe\x00\x01 not utf8")
        monkeypatch.setattr(public_safety, "_default_allowlist_file",
                            lambda repo: unreadable)
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, f"expected exactly one not-run row: {rows}"
            assert "did not run" in rows[0]["message"], rows[0]
            assert "unreadable" in rows[0]["message"], (
                f"the row must name the state it found: {rows[0]}")
        finally:
            _clear_denylist()

    def test_the_allowlist_path_never_appears_as_an_absolute_path(self, tmp_path,
                                                                   monkeypatch):
        """A row never prints a machine-local path, even for an env-named allowlist.

        The env route identifies a file outside the tree, so the loader's ``source`` is
        an absolute host path -- exactly what the public-repo hygiene rule forbids in any
        published row. The census falls back to the product's filename, and this test is
        what keeps that fallback from being "improved" away by a caller that finds the
        real path more informative.
        """
        allowlist = _with_allowlist(tmp_path, "this line is not an entry")
        repo = self._repo(tmp_path, "absolute")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, f"expected exactly one not-run row: {rows}"
            assert str(allowlist) not in out + err, (
                "a census row quoted the operator's absolute allowlist path")
            assert str(tmp_path) not in out + err, (
                "the row leaked the fixture directory, so the scrub was not what stopped it")

            assert allowlist.name in rows[0]["message"], (
                f"the row must name the file by its basename: {rows[0]}")
        finally:
            _clear_denylist()

    def test_the_allowlist_s_own_rows_split_like_a_violation(self, tmp_path):
        """The allowlist labels are in the table the census splits with.

        A label the census has never seen is reported verbatim, which breaks the
        documented ``subject`` = ``path:line`` contract and sends a caller hunting for a
        file called ".noni-scrub-allowlist:0: allowlist entry matches nothing (…)". The
        rows are shaped by the loader, so the shape has to be pinned against the real
        thing rather than a hand-written string.
        """
        repo = self._repo(tmp_path, "split")
        _with_committed_allowlist(repo, _allowlist_line("fixtures/gone.txt", TOKEN_LABEL))
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, rows
            import public_safety

            assert rows[0]["subject"] == f"{public_safety.ALLOWLIST_FILENAME}:0", rows[0]
        finally:
            _clear_denylist()

    def test_the_env_allowlist_is_cleared_between_runs(self, tmp_path):
        """No allowlist anywhere: the mechanism is opt-in and its absence is quiet.

        The counterpart to the rows above -- an attached project that never wrote a
        committed allowlist must see exactly what it saw before this feature existed,
        which is also the guarantee that shipping the mechanism cannot turn a previously
        clean tree into a reporting one.
        """
        repo = self._repo(tmp_path, "absent")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert rows == [], f"an absent allowlist must report nothing: {rows}"
        finally:
            _clear_denylist()
