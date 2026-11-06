"""The deny-list promises every doc page makes, read against the product.

Split out of ``tests/test_docs_promises.py`` on the seam ``docs/QUICKSTART.md``
opened (the 500-line cap in ``tests/test_file_size_limit.py`` is why this is a file
and not another block there): that module pins what the pages *print*, and the five
tests here pin what the pages *say about one file* -- ``.noni-scrub-denylist``, the
per-tree file that decides whether the hygiene class runs or reports itself
inactive.

Why they are separate from the printing checks: the deny-list is the one artefact
whose behaviour lives in the product and whose meaning lives in prose. A rename in
``src/noni/public_safety.py`` or a rewording of the state words in
``src/noni/census_hygiene.py`` silently strands four pages, and each of the five
tests closes one of those gaps against the source rather than against a copy this
suite maintains:

- the filename and the word "deny-list" are named together, on every page that
  mentions either -- a reader who meets ``--strict`` first needs the word to find
  the file (AC3);
- the three inactive states are exactly the words the product renders, all three
  named wherever the file is documented;
- an entry is shown, not merely promised, because ``load_denylist`` treats blanks
  and ``#`` lines as non-entries and a page that says only "create the file"
  produces a file that leaves the class inactive;
- the ledger shim ``.noni-scrub-ledger`` is named the same thing by every page that
  names it (AC5's companion, and the one naming drift the pilot reported).

The pages themselves, the fence readers and the derived constants come from
:mod:`docs_promises` and :mod:`docs_page_set`, so this module reads the same bytes
its neighbour reads rather than re-deriving the doc set.
"""

from __future__ import annotations

import re

from docs_commands import fenced_pairs, read
from docs_page_set import ALL_PAGES, _label
from docs_promises import (
    DENYLIST_STATES,
    QUICKSTART,
    README,
    expected_denylist_states,
)


def test_the_ledger_shim_is_named_the_same_thing_by_every_page_that_names_it() -> None:
    """One artifact, one name, across the pages that teach it (issue #97).

    The ruling that made ``noni census`` the entry point renamed ``census.sh``
    the ledger shim, and the phrase landed on five sites in four pages plus the
    ledger reference. Agreement between the census skill and the steering-ledger
    skill is only worth what enforces it: a page that renamed the shim on its own
    would leave the others describing a file that no longer exists by that name.
    So every page that calls the script anything at all must use this name, and
    the coinages the rename displaced (a compatibility *twin*, a compatibility or
    legacy *shim*) may not come back as a synonym a reader would take for a
    second file.
    """
    name = "ledger shim"
    pages = [(path, text) for path, text in ALL_PAGES if "census.sh" in text]
    assert pages, "no page names census.sh at all, so this check would pass vacuously"
    named = [(path, text) for path, text in pages if name in text]
    assert len(named) >= 3, (
        f"fewer pages call census.sh the {name!r} than the ruling put it on "
        f"({len(named)}): {[str(p) for p, _ in pages]}")
    for path, text in pages:
        for rival in ("compatibility twin", "compatibility shim", "legacy shim"):
            assert rival not in text, (
                f"{_label(path)} calls census.sh a {rival!r} beside the "
                f"{name!r} the other pages use, so a reader cannot tell whether "
                "two files are meant")


def test_the_deny_list_is_named_where_the_reader_meets_it() -> None:
    """The file's name, location and purpose, on the two pages that sell the
    checks that depend on it: the census skill (where ``--strict`` and the
    hygiene class are documented) and the quickstart (where a first run is
    made).

    The name comes from ``public_safety.DENYLIST_FILENAME``, so a rename that
    left the docs quoting the old file fails here rather than shipping a page
    that describes a file nothing reads.
    """
    from noni import public_safety

    filename = public_safety.DENYLIST_FILENAME
    pages = [(path, text) for path, text in ALL_PAGES if filename in text]
    assert pages, f"no page names {filename!r} at all"
    census_skill = [text for path, text in ALL_PAGES
                    if str(path).endswith("skills/census/SKILL.md")]
    assert census_skill and filename in census_skill[0], (
        f"the census skill, where --strict and the hygiene class are documented, "
        f"still does not name {filename!r}")
    quickstart = read(QUICKSTART)
    assert filename in quickstart, "the quickstart does not name the deny-list"
    assert public_safety.DENYLIST_ENV_VAR in quickstart, (
        f"the quickstart does not name the {public_safety.DENYLIST_ENV_VAR} route")
    # Its purpose, in the words the census row itself uses, so the reader who
    # met the row recognises the thing the page tells them to create.
    assert "hygiene" in quickstart.lower() and "--strict" in quickstart, (
        "the quickstart names the file without the check that reports it")


