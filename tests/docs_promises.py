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
# (``census_hygiene._denylist_state``). The page that tells a reader to create
# the file has to name all three, because the third is the state a reader who
# created an empty file lands in and would not recognise from the word `absent`.
DENYLIST_STATES: tuple[str, ...] = ("absent", "corrupt", "present but empty")

# One line of the page's gh + jq recipe: the filter that turns tracker output
# into the map the census accepts. Matched by the two conversions it owes the
# census's reader, so a rewrite that drops either stops matching rather than
# matching something narrower.
ISSUE_STATE_RECIPE = re.compile(
    r"(?=[^\n]*tostring)(?=[^\n]*ascii_downcase)(?=[^\n]*from_entries)[^\n]*")


def bash_blocks(path: Path) -> list[list[str]]:
    """The bash fences of one page, as lines."""
    return fenced_blocks(path.read_text(encoding="utf-8"), info="bash")


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
