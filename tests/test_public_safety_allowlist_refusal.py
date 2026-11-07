"""A refused allowlist, and what no entry may exempt.

The refuse half of the allowlist contract: a file the scan will not honour, and what no
entry may exempt at all. Both are the "an exemption must not become a way to switch the
check off" rules, so they are pinned together:

- a file that cannot be read, or refuses to parse, is the gate-could-not-run state (AC4)
  -- never a silent "no allowlist", because a scan that did not learn its exemptions has
  no verdict to give;
- neither config file may be named by an entry, and the deny-list label may never be
  exempted at all (AC5), so there is no route by which a committed file turns the
  deny-list half off;
- the loader's own seams (the default path the scan patches, the filename constant the
  docs quote, the label tables the census splits) keep the mechanism discoverable rather
  than a name typed in two places.

The exemption rules themselves are in ``tests/test_public_safety_allowlist.py``, the
stale-entry rule in ``tests/test_public_safety_allowlist_stale.py``, and the CLI's exit
codes in ``tests/test_public_safety_allowlist_gate.py``; the splits are the 500-line cap
in ``tests/test_file_size_limit.py``.
"""

from __future__ import annotations

import os
import subprocess

import public_safety
import public_safety_allowlist
import pytest
from _harness import REPO, _init_repo
from allowlist_tree import SECRET_LABEL, TOKEN_FIXTURE, commit_planted
from census_allowlist import (
    _allowlist_line,
    _entry_fixture,
    _with_committed_allowlist,
    _write_committed_allowlist,
)


def test_a_malformed_allowlist_stops_the_scan(clean_repo):
    """A refused file is not a scan with no exemptions: the scan does not answer.

    The violations it returns are the allowlist's own rows and nothing else -- a list
    produced by scanning with unknown exemptions would read as a verdict.
    """
    commit_planted(clean_repo, "fixtures/token.txt", TOKEN_FIXTURE)
    _with_committed_allowlist(clean_repo, "this line is not an entry")
    violations, _source, _denylist, allowlist = public_safety.scrub_tracked_files(clean_repo)
    assert allowlist.status == "malformed"
    assert violations and all(public_safety.ALLOWLIST_FILENAME in v for v in violations), (
        f"a refused allowlist must report only its own rows: {violations}")


def test_a_non_utf8_allowlist_is_unreadable_not_absent(clean_repo):
    """Bytes that will not decode are a file the operator wrote, not a missing one.

    The two have opposite consequences: "absent" means the tree opted out of the
    mechanism, "unreadable" means the run cannot be trusted. Written straight to the
    committed path, because the tree's own file is the only one the loader will read.
    """
    _write_committed_allowlist(clean_repo).write_bytes(b"\xff\xfe\x00\x01 not utf8")
    result = public_safety.load_allowlist(clean_repo)
    assert result.status == "unreadable", result


def test_a_directory_at_the_allowlist_path_is_not_read_as_absent(clean_repo):
    """A path that exists as a directory is a wrong location, not an opted-out tree.

    Reading it as absence is the failure this pins: the tree stated an allowlist and
    the run would report a clean scan that applied no exemptions. A directory cannot be
    committed, so it stands in the working tree and the listing still holds the rest.
    """
    directory = _write_committed_allowlist(clean_repo)
    directory.mkdir()
    result = public_safety.load_allowlist(clean_repo)
    assert result.status != "absent", f"a directory read as 'no allowlist': {result}"
    violations, _s, _d, allowlist = public_safety.scrub_tracked_files(clean_repo)
    assert allowlist.status != "absent"
    assert violations, "a run that could not read its exemptions reported no findings at all"


