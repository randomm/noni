"""What the start-here page promises, checked as text.

``skills/noni/SKILL.md`` is the one page an operator points a fresh agent at, so the
claims it has to hold are the claims an agent acts on: that one read shows the
direction, the queue and the settled answers, that the page sends each act to the
skill that owns it rather than restating its flags, and that it stays a page rather
than growing into a manual. Nothing here is checked by the page-set gates below
(``tests/test_docs_promises.py``, ``tests/test_docs_ci_neutrality.py``,
``tests/test_docs_install_promises.py`` and the purity and scrub censuses all read
the page the day it lands): those say a page is well-formed. These are the claims
that are the page's own, each with the planted-offender pair that proves the guard
can see it.

The line cap is this page's and not ``SKILL.md``'s general one: a start-here page
that reaches the 400-line ceiling a writer manual is allowed has stopped being the
page an agent reads before it starts work.
"""

from __future__ import annotations

import re

import pytest
from docs_commands import fenced_pairs, read
from docs_precondition import script_entry_points
from docs_promises import REPO, SKILL_NAMES

START_HERE = REPO / "skills" / "noni" / "SKILL.md"

# The page's own length cap. The 400-line ``SKILL.md`` ceiling is a writer manual's,
# and ``tests/test_skill_scrub.py`` and ``tests/test_file_size_limit.py`` both stop
# there; the precedent for a tighter cap on one page is
# ``tests/test_onboarding.py``'s ``ONBOARDING_LINE_LIMIT``. A start-here page is read
# before work, in the same sitting as the screen it tells the agent to run.
START_HERE_LINE_LIMIT = 120

# The six Agent Skills frontmatter fields, as the Agent Skills specification names
# them. AGENTS.md and docs/PRODUCT.md 3 state the six-field rule and nothing in the
# suite checked it for any page (the only frontmatter assertion was a startswith and
# a ``\\ndescription:`` probe on the direction page), so the start-here page's claim to
# carry only those fields is pinned here, field by field, rather than by shape.
SPEC_FRONTMATTER_FIELDS: tuple[str, ...] = (
    "name", "description", "license", "allowed-tools", "metadata", "compatibility",
)

# The four things the page has to tell an agent, in the order it tells them, each with
# the phrase that carries it. Held as data so a rewrap is a passing edit and a dropped
# instruction is a failure that names the instruction it dropped.
READ_ORDER: tuple[tuple[str, str], ...] = (
    # (the section of the page the claim lives in, the phrase that carries it). The
    # section heading is part of the pair because the page states the four parts of the
    # screen by name in its reading table, and a plain substring search would find those
    # names before the instructions that follow them -- which would have made the
    # sequence below a test of the table's layout rather than of the page's order.
    ("## The first action", "noni brief"),
    ("## How to read the screen", "part one, Purpose"),
    ("## How to read the screen", "top 10"),
    ("## How to read the screen", "Recent decisions."),
    ("## Carrying on", "first entry"),
    ("## Carrying on", "their words"),
    ("## Carrying on", "update the order"),
)

# The four skills the page routes to, each by the page path a loader reads. The page
# owns no writer, so every act it mentions has to arrive by a link to the skill that
# owns it -- the same shape docs/ONBOARDING.md uses for the same reason.
ROUTED_SKILLS: tuple[str, ...] = ("direction", "steering-ledger", "census")

# The boundary this page has to state without naming a tool: learned facts live
# somewhere else. Named here so the wording a reviewer must not lose is one string.
MEMORY_TOOL_PHRASE = "a separate memory tool"


def page_text() -> str:
    """The whole page, with the missing file named as the failure."""
    return read(START_HERE)


def _flowed(text: str) -> str:
    """A page with every run of whitespace collapsed, for a claim about a sentence."""
    return re.sub(r"\s+", " ", text)


def _section(flowed: str, heading: str) -> str:
    """The page's flowed text from one ``##`` heading up to the next.

    The unit a claim belongs to. A page that moved an instruction out of its section
    has changed what the reader reads in order, which is the thing the sequence case
    below judges, so a claim is located inside its own section and not anywhere in the
    document.
    """
    start = flowed.find(heading)
    assert start >= 0, f"the page has no {heading!r} section"
    following = flowed.find("## ", start + len(heading))
    return flowed[start:following if following >= 0 else len(flowed)]


def _frontmatter(text: str) -> dict[str, str]:
    """The page's frontmatter block as ``{field: value}``.

    Read line by line between the two ``---`` fences, which is the shape a loader
    reads, so a field spelled inside prose cannot answer for a field the block lacks.
    """
    lines = text.splitlines()
    assert lines and lines[0] == "---", "the page has no frontmatter opener"
    end = next((index for index in range(1, len(lines)) if lines[index] == "---"), None)
    assert end is not None, "the page's frontmatter is never closed"
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        match = re.match(r"^([a-z-]+):(.*)$", line)
        assert match, f"frontmatter line is not a field: {line!r}"
        fields[match.group(1)] = match.group(2)
    return fields


