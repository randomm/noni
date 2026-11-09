"""Purity tests: the noni purity rule (README "no project-specific content")
must itself be a test.

The purity rule has two tiers:
1. Core skills carry neither project content nor vocabulary from any specific driver, tracker or project.
2. The fixture set carries no machine-local path and no operator-specific
   content.

These tests enforce the two-tier purity:
- The core skill files (SKILL.md, references/*.md) and every page under ``docs/``
  contain no references to specific attached projects, no vocabulary from any
  specific driver, tracker or project, and no project-specific content.
- The fixture set (tests/fixtures/) contains no machine-local paths
  (/home/<user>, /Users/<user>) and no operator-specific content.

The banned *names* for tier 1 are the untracked local deny-list loaded via
``public_safety.load_denylist`` — the same source the scrub uses — so no real
external tool/project name ever has to be committed to this file. When the
deny-list is absent the name check is skipped via pytest.skip with a visible
reason (same contract as the scrub); the structural checks below — the committed
shape patterns and the no-committed-.git / product-docs-exist checks — still run,
which is what keeps a page from naming a vendor on a green CI run that skipped.
"""

from __future__ import annotations

import re
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# The shared pattern registry and the deny-list loader, from the package's own
# checker, so that new secret shapes or path patterns are added in exactly one
# place and the banned vocabulary is the same deny-list the scrub uses (never a
# committed list of real names).
from public_safety import (  # noqa: E402
    FIXTURE_HOME_PATH_PATTERNS,
    HOME_PATH_PATTERNS,
    load_denylist,
)

SKILL_DIRS = [REPO / "skills" / "steering-ledger", REPO / "skills" / "sessions-claims",
              REPO / "skills" / "census", REPO / "skills" / "direction"]
FIXTURES = REPO / "tests" / "fixtures"
README = REPO / "README.md"
PRODUCT = REPO / "docs" / "PRODUCT.md"

# The docs pages the vocabulary check covers. ``docs/*.md`` is read from the
# directory rather than listed, so a page added under ``docs/`` is covered the day
# it lands and cannot arrive as a page the purity rule speaks for but no check
# reads (the gap issue #73 closed for the agent-onboarding page). ``DOC_PAGES`` in
# ``tests/docs_promises.py`` is the docs suite's page set; this glob is purity's
# own view of it, and the test below asserts the two agree so they cannot drift.
DOC_PAGE_GLOB = "*.md"

# Banned vocabulary for the core skill files: the untracked local deny-list
# (two-tier purity: the core must be viable with no adapter installed). Real
# external tool/project names live only in that deny-list and in adapters;
# nothing real is committed here. Loaded once at module import; when the
# deny-list is absent or inactive, the vocabulary check is skipped via
# pytest.skip with a visible reason (same contract as the scrub's deny-list
# class) while the structural checks below still run.
_DENYLIST = load_denylist(REPO)
FORBIDDEN_VOCAB = [
    (re.compile(re.escape(entry), re.IGNORECASE), "external tool/project vocabulary")
    for entry in _DENYLIST.entries
]