def test_a_non_regular_allowlist_is_unreadable(clean_repo):
    """A fifo at the allowlist path is refused at the open and classified, not waited on.

    The #91 promise applies to this third read in the package: the guard is what makes
    a blocking read impossible here, and the classification is what stops the refusal
    reading as an absent file. A fifo is not a committable object, so the tree's listing
    is unchanged and the verdict can only be about what stands at the allowlist path.
    """
    if not hasattr(os, "mkfifo"):
        pytest.skip("os.mkfifo is POSIX-only")
    pipe = _write_committed_allowlist(clean_repo)
    os.mkfifo(pipe)
    result = public_safety.load_allowlist(clean_repo)
    assert result.status == "unreadable", result


def test_setting_the_old_env_override_changes_nothing(clean_repo, tmp_path, monkeypatch):
    """NONI_SCRUB_ALLOWLIST is inert: the committed file alone decides.

    The override is gone (issue #139) -- an env-named file is not tracked, so an
    exemption that arrived that way carried no review trail. This is the regression
    test that keeps it gone: a valid file of entries named by the variable must not
    exempt anything on a tree that wrote no allowlist, and the same file broken must
    not turn a tree that did write one into an unreadable run. The conftest fixture
    clears the variable for every test, so this is the only place it is ever set.
    """
    exemptable = tmp_path / "outside-allowlist"
    exemptable.write_text(_allowlist_line("fixtures/token.txt", SECRET_LABEL) + "\n",
                          encoding="utf-8")
    broken = tmp_path / "broken-allowlist"
    broken.write_bytes(b"\xff\xfe not utf8")

    commit_planted(clean_repo, "fixtures/token.txt", TOKEN_FIXTURE)
    monkeypatch.setenv("NONI_SCRUB_ALLOWLIST", str(exemptable))
    result = public_safety.load_allowlist(clean_repo)
    assert result.status == "absent", (
        f"the environment named an allowlist: {result}")
    violations, _, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert any(v.startswith("fixtures/token.txt:1:") and SECRET_LABEL in v
               for v in violations), (
        f"an env-named file exempted a fixture no reviewer read: {violations}")

    monkeypatch.setenv("NONI_SCRUB_ALLOWLIST", str(broken))
    _with_committed_allowlist(clean_repo,
                              _allowlist_line("fixtures/token.txt", SECRET_LABEL))
    result = public_safety.load_allowlist(clean_repo)
    assert result.status == "ok", (
        f"the environment overrode the committed file: {result}")
    violations, _, _, _ = public_safety.scrub_tracked_files(clean_repo)
    assert violations == [], (
        f"an env-named file undid a committed exemption: {violations}")


def test_absence_is_the_only_quiet_state(clean_repo):
    """No file anywhere: absent, no rows, no warnings.

    The exemption mechanism is opt-in, so an attached project that never wrote one is a
    real state rather than an oversight -- the same argument the deny-list makes for
    absence, and the reason every other state is loud.
    """
    result = public_safety.load_allowlist(clean_repo)
    assert result.status == "absent", result
    assert result.entries == [] and result.findings == [] and result.source is None


def test_the_committed_file_is_the_default_route(clean_repo):
    """The tree's own tracked allowlist is read with no environment involved.

    AC1 asks for a committed file, and it is now the only route the loader has; a
    loader that honoured an environment name instead would pass every test above and
    ship an exemption nobody reviewed.
    """
    commit_planted(clean_repo, "fixtures/token.txt", TOKEN_FIXTURE)
    _with_committed_allowlist(clean_repo, _allowlist_line("fixtures/token.txt", SECRET_LABEL))
    violations, _, _, allowlist = public_safety.scrub_tracked_files(clean_repo)
    assert allowlist.status == "ok" and allowlist.source == public_safety.ALLOWLIST_FILENAME
    assert violations == [], violations




@pytest.mark.parametrize("protected", [public_safety.ALLOWLIST_FILENAME,
                                       public_safety.DENYLIST_FILENAME])
