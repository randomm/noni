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
PRODUCT = REPO / "docs" / "PRODUCT.md"
PUBLISHING = REPO / "docs" / "PUBLISHING.md"

# The pages whose commands are product surface: a reader copies them, so they
# have to be runnable as printed. A ``.sh`` entry point belongs to bash; only a
# ``.py`` entry point runs under an interpreter.
DOC_PAGES: tuple[Path, ...] = (
    README,
    CONTRIBUTING,
    QUICKSTART,
    PRODUCT,
    PUBLISHING,
)
SKILL_PAGES: tuple[Path, ...] = tuple(sorted((REPO / "skills").rglob("*.md")))

# The state directory the quickstart's second route clones into the project.
STATE_DIR = ".noni-state"

# The three words the census renders for a deny-list class that did not run
# (``census_hygiene._denylist_state``), derived from the two product sources that
# write them rather than typed out again: the public_safety status names and the
# one literal the census adds for the comments-only file. The page that tells a
# reader to create the file has to name all three, because the third is the state
# a reader who created an empty file lands in and would not recognise from the
# word `absent`. A rename on either side changes this tuple, and the page fails.
def _denylist_state_words() -> tuple[str, ...]:
    """The inactive state words, read out of the two files that render them.

    ``public_safety`` owns the status names (``absent``, ``corrupt``) and
    ``census_hygiene`` owns the comments-only word. Both are read from source, not
    imported: the census module pulls in a scanner this helper has no business
    loading, and the words are what matters here.
    """
    hygiene = (REPO / "src" / "noni" / "census_hygiene.py").read_text(encoding="utf-8")
    safety = (REPO / "src" / "noni" / "public_safety.py").read_text(encoding="utf-8")
    empty = re.search(r'return "([^"]+)" if not getattr\(denylist, "entries"', hygiene)
    assert empty, "census_hygiene no longer renders a comments-only deny-list word"
    groups = re.findall(r'status: Literal\[([^\]]+)\]', safety)
    named = [word.strip().strip('"') for group in groups for word in group.split(",")]
    assert set(named) >= {"absent", "corrupt"}, (
        f"public_safety no longer names the deny-list statuses this page must "
        f"document: {named}")
    return tuple(word for word in ("absent", "corrupt") if word in named) + (
        empty.group(1),)


# Filled in here, once the reader above exists.
DENYLIST_STATES: tuple[str, ...] = _denylist_state_words()

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