# --- the page exists, is short, and carries only the six fields --------------

def test_the_start_here_page_exists_within_its_own_line_cap() -> None:
    """The page is there, and short enough to be a start-here page.

    The general ``SKILL.md`` ceiling of 400 lines would leave a page four times this
    length looking like a start-here page while nobody read it to the end, so the cap
    asserted here is the one the ticket set for this page.
    """
    lines = page_text().count("\n")
    assert lines <= START_HERE_LINE_LIMIT, (
        f"skills/noni/SKILL.md is {lines} lines; the cap is {START_HERE_LINE_LIMIT}")


def test_the_frontmatter_carries_only_the_six_spec_fields() -> None:
    """The block holds fields of the Agent Skills specification and nothing else.

    The rule is AGENTS.md's and docs/PRODUCT.md 3's, and no gate checked it for any
    page: a frontmatter key a loader does not read (``version``, ``tags``, an
    ``owner``) is invisible to a skimming author and a compatibility problem for
    whatever loads the directory next. Checked as a set rather than as a prefix, so
    the first check below would also catch a field named for something the spec has.
    """
    fields = _frontmatter(page_text())
    assert fields, "the page's frontmatter holds no field at all"
    assert set(fields) <= set(SPEC_FRONTMATTER_FIELDS), (
        f"the page carries a frontmatter field outside the six: "
        f"{sorted(set(fields) - set(SPEC_FRONTMATTER_FIELDS))}")
    # The two fields a loader has to have: a name to register the skill under and a
    # description to decide when to load it.
    assert {"name", "description"} <= set(fields), sorted(fields)


def test_the_frontmatter_name_is_the_directory_name() -> None:
    """``name:`` matches the directory, the way every other core page's does.

    The registration lists name the skill by its directory, and
    ``tests/test_onboarding.py`` asserts the linked set equals the registered set by
    that name; a page whose frontmatter disagreed would be a skill a loader registers
    under one name and a page links under another.
    """
    assert _frontmatter(page_text())["name"].strip() == "noni"


def test_the_page_is_registered_as_a_core_skill() -> None:
    """The directory the page lives in is in the list every skill census reads.

    The three literal lists (``tests/test_skill_scrub.py``, ``tests/test_purity.py``
    and ``tests/docs_promises.py``) all derive from or duplicate the same set, and the
    onboarding equality test is what reddens a page that arrived without a registration
    -- so this is the cheap half of that claim, stated where a reader of this page looks.
    """
    assert "noni" in SKILL_NAMES, SKILL_NAMES
    assert START_HERE.is_file(), f"{START_HERE} is missing"


# --- what the page tells an agent, and in what order ------------------------

@pytest.mark.parametrize("heading,phrase", READ_ORDER,
                         ids=[f"{heading.strip('# ')}-{index}"
                              for index, (heading, _phrase) in enumerate(READ_ORDER)])
def test_the_page_states_each_instruction_of_the_first_read(heading: str,
                                                           phrase: str) -> None:
    """Every instruction of the ticket's first-read sequence is on the page.

    Located inside the section the claim belongs to, and case-insensitively: the page
    wraps at eighty columns, so what has to survive a rewrap is the phrase, and a
    heading's capitalisation is the page's business. What a rewrite loses is the
    instruction, and that is what this reddens on.
    """
    body = _flowed(page_text())
    assert phrase.lower() in _section(body, heading).lower(), (
        f"{heading!r} no longer states {phrase!r}")
    # The first screen line is the command itself, and the page says so in words: a
    # fence alone would let a page that never named the command pass on a copy.
    if heading == "## The first action":
        assert "run the brief" in body.lower(), (
            "the page prints the command without telling the reader to run it first")


def test_the_page_names_the_instructions_in_that_order() -> None:
    """The sequence is the page's contract, not merely its contents.

    An agent that read the order before the intent, or recorded a steer before it read
    what was already settled, has the protocol upside down; the page's value is that it
    can be read top to bottom and followed in that order.
    """
    body = _flowed(page_text())
    # The sections themselves have to fall in this order, which is the shape an agent
    # reads: screen first, then what the four parts mean, then the three moves. The
    # phrases are then located inside their own section, so neither a rewrap nor a
    # duplicated mention elsewhere on the page can stand in for the instruction.
    headings = [_section(body, heading) for heading, _phrase in READ_ORDER]
    starts = [body.find(heading.strip()) for heading, _phrase in READ_ORDER]
    assert all(start >= 0 for start in starts), list(zip(READ_ORDER, starts, strict=True))
    assert starts == sorted(starts), (
        f"the instructions are out of order on the page: {starts}")
    found = [section.lower().find(phrase.lower())
             for section, (_heading, phrase) in zip(headings, READ_ORDER, strict=True)]
    assert all(index >= 0 for index in found), list(zip(READ_ORDER, found, strict=True))


