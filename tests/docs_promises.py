"""Where the docs tests look, and the strings they agree on.

``tests/test_quickstart.py`` runs the quickstart's commands and
``tests/test_docs_promises.py`` checks what the pages claim; both read the same
small set of pages, and one of them needs a few of the same literals: the page
paths, the state directory the quickstart sells, the three words the census uses
for an inactive deny-list, and the shape of the recipe that produces the
census's ``--issue-state`` map.

Kept in a helper module rather than duplicated, so a page that moves cannot
leave one of the two tests checking the old location -- the same reason
``tests/readme_support.py`` holds the README's reading layer apart from its
promises. No assertion lives here: those stay with the test that makes them.
"""

from __future__ import annotations

import re
from pathlib import Path

from docs_commands import fenced_blocks

REPO = Path(__file__).resolve().parent.parent

README = REPO / "README.md"
CONTRIBUTING = REPO / "CONTRIBUTING.md"
QUICKSTART = REPO / "docs" / "QUICKSTART.md"
# The agent-onboarding page (issue #73): the sole home of the instruction that
# makes the four core skills available to a team's agents, and of the
# per-session protocol. It prints no command, so joining ``DOC_PAGES`` costs it
# nothing at the fence census and buys it every promise test over the page set.
ONBOARDING = REPO / "docs" / "ONBOARDING.md"
PRODUCT = REPO / "docs" / "PRODUCT.md"
PUBLISHING = REPO / "docs" / "PUBLISHING.md"

# The forge-specific page: the one place in the repository allowed to speak one
# CI system's vocabulary (docs/QUICKSTART.md's CI section links it, and
# ``test_the_forge_example_lives_under_integrations_and_is_linked`` checks both
# halves). It is deliberately absent from DOC_PAGES below: the core-page gate is
# the reason it exists, so it cannot also be one of the pages that gate clears.
FORGE_CI_README = REPO / "integrations" / "github-issues" / "README.md"

# The pages whose commands are product surface: a reader copies them, so they
# have to be runnable as printed. A ``.sh`` entry point belongs to bash; only a
# ``.py`` entry point runs under an interpreter.
DOC_PAGES: tuple[Path, ...] = (
    README,
    CONTRIBUTING,
    QUICKSTART,
    ONBOARDING,
    PRODUCT,
    PUBLISHING,
)

# The three core skills, each named by the path of the page a loader reads. The
# onboarding page has to name all three literally (issue #73 AC1), so the names
# live here as data beside the page set rather than as strings inside one test:
# the reader that builds a skill directory list and the test that pins the page
# then agree on one list, and a fourth core skill is a failure in both places.
SKILL_NAMES: tuple[str, ...] = ("steering-ledger", "direction", "census")
SKILL_PAGE_PATHS: tuple[str, ...] = tuple(f"skills/{name}/SKILL.md"
                                          for name in SKILL_NAMES)
SKILL_PAGES: tuple[Path, ...] = tuple(sorted((REPO / "skills").rglob("*.md")))

# The state directory the quickstart's second route clones into the project.
STATE_DIR = ".noni-state"

# The first push Route B prints. Held here, beside the state directory it acts on,
# because three readers need the same string: the prose test below, the golden list
# in ``quickstart_golden`` (which is what makes the page's line the reviewed line),
# and ``tests/test_quickstart.py``, which runs it and reads the upstream back.
# ``HEAD`` rather than a branch name: a fresh ``git init`` need not default to
# ``main``, and the page cannot know the reader's branch (pilot point 4).
FIRST_PUSH_COMMAND = f"git -C {STATE_DIR} push -u origin HEAD"

# The state-repository rule, as the facts a page must state (pilot point 5). The
# census's hygiene class reads every tracked file of the tree ``--repo`` names, so a
# state repository that also holds other work reports that work as direction. Both
# pages that sell the route -- the quickstart's Route B and ``docs/PRODUCT.md`` 7 --
# owe every fact, which is why they are one tuple rather than two prose searches.
STATE_REPO_LAYOUT_ONLY: tuple[str, ...] = (
    "a new, empty, private repository",
    "hygiene",
    "every tracked file",
    # The sentence's own words, in the order the sentence has them: a qualifier
    # dropped from either page leaves the bare name of the layout standing, which
    # is what a reader needs and what a looser phrase would let a page lose.
    "layout and nothing else",
)

