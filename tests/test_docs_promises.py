"""What the docs promise about the things a first run meets, checked as text.

``tests/test_quickstart.py`` runs the quickstart's commands. This module reads
the same pages for the claims a command cannot settle, over the one set of files
the issue named: the README, CONTRIBUTING, ``docs/*.md`` and every page under
``skills/``. The install claims -- no package index, no system Python, the README's
pointer -- live in ``tests/test_docs_install_promises.py``, which reads the very
same page set through ``tests/docs_page_set.py``; the split is the 500-line cap in
``tests/test_file_size_limit.py``, along the seam of one promise per module. Three
claims remain here, each of which was the cause of a real first-run failure an
agent hit by following only the docs:

- **The shell shims are shown as shell.** ``census.sh`` and
  ``census-sessions.sh`` are bash scripts; a page that shows one under
  ``python3`` hands the reader a Python traceback instead of the exit-code
  contract the same page documents. Conversely the ``.py`` entry points are
  shown under an interpreter, because that is how the README launches them.
- **Where a reader meets ``--strict`` and the hygiene class, the deny-list is
  named.** The file, its location, its purpose, and the three states in which
  creating it does not yet switch the class on -- including the one a reader
  who "just made the file" lands in.
- **The quickstart is reachable and carries its two recipes.** The README links it
  by exact path, the ``--issue-state`` recipe is printed with every flag the
  census's reader needs, and the state route is named the way the code names it.

Each check reads the product's own constants rather than a copy of them, so the
page that drifts fails and the product that renames fails, in the same place.
"""

from __future__ import annotations

import re

import pytest
from docs_commands import block_commands, read
from docs_page_set import ALL_PAGES, _label, bash_of
from docs_promises import (
    DENYLIST_STATES,
    ISSUE_STATE_FILTER,
    ISSUE_STATE_RECIPE,
    PUBLISHING,
    QUICKSTART,
    README,
    SKILL_PAGES,
    STATE_DIR,
    expected_denylist_states,
)

# A line that runs a shell script under an interpreter. ``python3 skills/x/y.py``
# is fine and expected; ``python3 .../census.sh`` is the failure.
_PYTHON_OVER_SH = re.compile(r"\bpython3?\b[^\n|;&]*?\S+\.sh\b", re.IGNORECASE)


def _command_lines(path: object, text: str) -> list[str]:
    """Every command line any fenced block of one page prints."""
    return [line for block in bash_of(text) for line in block]


# --- AC5: the shell shims are shown as shell --------------------------------

def test_no_doc_page_runs_a_shell_script_under_python() -> None:
    """No page names an interpreter in front of a ``.sh`` entry point.

    The two shims are bash (``census.sh`` needs jq, ``census-sessions.sh``
    execs ``NONI_PYTHON`` itself). Running either under ``python3`` dies on a
    brace before any check runs, so the reader gets a traceback where the page
    promised an exit code.
    """
    offenders = [(_label(path), line.strip())
                 for path, text in ALL_PAGES for line in _command_lines(path, text)
                 if _PYTHON_OVER_SH.search(line)]
    assert not offenders, f"pages run a shell script under python3: {offenders}"


@pytest.mark.parametrize("name", ("census.sh", "census-sessions.sh"))
def test_every_page_that_shows_a_shim_shows_it_as_bash(name: str) -> None:
    """Where a page prints one of the shims as a command, it prints it under
    ``bash`` or as a direct invocation -- never bare in a way that leaves the
    interpreter open to guess.

    The rule is per line rather than per page: a page may mention the shim in
    prose all it likes, and only the lines that put it in command position have
    to name how to run it.
    """
    pattern = re.compile(rf"(?<![\w/]){re.escape(name)}\s+\S")
    offenders: list[tuple[str, str]] = []
    for path, text in ALL_PAGES:
        for line in _command_lines(path, text):
            stripped = line.strip()
            if not pattern.search(stripped):
                continue
            if stripped.startswith("bash ") or "bash " in stripped.split(name)[0]:
                continue
            offenders.append((_label(path), stripped))
    assert not offenders, (
        f"pages print {name} in command position without showing bash: {offenders}"
    )


def test_the_sessions_shim_exit_3_row_names_its_own_interpreter() -> None:
    """The sessions census's exit-3 row names the interpreter it execs.

    Read as a plain "python3 not found", that row is what made the wrapper look
    like a Python script. It is not: exit 3 is the wrapper failing to find the
    interpreter it is about to exec, which is ``NONI_PYTHON`` when that is set.

    Scoped to a page that documents this shim's own exit-code table (a row
    rendering ``3`` and the double-claim row together): a page that mentions the
    shim in passing owes no table, and demanding one would push prose into
    places it does not belong.
    """
    table_marks = ("`30`", "double-claim")
    offenders = [_label(path) for path in SKILL_PAGES
                 if (page := read(path))
                 and "census-sessions" in page
                 and all(mark in page for mark in table_marks)
                 and "NONI_PYTHON" not in page]
    assert not offenders, (
        f"pages table the sessions shim's exit codes without naming NONI_PYTHON, "
        f"which is the interpreter exit 3 is about: {offenders}")