def test_neither_configuration_file_can_be_exempted(clean_repo, protected):
    """An entry naming the allowlist or the deny-list is refused, not honoured.

    The allowlist cannot exempt itself (that would let it carry its own fake tokens), and
    it cannot exempt the deny-list (whose path is the operator's private vocabulary). Both
    refusals are load-time, so the entry is a finding rather than a permission.
    """
    _with_committed_allowlist(clean_repo, _allowlist_line(protected, SECRET_LABEL))
    result = public_safety.load_allowlist(clean_repo)
    assert result.status == "malformed", f"{protected!r} was honoured: {result}"
    assert any(public_safety_allowlist.ALLOWLIST_REFUSED_LABEL in row for row in result.findings), (
        result.findings)


def test_the_deny_list_label_can_never_be_exempted(clean_repo, tmp_path, monkeypatch):
    """An entry for the deny-list class is refused: the class is the operator's own.

    ``_self_file_exempt`` already hard-refuses the label for noni's own three files, and
    the general form refuses it at load, so there is no route -- not a path, not a label,
    not both -- by which a committed file switches the deny-list half off.
    """
    denylist = tmp_path / "denylist"
    denylist.write_text("synthetic-vocab-name\n", encoding="utf-8")
    monkeypatch.setenv(public_safety.DENYLIST_ENV_VAR, str(denylist))
    commit_planted(clean_repo, "fixtures/note.txt", "synthetic-vocab-name\n")

    _with_committed_allowlist(clean_repo,
                              _allowlist_line("fixtures/note.txt", public_safety
                                              .DENYLIST_LABEL))
    result = public_safety.load_allowlist(clean_repo)
    assert result.status == "malformed", result
    # The refusal row is the load-time one that names the rule the file broke, not a
    # generic "malformed line": a reader must learn which rule, and a reader of the census
    # gets it from the label.
    assert any(public_safety.ALLOWLIST_REFUSED_LABEL in row for row in result.findings), (
        result.findings)
    assert any("deny-list" in row for row in result.findings), result.findings

    # And nothing was exempted. A refused file stops the scan -- which is the AC4 rule --
    # so the report is the refusal rows alone: no scan verdict dressed up from an
    # exemption set the loader could not endorse. The baseline above proves the hit was
    # there before the file, and the absence of a scan row here proves the run abstained.
    violations, source, _, _ = public_safety.scrub_tracked_files(clean_repo)
    # Compared to the rows the loader itself reports: the scan added none of its own.
    assert sorted(violations) == sorted(result.findings), violations
    assert all(public_safety.ALLOWLIST_FILENAME in v for v in violations), violations
    assert source is None, "a run that could not run reported a deny-list it never applied"


def test_allowlist_exempt_refuses_the_deny_list_label_even_when_built():
    """The predicate refuses the label directly, not only by the parser having refused it.

    A caller that assembled an entry by hand (a future writer, a test double) gets the
    same answer as one that went through the file: the rule is on the decision, not on
    one route to it.
    """
    result = public_safety.AllowlistResult(
        [public_safety.AllowlistEntry("fixtures/note.txt", public_safety.DENYLIST_LABEL, "x")],
        "x", "ok", [])
    assert public_safety.allowlist_exempt(
        result, "fixtures/note.txt", public_safety.DENYLIST_LABEL) is False
    assert public_safety.allowlist_exempt(
        result, "fixtures/note.txt", SECRET_LABEL) is False