# The three words the census renders for a deny-list class that did not run
# (``census_hygiene._denylist_state``), derived from the two product sources that
# write them rather than typed out again: the public_safety status names and the
# one literal the census adds for the comments-only file. The page that tells a
# reader to create the file has to name all three, because the third is the state
# a reader who created an empty file lands in and would not recognise from the
# word `absent`. A rename on either side changes this tuple, and the page fails.
def _denylist_state_words() -> tuple[str, ...]:
    """The inactive state words, read out of the two files that render them.

    ``public_safety`` owns the status names and ``census_hygiene`` owns the
    comments-only word, and both are read from source rather than imported: the
    census module pulls in a scanner this helper has no business loading.

    The status names come from the ``Literal`` annotation on
    ``DenylistResult.status`` -- the one declaration of the closed set -- with
    ``"ok"`` removed as the state a reader never sees in an "inactive" row.
    Reading it that way is what makes the derivation fail loudly: a status that
    is renamed, added or dropped changes this tuple and the pages that have to
    name all of them fail, instead of the tuple shrinking quietly around a word
    the page no longer documents. Both files are asserted to be the ones this
    helper believes they are, so a source that moved or reworded its declaration
    is a failure rather than an empty derivation.
    """
    hygiene = (REPO / "src" / "noni" / "census_hygiene.py").read_text(encoding="utf-8")
    safety = (REPO / "src" / "noni" / "public_safety.py").read_text(encoding="utf-8")
    empty = re.search(r'return "([^"]+)" if not getattr\(denylist, "entries"', hygiene)
    assert empty, "census_hygiene no longer renders a comments-only deny-list word"
    declared = re.search(r"status:\s*Literal\[([^\]]+)\]", safety)
    assert declared, (
        "public_safety no longer declares DenylistResult.status as a Literal, so "
        "this helper has no source for the deny-list states the page must document")
    named = tuple(word.strip().strip('"').strip("'")
                  for word in declared.group(1).split(","))
    assert all(named), f"public_safety declares an empty deny-list status name: {named}"
    assert "ok" in named, (
        f"public_safety's DenylistResult.status no longer names the active state "
        f"'ok', so this helper cannot subtract it from the set: {named}")
    inactive = tuple(word for word in named if word != "ok")
    assert set(inactive) >= {"absent", "corrupt"}, (
        f"public_safety no longer names the deny-list statuses this page must "
        f"document: {inactive}")
    return (*inactive, empty.group(1))


# The three words, in the order the page lists them. The expected set is stated
# here as data rather than asserted at import: a module-level ``assert`` would red
# every module that imports this one (both quickstart test modules, the promises
# test, the try-it harness) for a problem that is one test's claim, and a failed
# import is a collection error that hides the message. The exact-set comparison is
# ``test_the_deny_list_state_words_are_exactly_the_documented_set``, and
# ``DENYLIST_STATES`` below is what it reads.
_EXPECTED_DENYLIST_STATES: tuple[str, ...] = ("absent", "corrupt", "present but empty")

DENYLIST_STATES: tuple[str, ...] = _denylist_state_words()


def expected_denylist_states() -> tuple[str, ...]:
    """The closed set of inactive state words any page must name.

    A function rather than a bare constant so the comparison happens at assertion
    time, in the test that owns the claim, and its message reaches the reader as a
    failure rather than as an import error.
    """
    return _EXPECTED_DENYLIST_STATES

# One line of the page's gh + jq recipe: the filter that turns tracker output
# into the map the census accepts. Matched by the two conversions it owes the
# census's reader, so a rewrite that drops either stops matching rather than
# matching something narrower.
ISSUE_STATE_RECIPE = re.compile(
    r"(?=[^\n]*tostring)(?=[^\n]*ascii_downcase)(?=[^\n]*from_entries)[^\n]*")

# The filter text the recipe quotes, as the page prints it: the two conversions
# above are the whole of its correctness, so both tests (the one that runs it and
# the one that pins the command line around it) locate the same string.
ISSUE_STATE_FILTER = (
    "map({key: (.number | tostring), value: (.state | ascii_downcase)}) | from_entries")


def issue_state_from_page() -> str:
    """The quickstart's jq filter text, read out of the page rather than copied.

    Located by :data:`ISSUE_STATE_RECIPE` and then by the quote that carries the
    filter, so a page that reworded the recipe into prose fails here instead of
    letting a recipe test read a filter out of thin air.
    """
    joined = ISSUE_STATE_RECIPE.search(QUICKSTART.read_text(encoding="utf-8"))
    assert joined is not None, (
        "the page no longer carries a jq recipe that builds a map with tostring "
        "and ascii_downcase")
    match = re.search(r"'([^']*from_entries[^']*)'", joined.group(0))
    assert match, (
        f"the recipe's filter is not quoted where the page prints it: {joined.group(0)!r}")
    return match.group(1)


def bash_blocks_text(text: str) -> list[list[str]]:
    """The bash fences of one page's text, for a caller that already read it."""
    return fenced_blocks(text, info="bash")


def section_body(text: str, heading_start: str) -> str:
    """The body of the first ``##`` section whose heading starts with ``heading_start``.

    Matched by prefix so a heading may carry a qualifier
    (``Route A: state inside the project``) without the caller having to repeat
    it; a section that does not exist is the failure it is.
    """
    start = text.find(f"## {heading_start}")
    assert start >= 0, f"the page has no '## {heading_start}...' section"
    rest = text[start:]
    following = re.search(r"\n## ", rest[1:])
    return rest if following is None else rest[:following.start() + 1]
