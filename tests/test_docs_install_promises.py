"""The install precondition every page that prints a script command has to state.

The claim: a reader who copies ``scripts/claim.py --repo REPO --session-id SID`` out
of a ``SKILL.md`` meets ``the noni package is not importable`` on a machine where noni
was never installed, because every wrapper under ``skills/*/scripts/`` is a shim that
imports the package and exits 3 when that import fails. So the pages that print such a
command owe one sentence naming the precondition, and the link to the page that owns
the install.

This is the third file the docs promise suite has grown on the same seam:
``tests/test_docs_promises.py`` pins what the pages print, and split its install
commands into ``tests/test_docs_install_commands.py``, the deny-list into
``tests/test_docs_denylist_promises.py`` and the state route into
``tests/test_docs_state_route_promises.py``, each under the 500-line cap in
``tests/test_file_size_limit.py``. The install module keeps the claims about the
commands no page may print; the claim here is about the *script* commands every page
that prints them has to qualify, and the two share the subject -- installing noni --
which is why the file carries this name rather than a new one.

The page set is shared rather than redeclared (``tests/docs_page_set.py``), so a page
that joins the docs suite is gated the day it lands. The reading half lives in
``tests/docs_precondition.py``.

Four claims:

- **Every page that prints a script command states the precondition and links the
  install section**, per page rather than per fence: one sentence beside the first
  command covers the commands after it, which is what the issue asks for.
- **The reader is proven to see the commands.** The gate above is satisfied by the
  absence of commands, so the reading half is exercised against each shape the real
  pages print, in the fence tags the real pages use.
- **The offender shape is proven on a planted page**, so the gate cannot rest on a
  page set that quietly stopped matching the rule.
- **The exempt page still carries the prose** the other pages link.
"""

from __future__ import annotations

import re
from pathlib import Path

import docs_precondition
import pytest
from _harness import _git, _init_repo
from docs_commands import read
from docs_page_set import ALL_PAGES, _label
from docs_precondition import (
    has_install_precondition,
    quickstart_install_link,
    script_entry_points,
)
from docs_promises import QUICKSTART, section_body

# The sentence the pages owe, as the gate reads it and as the fix writes it. Both
# facts are required because the failure a reader meets names only one of them: a
# wrapper whose package is missing says it is "not importable", and the route out is an
# install. Held here so the planted page below and the real pages are measured against
# one wording.
# The anchor's page, spelled from the page that owns the link: the quickstart's own
# path, then the anchor. Written this way so the sentence can be planted at any depth
# under a tree, which is where the non-vacuity rows below put it -- see
# ``_install_link_from`` for what each page's own directory has to contribute.
_INSTALL_LINK = "[Install noni](docs/QUICKSTART.md#install-noni)"
PRECONDITION_SENTENCE = (
    "The wrappers under `skills/<skill>/scripts/` import the package, so it must be "
    "installed, installed editable, or importable via `PYTHONPATH=<clone>/src`; the "
    "commands are in the *Install noni* section of "
    + _INSTALL_LINK + "."
)


def _install_link_from(depth: int) -> str:
    """The install link as a page in ``depth`` directories below the root must write it.

    The gate resolves a relative href against the linking page's own directory, so the
    correct form is a function of where the page sits: a page in ``skills/x/`` (two
    directories deep) needs ``../../docs/QUICKSTART.md``, a page at the root needs
    ``docs/QUICKSTART.md``, and a page under a link farm's ``x/y/`` needs three. A page
    that wrote the root form from ``skills/<skill>/references/`` aimed at
    ``skills/<skill>/references/docs/QUICKSTART.md``, which is no page at all, and only
    a resolver catches that.
    """
    return "[Install noni](" + "../" * depth + "docs/QUICKSTART.md#install-noni)"


