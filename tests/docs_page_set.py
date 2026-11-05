"""The page set the docs promise tests read, and the two readings they share.

``tests/docs_promises.py`` owns *where* the docs tests look (the paths) and the strings
they agree on. This module adds the one thing the install claims and the deny-list
claims both need and neither should redeclare: the pages opened once, as
``(path, text)`` pairs, plus the two shorthands every test over them uses -- a label for
the failure message and the bash fences of a page already read.

Split from ``tests/test_docs_promises.py`` for the same reason that module split its
install claims into ``tests/test_docs_install_promises.py``: the 500-line cap in
``tests/test_file_size_limit.py``, along the seam of one promise per module. Kept as a
helper rather than duplicated because a page set that two gate modules hold separately
can drift -- one gains ``docs/PUBLISHING.md``, the other does not, and a page stops
being gated without anything turning red.

No assertion lives here: those stay with the test that makes them.
"""

from __future__ import annotations

from pathlib import Path

from docs_commands import read
from docs_promises import DOC_PAGES, SKILL_PAGES

# Every page whose commands a reader may copy, as (path, text) pairs, read once.
ALL_PAGES: tuple[tuple[Path, str], ...] = tuple(
    (path, read(path)) for path in (*DOC_PAGES, *SKILL_PAGES)
)


def label(path: Path) -> str:
    """A page's path relative to the repository, for a failure that names it."""
    from docs_promises import README

    return str(path.relative_to(README.parent))


# Kept under the underscore alias the existing tests call it by, so the two modules
# read the same function rather than one wrapping the other.
_label = label


def bash_of(text: str) -> list[list[str]]:
    """The bash fences of one page already read, as lines."""
    from docs_promises import bash_blocks_text

    return bash_blocks_text(text)