# --- AC3: the deny-list is named where a reader meets --strict --------------

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
    source = (README.parent / "src" / "noni" / "census_hygiene.py").read_text(encoding="utf-8")
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
    the class inactive.
    """
    from noni import public_safety

    quickstart = read(QUICKSTART)
    start = quickstart.find(public_safety.DENYLIST_FILENAME)
    assert start >= 0
    window = quickstart[start:start + 2000]
    assert "#" in window, "the deny-list section never shows the comment/entry form"
    assert re.search(r"\nexample|\n[a-z][a-z0-9.-]+\n", window), (
        "the deny-list section gives no minimal example entry")


# --- AC2/AC4: the quickstart is reachable and carries its two recipes -------

def test_the_quickstart_is_linked_from_the_readme_by_exact_path() -> None:
    """README names the page the way the README's own path gate can resolve it.

    ``tests/test_readme.py::test_every_path_the_readme_names_exists`` resolves
    every repo-relative token on the page, so the link has to be the literal
    path and not prose about a "quickstart".
    """
    readme = read(README)
    assert "docs/QUICKSTART.md" in readme, "README does not name the quickstart by path"
    assert QUICKSTART.is_file(), "docs/QUICKSTART.md is missing"


def test_the_readme_stays_within_its_own_cap_besides_the_link() -> None:
    """The quickstart link did not cost the README its size cap.

    The cap is the README test's own (``README_LINE_LIMIT``), re-checked here on
    the reading this module already did: AC2 asks for the quickstart on a page of
    its own precisely so the README keeps it.
    """
    from readme_support import README_LINE_LIMIT

    lines = read(README).count("\n")
    assert lines <= README_LINE_LIMIT, (
        f"README.md is {lines} lines; the cap is {README_LINE_LIMIT}")


def test_the_issue_state_recipe_carries_every_flag_the_reader_needs() -> None:
    """The one recipe the census has no producer for is pinned flag by flag.

    ``gh issue list`` defaults its fields and its output format, so a recipe that
    quietly lost ``--json number,state`` prints a table no ``jq`` filter reads and
    a recipe that lost the redirect leaves the map on the terminal instead of in
    the file ``--issue-state`` opens. The filter itself is pinned by
    ``tests/test_quickstart.py``, which runs it; this pins the command line around
    it, which nothing else can.
    The command is read as the page prints it (fence lines joined, before
    ``shlex`` strips the quoting), so a flag lost from the printed line is caught
    here while ``tests/test_quickstart.py`` runs the filter itself.
    """
    blocks = [" ".join(block) for block in bash_of(read(QUICKSTART))]
    recipe = [block for block in blocks
              if re.search(r"(?<![\w-])gh\s+issue\s+list\b", block)]
    assert len(recipe) == 1, (
        f"the quickstart must print exactly one gh issue list recipe, got {recipe}")
    joined = " ".join(recipe)
    for token in ("--json", "number,state", "--jq", "> issue-state.json"):
        assert token in joined, (
            f"the gh+jq recipe does not name {token!r} as printed: {joined!r}")
    assert ISSUE_STATE_FILTER in joined, (
        f"the recipe's filter is not the one the census's reader accepts: {joined!r}")


def test_the_issue_state_recipe_is_documented_once_and_named() -> None:
    """The gh + jq recipe exists, and the docs say what is skipped without it.

    Located by the two conversions the census's reader requires (see
    ``docs_promises.ISSUE_STATE_RECIPE``); the note text is checked against the
    product's own string so a rename fails the page.
    """
    from noni import census_report  # noqa: F401  (the module that holds and prints the note)

    source = (README.parent / "src" / "noni" / "census_report.py").read_text(encoding="utf-8")
    assert "ordering-closed was not evaluated" in source, "the note left the product"
    quickstart = read(QUICKSTART)
    assert ISSUE_STATE_RECIPE.search(quickstart), (
        "no page carries a gh+jq recipe that builds the map with tostring and "
        "ascii_downcase")
    assert "ordering-closed was not evaluated" in quickstart, (
        "the docs do not name the note the census prints without the file")
    assert "never contacts a tracker" in quickstart, "the docs do not say why"
    assert "json" in quickstart.lower(), "the docs do not say the note is human-mode only"


def test_the_state_route_is_named_the_way_the_code_names_it() -> None:
    """The state directory the quickstart sells is one the tools can be pointed at.

    ``.noni-state`` is this page's convention, not the product's, so the check
    is that every command in the route's blocks names it as a value and none of
    them relies on a mechanism the product does not have (no pointer file, no
    environment variable selecting a state root).
    """
    quickstart = read(QUICKSTART)
    assert STATE_DIR in quickstart, "the quickstart does not name the state directory"
    # The clone line names the directory as its target and nothing else may
    # reach the state tree except through --repo or an explicit -C: no pointer
    # file and no environment variable selects a state root (docs/PRODUCT.md 7).
    for line in _command_lines(QUICKSTART, quickstart):
        if STATE_DIR not in line or line.lstrip().startswith("#"):
            continue
        head = line.split("|")[0]
        ok = ("--repo" in head or "-C" in head or "echo" in head
              or "printf" in head
              or re.search(r"git clone\s+\S+\s+\.\S*\s*$", head.strip()))
        assert ok, (
            f"a state-route command does not name the state root explicitly: {line!r}")
    # docs/PRODUCT.md 7: no environment variable and no config file names the
    # state root, and there is no pointer file. The product's own variable set
    # is read from the package rather than copied here, so the only names a page
    # may offer the reader as selectors are the ones the code actually reads --
    # and none of them selects a state root.
    selectors = _product_env_vars()
    named = set(re.findall(r"\bNONI_[A-Z_]+\b", quickstart)) - selectors
    assert not named, (
        f"the quickstart names environment variables the product does not read, "
        f"which reads as a state-root selector: {sorted(named)}")
    assert not any(re.search(rf"\b{word}\b", quickstart)
                   for word in ("pointer file", "state root file", "noni.json")), (
        "the quickstart names a state-root selection mechanism the product does not have")


def _product_env_vars() -> set[str]:
    """Every ``NONI_*`` name the shipped package actually reads.

    Read off the source rather than hard-coded, so the page that invents a
    variable fails here and the product that adds one does not.
    """
    src = README.parent / "src" / "noni"
    found: set[str] = set()
    for path in sorted(src.glob("*.py")):
        found.update(re.findall(r"\bNONI_[A-Z_]+\b", path.read_text(encoding="utf-8")))
    return found


def test_the_publishing_checklist_still_owns_the_gate() -> None:
    """The deny-list prose moved into the reader's pages without leaving the
    operator's checklist behind: PUBLISHING remains the gate, and the quickstart
    says so rather than offering the census as a substitute.
    """
    publishing = read(PUBLISHING)
    assert "scripts/public_safety.py" in publishing, "the gate left the checklist"
    assert "docs/PUBLISHING.md" in read(QUICKSTART), (
        "the quickstart documents the deny-list without routing the reader to "
        "the checklist that actually gates on it")


def test_the_coexistence_section_offers_no_command_the_page_does_not_run() -> None:
    """The driver-coexistence section is prose, so it prints no fence of its own.

    Every command-bearing fence on the quickstart belongs to a section the golden
    command list covers, and this section's whole purpose is a position a reader
    takes rather than a step they type: a bash fence added under this heading would
    be a command the launcher never runs and no review covered, and the fence census
    in ``tests/test_quickstart.py`` catches it only because it compares the page's
    whole flattened list. The check belongs here too because it is a claim about
    this section: the position is documentation, and documentation that has grown a
    command line has grown something the suite does not run.
    """
    from docs_commands import fenced_pairs
    from docs_promises import section_body
    from quickstart_page import COEXISTENCE_HEADING

    body = section_body(read(QUICKSTART), COEXISTENCE_HEADING)
    blocks = [lines for info, lines in fenced_pairs(body) if info == "bash"]
    commands = [argv for lines in blocks for argv in block_commands(lines)]
    assert not commands, (
        f"the coexistence section prints {len(commands)} command(s), which the "
        f"golden list does not cover: {commands}"
    )


def test_the_forge_page_links_the_coexistence_position() -> None:
    """The forge copy links the coexistence section, because its own page sells claims.

    The generic step stays uncluttered: a team with no driver reads the quickstart
    and types the census line, and does not need a paragraph about a driver they do
    not run. The page that does need it is the forge copy -- the page whose own
    commands claim an issue before they work it, which is the exact situation the
    section addresses. It is read explicitly rather than through ``DOC_PAGES``
    because it is the one page the neutrality gate exempts, so a gate written over
    the core set stays green while this page drifts.
    """
    from docs_promises import FORGE_CI_README
    from quickstart_page import COEXISTENCE_HEADING

    example = read(FORGE_CI_README)
    # Located word by word with any run of whitespace between them: the forge page
    # wraps the link's heading text to its own column, exactly as the quickstart
    # page wraps its headings, and the words are the contract.
    heading = r"\s+".join(re.escape(word) for word in COEXISTENCE_HEADING.split())
    assert re.search(heading, example), (
        f"{FORGE_CI_README.name} claims issues without pointing at the page that "
        f"says what to do when a driver already keeps its own claims: name "
        f"{COEXISTENCE_HEADING!r} and link docs/QUICKSTART.md")
    assert "docs/QUICKSTART.md" in example, (
        f"{FORGE_CI_README.name} names the section without naming the page that "
        "carries it, so the link has nothing to resolve against")


def test_commands_the_pages_print_are_all_parseable() -> None:
    """Every fenced bash block on every page in scope lexes as commands.

    A block whose quoting does not close is a page a reader cannot copy, and
    the quickstart's runner would otherwise meet it as a harness error rather
    than a broken promise.
    """
    for path, text in ALL_PAGES:
        for block in bash_of(text):
            try:
                block_commands(block)
            except AssertionError as exc:
                pytest.fail(f"{_label(path)}: {exc}")