def test_the_page_tells_the_agent_not_to_re_open_a_recorded_decision() -> None:
    """A settled question stays settled, and the page says so in the same breath.

    The ticket's reason for existing is that a fresh agent stops re-arguing what the
    operator already decided, so both halves have to be on the page: the instruction not
    to re-open one, and the route to changing it (supersede, on the operator's word) --
    otherwise an agent that met a wrong decision had no lawful way to correct it.
    """
    flowed = _flowed(page_text())
    assert "do not re-open" in flowed.lower()
    assert "supersede" in flowed
    assert "operator's word" in flowed


def test_the_page_never_answers_for_the_operator() -> None:
    """Steering is the operator's act, and the page keeps the agent out of it.

    The rule is in AGENTS.md's project constraints ("Steering never auto-answers for the
    operator") and the start-here page is where a fresh agent meets it, so the page has
    to carry the prohibition and the reason an unrecorded steer dies with the session.
    """
    flowed = _flowed(page_text())
    assert "never answer" in flowed.lower() or "never your own" in flowed.lower(), (
        "the page no longer forbids answering a question on the operator's behalf")
    assert "their words" in flowed, (
        "the page no longer says the record is written in the operator's words")


# --- the page owns no writer: every act is routed --------------------------------

@pytest.mark.parametrize("skill", ROUTED_SKILLS, ids=ROUTED_SKILLS)
def test_the_page_links_the_skill_that_owns_each_act(skill: str) -> None:
    """Each act the page mentions arrives at the page that owns it.

    The page restates no flags, so a mention of an act with no link is an instruction an
    agent can read and cannot carry out; the link is the how. Read from the *body*: the
    frontmatter a loader also reads is checked on its own below, and a link that lived
    only in that sentence would be a route no agent reading the page could follow.
    """
    # The page sits two directories deep, so the href it owes a sibling skill starts
    # with ``../`` and names the directory, never ``../skills/<name>/``: that form
    # resolves to a path that does not exist. Both halves are asserted so a link that
    # was spelled for a page in ``docs/`` is caught rather than rendered as a dead link.
    body = page_text().split("---", 2)[-1]
    link = f"[`skills/{skill}/SKILL.md`](../{skill}/SKILL.md)"
    assert link in body, (
        f"the page does not link skills/{skill}/SKILL.md in the form a page two "
        f"directories deep has to write ({link!r}); a link carrying the ``skills/`` "
        "segment inside the href resolves outside the tree")
    target = (START_HERE.parent.parent / skill / "SKILL.md").resolve()
    assert target.is_file(), f"{link} resolves to no file: {target}"


def test_the_frontmatter_routes_every_act_it_names() -> None:
    """The description's Do-NOT-use clause names the owners of what the page routes.

    A loader decides whether to read a page from its description alone, so the read-only
    claim has to be in that sentence rather than only in the body: the page owns the
    start-here read and sends every act to the skill that holds its writer.
    """
    description = _frontmatter(page_text())["description"]
    assert "Do NOT use for" in description, description
    for skill in ("direction", "steering-ledger", "census"):
        assert skill in description, (
            f"the description's Do-NOT-use clause does not name {skill}, whose act the "
            "page routes rather than performs")


# --- the page's own hygiene ---------------------------------------------------

def test_the_page_carries_the_install_promise_when_it_prints_a_command() -> None:
    """A page that prints a command owes the install precondition, or prints none.

    ``tests/test_docs_install_promises.py`` fires only for a script path in command
    position; ``noni brief --repo DIR`` is a console form and owes no sentence. The
    assertion is written as an implication so it keeps holding if the page grows a
    ``scripts/`` command later, and it is tested here as well as there because this
    page's fence is the one its own readers copy.
    """
    text = page_text()
    if script_entry_points(text):
        assert "must be installed" in _flowed(text)
        assert "importable" in _flowed(text)
        assert "QUICKSTART.md#install-noni" in text, (
            "the page prints a script command without linking the install section")


def test_the_page_states_the_read_only_promise_of_the_screen_it_prints() -> None:
    """The one command the page prints is the one the ticket made read-only.

    An agent deciding whether it may look needs to know looking is safe: the page says
    the screen writes nothing, so the first action costs nothing and commits nothing.
    """
    flowed = _flowed(page_text())
    assert "read-only" in flowed
    assert "noni brief" in flowed
    assert "writes no file" in flowed or "write no file" in flowed