def _quickstart_tree(repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A committed ``docs/QUICKSTART.md`` carrying the anchor the links point at.

    The planted tree plays the role of the repository for the tests that need a real
    link target, so the page the gate treats as exempt is pointed at the plant for the
    duration of the test and restored by the fixture. It is routed through
    ``monkeypatch`` rather than a plain assignment because a bare module global leaks
    into every later test in the session, which would hand the exemption to whichever
    page happened to share the plant's path. The path is resolved the way the gate
    resolves it, so a tree reached through a symlink still compares equal.
    """
    docs = repo / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    page = docs / "QUICKSTART.md"
    page.write_text("# Quickstart\n\n## Install noni\n\nbody\n", encoding="utf-8")
    _commit_tree(repo)
    quickstart = page.resolve() if page.is_file() else page
    monkeypatch.setattr(docs_precondition, "QUICKSTART", quickstart)
    return page


# --- AC1: the sentence every page with a command owes ---------------------------

def test_every_page_printing_a_script_command_states_the_install_promise() -> None:
    """A script in command position buys a precondition sentence on the same page.

    Per page rather than per fence: the issue asks for the sentence beside the first
    command, and a page printing four verbs of one writer says the same thing about all
    four. What the page owes is both facts (installed, or importable on ``PYTHONPATH``)
    and the route to the install -- ``docs/QUICKSTART.md``'s *Install noni* section, by
    anchor, so the link resolves against the heading that carries the prose rather than
    against the top of the page.

    A page with no command in it is not asserted: the reader proof below is what shows
    a page set that stopped matching the rule cannot leave this green.
    """
    offenders: list[tuple[str, list[str]]] = []
    unlinked: list[str] = []
    for path, text in ALL_PAGES:
        entry_points = sorted({name for name, _line in script_entry_points(text)})
        if not entry_points:
            continue
        if not has_install_precondition(text):
            offenders.append((_label(path), entry_points))
        elif not quickstart_install_link(text, path=path):
            unlinked.append(_label(path))
    assert not offenders, (
        f"pages print a script entry point without stating that the noni package "
        f"must be installed or importable: {offenders}")
    assert not unlinked, (
        f"pages state the precondition without linking the section that owns the "
        f"install (docs/QUICKSTART.md#install-noni): {unlinked}")


def test_the_quickstart_states_the_precondition_its_pages_link() -> None:
    """The page every other page points at still says it.

    The quickstart's command fences belong to the golden list in
    ``tests/quickstart_golden.py`` and are run by ``tests/test_quickstart.py``, so this
    module does not gate them. What it does gate is the paragraph those links resolve
    to: a page that sends a reader to *Install noni* for the precondition has to arrive
    at a section that states it.
    """
    body = section_body(read(QUICKSTART), "Install noni")
    assert has_install_precondition(body), (
        "the Install noni section no longer states the precondition the skill pages "
        "point a reader here for")


# --- the reader is proven to see what the gate refuses -------------------------

# Each row is a page that must produce a finding: the command shapes the real pages
# carry, inside the fence tags the real pages use. Held as data because a reader that
# matched one shape and missed the rest would leave the gate above green on a page set
# that stopped matching the rule.
_COMMAND_SHAPES: tuple[tuple[str, str, str], ...] = (
    ("an untagged fence with the bare script form",
     "```", "scripts/order.py --repo REPO add 7 --decision 2026-01-01-x"),
    ("an untagged fence with the bash shim form",
     "```", "bash scripts/census.sh <state-root>/noni/decisions"),
    ("a bash-tagged fence with the interpreter form",
     "```bash", "python3 skills/census/scripts/census.py --repo REPO"),
    ("a command continued with a backslash",
     "```", "scripts/decide.py --repo REPO --slug s \\"),
    ("a script run from an expanded clone path",
     "```", "<clone>/skills/census/scripts/census.py --repo ."),
    ("a wrapper reached through a relative clone path",
     "```", "python3 ../noni/skills/steering-ledger/scripts/decide.py --repo ."),
    ("the module form, which names a package and not a script path",
     "```bash", "PYTHONPATH=<clone>/src python3 -m noni census --repo ."),
)


@pytest.mark.parametrize("row", _COMMAND_SHAPES, ids=[row[0] for row in _COMMAND_SHAPES])
def test_the_reader_finds_a_script_command_in_every_shape_the_pages_use(
    row: tuple[str, str, str]
) -> None:
    """Every command shape the pages print is a finding for the reader.

    The gate above is satisfied by the absence of commands, so the reading half needs
    its own proof. The fence tags matter: every command fence under ``skills/`` is
    untagged, so a reader that reused the suite's bash-only fence helper would find
    nothing in those pages and report a clean documentation set.
    """
    description, opener, command = row
    text = f"# A page\n\n{description}\n\n{opener}\n{command}\n```\n"
    found = script_entry_points(text)
    if _MODULE_FORM.search(command):
        # The one row the reader must find nothing in: ``-m`` names a module, so no
        # file path is in command position and the page's own install sentence is the
        # only thing the reader can check. Asserting the absence here is what keeps
        # the row from being satisfied by the ``.py`` of a neighbouring path.
        assert found == [], f"the reader read a module run as a script: {found}"
        return
    assert found, f"the reader missed {description}: {text!r}"
    assert any(name.endswith((".py", ".sh")) for name, _line in found), (
        f"the reader named no entry point for {description}: {found}")
    assert all(name.endswith((".py", ".sh")) for name, _line in found), (
        f"the reader named something that is not a script for {description}: {found}")


# The console form the pages print beside the script form: an interpreter running the
# package as a module. No script path is in command position, so the page that offers
# only this form owes no script precondition.
_MODULE_FORM = re.compile(r"\s-m\s")


def test_the_reader_does_not_read_prose_as_a_command() -> None:
    """A script name in a sentence is not a run, so it owes no sentence.

    The pages discuss their writers in prose constantly (``scripts/decide.py`` is the
    only writer; the claim reference names it again). A gate that charged every mention
    would be satisfied only by pushing the prose into fences, which the fence censuses
    in ``tests/test_onboarding.py`` and ``tests/test_quickstart.py`` refuse. So the
    reader has to be narrow, and the narrowness is asserted rather than trusted: each
    line below is a form a real page carries in running text.
    """
    prose = (
        "# A page\n\n"
        "Records are written with `scripts/decide.py`, which is the only writer, and\n"
        "`scripts/census.sh` is the ledger shim. The table lists `scripts/claim.py`.\n\n"
        "- run it as `bash scripts/census.sh <dir>`, never under `python3`\n"
    )
    assert script_entry_points(prose) == [], script_entry_points(prose)
    # And the console route is not a script command either: the page that shows
    # `noni <verb>` has sent the reader to the installed command, which is the state
    # the precondition exists to describe.
    assert script_entry_points("# P\n\n```bash\nnoni order --repo REPO add 7\n```\n") == []


# --- the offender shape is proven on a planted page ----------------------------

def test_the_gate_refuses_a_command_page_with_no_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pilot's page, planted: a bare script fence and no precondition anywhere.

    Built in a throwaway repository rather than edited into a real page, so the
    offender shape is asserted without touching the tree the other checks read. The
    tree is committed because the size gate measures a worktree against
    ``git ls-files``: an uncommitted plant is an offender for that gate, exactly as an
    uncommitted scratch file would be. A ``docs/QUICKSTART.md`` carrying the anchor is
    planted beside it so the link half has a real target to resolve to, and the
    passing form of the link is the one ``skills/probe-skill/`` has to write -- two
    directories below the root.

    The same page, carrying the sentence and the link, then has to pass: that half is
    what shows the gate refuses the missing sentence rather than the page's subject. A
    third state -- the sentence present, the link absent -- is reported by the gate's
    second assertion, so the two failures stay distinguishable.
    """
    repo = _init_repo(tmp_path / "probe")
    _quickstart_tree(repo, monkeypatch)
    skill = repo / "skills" / "probe-skill"
    skill.mkdir(parents=True)
    command_page = (
        "# Claiming\n\n"
        "```\nscripts/claim.py --repo REPO --session-id SID --task TASK\n```\n\n"
        "The writer appends one row and commits it.\n"
    )
    page = skill / "SKILL.md"
    page.write_text(command_page, encoding="utf-8")
    _commit_tree(repo)
    assert _verdicts(repo)[0] == ["skills/probe-skill/SKILL.md"], (
        "the gate let a bare script command through with no precondition on the page")

    page.write_text(command_page.replace(
        "The writer appends one row and commits it.",
        PRECONDITION_SENTENCE.replace(_INSTALL_LINK, _install_link_from(2))),
        encoding="utf-8")
    assert _verdicts(repo) == ([], []), (
        "the gate refuses a page that states the precondition and links the install")

    page.write_text(command_page.replace(
        "The writer appends one row and commits it.",
        PRECONDITION_SENTENCE.replace(_INSTALL_LINK, "the quickstart")),
        encoding="utf-8")
    assert _verdicts(repo) == ([], ["skills/probe-skill/SKILL.md"]), (
        "a page with the sentence and no link is not reported by the link assertion")


def _verdicts(root: Path) -> tuple[list[str], list[str]]:
    """The gate's two lists, built over a planted tree instead of ``ALL_PAGES``.

    The same three readers the page-set test calls, so the plant is evidence about that
    gate and not about a second implementation of it. Labels are paths relative to the
    tree the caller handed, the shape the real gate's labels take.
    """
    offenders: list[str] = []
    unlinked: list[str] = []
    for path in sorted(root.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        if not script_entry_points(text):
            continue
        if not has_install_precondition(text):
            offenders.append(str(path.relative_to(root)))
        elif not quickstart_install_link(text, path=path):
            unlinked.append(str(path.relative_to(root)))
    return offenders, unlinked


def _commit_tree(repo: Path) -> None:
    """Commit the planted tree so the size gate's listing sees exactly it."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "planted")


def test_the_promise_survives_a_rewrap_and_dies_on_a_dropped_fact() -> None:
    """The reader compares words across wraps, so the pages stay writable.

    Every page under ``skills/`` is wrapped at ~80 columns and the reference pages
    rewrap constantly. A reader that matched the sentence as one literal would make a
    reflow of the docs a red test, and the cheapest way out of that is a shorter
    sentence that drops a fact. So the sentence is planted here broken onto its own
    line at every word and has to read as stated -- and each fact, dropped on its own,
    has to read as not stated. Without the second half the reader could be satisfied by
    a page that kept the install and lost the importability.
    """
    assert has_install_precondition(PRECONDITION_SENTENCE.replace(" ", "\n")), (
        "the reader needs the sentence on one line, which makes rewrapping the docs a "
        "failure and invites a page to shorten the sentence instead")
    for fact in ("installed", "importable"):
        dropped = " ".join(word for word in PRECONDITION_SENTENCE.split()
                           if fact not in word)
        assert not has_install_precondition(dropped), (
            f"a sentence with no {fact} still reads as the precondition")
    assert quickstart_install_link(PRECONDITION_SENTENCE)
    assert not quickstart_install_link(
        PRECONDITION_SENTENCE.replace("#install-noni", "")), (
        "a sentence that names the quickstart without the install anchor counts as the "
        "link")


# --- the link half is proven on the shapes a page can carry it wrong ------------

# Each row is a page state that must NOT satisfy the link gate, with the reason the
# gate owes the reader. The real pages got all three wrong at once when the sentence
# landed: nine pages wrote the root-relative form of the href, which resolves inside
# ``skills/<skill>/references/`` to a file that has never existed, and the words were
# present as well, so a gate that looked for the words was green.
@pytest.mark.parametrize("form", (
    pytest.param("wrong-base", id="a link whose base is the repo root, not the page"),
    pytest.param("inline-code", id="the target spelled as inline code, not a link"),
    pytest.param("no-anchor", id="a link to the page with no section anchor"),
))
def test_the_link_gate_refuses_a_link_the_reader_cannot_follow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str
) -> None:
    """Each wrong shape of the install link is a finding, not a pass.

    Planted one directory deep (``skills/probe-skill/references/``) next to a
    ``docs/QUICKSTART.md`` that carries the anchor, so the only thing deciding the
    verdict is the href: the file exists, the anchor exists, the sentence exists.
    """
    repo = _init_repo(tmp_path / "probe")
    _quickstart_tree(repo, monkeypatch)
    page_dir = repo / "skills" / "probe-skill" / "references"
    page_dir.mkdir(parents=True)
    sentence = PRECONDITION_SENTENCE.replace(_INSTALL_LINK, {
        # The form every real page carried: written for the root, resolved from here.
        "wrong-base": _INSTALL_LINK,
        # The promise named in the reader's vocabulary but not linked: nothing to follow.
        "inline-code": "`docs/QUICKSTART.md#install-noni`",
        # The right file, the wrong section: lands on the top of a long page.
        "no-anchor": "[docs/QUICKSTART.md](../../../docs/QUICKSTART.md)",
    }[form])
    page = page_dir / "claim.md"
    page.write_text("# Claiming\n\n" + sentence + "\n", encoding="utf-8")
    _commit_tree(repo)
    assert not quickstart_install_link(page.read_text(encoding="utf-8"), path=page), (
        f"the gate accepted {form}, which leaves the reader no link to follow")


def test_the_link_gate_accepts_the_form_each_page_depth_has_to_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resolved form passes at the depth it was written for, and only there.

    The positive half of the row above, and the reason the depth is a parameter rather
    than a constant: a gate that only ever saw the root form would accept a reference
    page that links nothing and refuse one that links correctly.

    The exemption for the quickstart's own path has to be switched off here: depth 0
    plants its page in ``docs/``, the same directory the quickstart itself sits in, and
    a fixture whose subject is other pages' links must not be answered by the rule for
    one page. The exempt page itself is asserted on its own below, where the plant is
    the exempt page rather than a neighbour of it.
    """
    repo = _init_repo(tmp_path / "probe")
    _quickstart_tree(repo, monkeypatch)
    monkeypatch.setattr(docs_precondition, "QUICKSTART", Path("/__no_such_page__.md"))
    for depth in (0, 1, 2, 3):
        page_dir = repo
        for part in ("a", "b", "c")[:depth]:
            page_dir = page_dir / part
        page_dir.mkdir(parents=True, exist_ok=True)
        page = page_dir / "page.md"
        page.write_text(PRECONDITION_SENTENCE.replace(_INSTALL_LINK,
                                                      _install_link_from(depth)),
                        encoding="utf-8")
        assert quickstart_install_link(page.read_text(encoding="utf-8"), path=page), (
            f"the gate refuses the correct link from depth {depth}, so a page has no "
            f"form it can write to satisfy it: {page}")
        if depth:
            # The same bytes one level up resolve to a directory that holds no
            # quickstart, which is the mistake the real pages made in reverse.
            shallow = page_dir.parent / "shallow.md"
            shallow.write_text(PRECONDITION_SENTENCE.replace(_INSTALL_LINK,
                                                             _install_link_from(depth)),
                               encoding="utf-8")
            assert not quickstart_install_link(shallow.read_text(encoding="utf-8"),
                                               path=shallow), (
                f"a link written for depth {depth} passes from its parent, so the gate "
                "is not resolving hrefs against the page's own directory")


def test_the_link_gate_needs_the_anchor_to_be_a_heading_in_the_target(
    tmp_path: Path
) -> None:
    """A target file without the heading is not the section the reader was sent to.

    The anchor is the half of the link that survives a page rewrite least well: rename
    the heading and every link on every page points at the top of the document. The
    gate reads the target, so a heading rename that orphans the links turns the pages
    red rather than the reader's browser.
    """
    repo = _init_repo(tmp_path / "probe")
    docs = repo / "docs"
    docs.mkdir(parents=True)
    (docs / "QUICKSTART.md").write_text("# Quickstart\n\n## Getting it\n\nbody\n",
                                        encoding="utf-8")
    _commit_tree(repo)
    page = repo / "page.md"
    page.write_text(PRECONDITION_SENTENCE, encoding="utf-8")
    assert not quickstart_install_link(page.read_text(encoding="utf-8"), path=page), (
        "a link whose anchor matches no heading in the target counts as the promise")


def test_the_link_gate_resolves_a_link_that_points_at_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The quickstart stays exempt, and the exemption is about that page alone.

    The exemption exists because the page cannot link the section it is standing in.
    A second page named QUICKSTART.md, or the quickstart judged at another path, must
    not inherit it, or one mis-named file would silence the gate over the whole set.
    """
    repo = _init_repo(tmp_path / "probe")
    _quickstart_tree(repo, monkeypatch)
    quickstart = repo / "docs" / "QUICKSTART.md"
    assert quickstart_install_link("no link at all", path=quickstart), (
        "the quickstart is charged for a link it cannot write")
    lookalike = repo / "skills" / "QUICKSTART.md"
    lookalike.parent.mkdir(parents=True)
    lookalike.write_text("# Quickstart\n\nnothing here\n", encoding="utf-8")
    assert not quickstart_install_link("no link at all", path=lookalike), (
        "a page that merely shares the quickstart's file name is exempt from the "
        "link")