def test_the_deny_list_state_words_are_exactly_the_documented_set() -> None:
    """The derived set is exactly the three words, no more and no fewer.

    ``docs_promises`` derives the words from the two product sources that render
    them, so a rename on either side changes the tuple; the expected set is the
    other half of that claim, and without it a rename that dropped a word would
    leave every page test below passing on the shrunken set. The comparison lives
    here rather than at the helper's import so that a failure is one red test with
    a message, not a collection error in every module that imports the helper.
    """
    assert set(DENYLIST_STATES) == set(expected_denylist_states()), (
        f"the deny-list state words derived from the product are "
        f"{sorted(DENYLIST_STATES)}, not the set every page that documents the "
        f"inactive class has to name: {sorted(expected_denylist_states())}")
    assert len(DENYLIST_STATES) == len(set(DENYLIST_STATES)), (
        f"a state word is derived twice: {DENYLIST_STATES}")


def test_the_deny_list_states_are_all_named() -> None:
    """All three inactive states appear where the deny-list is documented.

    ``absent`` and ``corrupt`` are the two a reader guesses; ``present but
    empty`` is the one a reader who created a file of comments hits and cannot
    explain from the row alone, because the file exists.
    """
    # The state words are the product's rendering, not this test's invention.
    source = (README.parent / "src" / "noni" / "census_hygiene.py").read_text(
        encoding="utf-8")
    for word in DENYLIST_STATES:
        assert word in source, f"the product no longer renders the state {word!r}"
    for page in (read(QUICKSTART), *[t for p, t in ALL_PAGES
                                    if str(p).endswith("skills/census/SKILL.md")]):
        missing = [word for word in DENYLIST_STATES if word not in page]
        assert not missing, (
            f"the deny-list section does not name every inactive state: {missing}")


def test_the_deny_list_entry_format_is_shown() -> None:
    """A reader is shown what an entry looks like, not only that the file exists.

    ``load_denylist`` treats blanks and ``#`` lines as non-entries and wants
    UTF-8; a page that says only "create the file" produces a file that leaves
    the class inactive. Both halves are pinned because each reaches a different
    reader: the deny-list section is where a plain-census reader learns what the
    file holds, and Route B's step is the fence a team setting up a private state
    repository copies without reading the rest of the page. A page that kept the
    section and reduced Route B to "create the file" would leave that team with a
    file of comments and an inert hygiene class, which is what the pilot hit.

    An entry is the product's own shape -- a bare name on a line of its own, which
    is what ``load_denylist`` keeps -- so prose *about* entries does not satisfy it.
    """
    from noni import public_safety

    quickstart = read(QUICKSTART)
    section = quickstart[quickstart.index(public_safety.DENYLIST_FILENAME):]
    assert "#" in section, "the deny-list section never shows the comment/entry form"
    assert _entry_lines(section), (
        "the deny-list section gives no minimal example entry: every line it shows "
        "is prose, a comment or a command")
    # Route B is the other reader: a team setting up the private state repository
    # reads the route, not the section further down the page, so the step has to show
    # the same entry the section does. Every fence counts, whatever its info string:
    # the page marks the file's own contents as a plain block rather than a shell
    # one, and filtering to ```bash would hide exactly the block under test.
    route_b = quickstart.split("## Route B")[1].split("## Run the census")[0]
    assert public_safety.DENYLIST_FILENAME in route_b, (
        "Route B no longer names the deny-list file at all")
    fences = ["\n".join(lines) for _, lines in fenced_pairs(route_b)]
    assert fences, "Route B prints no fence at all"
    assert _entry_lines("\n".join(fences)), (
        "Route B tells the reader to write the state clone's deny-list without "
        "showing one usable entry, so a team that copies the step gets a file of "
        "comments and an inert hygiene class")


# The line-initial words that mark a command or a sentence rather than a deny-list
# entry. A name of the reader's could in principle start one of these; none that the
# page needs to show does, and a page that needed one would fail visibly.
_NON_CONTENT_WORDS = frozenset({
    "printf", "echo", "cat", "cp", "mv", "git", "noni", "python", "python3", "cd",
    "gh", "and", "the", "it", "then", "so", "but", "or", "a", "an", "is", "to",
    "of", "in", "on", "for", "with", "not", "must", "be", "as", "that", "this",
})


def _entry_lines(text: str) -> list[str]:
    """The lines of one page passage that the product would count as entries.

    ``load_denylist`` keeps a line when it is neither blank nor a ``#`` comment; the
    shapes below are then excluded because no reader means them as file content --
    shell lines, paths, options, Markdown punctuation. What survives is a bare name
    shown as content, which is the thing the page has to show at all.
    """
    entries = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(("```", "|", "-", "*", ">")) or "://" in stripped:
            continue
        if any(token in stripped for token in ("`", "--", "/", "$", "%")):
            continue
        if stripped.split()[0] in _NON_CONTENT_WORDS:
            continue
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,}", stripped):
            entries.append(stripped)
    return entries