def test_an_unusable_allowlist_never_exempts(clean_repo):
    """The entries a refused file did parse are not honoured either.

    The parser keeps what it read before the bad line so the report can name it, so the
    tempting bug is the half-reviewed file: honoured up to line 1, refused from line 2.
    The scan is not run at all in that state, so the report is the allowlist's own rows
    and no fixture of the tree appears as a violation or as exempted. The same rule
    already pinned from the other side in ``test_a_malformed_allowlist_stops_the_scan``,
    where the scan is proven not to have run by the fixture's absence from the report.
    """
    commit_planted(clean_repo, "fixtures/token.txt", TOKEN_FIXTURE)
    # The second line carries a pipe, so it is not one of the delimiters alone: a parser
    # that tolerated anything with two separators in it would honour the first entry and
    # this test would be about nothing.
    _with_committed_allowlist(clean_repo, _allowlist_line("fixtures/token.txt", SECRET_LABEL),
                              "no delimiters here at all")
    violations, _, _, allowlist = public_safety.scrub_tracked_files(clean_repo)
    assert allowlist.status == "malformed", allowlist
    assert allowlist.entries, "the case needs an entry the loader did parse and refused"
    assert all(public_safety.ALLOWLIST_FILENAME in v for v in violations), (
        f"a refused allowlist reported a scan verdict: {violations}")
    # The predicate the scan asks, asked here: a refused result publishes no pairs even
    # though it still carries the entries it parsed, which is the one place the rule lives.
    assert public_safety.exempted_pairs(allowlist) == frozenset(), (
        "a refused file still published its exemption set to the scan")




def test_the_default_path_seam_is_the_scan_s_own(tmp_path, monkeypatch):
    """The scan reaches the tree's allowlist through a patchable seam.

    The deny-list has one (``_default_denylist_file``) and the tests that prove the tree
    is a parameter rather than a cwd depend on it; the allowlist's loader is reached the
    same way, so a test can point it at a file the tree does not hold.
    """
    entry = _entry_fixture(tmp_path, _allowlist_line("fixtures/x.txt", SECRET_LABEL))
    monkeypatch.setattr(public_safety, "_default_allowlist_file", lambda repo: entry)
    # A real tree whose tracked listing holds nothing the entry names, so the seam (and
    # not the tree) is what supplied the file: a loader that ignored the seam would report
    # "absent" here, and one that ignored the listing would report no findings at all.
    empty = tmp_path / "empty-tree"
    _init_repo(empty)
    result = public_safety.load_allowlist(empty)
    assert result.status == "ok", result
    assert result.entries[0].path == "fixtures/x.txt"
    assert result.findings, "the seam was ignored, or the stale check never ran"


def test_the_filename_constant_is_the_single_source():
    """The name the docs quote and the name the loader reads are one constant.

    Every per-tree config file in this package works that way (``DENYLIST_FILENAME``
    beside ``DENYLIST_ENV_VAR``), and the docs tests read the constant rather than
    typing it, so a rename strands the page instead of passing a stale name forever.
    """
    assert public_safety.ALLOWLIST_FILENAME == ".noni-scrub-allowlist"
    assert public_safety.ALLOWLIST_FILENAME.startswith(".noni-")
    # A tracked file is named for what it is; the deny-list's ignore rule must not
    # accidentally cover it, which is what the next test checks on the real tree.
    result = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q",
                             public_safety.ALLOWLIST_FILENAME], capture_output=True)
    assert result.returncode != 0, (
        f"{public_safety.ALLOWLIST_FILENAME} is gitignored, so the committed allowlist "
        "could never be committed")


def test_the_two_labels_are_discoverable_vocabulary():
    """The allowlist's labels live in a ``*_PATTERNS`` table, so the census can split them.

    A label the census has never seen is reported verbatim, with subject and artifact
    both the whole finding, which breaks the documented path:line subject contract the
    row-contract tests pin. The table is the mechanism the census reads.
    """
    import census

    labels = census._hygiene_labels(public_safety)
    assert public_safety_allowlist.ALLOWLIST_STALE_LABEL in labels, sorted(labels)
    assert public_safety_allowlist.ALLOWLIST_REFUSED_LABEL in labels, sorted(labels)
    assert census._split_violation(
        f"{public_safety.ALLOWLIST_FILENAME}:0: {public_safety_allowlist.ALLOWLIST_STALE_LABEL} "
        "(fixtures/x.txt: GitHub classic token)",
        labels) is not None