def test_the_page_names_the_memory_boundary_without_naming_a_tool() -> None:
    """Learned facts live elsewhere, and the page says so without naming a vendor.

    The purity rule's tier 1 is the reason the boundary is phrased as "a separate
    memory tool" rather than by name, and the committed structural half of
    ``tests/test_purity.py`` is what enforces that in CI; the phrase is pinned here so
    the sentence a rewrite might drop is named before it goes.
    """
    assert MEMORY_TOOL_PHRASE in _flowed(page_text()), (
        "the page no longer routes learned facts to a separate memory tool")


def test_the_page_writes_no_em_dash() -> None:
    """The page's prose carries no em dash.

    AGENTS.md states the rule as prose and no gate in the suite enforces it for any
    page, so the claim on this one is enforced here rather than assumed: a reviewer
    reading the ticket's "plain prose, no em dashes" should find a check, not a hope.
    """
    offenders = [index for index, line in enumerate(page_text().splitlines(), 1)
                 if "\u2014" in line]
    assert not offenders, (
        f"skills/noni/SKILL.md carries an em dash on line(s) {offenders}")


def test_the_page_prints_no_path_that_is_not_the_state_root_or_a_link() -> None:
    """No machine-local or host path on the page.

    The scrub and purity censuses own the general rule; this is the one shape this page
    is most likely to grow -- a worked example pointing at somebody's own checkout.
    """
    offenders = [line for line in page_text().splitlines()
                 if re.search(r"(?:^|\s)/(?:home|Users|mnt|Volumes)/", line)]
    assert not offenders, f"the page prints a host path: {offenders}"


# --- the guards above fire on the offenders they name -----------------------

def test_the_line_cap_guard_refuses_a_page_past_it(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The cap is a guard, not a coincidence of the current page's length.

    A page that happened to be short would pass a cap check whose reader was broken,
    so the reader is driven against a page that is not: the plant has to raise with the
    number it counted, not pass silently.
    """
    planted = "---\nname: noni\n---\n\n" + "\n".join("line" for _ in range(200)) + "\n"
    monkeypatch.setattr("test_start_here_page_docs.read",
                        lambda _path: planted)
    with pytest.raises(AssertionError, match="is 204 lines; the cap is 120"):
        test_the_start_here_page_exists_within_its_own_line_cap()


def test_the_field_guard_refuses_a_field_outside_the_six(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A frontmatter carrying an invented key is caught by name, not by luck."""
    planted = ("---\nname: noni\ndescription: x\nversion: 1\n---\n\n# noni\n")
    monkeypatch.setattr("test_start_here_page_docs.read", lambda _path: planted)
    with pytest.raises(AssertionError, match="version"):
        test_the_frontmatter_carries_only_the_six_spec_fields()


def test_the_order_guard_refuses_an_instruction_printed_out_of_sequence(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The sequence check sees a rewrite that kept every phrase and lost the order.

    The plant moves one instruction, and only that one, from its own section into a
    later one: every heading stays where the page has it and every phrase is still on
    the page, so the only thing this case can be reddening on is the sequence. A plant
    that dropped a heading would pass on the section reader's own guard instead, which
    is the failure mode this fixture exists to rule out.
    """
    moved = page_text().replace("**Take the first entry", "**TAKE PLACEHOLDER")
    moved = moved.replace("## Settled questions\n\nDo not re-open",
                          "## Settled questions\n\nTake the first entry of the list "
                          "before anything else.\n\nDo not re-open")
    for heading, _phrase in READ_ORDER:
        assert moved.count(heading + "\n") == page_text().count(heading + "\n")
    monkeypatch.setattr("test_start_here_page_docs.read", lambda _path: moved)
    with pytest.raises(AssertionError, match=r"first entry.*-1|, -1\)"):
        test_the_page_names_the_instructions_in_that_order()


def test_the_em_dash_guard_refuses_a_page_that_carries_one(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The punctuation rule fires on the character, on the line it names."""
    monkeypatch.setattr("test_start_here_page_docs.read",
                        lambda _path: "# noni\n\nplain prose \u2014 with a dash\n")
    with pytest.raises(AssertionError, match="line\\(s\\) \\[3\\]"):
        test_the_page_writes_no_em_dash()


def test_the_fences_the_page_prints_are_console_forms() -> None:
    """Every fence on the page is a console command or a table, never a script path.

    The page is two directories deep, so a fence printing ``scripts/x.py`` would owe the
    install sentence and the ``../../docs/QUICKSTART.md`` link; keeping the page to the
    console form is the simpler contract with the reader, and this is where a fence that
    grew one is noticed rather than at the gate that also demands the sentence.
    """
    assert not script_entry_points(page_text()), (
        "the page prints a script path in command position")
    for info, _lines in fenced_pairs(page_text()):
        assert info in ("", "console", "text"), (
            f"the page opens a fence tagged {info!r}, which a reader copies as a "
            "command no test runs")
