"""An allowlist entry that matches nothing is a finding, not a setting.

The direction that matters: a fixture renamed or deleted leaves its exemption standing,
and the next file to land on that path inherits an exemption nobody re-reviewed. Silence
is the safe-looking bug, so the entry earns a row of its own and the row travels with the
scan's violations -- which is what makes the CI gate red on it and what the census reports
(its side of the same rule is ``tests/test_census_hygiene_allowlist.py``).

The control cases are what make the stale rows mean something: an entry whose path the
listing does hold reports nothing, and the check asks the scan's own ``git ls-files`` so
the two cannot disagree about whether a path exists. The exemption rules themselves are in
``tests/test_public_safety_allowlist.py``; the split is the 500-line cap in
``tests/test_file_size_limit.py``.
"""

from __future__ import annotations

import public_safety
from _harness import _git
from allowlist_tree import SECRET_LABEL, TOKEN_FIXTURE, commit_planted
from census_allowlist import (
    _allowlist_line,
    _with_committed_allowlist,
)


def test_a_stale_entry_is_a_finding(clean_repo):
    """An entry whose path the listing does not hold earns a row of its own.

    The direction that matters: a renamed or deleted fixture leaves its exemption
    standing, and the next file to land on that path inherits an exemption nobody
    re-reviewed. Silence would be the safe-looking bug.

    The committed route, because staleness is a claim about a *tracked* tree: the row is
    named by the file's repository-relative path, and an env-named file would name a
    basename instead.
    """
    _with_committed_allowlist(clean_repo, _allowlist_line("fixtures/gone.txt", SECRET_LABEL))
    result = public_safety.load_allowlist(clean_repo)
    assert result.status == "ok", result
    assert len(result.findings) == 1, result.findings
    row = result.findings[0]
    assert row.startswith(public_safety.ALLOWLIST_FILENAME + ":0: ")
    assert "allowlist entry matches nothing" in row
    assert "fixtures/gone.txt" in row and SECRET_LABEL in row, (
        f"a stale row must name the entry it is about: {row}")


def test_a_stale_entry_surfaces_through_the_scan(clean_repo):
    """The stale row travels with the scan's violations, so both entry points see it.

    A finding only the loader could see is a finding the gate and the census would
    disagree about; travelling in ``violations`` is what makes the CI gate red on it.
    """
    _with_committed_allowlist(clean_repo, _allowlist_line("fixtures/gone.txt", SECRET_LABEL))
    assert "fixtures/gone.txt" not in _git(clean_repo, "ls-files").stdout.split()
    violations, _, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert len(violations) == 1 and "matches nothing" in violations[0], violations


def test_a_live_entry_earns_no_stale_row(clean_repo):
    """The control: an entry whose path is tracked reports nothing.

    Without it the test above would pass on an implementation that called every entry
    stale.
    """
    commit_planted(clean_repo, "fixtures/kept.txt", TOKEN_FIXTURE)
    _with_committed_allowlist(clean_repo, _allowlist_line("fixtures/kept.txt", SECRET_LABEL))
    violations, _, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert violations == [], violations


def test_the_stale_check_asks_the_scan_s_own_listing(clean_repo):
    """The path is matched against the same ``git ls-files`` the scan matched.

    A second Git view could answer differently about the same tree, and then a live
    exemption reports as stale (or a stale one as live) depending on which caller got
    there first. An untracked file is the case the two views disagree on by default.
    """
    # The precondition the case rests on, asserted rather than assumed: the path the entry
    # names is absent from git's view, while a file of that name sits in the working tree.
    # That is the only state in which the two Git views can disagree, which is what the
    # rule is about (an exemption nobody re-reviewed is the dangerous direction).
    fresh = clean_repo / "fixtures" / "untracked.txt"
    fresh.parent.mkdir(parents=True, exist_ok=True)
    fresh.write_text("x\n", encoding="utf-8")
    _with_committed_allowlist(clean_repo, _allowlist_line("fixtures/untracked.txt", SECRET_LABEL),
                              commit_only=True)
    assert fresh.is_file()
    assert "fixtures/untracked.txt" not in _git(clean_repo, "ls-files").stdout.split()
    violations, _, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert any("matches nothing" in v and "fixtures/untracked.txt" in v for v in violations), (
        f"an untracked path is not in the scan's listing, so the entry is stale: {violations}")
