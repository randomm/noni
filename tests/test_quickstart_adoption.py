"""The adoption path the quickstart carries for an agent told to take noni into use.

``docs/QUICKSTART.md`` is that path (PM ruling 1: no new page). Above its first
section it lists the steps in order, each linking its own section, and after Route B
it ships the standing paragraph a project copies into its own agent instructions
file. ``tests/test_quickstart.py`` runs the page's commands; this module reads the
adoption half of the page as text, and pins the paragraph an agent copies byte for
byte against ``quickstart_adoption.STANDING_PARAGRAPH``.

Why exact-string rather than a phrase set: the acceptance is that the shipped text is
what lands in the project's instructions file, and a paragraph reworded to keep every
phrase still passes a phrase check while shipping something else.

Each rule of the issue is one test, so each can fail on its own.
"""

from __future__ import annotations

import re

from docs_commands import read
from docs_promises import QUICKSTART, README, STATE_DIR
from quickstart_adoption import (
    ADOPTION_LINK,
    QUICKSTART_LINE_LIMIT,
    README_LINE_LIMIT,
    STANDING_PARAGRAPH,
    STANDING_PARAGRAPH_MAX,
    ledger_page,
    readme_first_screen,
    standing_paragraph_as_shipped,
    wire_section,
    wire_section_flowed,
)
from quickstart_golden import COVERED_SECTIONS, GOLDEN, WIRE

# The steps the adoption paragraph owes, in order, each as the link target its own
# section carries. The order is the rule: an agent follows the list top to bottom.
ADOPTION_STEPS: tuple[str, ...] = (
    "#install-noni",
    "#the-state-root",
    "#route-a-state-inside-the-project",
    "#route-b-a-separate-private-state-repository",
    "#run-the-census-in-ci",
    "#wire-the-project",
)

# The two attribution flag sets the ledger page owes, as the writer spells them.
ATTRIBUTION_FLAG_SETS: tuple[str, ...] = (
    "--asked-by <agent> --decided-by <operator>",
    "--decided-by <agent> --on-behalf-of <operator>",
)


def _adoption_paragraph() -> str:
    """The adoption path the page carries, wrapping collapsed.

    The path is the page's own ``## Taking noni into use`` section, which sits above
    every command section: the list an agent follows first. Whitespace is collapsed,
    so the page's column budget cannot decide the answer.
    """
    from docs_promises import section_body
    from quickstart_page import flowed_text

    return flowed_text(section_body(read(QUICKSTART), "Taking noni into use"))


# --- the adoption paragraph -------------------------------------------------

def test_the_adoption_paragraph_lists_every_step_in_order() -> None:
    """The page opens with the path, and its steps link their own sections in order.

    Checked as positions rather than a set: an agent reads the list top to bottom, so
    a paragraph that names all six links in the wrong order is a page that sends the
    agent to wire the project before it has a state root.
    """
    flowed = _adoption_paragraph()
    assert "install noni and take it into use" in flowed, (
        "the page no longer addresses the agent it is written for")
    positions = [flowed.find(target) for target in ADOPTION_STEPS]
    assert -1 not in positions, (
        f"the adoption paragraph omits a step link: "
        f"{[t for t, p in zip(ADOPTION_STEPS, positions, strict=True) if p < 0]}")
    assert positions == sorted(positions), (
        f"the adoption steps are out of order: "
        f"{list(zip(ADOPTION_STEPS, positions, strict=True))}")


def test_the_adoption_paragraph_links_the_wire_section_that_exists() -> None:
    """Every step link lands on a heading the page actually carries.

    A renamed heading leaves the step pointing at nothing, which the paragraph itself
    cannot show; each link is matched against the page's own ``##`` headings.
    """
    headings = {re.sub(r"[^a-z0-9 -]+", "", h.lower()).replace(" ", "-")
                for h in re.findall(r"^## (.+)$", read(QUICKSTART), re.MULTILINE)}
    missing = [target for target in ADOPTION_STEPS
               if target.lstrip("#") not in headings]
    assert not missing, (
        f"a step links a section the page has no heading for: {missing}")


def test_the_adoption_paragraph_records_only_what_the_operator_decided() -> None:
    """Ruling 2, stated on the page: the walk records the two operator answers.

    The pilot's failure was a first run that invented direction, so the page says
    which records it writes and that it writes no open records by default.
    """
    flowed = _adoption_paragraph()
    for phrase in ("records only what the operator actually decided",
                   "state-root answer", "purpose",
                   "writes no open records by default"):
        assert phrase in flowed, (
            f"the adoption paragraph no longer says {phrase!r}")


def test_the_walk_writes_no_open_record_and_reuses_the_one_order_line() -> None:
    """No open record is written, and ordering is Route B's line, not a new one.

    Ruling 8: the walk adds no ``order add`` line of its own. The whole golden list
    is the page's command list, so counting the ordering lines there is counting what
    the page prints, and what the harness launches.
    """
    orders = [argv for label in GOLDEN for argv in GOLDEN[label]
              if argv[:2] == ["noni", "order"]]
    assert orders == [["noni", "order", "--repo", STATE_DIR, "add", "12",
                       "--decision", "<record-id>"]], (
        f"the page prints {len(orders)} ordering line(s); the adoption path reuses "
        f"Route B's and adds none: {orders}")


