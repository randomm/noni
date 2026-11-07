"""What one allowlist entry exempts, and the shapes of entry it refuses.

The hygiene check's only exemption before issue #118 was a hard-coded list of three of
noni's own files, so a tracked fixture that holds a fake token on purpose always failed
the gate. The allowlist is that exemption made general -- a committed file in the audited
tree naming, per exact tracked path, the one label it may carry and why -- and these are
the rules that keep a general exemption from becoming a way to switch the check off: an
entry covers exactly one (path, label) pair, so a second label on the line still fails
(AC2, and the row it produces is a row the report still prints rather than a deleted one);
a path is exact, never a glob, a directory or a traversal, because a widened match would
exempt files no reviewer read; and a line that is not a complete entry is a refusal rather
than a line nobody wrote, since silently skipping it is the exemption nobody reviewed.

Every planted token is assembled at runtime from the product's own pattern tables, the way
``tests/harness_faults.py`` builds its fixtures: a file that carried a literal shaped like
a token would need an allowlist entry to pass the check it is testing.

The rest of the contract is in sibling modules, split at the 500-line cap of
``tests/test_file_size_limit.py``: ``..._stale.py`` for an entry that matches nothing
(AC3), ``..._refusal.py`` for a file the scan could not read or honour (AC4) and for what
no entry may exempt (AC5), and ``..._gate.py`` for the CLI's exit codes. The census-side
verdict of the same states is in ``tests/test_census_hygiene_allowlist.py``: the two entry
points share the verdict, not the exit code. The planted values and the commit helper the
siblings need are module-level here and imported from here, so one fixture format has one
owner.
"""

from __future__ import annotations

import public_safety
from allowlist_tree import (
    HOME_LABEL,
    SECRET_LABEL,
    SECRET_LINE,
    TOKEN_FIXTURE,
    commit_planted,
)
from census_allowlist import (
    _allowlist_line,
    _with_allowlist,
)
from harness_faults import _home_path_violation

# The second label a line can carry, assembled at runtime for the same reason the token
# is: a file that wrote a home path out loud would need an allowlist entry itself.
HOME_VIOLATION = _home_path_violation()


# --- AC1: the file's format is exact paths, one label, and a reason ------------------


def test_an_entry_exempts_its_path_and_label_only(clean_repo, tmp_path):
    """The fixture named by the allowlist comes back as nothing, and the same label at
    a path nobody named still fails.

    Both halves in one test because they are one rule seen from two sides: an exemption
    that exempted nothing fails the first assertion, and an exemption that exempted
    everything fails the second.
    """
    commit_planted(clean_repo, "tests/fixtures/token.txt", TOKEN_FIXTURE)
    commit_planted(clean_repo, "src/other.py", TOKEN_FIXTURE)
    _with_allowlist(tmp_path, _allowlist_line("tests/fixtures/token.txt", SECRET_LABEL))

    violations, _, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert not any(v.startswith("tests/fixtures/token.txt") for v in violations), violations
    assert any(v.startswith("src/other.py:1:") and SECRET_LABEL in v for v in violations), (
        f"an exemption at one path silenced the same label at another: {violations}")


def test_an_allowlisted_path_still_fails_a_different_label(clean_repo, tmp_path):
    """The (path, label) pair is the unit, so a second label at an exempt path fails.

    The scan reports at most one label per line, and the loop used to stop at the first
    match: applied as a post-filter on rows, an exemption would have made this line's
    second, non-allowlisted label disappear. This is the case that pins per-pair
    exemption inside the per-line loop rather than around it.
    """
    commit_planted(clean_repo, "fixtures/both.txt", f"{SECRET_LINE} {HOME_VIOLATION}\n")
    _with_allowlist(tmp_path, _allowlist_line("fixtures/both.txt", SECRET_LABEL))

    violations, _, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert violations == ["fixtures/both.txt:1: " + HOME_LABEL], (
        f"the line's second label was lost, or the exempt label was reported: {violations}")


