"""The install precondition every page that prints a script command has to state.

The claim: a reader who copies ``scripts/order.py --repo REPO add ...`` out of a
``SKILL.md`` meets ``the noni package is not importable`` on a machine where noni was
never installed, because every wrapper under ``skills/*/scripts/`` is a shim that
imports the package and exits 3 when that import fails. So the pages that print such
a command owe one sentence naming the precondition, and the link to the page that owns
the install.

Split out of ``tests/test_docs_install_promises.py`` on the same seam that split that
module from ``tests/test_docs_promises.py``: one promise per module, under the
500-line cap in ``tests/test_file_size_limit.py``. That module's claims are about the
install commands no page may print; this module's claim is about the *script* commands
every page that prints them has to qualify.

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
PRECONDITION_SENTENCE = (
    "The wrappers under `skills/<skill>/scripts/` import the package, so it must be "
    "installed, installed editable, or importable via `PYTHONPATH=<clone>/src`; the "
    "commands are in the *Install noni* section of "
    "[docs/QUICKSTART.md](docs/QUICKSTART.md#install-noni)."
)


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

def test_the_gate_refuses_a_command_page_with_no_sentence(tmp_path: Path) -> None:
    """The pilot's page, planted: a bare script fence and no precondition anywhere.

    Built in a throwaway repository rather than edited into a real page, so the
    offender shape is asserted without touching the tree the other checks read. The
    tree is committed because the size gate measures a worktree against
    ``git ls-files``: an uncommitted plant is an offender for that gate, exactly as an
    uncommitted scratch file would be.

    The same page, carrying the sentence and the link, then has to pass: that half is
    what shows the gate refuses the missing sentence rather than the page's subject. A
    third state -- the sentence present, the link absent -- is reported by the gate's
    second assertion, so the two failures stay distinguishable.
    """
    repo = _init_repo(tmp_path / "probe")
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
        "The writer appends one row and commits it.", PRECONDITION_SENTENCE),
        encoding="utf-8")
    assert _verdicts(repo) == ([], []), (
        "the gate refuses a page that states the precondition and links the install")

    page.write_text(command_page.replace(
        "The writer appends one row and commits it.",
        PRECONDITION_SENTENCE.replace(
            "[docs/QUICKSTART.md](docs/QUICKSTART.md#install-noni)", "the quickstart")),
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