# Committed hygiene shapes: the forms a project, tracker or vendor name always
# arrives in, independent of which name it is. These run whether or not a deny-list
# is present, so tier 1 has a half that fires in CI with nothing untracked to
# consult — the deny-list above owns the *name* half only (the public-repo hygiene
# rule forbids committing a real name, so only its shape is committed here).
#
# Two shapes survive the test of precision, and each exempts only the placeholder
# forms the product's own pages print:
#
# - **A corporate entity name.** ``acme-corp`` is the shape a vendor takes in
#   prose, with the common entity suffixes in one closed set; the one exemption is
#   the quickstart's own illustration of a deny-list entry (``example-corp``,
#   docs/QUICKSTART.md).
# - **A service hostname.** Matched behind a URL scheme, an ``@`` in the user
#   position of a remote, a ``www.`` prefix, or as a bare ``label.tld`` sitting in
#   a sentence (``Point your agents at widgets.dev``), because a page can name a
#   vendor's domain without spelling the scheme. Exempt are the reserved
#   documentation hosts (``forge.example``, ``*.example.com``, ``*.test``), every
#   name whose last label is a file suffix (``census.sh``, ``order.py``,
#   ``docs/QUICKSTART.md`` -- the script names this product's pages write daily),
#   and the reader's own remote spelled with its placeholder owner
#   (``github.com/OWNER/…``, ``forge.example``). The bare shape deliberately starts
#   at a word character, so ``<project>/.noni-scrub-denylist`` and
#   ``<record-id>.md`` -- dotted names the pages print inside angle brackets -- are
#   read as path syntax, and a gate that flagged them would be reworded away.
#
# What the shapes do not claim: prose that names a vendor in plain words -- ``use
# it with jira``, ``the team at Widgetsmate`` -- matches nothing here, because no
# committed pattern tells a vendor word from an ordinary one. That half is the
# deny-list's job (docs/PUBLISHING.md step 1), and a green run with no deny-list
# does not mean it was checked. A bare ``@handle`` shape was considered and dropped:
# every ``@`` in this repository's own sources is a Python decorator, so the pattern
# would fire on ordinary code and be reworded around — the failure mode of a gate
# with more false positives than true ones.
_PLACEHOLDER_ENTITY = r"example-corp|example-inc|example-llc|example-gmbh|example-ltd"
_PLACEHOLDER_REMOTE_PATH = r"/(?:OWNER|owner|YOU|you|YOUR[-_]?OWNER)[/?]"
# A placeholder owner can sit behind the path a host match stops at
# (``github.com/OWNER/…`` ends its match at the first slash), so the owner is also
# refused ahead of the path: without this, the bare host shape would flag the very
# clone line the quickstart tells the reader to fill in.
_PLACEHOLDER_OWNER_AHEAD = r"(?![\w/.-]*(?:OWNER|YOU|YOUR[-_]?OWNER)[/?])"
# Reserved documentation / private-use top-level labels: a host ending in one of
# these resolves nowhere, so it names no vendor. ``example`` is IANA-reserved for
# documentation and is what the quickstart's Route B clone line uses.
_RESERVED_HOST_LABELS = r"example|invalid|localhost|local|internal|test|onion|arpa"

# The TLD a real service's hostname ends in. The set is closed on purpose: an open
# ``\.[\w-]+`` would reach every dotted name in a page. ``_FILE_SUFFIXES`` removes
# the overlaps with file extensions from the label the host pattern starts on, so a
# file name never reads as a host: this product's pages write ``census.sh``,
# ``order.py`` and ``docs/QUICKSTART.md`` in every section, and ``.sh``, ``.io``,
# ``.co`` and ``.me`` are both TLDs and file suffixes.
_TLDS = ("com|org|net|edu|gov|mil|int|io|dev|app|cloud|ai|co|me|xyz|sh|so|tv|fm|info|"
         "biz|online|site|space|tech|website|live|digital|host|page")
_FILE_SUFFIXES = ("sh|py|md|txt|json|ya?ml|csv|tsv|toml|cfg|ini|log|lock|sum|html|css|js|"
                  "ts|tsx|jsx|go|rs|rb|java|c|h|cpp|hpp|pl|php|sql|svg|png|jpg|jpeg|gif|"
                  "pdf|zip|tar|gz|tgz|bz2|xz|exe|so|a|o|pyc|template|sample|example|min|"
                  "test|spec|old|new|bak|tmp|temp|in|rc|env|gitignore|gitattributes|"
                  "dockerignore|editorconfig|nvmrc|npmignore|eslint|prettier|bashrc|"
                  "zshrc|profile|history|version|sig|asc|pem|key|crt|cer|der|p12|pfx|"
                  "jks|keystore")
_LABEL = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"

# The two ways a host is named. Triggered by a scheme, an ``@`` or a ``www.``: the
# trigger itself makes it unambiguous, so the host may be a multi-label remote and
# the owner placeholder is read off the path that follows. Bare: one label plus a
# TLD, sitting at a word boundary in a sentence, refused when a placeholder owner
# follows it. The bare half is what catches ``widgets.dev`` written without a
# scheme, the shape a prose page actually writes.
#
# The file-name exemption sits where each half can *start*, not after the match:
# a negative look-ahead is evaluated at the position the match begins, so stating
# it once at the end of the alternation tests the empty string there and lets
# ``census.sh`` read as a host -- ``sh`` is both a file suffix this product's pages
# print and a TLD in the closed set above.
_FILE_NAME_AHEAD = rf"(?!{_LABEL}\.(?:{_FILE_SUFFIXES})\b)"
_TRIGGERED_HOST = (rf"(?:https?://|www\.|[^\s/@:]+@){_FILE_NAME_AHEAD}"
                   rf"{_LABEL}(?:\.{_LABEL})*\.(?:{_TLDS})\b")
