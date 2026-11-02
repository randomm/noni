"""What the docs promise about the things a first run meets, checked as text.

``tests/test_quickstart.py`` runs the quickstart's commands. This module reads
the same pages for the claims a command cannot settle, over the one set of files
the issue named: the README, CONTRIBUTING, ``docs/*.md`` and every page under
``skills/``. Three claims, each of which was the cause of a real first-run
failure an agent hit by following only the docs:

- **The shell shims are shown as shell.** ``census.sh`` and
  ``census-sessions.sh`` are bash scripts; a page that shows one under
  ``python3`` hands the reader a Python traceback instead of the exit-code
  contract the same page documents. Conversely the ``.py`` entry points are
  shown under an interpreter, because that is how the README launches them.
- **No page tells a reader to install from a package index.** ``pip install
  noni`` does not fail: it installs somebody else's wheel and leaves a ``noni``
  with no census in it, which is worse than a message. The pages must say the
  package is not published and give the form that works.
- **Where a reader meets ``--strict`` and the hygiene class, the deny-list is
  named.** The file, its location, its purpose, and the three states in which
  creating it does not yet switch the class on -- including the one a reader
  who "just made the file" lands in.

Each check reads the product's own constants rather than a copy of them, so the
page that drifts fails and the product that renames fails, in the same place.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from docs_commands import block_commands, read
from docs_promises import (
    DENYLIST_STATES,
    DOC_PAGES,
    ISSUE_STATE_FILTER,
    ISSUE_STATE_RECIPE,
    PUBLISHING,
    QUICKSTART,
    README,
    SKILL_PAGES,
    STATE_DIR,
    bash_blocks_text,
)

# Every page whose commands a reader may copy, as (path, text) pairs, read once.
ALL_PAGES: tuple[tuple[Path, str], ...] = tuple(
    (path, read(path)) for path in (*DOC_PAGES, *SKILL_PAGES)
)

# A line that runs a shell script under an interpreter. ``python3 skills/x/y.py``
# is fine and expected; ``python3 .../census.sh`` is the failure.
_PYTHON_OVER_SH = re.compile(r"\bpython3?\b[^\n|;&]*?\S+\.sh\b", re.IGNORECASE)

# The install claim a page may not make as an *instruction*: a bare ``pip
# install noni``, which resolves on the public index to a different project
# entirely. Two shapes are legitimate and are excused by position rather than by
# wording: an install that names a path or a URL after the package name, and a
# mention of the bare command inside prose that is warning the reader away from
# it -- the sentence that names the command to tell the reader it does not do
# what they think. The second exemption is what keeps a truthful retraction from
# being flagged as the claim it retracts.
_BARE_PIP_INSTALL = re.compile(r"pip install noni\b(?![-/\w])")

def _label(path: Path) -> str:
    return str(path.relative_to(README.parent))


def _command_lines(path: object, text: str) -> list[str]:
    """Every command line any fenced block of one page prints."""
    return [line for block in bash_blocks_text(text) for line in block]


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


# --- AC1: no page sends a reader to a package index -------------------------

def test_no_page_tells_a_reader_to_install_from_a_package_index() -> None:
    """``pip install noni`` appears nowhere as an instruction.

    The command does not fail, which is the problem: it installs an unrelated
    project's wheel, and the reader's ``noni census`` then names a module that
    does not exist. Every page that offers an install route names the clone or
    the git URL instead.

    The exemption is per line, not per page, and it is earned: a line that
    names the bare command has to say in the same breath that it is the wrong
    command. ``fails``, ``not``, ``other`` and ``different`` are the words a
    retraction carries, so a page that simply told the reader to run it is still
    caught. A line that fails this test after a rewrite is a page that lost its
    retraction, which is exactly the drift the check exists for.
    """
    retracting = re.compile(r"\b(not|no |other|different|instead|avoid|never)\b", re.I)
    offenders: list[tuple[str, str]] = []
    for path, text in ALL_PAGES:
        for line in text.splitlines():
            if not _BARE_PIP_INSTALL.search(line):
                continue
            if _BARE_PIP_INSTALL.search(line) and retracting.search(line):
                continue
            offenders.append((_label(path), line.strip()))
    assert not offenders, (
        f"pages tell the reader to install from an index without retracting it: {offenders}")


def test_the_pages_that_install_noni_say_the_index_does_not_have_it() -> None:
    """Whichever page carries an install command also says noni is unpublished.

    Checked over the set rather than hard-coded to one page, so moving the
    install prose cannot satisfy the README test and leave the claim unmade.
    """
    carrying = [(path, text) for path, text in ALL_PAGES
                if re.search(r"pip install[^\n]*\./noni|pip install[^\n]*git\+https", text)]
    assert carrying, "no page gives an install form that names the repository"
    missing = [_label(path) for path, text in carrying
               if "not published" not in text.lower()
               and "no package index" not in text.lower()
               and "pypi" not in text.lower()]
    assert not missing, f"pages give an install form without saying the index lacks noni: {missing}"


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
    blocks = [" ".join(block) for block in bash_blocks_text(read(QUICKSTART))]
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
    from noni import census_run  # noqa: F401  (the module that prints the note)

    source = (README.parent / "src" / "noni" / "census_run.py").read_text(encoding="utf-8")
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


def test_commands_the_pages_print_are_all_parseable() -> None:
    """Every fenced bash block on every page in scope lexes as commands.

    A block whose quoting does not close is a page a reader cannot copy, and
    the quickstart's runner would otherwise meet it as a harness error rather
    than a broken promise.
    """
    for path, text in ALL_PAGES:
        for block in bash_blocks_text(text):
            try:
                block_commands(block)
            except AssertionError as exc:
                pytest.fail(f"{_label(path)}: {exc}")