# --- the wire section and the standing paragraph ----------------------------

def test_the_wire_section_is_a_covered_golden_section() -> None:
    """The wire section is registered as its own golden section, and its list is the
    one brief line.

    A page section that gained a fence no key covers is a step nobody runs; the
    registration in ``quickstart_golden`` is what makes the walk launch it, so it is
    asserted here beside the text that depends on it.
    """
    assert WIRE in COVERED_SECTIONS, "the wire section is not a covered golden section"
    assert GOLDEN[WIRE] == [["noni", "brief", "--repo", STATE_DIR]], GOLDEN[WIRE]


def test_the_standing_paragraph_is_shipped_verbatim() -> None:
    """The page ships the paragraph exactly as the constant holds it.

    Compared on collapsed whitespace, because the page wraps for its own columns and
    the constant holds the words an agent copies: what may not change is the words,
    in this order, with this punctuation.
    """
    assert standing_paragraph_as_shipped() == STANDING_PARAGRAPH, (
        "the wire section's paragraph is no longer the shipped text, so a project "
        "copying it copies something else")


def test_the_standing_paragraph_is_short_and_carries_no_em_dash() -> None:
    """The paragraph is one paragraph of an instructions file, not a document, and no
    em dash: an agent copies it into a file its own gates may scan.
    """
    assert len(STANDING_PARAGRAPH) <= STANDING_PARAGRAPH_MAX, (
        f"the standing paragraph is {len(STANDING_PARAGRAPH)} characters; the cap is "
        f"{STANDING_PARAGRAPH_MAX}")
    assert "—" not in STANDING_PARAGRAPH, "an em dash in the shipped paragraph"


def test_the_wire_section_prints_the_brief_line_it_names() -> None:
    """The section that hands a project its standing paragraph also prints the read
    that paragraph tells a session to run.
    """
    from docs_commands import block_commands
    from docs_promises import bash_blocks_text

    printed = [argv for block in bash_blocks_text(wire_section())
               for argv in block_commands(block)]
    assert printed == GOLDEN[WIRE], (
        f"the wire section prints {printed}, not the one brief line the golden list "
        f"runs: {GOLDEN[WIRE]}")
    assert "noni brief --repo" in wire_section_flowed()


def test_the_wire_section_links_integrations_and_names_no_harness() -> None:
    """Ruling 4: the hook half is one sentence that links ``integrations/`` by path.

    The core stays harness-neutral, so the section points at the directory and names
    no harness; the page under ``integrations/`` is the one allowed to.
    """
    flowed = wire_section_flowed()
    assert "](../integrations/)" in wire_section(), (
        "the wire section does not link integrations/ by relative path")
    assert "hook for your harness" in flowed, (
        "the wire section no longer says what to do where a hook exists")
    assert not re.search(r"\b(?:pi|claude|cursor|copilot)\b", flowed, re.IGNORECASE), (
        "the wire section names a harness, which only a page under integrations/ may")


def test_the_wire_section_tells_the_in_project_route_which_root_to_use() -> None:
    """The other route's root is named, in one clause, in the page's own words.

    QUICKSTART's in-project route is Route A, whose commands run with ``--repo .``, so
    that is what the clause has to hand the reader rather than a second path.
    """
    assert "--repo ." in wire_section_flowed(), (
        "the wire section does not say which root the in-project route runs the brief "
        "against")


def test_the_wire_section_writes_no_em_dash() -> None:
    """Ruling 9: the guard is scoped to the new section and the paragraph.

    Scoped on purpose: the page carries em dashes elsewhere as existing prose, and a
    whole-page guard would be a rewrite this issue does not own.
    """
    assert "—" not in wire_section(), "an em dash in the new wire section"


def test_the_quickstart_and_readme_stay_within_their_caps() -> None:
    """The adoption path paid for its lines: neither page grew past its cap.

    The caps are the pages' own gates; restated here so the adoption change is the
    thing that reddens when one of them is passed.
    """
    quickstart_lines = read(QUICKSTART).count("\n")
    assert quickstart_lines <= QUICKSTART_LINE_LIMIT, (
        f"docs/QUICKSTART.md is {quickstart_lines} lines; the cap is "
        f"{QUICKSTART_LINE_LIMIT}")
    readme_lines = read(README).count("\n")
    assert readme_lines <= README_LINE_LIMIT, (
        f"README.md is {readme_lines} lines; the cap is {README_LINE_LIMIT}")


# --- the README's one link ---------------------------------------------------