_BARE_HOST = (rf"(?<![\w./@-]){(_FILE_NAME_AHEAD)}{_LABEL}"
              rf"(?:\.{_LABEL})*\.(?:{_TLDS})\b")

FORBIDDEN_STRUCTURAL: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(
        rf"(?:{_TRIGGERED_HOST}|{_PLACEHOLDER_OWNER_AHEAD}{_BARE_HOST}{_PLACEHOLDER_OWNER_AHEAD})"
        rf"(?!{_PLACEHOLDER_REMOTE_PATH})"
        rf"(?!{_LABEL}\.(?:{_RESERVED_HOST_LABELS})\b)",
        re.IGNORECASE),
     "third-party hostname"),
    (re.compile(rf"\b(?!{_PLACEHOLDER_ENTITY}\b){_LABEL}-(?:corp|inc|llc|gmbh|ltd)\b",
                re.IGNORECASE),
     "corporate entity name"),
)

# Machine-local path patterns. The known-identity patterns come from the
# shared registry; the fixture-only catch-alls retain any-username coverage
# (the shared registry is deliberately limited to well-known identities for
# the scrub, where any-user names are the deny-list class's job).
FORBIDDEN_PATHS: tuple[tuple[re.Pattern, str], ...] = tuple(HOME_PATH_PATTERNS) + tuple(FIXTURE_HOME_PATH_PATTERNS)

SKILL_CORE_FILES = sorted(
    p
    for d in SKILL_DIRS
    for p in d.rglob("*.md")
    if p.is_file() and "__pycache__" not in p.parts
)

# The docs pages the vocabulary check walks, alongside the core skill files: the
# tier-1 rule (no vocabulary from any specific driver, tracker or project) is a
# rule about what a reader copies, and a page under ``docs/`` is exactly that.
DOC_CORE_FILES = sorted(
    p for p in (REPO / "docs").glob(DOC_PAGE_GLOB) if p.is_file()
)

# Suffixes no text check reads. ``.pyc`` was the only one until the brief fixture arrived as
# a tar, which carries a packed git repository: its members are the text the checks are about
# and the tar itself is bytes. ``fixture_texts`` below reads one or the other.
BINARY_SUFFIXES = {".pyc", ".tar"}

FIXTURE_FILES = sorted(
    p
    for p in FIXTURES.rglob("*")
    if p.is_file() and "__pycache__" not in p.parts and p.suffix not in BINARY_SUFFIXES
)


def fixture_texts(path):
    """The ``(where, text)`` pairs a fixture file contributes to the text checks.

    ``where`` names the member inside a tar and is ``""`` for a plain file, so a failure can
    point at the path that actually holds the bytes.
    """
    if path.suffix == ".tar":
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                if member.isfile() and "__pycache__" not in Path(member.name).parts:
                    handle = archive.extractfile(member)
                    assert handle is not None, f"{path}: member {member.name} vanished"
                    yield member.name, handle.read().decode("utf-8")
    else:
        yield "", path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", SKILL_CORE_FILES + DOC_CORE_FILES,
                         ids=lambda p: f"{p.parent.name}/{p.name}")