def test_the_reason_is_carried_by_the_exemption_row(clean_repo, tmp_path):
    """The one-line reason is not decoration: it is what the exemption reports.

    The row's wording is the product's, and the reason is quoted into it, so a reader of
    the report sees the justification rather than a pointer to a file they then have to
    open. This pins the choice the docs test also asserts.
    """
    reason = "synthetic token used by the fixture loader"
    commit_planted(clean_repo, "fixtures/token.txt", TOKEN_FIXTURE)
    allowlist = _with_allowlist(tmp_path,
                                _allowlist_line("fixtures/token.txt", SECRET_LABEL, reason))

    result = public_safety.load_allowlist(clean_repo)
    assert result.status == "ok", result
    assert result.entries[0].reason == reason
    assert public_safety.allowlist_reason(result, "fixtures/token.txt", SECRET_LABEL) == reason
    assert allowlist.is_file()


def test_globs_and_loose_path_forms_are_refused(clean_repo, tmp_path):
    """No glob, no directory, no traversal, no drive spec: an entry names one path.

    Each form below would widen an exemption the moment a file landed on a path the
    reviewer never read, and every one of them is a shape ``git ls-files`` itself never
    produces -- which is what makes refusing them free.
    """
    for bad in ("fixtures/*.txt", "fixtures/", "/etc/passwd", "./fixtures/x.txt",
                "../outside.txt", "fixtures/../fixtures/x.txt", "C:/fixtures/x.txt",
                "~/fixtures/x.txt", "fixtures/[a-z].txt", "fixtures/?.txt",
                "fixtures/$HOME/x.txt"):
        _with_allowlist(tmp_path, _allowlist_line(bad, SECRET_LABEL))
        result = public_safety.load_allowlist(clean_repo)
        assert result.status == "malformed", f"{bad!r} was accepted: {result}"
        assert any("exact tracked path" in row for row in result.findings), (
            f"{bad!r} refused without saying why: {result.findings}")


def test_a_blank_or_comment_only_allowlist_changes_nothing(clean_repo, tmp_path):
    """A file of comments is an allowlist with no entries, and an ok status.

    The deny-list's comments-only file is its own inactive state because an inactive
    deny-list is a missing half of the check; an allowlist with nothing in it exempts
    nothing, which is what a tree with no allowlist means. The two are different
    questions and get different answers on purpose.
    """
    commit_planted(clean_repo, "fixtures/token.txt", TOKEN_FIXTURE)
    _with_allowlist(tmp_path, "# nothing exempt here", "")

    result = public_safety.load_allowlist(clean_repo)
    assert result.status == "ok", result
    assert result.entries == []
    violations, _, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert any(v.startswith("fixtures/token.txt:1:") for v in violations), violations


def test_the_reason_may_carry_a_pipe(clean_repo, tmp_path):
    """The reason is free text: split on the first two fields, not on every separator.

    A path or label may not, which is why the split is bounded rather than exhaustive --
    the last field takes the remainder so a reviewer quoting a shell pipeline is not
    told their file is malformed.
    """
    reason = "grep -n 'a|b' in the loader"
    _with_allowlist(tmp_path, f"fixtures/x.txt | {SECRET_LABEL} | {reason}")
    result = public_safety.load_allowlist(clean_repo)
    assert result.status == "ok", result
    assert result.entries[0].reason == reason


def test_a_missing_field_is_a_malformed_line(clean_repo, tmp_path):
    """Two fields is not a path/label/reason entry: it is a line nobody wrote correctly.

    Silently skipping it is the exemption nobody reviewed -- the file would read as
    exempting that path while the loader never parsed it.
    """
    _with_allowlist(tmp_path, f"fixtures/x.txt | {SECRET_LABEL}")
    result = public_safety.load_allowlist(clean_repo)
    assert result.status == "malformed", result
    assert result.findings, "a malformed line earned no row"