def test_the_readme_first_screen_holds_exactly_one_adoption_link() -> None:
    """Ruling 5: everything above ``## The problem`` carries one link to the path.

    Counted in that region alone, because the rest of the page links the same file for
    its own reasons and an agent reads the first screen to find the path.
    """
    screen = readme_first_screen()
    assert screen.count(ADOPTION_LINK) == 1, (
        f"the README's first screen holds {screen.count(ADOPTION_LINK)} links to the "
        f"adoption path; the rule is exactly one: {ADOPTION_LINK!r}")


def test_the_readme_added_no_section() -> None:
    """No new README section: the link lives in prose the page already had."""
    assert re.findall(r"^## (.+)$", read(README), re.MULTILINE) == [
        "The problem", "What you get", "Try it in five minutes", "How it works",
        "Status", "Purity", "Contributing"], "the README gained or lost a section"


# --- the state root section's one sentence ----------------------------------

def test_the_state_root_section_says_the_branch_name_does_not_matter() -> None:
    """Ruling 7: one sentence, in ``## The state root``, and nowhere else.

    Counted over the page so a restatement under another heading is caught: the
    precedent for routing rather than restating is
    ``test_the_page_names_the_coexistence_section_without_restating_it``.
    """
    from docs_promises import section_body

    section = " ".join(section_body(read(QUICKSTART), "The state root").split())
    assert "branch name does not matter" in section, (
        "the state-root section no longer says the state repository's branch name "
        "does not matter")
    whole = " ".join(read(QUICKSTART).split())
    assert whole.count("branch name does not matter") == 1, (
        "the branch-name sentence is restated outside the state-root section")


# --- the release tag both pages name ----------------------------------------

def test_both_pages_name_the_current_release_tag() -> None:
    """Ruling 3: both pages name ``v`` + ``noni.__version__``, so a bump moves them.

    Read from the package rather than a literal, so the docs and the version cannot
    drift apart silently: the day ``__version__`` moves, this test reddens until both
    pages move with it.
    """
    from noni import __version__

    tag = f"v{__version__}"
    for path in (README, QUICKSTART):
        assert tag in read(path), (
            f"{path.name} does not name the release tag {tag!r}")


# --- the steering-ledger page's recording and attribution guidance ----------

def test_the_ledger_page_states_the_recording_guidance() -> None:
    """Ruling 8, the recording half: what belongs in the ledger and how it is drafted.

    Each phrase is a separate obligation, so a page that kept the supersede rule and
    lost the draft-first rule fails rather than reading plausibly.
    """
    flowed = " ".join(ledger_page().split())
    for phrase in ("decisions that change direction, not the requirements",
                   "proposal is a question for the operator",
                   "write with `--no-commit`",
                   "fixed with `--supersedes`"):
        assert phrase in flowed, (
            f"the steering-ledger page no longer states {phrase!r}")


def test_the_ledger_page_documents_both_attribution_flag_sets() -> None:
    """Ruling 8, the attribution half: two flag sets and the single-option marker.

    Pinned as the flag pairs themselves, not the words around them: an agent reads
    the flags off this page when it writes a record, and the writer's refusals are
    what a wrong set earns.
    """
    flowed = " ".join(ledger_page().split())
    for flags in ATTRIBUTION_FLAG_SETS:
        assert flags in flowed, (
            f"the steering-ledger page does not document the flag set {flags!r}")
    assert "--single-option" in flowed, (
        "the steering-ledger page does not say what --single-option marks")


def test_the_ledger_page_shows_the_single_option_flag_set_in_full() -> None:
    """The flag-set paragraph shows --single-option beside an --option and an --answer.

    The writer refuses --single-option unless a question carries exactly one explicit
    --option, so a page that printed the marker alone handed the agent a refusal. The
    three flags are pinned in one line of the paragraph, so a reword that dropped the
    --option half reddens rather than reading plausibly.
    """
    flowed = " ".join(ledger_page().split())
    line = next((line for line in ledger_page().splitlines()
                 if "--single-option" in line and "--option " in line
                 and "--answer" in line), "")
    assert line, (
        "the steering-ledger page never shows --single-option together with an "
        "explicit --option and --answer")
    assert "--single-option" in flowed


def test_the_ledger_census_section_names_the_console_command_first() -> None:
    """The Census section leads with `noni census --repo`, not with an installed path.

    Agents install skills under folder names of their own, so a page that sent them to
    skills/census/scripts/census.py handed them a path that does not resolve. The
    console command is the one form that works wherever the skill landed, and the shim
    keeps its place after it as the thin wrapper it is.
    """
    from docs_promises import section_body

    census = " ".join(section_body(ledger_page(), "Census").split())
    command = census.find("noni census --repo")
    shim = census.find("scripts/census.sh")
    assert command >= 0, "the Census section does not name `noni census --repo`"
    assert shim >= 0, "the Census section no longer describes the ledger shim"
    assert command < shim, (
        "the Census section must name `noni census --repo` before the shim")
    assert "skills/census/scripts/census.py" not in census, (
        "the Census section still sends the agent to an installed skill path")