def test_core_pages_have_no_driver_tool_vocabulary(path):
    """The core skill files and every page under ``docs/`` contain no vocabulary
    from any specific driver, tracker or project. The two-tier purity rule: the
    core must be viable with no adapter installed, and the adapters are the only
    place those names appear.

    The docs pages ride the same deny-list as the skill files (one source of banned
    vocabulary, never a committed name list), which is what makes the rule on the
    agent-onboarding page a checked rule rather than an intention: a page that named
    the runtime or tracker it was written next to fails here, in CI, with nothing
    untracked to consult.

    The shape check below runs whether or not the deny-list is present. The skip is
    only for the name half of the rule, so a page cannot carry a vendor hostname or
    a corporate entity name while the CI run that should have caught it skipped.
    """
    rel = (path.relative_to(SKILL_DIRS[0].parent.parent) if path.is_relative_to(REPO)
           else path.name)
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        for pattern, label in FORBIDDEN_STRUCTURAL:
            assert not pattern.search(line), f"{rel}:{lineno}: {label}"
    if _DENYLIST.status != "ok" or not _DENYLIST.entries:
        # Same contract as the scrub: without an active deny-list the
        # vocabulary class is skipped visibly (pytest.skip, not a silent
        # no-op pass).
        pytest.skip(
            f"deny-list inactive: {_DENYLIST.status}; core skill files and docs "
            "pages unchecked for external tool/project vocabulary. This is NOT "
            "a purity guarantee. See docs/PUBLISHING.md step 1."
        )
    for lineno, line in enumerate(text.splitlines(), 1):
        for pattern, label in FORBIDDEN_VOCAB:
            assert not pattern.search(line), f"{rel}:{lineno}: {label}"


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_fixtures_have_no_machine_local_paths(path):
    """The fixture set contains no machine-local paths (/home/<user>,
    /Users/<user>). The noni purity rule: no project-specific content, and the
    fixture set itself must be cloneable without a host dependency."""
    for member, text in fixture_texts(path):
        location = path.relative_to(FIXTURES).as_posix() + (f":{member}" if member else "")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, label in FORBIDDEN_PATHS:
                assert not pattern.search(line), f"{location}:{lineno}: {label}"


def test_the_docs_page_set_and_the_docs_glob_agree():
    """Purity's view of ``docs/`` is the docs suite's page set, plus nothing lost.

    Two readers of the same directory can drift: ``tests/docs_promises.py`` names
    its pages one by one, this module globs. The glob is the wider net -- a page the
    docs suite forgot is still scanned here -- but the direction that matters is the
    other one: every page the docs suite reads must be inside purity's net, so a
    page cannot be product surface for one gate and invisible to the other.
    """
    from docs_promises import DOC_PAGES

    globbed = {p.resolve() for p in DOC_CORE_FILES}
    named = {p.resolve() for p in DOC_PAGES if p.parent.name == "docs"}
    missing = sorted(str(p.relative_to(REPO)) for p in named - globbed)
    assert not missing, (
        f"tests/docs_promises.py reads docs pages that this module's vocabulary "
        f"check does not: {missing}")


