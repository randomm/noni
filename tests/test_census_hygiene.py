"""The hygiene class: the in-process public_safety scan over the census's own tree.

Planted violations, the deny-list's active and inactive states, a scan that could not
run, and the four machine-distinguishable row states that tell a caller which half of
the scan a row is about.

Split out of ``tests/test_census_unified.py``; the builders are in
``tests/census_fixtures.py``, the runners in ``tests/census_run.py`` and the
deny-list planting in ``tests/census_denylist.py``.
"""

from __future__ import annotations

import json
import os

from _harness import _commit_file, _home_path_violation, _init_repo, _secret_violation
from census_denylist import _clear_denylist, _with_denylist
from census_fixtures import _ndjson_rows, _valid_record
from census_hygiene_child import BOUND_SECONDS, fifo_tree_census_run, tree_dir
from census_hygiene_target import _hygiene_target
from census_run import _run_census

_HOME_PATH = _home_path_violation()

_SECRET = _secret_violation()

class TestHygiene:
    """The hygiene class (warn 50): the in-process public_safety scan over the
    census's own git tree, which always reports — a clean tree included."""

    def test_planted_violation_is_reported(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "note.md", "token " + _SECRET + "\n")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"hygiene is warn: expected 0 without --strict, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, f"expected one hygiene row for the violation: {rows}"
            row = rows[0]
            assert row["code"] == 50
            assert row["severity"] == "warn"
            assert "note.md" in row["subject"], f"row must name the file: {row}"
            assert "note.md" in row["artifact"]
            assert "public hygiene" in row["message"]
            assert row["fix"]

            rc_strict, _o, err = _run_census(repo, "--only", "hygiene", "--strict")
            assert rc_strict == 50, f"expected 50 under --strict, got {rc_strict}\n{err}"
        finally:
            _clear_denylist()

    def test_planted_home_path_is_reported(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "note.md", _HOME_PATH + "\n")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1 and "note.md" in rows[0]["subject"], f"rows: {rows}"
        finally:
            _clear_denylist()

    def test_split_violation_is_exact_not_a_colon_count(self, tmp_path):
        """The parse is exact against public_safety's own label set, not a
        colon-count heuristic: an ambiguous path whose tail would otherwise
        look like a valid "<digits>: <label>" split is refused rather than
        guessed (probe honesty: a verbatim row beats a garbled one).

        "a:1: b" is the trap — dropping the last colon-segment would make "a"
        look like a path with line "1" and label "b". "b" is not a label
        public_safety can emit, so there is no legal split."""
        import census

        # Sanity: the label set is read from public_safety, not duplicated.
        labels = census._hygiene_labels(_hygiene_target())
        assert "GitHub classic token" in labels
        assert "deny-list entry" in labels, "the deny-list label is not in BUILTIN_PATTERNS"

        # Legal shapes, including colons in the path.
        assert census._split_violation("x:y/p.txt:1: GitHub classic token",
                                       labels) == ("x:y/p.txt", 1, "GitHub classic token")
        assert census._split_violation("a:b/c:d.txt:42: deny-list entry",
                                       labels) == ("a:b/c:d.txt", 42, "deny-list entry")
        assert census._split_violation(
            "n.md:3: machine-local absolute home path (/home/<known identity>)",
            labels) == ("n.md", 3, "machine-local absolute home path (/home/<known identity>)")

        # Illegal shapes: refused, so the caller reports them verbatim.
        for bad in ("a:1: b",                      # label "b" is not a real label
                    "n.md:7: not a real label",     # unknown label
                    "nocolons here",                # no structure at all
                    "n.md:xx: private key block",   # non-numeric line
                    ":1: private key block"):       # empty path
            assert census._split_violation(bad, labels) is None, (
                f"must refuse an illegal violation shape: {bad!r}"
            )

    def test_split_violation_tries_every_label_before_giving_up(self):
        """A label whose suffix matches is not the end of the search: when its
        head does not parse, the walk must continue to the next candidate
        rather than returning None there and then. With the early return the
        verdict depends on set-iteration order, so a violation public_safety
        could resolve is reported verbatim on some runs and split on others.

        The fixture is two labels sharing one tail — ``"secret shape (PEM)"``
        and ``"1: secret shape (PEM)"`` — and a violation ending in both:
        ``x:1: 1: secret shape (PEM)``. Against the shorter label the head is
        ``x:1: 1`` (rpartitions to line ``" 1"``, not a digit) so that split
        must be rejected; the longer label's head, ``x:1``, is the one legal
        split. The old ``return None`` found the split only when the shorter
        label happened to sort second, so the loop below pins every order."""
        import census

        unparseable = "secret shape (PEM)"
        parsable = "1: secret shape (PEM)"
        violation = "x:1" + ": " + parsable
        expected = ("x", 1, parsable)

        # Both labels really do claim this violation, and only one parses.
        assert violation.endswith(": " + unparseable)
        assert violation.endswith(": " + parsable)

        for _ in range(200):
            # A fresh set each round, and both insertion orders: the label set
            # is a set, so iteration order is the thing the bug varies on.
            assert census._split_violation(violation, {unparseable, parsable}) == expected
            assert census._split_violation(violation, {parsable, unparseable}) == expected
        # The refusal cases still refuse: nothing matched, so the caller goes
        # verbatim rather than inventing a split.
        assert census._split_violation("1: secret shape (PEM", {unparseable, parsable}) is None

    def test_violation_in_path_containing_a_colon_is_split_correctly(self, tmp_path):
        """Regression: a tracked path may legally contain a colon
        ("x:y/p.txt"). Splitting public_safety's "path:line: label" at the
        FIRST colon truncated artifact to the path prefix before the colon
        ("x") and garbled the message, which also broke the documented
        (artifact, check, subject) sort grouping. The row must name the whole
        path as artifact and the whole path:line as subject."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "x:y/p.txt", "token " + _SECRET + "\n")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"hygiene is warn: expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, f"expected one hygiene row: {rows}"
            row = rows[0]
            assert row["artifact"] == "x:y/p.txt", (
                f"artifact must be the whole violating path, colon and all: {row}"
            )
            assert row["subject"] == "x:y/p.txt:1", (
                f"subject must be the whole path:line: {row}"
            )
            # The message must not be garbled: it names the full path and the
            # label, and never the truncated "y/p.txt1" prefix the first-colon
            # split produced.
            assert "x:y/p.txt" in row["message"], f"message lost the path: {row}"
            assert "y/p.txt1" not in row["message"], f"garbled message: {row}"
            assert row["code"] == 50 and row["severity"] == "warn"
        finally:
            _clear_denylist()

    def test_violation_subject_sorts_with_its_artifact(self, tmp_path):
        """The colon path must sort under its own artifact, not a truncated
        prefix: two rows in one colon-named file keep one artifact."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "x:y/p.txt", "token " + _SECRET + "\nline two\n")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            _rows = _run_census(repo, json_out=True)
            rows = [r for r in _ndjson_rows(_rows[1]) if r.get("check") == "hygiene"]
            artifacts = {r["artifact"] for r in rows}
            assert artifacts == {"x:y/p.txt"}, f"artifact grouping broke: {artifacts}"
        finally:
            _clear_denylist()

    def test_absent_denylist_is_reported_inactive_never_clean(self, tmp_path):
        """With no deny-list the class never reads "clean": it emits exactly
        one row naming the inactive state, even on a violation-free tree."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        rc, out, err = _run_census(repo, json_out=True)
        assert rc == 0, f"expected 0 (warn) without --strict, got {rc}\n{err}"
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
        assert len(rows) == 1, f"expected exactly one inactive-deny-list row: {rows}"
        row = rows[0]
        assert row["subject"] == "deny-list", f"expected the deny-list subject: {row}"
        assert "inactive" in row["message"] and "absent" in row["message"]
        assert "not a hygiene-clean guarantee" in row["message"]
        assert "hygiene-clean" not in row["message"].replace("not a hygiene-clean", ""), (
            f"an inactive class must never describe itself as clean: {row['message']}"
        )

    def test_corrupt_denylist_is_reported_inactive(self, tmp_path, monkeypatch):
        """"corrupt" is a third inactive state: named in the row, never clean."""
        public_safety = _hygiene_target()

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        corrupt = tmp_path / "corrupt-denylist.txt"
        corrupt.write_bytes(b"\xff\xfe\x00\x01not utf8")
        monkeypatch.setattr(public_safety, "_default_denylist_file", lambda repo: corrupt)
        rc, out, err = _run_census(repo, json_out=True)
        assert rc == 0, f"expected 0 (warn) without --strict, got {rc}\n{err}"
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
        assert len(rows) == 1, f"expected exactly one inactive-deny-list row: {rows}"
        assert rows[0]["subject"] == "deny-list"
        assert "corrupt" in rows[0]["message"], f"expected the corrupt state: {rows[0]['message']}"

    def test_empty_denylist_is_reported_inactive(self, tmp_path, monkeypatch):
        """A deny-list that is present but holds no entry is its own state:
        the class did not run, and the row says so."""
        public_safety = _hygiene_target()

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        empty = tmp_path / "empty-denylist.txt"
        empty.write_text("# only a comment\n", encoding="utf-8")
        monkeypatch.setattr(public_safety, "_default_denylist_file", lambda repo: empty)
        rc, out, err = _run_census(repo, json_out=True)
        assert rc == 0, f"expected 0 (warn) without --strict, got {rc}\n{err}"
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
        assert len(rows) == 1, f"expected exactly one inactive-deny-list row: {rows}"
        assert "present but empty" in rows[0]["message"], (
            f"expected the present-but-empty state: {rows[0]['message']}"
        )

    def test_active_denylist_on_clean_tree_reports_nothing(self, tmp_path):
        """With the deny-list class active and nothing to flag, hygiene is
        genuinely clean: zero rows."""
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert rows == [], f"expected no hygiene rows on a clean active-deny-list run: {rows}"
        finally:
            _clear_denylist()

    def test_denylist_entry_violation_is_reported(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        _commit_file(repo, "note.md", "port from synthetic-project-name\n")
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0, got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1 and "note.md" in rows[0]["subject"], f"rows: {rows}"
        finally:
            _clear_denylist()

    def test_violation_of_an_unknown_label_is_reported_verbatim(self, tmp_path, monkeypatch):
        """The verbatim fallback branch is load-bearing: a violation public_safety
        emits with a label the census has never seen must still produce a row
        that carries the whole finding. A row silently dropped here would read
        as a clean scan — the exact probe-honesty failure this class exists to
        close — so this test pins the row, its subject/artifact and its message
        (mutation guard: deleting the add(), or emptying any of its three
        fields, fails here)."""
        public_safety = _hygiene_target()

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        # A label absent from public_safety's tables: _split_violation must
        # refuse it, so the caller reports it verbatim.
        monkeypatch.setattr(
            public_safety, "_scan_tracked_files",
            lambda repo, patterns: ["x:y/p.txt:1: unrecognised future label"],
        )
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0 (warn), got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, f"expected one verbatim hygiene row: {rows}"
            row = rows[0]
            whole = "x:y/p.txt:1: unrecognised future label"
            assert row["subject"] == whole, f"subject must carry the whole finding: {row}"
            assert row["artifact"] == whole, f"artifact must carry the whole finding: {row}"
            assert row["message"] == f"public hygiene: {whole}", (
                f"message must carry the whole finding verbatim: {row['message']}"
            )
            assert row["code"] == 50 and row["severity"] == "warn"
            assert row["fix"]
        finally:
            _clear_denylist()

    def test_malformed_pattern_table_never_crashes_the_census(self, tmp_path, monkeypatch):
        """The label scan reads every ``*_PATTERNS`` attribute public_safety
        exposes, so a future table bound to a truthy non-iterable must degrade
        to the verbatim row rather than raise out of the census (the class's
        own contract is never-crash, report-instead)."""
        public_safety = _hygiene_target()

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        monkeypatch.setattr(public_safety, "FUTURE_PATTERNS", 5, raising=False)
        monkeypatch.setattr(
            public_safety, "_scan_tracked_files",
            lambda repo, patterns: ["n.md:2: GitHub classic token"],
        )
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0 (warn), got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, f"expected one row, no crash: {rows}"
            # The known tables still load, so the well-shaped row still splits.
            assert rows[0]["artifact"] == "n.md", f"expected a split row: {rows[0]}"
        finally:
            _clear_denylist()

    def test_pattern_table_that_raises_on_iteration_never_crashes_the_census(
            self, tmp_path, monkeypatch):
        """The never-crash claim covers more than TypeError.

        A table whose iteration protocol raises (``__iter__``, ``__len__`` or
        ``__bool__`` blowing up) must contribute no labels and let the run
        report verbatim rows — not escape as a traceback that discards every
        finding the census already collected. The int fixture above pins only
        the TypeError shape, so this is the case that makes the contract real."""
        public_safety = _hygiene_target()

        class _BadTable:
            def __bool__(self) -> bool:
                return True

            def __iter__(self):
                raise RuntimeError("table hang")

        repo = _init_repo(tmp_path / "repo")
        _commit_file(repo, "noni/decisions/2026-10-01-alpha.json",
                      json.dumps(_valid_record(), indent=2))
        monkeypatch.setattr(public_safety, "FUTURE_PATTERNS", _BadTable(), raising=False)
        monkeypatch.setattr(
            public_safety, "_scan_tracked_files",
            lambda repo, patterns: ["n.md:2: unrecognised future label"],
        )
        _with_denylist(tmp_path, "synthetic-project-name")
        try:
            rc, out, err = _run_census(repo, json_out=True)
            assert rc == 0, f"expected 0 (warn), got {rc}\n{err}"
            rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
            assert len(rows) == 1, f"expected one verbatim row, no crash: {rows}"
            assert rows[0]["artifact"] == "n.md:2: unrecognised future label", (
                f"a table that cannot be walked must not garble the row: {rows[0]}"
            )
        finally:
            _clear_denylist()

    def test_non_git_repo_reports_scan_did_not_run(self, tmp_path):
        """A non-git --repo is probe honesty, never a clean: one row saying the
        scan did not run."""
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "note.txt").write_text("hello\n", encoding="utf-8")
        rc, out, err = _run_census(plain, json_out=True)
        assert rc == 0, f"expected 0 (warn) without --strict, got {rc}\n{err}"
        rows = [r for r in _ndjson_rows(out) if r.get("check") == "hygiene"]
        assert len(rows) == 1, f"expected one not-run row: {rows}"
        assert "did not run" in rows[0]["message"]
        assert rows[0]["code"] == 50
        # The artifact is pinned, not just "truthy": the not-run row names the
        # checker by its package-relative id (the hygiene artifact namespace),
        # and a row that pointed anywhere else would send a caller to the wrong
        # file when it goes to fix the scan. Read from the product's constant so
        # the row and the checker's own name cannot drift apart unnoticed.
        import census_hygiene

        assert rows[0]["artifact"] == census_hygiene.HYGIENE_SCAN_ARTIFACT, (
            f"not-run row must name the checker: {rows[0]}"
        )
        assert rows[0]["artifact"] == "noni/public_safety.py", rows[0]

    def test_non_git_repo_strict_lifts_the_exit(self, tmp_path):
        """The not-run row is a warn like any other hygiene row: --strict turns
        it into exit 50."""
        plain = tmp_path / "plain-strict"
        plain.mkdir()
        (plain / "note.txt").write_text("hello\n", encoding="utf-8")
        rc, _out, err = _run_census(plain, "--only", "hygiene", "--strict")
        assert rc == 50, f"expected 50 under --strict, got {rc}\n{err}"


class TestHygieneFifoTree:
    """A tracked fifo is skipped and reported, in bounded time, at census level.

    Every case here runs the census in a subprocess (``census_hygiene_child``),
    never through the file's in-process ``_run_census``: the fault being pinned
    is a read that never returns, it raises nothing, so ``check_hygiene``'s
    ``except Exception`` cannot turn it into a row and an in-process regression
    would wedge the pytest worker instead of failing one test.
    """

    def test_a_tracked_fifo_yields_no_violation_and_a_prompt_exit(self, tmp_path):
        """AC1 at the census: the run returns, the pipe earns no violation row.

        The tree is built by the same harness builders the in-process tests use
        (a ledger record, a planted deny-list violation in a regular file, and
        a tracked path swapped for a pipe after its commit). The scan must answer
        in bounded time, exit 0 (hygiene is warn), and produce no row whose
        subject is the pipe.
        """
        rc, rows, elapsed = fifo_tree_census_run(tmp_path)
        assert rc == 0, f"hygiene is warn: expected 0 without --strict, got {rc}"
        assert elapsed < BOUND_SECONDS, f"the census took {elapsed:.1f}s"
        findings = [r for r in rows if r.get("kind") == "finding"]
        assert not [r for r in findings if r["subject"].startswith("plain.md")], (
            f"the scan reported the fifo as a violating file: {findings}")

    def test_the_skipped_fifo_is_reported_never_a_clean_scan(self, tmp_path):
        """The census's honesty half: a path it did not read is a row, not a clean.

        The row is the scan's own -- ``subject`` ``hygiene scan``, the checker in
        the hygiene artifact namespace -- because the finding is that the scan
        could not look, not that some file holds something. It names the count
        and the class and never the skipped path, which is the census's rule for
        every row about someone else's tree.
        """
        import census_hygiene

        _rc, rows, _elapsed = fifo_tree_census_run(tmp_path)
        scan_rows = [r for r in rows
                     if r.get("check") == "hygiene" and r["subject"] == "hygiene scan"]
        assert len(scan_rows) == 1, f"expected exactly one scan row: {rows}"
        row = scan_rows[0]
        assert row["artifact"] == census_hygiene.HYGIENE_SCAN_ARTIFACT, row
        assert "skipped" in row["message"] and "non-regular" in row["message"], row
        assert "not a hygiene-clean guarantee" in row["message"], row["message"]
        assert row["severity"] == "warn"
        assert "plain.md" not in json.dumps(row), (
            f"a skipped path reached the row: {row}")

    def test_a_violation_beside_the_fifo_is_still_reported(self, tmp_path):
        """The control that keeps the two cases above from passing for nothing.

        A scan that abandoned the whole tree would emit no pipe row and no
        violation row. This requires the violation in the regular tracked file
        beside the pipe to still be there, with its path, line and label.
        """
        _rc, rows, _elapsed = fifo_tree_census_run(tmp_path)
        findings = [r for r in rows if r.get("kind") == "finding"]
        assert any(r["subject"] == "note.md:1" and "note.md" in r["artifact"]
                   and "deny-list entry" in r["message"] for r in findings), (
            f"a violation beside the fifo was lost: {findings}")

    def test_the_fifo_is_left_untouched_on_disk(self, tmp_path):
        """Skipping is not consuming: the pipe is still a pipe afterwards.

        A guard that opened the path and read it to EOF, or that unlinked it to
        get rid of the problem, would both pass the row assertions above.
        """
        import stat

        # The launcher's own tree name, passed explicitly rather than left to
        # the default: this assertion reaches into the tree the child built.
        _rc, _rows, _elapsed = fifo_tree_census_run(tmp_path, name="fifo-tree-untouched")
        pipe = tree_dir(tmp_path, "fifo-tree-untouched") / "plain.md"
        assert stat.S_ISFIFO(os.lstat(pipe).st_mode), (
            "the scan removed or replaced the pipe it was meant to skip")