def test_the_shape_check_catches_a_named_vendor_with_the_deny_list_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8's honest half: a page that names a vendor fails on a CI run with no deny-list.

    The vocabulary check above skips visibly when the untracked deny-list is absent,
    which is the correct contract for the *name* half of the rule but leaves the
    onboarding page's runtime neutrality unenforced in CI -- the exact gap the review
    of issue #73 found. So the shape check must run first, and this test proves it
    does: it plants pages naming a vendor in every written form the shapes claim to
    cover, forces the deny-list to the inactive state CI runs in, and asks whether
    the parametrised check fails rather than skips. A version of that check placed
    after the ``pytest.skip`` would fail here, which is the point.

    The plants are the forms, not one literal per pattern. The review of issue #73
    found the first cut of this test pinned the host half to a single ``https://``
    string and the entity half to a single ``-corp`` suffix, so dropping the ``www.``
    trigger, the ``@``-trigger or any entity suffix from the pattern left the suite
    green while the gate went blind to the form it stopped matching. Each plant below
    is a form the pattern is documented to catch, and each is planted on its own page
    so one shape cannot stay green on the strength of another firing.

    What is deliberately not planted here is prose that names a vendor in plain words
    (``the team at Widgetsmate``, ``use it with jira``): no committed pattern tells a
    vendor word from an ordinary one, and that half belongs to the untracked
    deny-list (docs/PUBLISHING.md step 1). A green run with no deny-list means the
    name half was skipped, not that the page is clean.
    """
    monkeypatch.setattr("test_purity._DENYLIST",
                        type(_DENYLIST)([], None, "absent"))

    def _assert_fails(page: Path, label: str) -> None:
        """One planted page has to fail the check with this label, not pass or skip.

        Three outcomes are distinguished on purpose. ``pytest.raises`` alone would
        let a Skipped outcome count as a pass -- that is what hid the ordering bug
        this test exists to catch -- so a skip is its own failure, and so is a check
        that returned without asserting anything. Reaching the end of the ``try``
        means the page was accepted, which is the third failure.
        """
        outcome: str
        try:
            test_core_pages_have_no_driver_tool_vocabulary(page)
        except pytest.skip.Exception:
            outcome = (
                "the vocabulary check skipped first, so AC8 is unenforced on a CI "
                "run with no deny-list -- the shape assertions must sit above the "
                "pytest.skip")
        except AssertionError as exc:
            assert label in str(exc), f"{label} not reported for {page.name}: {exc}"
            return
        else:
            outcome = f"the check passed a page naming {label}"
        raise AssertionError(
            f"{outcome}: {page.name} holds {page.read_text()!r}")

    # (file name, line, label) for every form the two shapes claim to catch.
    plants = (
        ("ENTITY.md", "A team on acme-corp's forge reads this page.",
         "corporate entity name"),
        ("ENTITY_GMBH.md", "The widgets-gmbh instance holds the ledger.",
         "corporate entity name"),
        ("SCHEME.md", "See https://widgets.dev/docs.", "third-party hostname"),
        ("WWW.md", "See www.widgets.dev/docs for the loader rules.",
         "third-party hostname"),
        ("REMOTE.md", "Push to git@widgets.dev:you/your-project.git.",
         "third-party hostname"),
        ("BARE.md", "Point your agents at widgets.dev for the loader docs.",
         "third-party hostname"),
    )
    for index, (name, line, label) in enumerate(plants):
        page = tmp_path / f"{index}-{name}"
        page.write_text(f"# Page\n\n{line}\n", encoding="utf-8")
        _assert_fails(page, label)


def test_the_shape_check_spares_the_pages_own_placeholder_forms() -> None:
    """The shapes the product's own pages print are not violations.

    Three forms carry a domain or an entity suffix legitimately, and each is the
    thing a real page prints today: the quickstart's ``example-corp`` deny-list
    illustration, its ``github.com/OWNER/…`` clone line with the owner left to fill
    in, and the reserved ``git@forge.example:`` remote on Route B. A gate that
    flagged any of them would be answered by rewording the page, not by removing a
    vendor name, so the exemptions are pinned as directly as the patterns are.
    """
    for line in (
        "example-corp",
        "git clone https://github.com/OWNER/noni noni",
        "git clone git@forge.example:you/your-project-direction.git .noni-state",
        "the census reads `<project>/.noni-scrub-denylist` and `<record-id>.md`",
        "run `census.sh`, `decide.py` and `order.py` (e.g. from the skill dir)",
        "the reader's own remote is `git@forge.internal:you/your-project.git`",
        "copy `census-sessions.sh` into the project and the `noni/direction/` dir",
        "read docs/QUICKSTART.md and docs/PUBLISHING.md before the first run",
        "the census reports `absent`, `corrupt` and `present but empty`",
        "push to `github.com/OWNER/your-project` with the placeholder owner filled",
    ):
        hits = [label for pattern, label in FORBIDDEN_STRUCTURAL if pattern.search(line)]
        assert not hits, f"the shape check flags the placeholder form {line!r}: {hits}"


def test_readme_states_the_purity_rule():
    """The README explicitly states the purity rule: no project-specific
    content. This pins the rule so it cannot be silently removed."""
    assert README.is_file(), "README.md is missing"
    text = README.read_text(encoding="utf-8")
    assert "purity" in text.lower(), "README does not mention the purity rule"
    assert "no project-specific" in text.lower() or "project-specific" in text.lower(), (
        "README does not state the 'no project-specific content' rule"
    )


def test_product_md_exists():
    """The product document exists (it is the binding reference for the
    steering ledger's record shape and the census's exit codes)."""
    assert PRODUCT.is_file(), "docs/PRODUCT.md is missing"


def test_no_committed_git_dir_in_fixtures():
    """The fixtures directory contains no committed .git directory. The
    replay-repo fixture is generated by generate.sh (not committed), so no
    .git dir should be in the fixtures tree."""
    git_dirs = list(FIXTURES.rglob(".git"))
    assert not git_dirs, f"found committed .git dirs in fixtures: {[str(p) for p in git_dirs]}"
