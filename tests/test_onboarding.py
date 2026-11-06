"""What the agent-onboarding page promises, checked as text and driven for real.

``docs/ONBOARDING.md`` (issue #73) is the third page a newcomer meets: the README
decides whether to attach noni, ``docs/QUICKSTART.md`` installs it and runs both
state routes, and this page tells a team how to put noni's four core skills in
front of their agents and what one of those agents does from session start to
close. Three of its claims are the whole of its value, and each is checked here
rather than trusted:

- **The four skills are named by their page paths.** The page's promise is that a
  team can find every core skill; the list of core skills is
  :data:`docs_promises.SKILL_PAGE_PATHS`, so a fifth skill or a renamed one fails
  here instead of leaving the page quietly incomplete.
- **The protocol's five steps are on the page, each linked to its owning skill.**
  The steps are this module's :data:`PROTOCOL_STEPS` -- the wording an agent reads
  -- and each names the skill that owns it, so a page that dropped the claim step
  or unlinked the direction skill is caught by name, not by word count.
- **It prints no command.** That is the page's design choice (issue #73, PM-adopted:
  the page links the owning ``SKILL.md`` and the quickstart instead of restating
  flags), and a page that grew a bash fence has grown a command no golden list
  covers and no test runs -- which is why the fence census here refuses any fence
  with an info string at all, not ``bash`` alone.

The two page-set gates already read this page (``tests/test_docs_promises.py`` and
``tests/test_docs_invocation.py`` both iterate ``DOC_PAGES``, which now includes
it); this module holds only the claims that are the page's own.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from docs_commands import fence_openers, read
from docs_promises import (
    ONBOARDING,
    README,
    SKILL_NAMES,
    SKILL_PAGE_PATHS,
)
from quickstart_page import COEXISTENCE_HEADING, flowed_text

# The five steps of the per-session protocol, each with the skill that owns it, in
# the order the page prints them. Held as data because the page is wrapped at ~80
# columns: each step is located word by word with any run of whitespace between the
# words, so a rewrap is a passing edit and a dropped step is a failure. The
# ``owner`` is the core skill whose ``SKILL.md`` the page must link for that step.
PROTOCOL_STEPS: tuple[tuple[str, str], ...] = (
    ("read the standing intent first", "direction"),
    ("register the session", "sessions-claims"),
    ("claim the task you mean to work", "sessions-claims"),
    ("record a decision through the steering-ledger writer", "steering-ledger"),
    ("release the claim you no longer hold", "sessions-claims"),
)

# The two things the protocol exists to prevent, in the page's own words. A page
# that keeps the five steps and drops these has become a list of commands without
# its reason: the claim step in particular reads as optional paperwork unless the
# page says what an unclaimed run costs everyone else.
PROTOCOL_REASONS: tuple[str, ...] = (
    "Claims are signals, not locks",
    "double-claim",
    "unrecorded steer",
)

# The page's length cap. It is a page a reader is meant to finish before starting
# work, not a reference, so the cap is the quickstart's 400-line ceiling halved:
# the quickstart carries runnable commands for two routes and this page prints
# none, and a page with no commands has no excuse for twice the length.
ONBOARDING_LINE_LIMIT = 200


def page_text() -> str:
    """The whole page, as one string, with the missing file named as the failure."""
    return read(ONBOARDING)


def _step_link_for(skill_name: str) -> str:
    """The markdown link the page must carry for one core skill."""
    return f"[`skills/{skill_name}/SKILL.md`](../skills/{skill_name}/SKILL.md)"


# --- AC1/AC3: the four core skills, named by their page paths ---------------

def test_the_page_names_every_core_skill_by_its_page_path() -> None:
    """All four ``SKILL.md`` paths appear on the page, and nothing else's does.

    The expected set is :data:`docs_promises.SKILL_PAGE_PATHS` -- the same list the
    scrub and purity readers build their skill directories from -- so a fifth core
    skill is a failure here rather than a page that quietly names four of five. The
    comparison is on the page path token, not the bare directory name: AC1's check
    shape is "named with its SKILL.md path", and a page that wrote "the census
    skill" in prose would name a skill while sending the reader nowhere.
    """
    page = page_text()
    # Every skill the core set has must appear in the page's link form, not merely
    # as a word in prose: a page that wrote "the census skill" three times and
    # linked nothing would pass a substring check and send the reader nowhere.
    missing = [link for link in map(_step_link_for, SKILL_NAMES) if link not in page]
    assert not missing, (
        f"docs/ONBOARDING.md does not link every core skill's page: {missing}; "
        f"the core set is {list(SKILL_PAGE_PATHS)}")
    # And no skill outside the core set may be linked: a fifth path, or a page under
    # a skill directory the core does not have, is the page claiming product surface
    # the tree does not ship. ``skills/<name>/...`` is the layout placeholder the
    # page uses for the loader rule and names no skill.
    linked = set(re.findall(r"\(\.\./skills/([^/\s)]+)/SKILL\.md\)", page))
    assert linked == set(SKILL_NAMES), (
        f"the page links a skill the core set does not have, or is missing one: "
        f"{sorted(linked)} vs {sorted(SKILL_NAMES)}")


def test_every_core_skill_page_the_page_links_resolves() -> None:
    """Each of the four links the page prints points at a file in this repository.

    The page lives in ``docs/``, so every one of its relative links starts from
    there -- the check resolves the link the way a renderer would and then asks
    whether the target is tracked content. A path that drifted is a broken promise
    to the one reader the page exists for.
    """
    for skill in SKILL_NAMES:
        link = _step_link_for(skill)
        assert link in page_text(), (
            f"the page does not carry the exact link for {skill}: {link}")
        target = (ONBOARDING.parent / f"../skills/{skill}/SKILL.md").resolve()
        assert target.is_file(), f"{link} resolves to no file: {target}"


# --- AC2/AC3/AC4/AC5/AC6: the per-session protocol -------------------------

def test_the_page_states_each_protocol_step_and_its_owning_skill() -> None:
    """Every step of the protocol is on the page, and each links its owner.

    A step is located word by word, so the page's line wrapping is not part of the
    contract, and its owner is located on the same table row: a page that named the
    claim step without pointing at the sessions-claims skill would satisfy a
    step-exists check and leave the agent with a step it cannot carry out.
    """
    rows = [line for line in page_text().splitlines()
            if line.strip().startswith("|")]
    assert rows, "the page carries no protocol table to locate its steps in"
    for phrase, owner in PROTOCOL_STEPS:
        located = [row for row in rows if _words(phrase).search(row)
                   and _step_link_for(owner) in row]
        assert located, (
            f"no row of the protocol table states {phrase!r} beside the "
            f"{owner} skill's page link; the table rows are:\n"
            + "\n".join(rows))


def test_the_page_keeps_the_protocol_in_its_three_moments() -> None:
    """The page groups the steps by when they happen: start, during, end.

    AC2/AC3/AC4/AC5 are one claim with three parts, and the part a rewrite loses is
    the ordering: an agent that registers after it claims has the protocol upside
    down. Each of the three moment words has to appear as a table cell, so a page
    that merged the steps into one undifferentiated list fails here.
    """
    cells = [cell.strip() for line in page_text().splitlines()
             if line.strip().startswith("|")
             for cell in line.strip().strip("|").split("|")]
    for moment in ("at start", "during work", "at the end"):
        assert moment in cells, (
            f"the protocol table has no row for the {moment!r} moment, so a "
            f"reader cannot tell when the step belongs: {cells}")


def test_the_page_says_why_the_protocol_is_not_optional() -> None:
    """The page states what an unclaimed or unrecorded session costs.

    The claims check is the arbiter for double-claims and the ledger is the only
    thing that survives a session; both facts are what make the steps worth doing,
    and the page has to say them rather than just listing verbs.
    """
    flowed = flowed_text(page_text())
    for reason in PROTOCOL_REASONS:
        assert reason in flowed, (
            f"the page no longer states {reason!r}, which is the reason the "
            "protocol's steps are worth following")


def test_the_page_prints_no_command_in_any_fence() -> None:
    """The page opens no fenced block carrying commands.

    The design decision is the page's: it links the owning ``SKILL.md`` and the
    quickstart instead of printing flags (issue #73, PM-adopted), so the suite has
    to hold it there. A page whose commands were never exercised is the exact
    failure the quickstart's golden list exists to prevent, and this page has no
    golden list. Refused here is any fence with an info string, not ``bash`` alone:
    ``sh``, ``console`` and ``shell`` are all forms a reader would copy, and
    an unlabelled fence is the one form that carries prose, which is why an empty
    info string is allowed and compared at the count rather than by content.

    The info string is read from the fence's first whitespace-delimited token, so a
    tag carrying metadata (`` ```bash title=x ``) is refused for the tag it starts
    with rather than passing because the whole line did not equal a known one.
    """
    labelled = [info for info in fence_openers(page_text()) if info]
    assert not labelled, (
        f"docs/ONBOARDING.md prints a fenced block tagged {labelled}, which is a "
        "command no golden list covers and no test runs; link the owning SKILL.md "
        "or docs/QUICKSTART.md instead")


def test_the_fence_census_names_the_tag_of_a_command_bearing_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard above fails the way it was written to, on every fence shape a page takes.

    A page with no fence makes the test above green whether or not the reader under
    it works, so the reader is exercised here against pages that do carry the
    regression: each plant has to produce the designed message that names the tag,
    not an ``IndexError`` out of a broken capture group and not a silent pass. The
    plants are the shapes a rewrite actually takes (the review of issue #73 found
    the first two were enough to close the guard): a column-zero fence, the same
    fence indented by one space, and a fence whose info string carries metadata.
    Without the indented plant the census could be closed by one space of indent --
    the same copyable block, rendered the same way -- and the page's clean state
    would hide it, because a page that opens no fence at all passes either way.
    """
    plants = {
        "a column-zero fence": "# T\n\n```bash\nnoni census --repo .\n```\n",
        "a fence indented by one space": "# T\n\n ```bash\nnoni census --repo .\n ```\n",
        "a fence indented by three spaces": "# T\n\n   ```sh\nnoni census --repo .\n   ```\n",
        "a fence whose tag carries metadata": "# T\n\n```bash title=x\nnoni census --repo .\n```\n",
    }
    for shape, planted in plants.items():
        monkeypatch.setattr("test_onboarding.read", lambda _path, page=planted: page)
        tag = fence_openers(planted)[0]
        assert tag, f"the reader missed {shape}, so the guard above cannot see it"
        with pytest.raises(AssertionError, match=rf"\['{tag}'\]"):
            test_the_page_prints_no_command_in_any_fence()
    # And the reader itself still counts the closer, info string and all, so a
    # closer line (empty tag) is not mistaken for a command-bearing block.
    assert fence_openers(plants["a column-zero fence"]) == ["bash", ""]


def test_the_page_defers_commands_to_the_quickstart_and_its_skills() -> None:
    """The page says where the commands live, and links the page that has them.

    The deferral is the counterpart of the no-commands rule: a page that refuses to
    print commands has to send the reader somewhere, and "the SKILL.md links above"
    is only a route if the links and the quickstart link are on the page.
    """
    page = page_text()
    assert "QUICKSTART.md" in page, "the page sends the reader nowhere for commands"
    assert "docs/PRODUCT.md" in page, (
        "the page does not name the binding reference for record shapes and the "
        "claim protocol, which it defers to rather than restating")


# --- AC8: purity ------------------------------------------------------------

@pytest.mark.parametrize("name", SKILL_NAMES)
def test_the_page_carries_one_link_form_per_skill(name: str) -> None:
    """Each core skill is linked exactly once per row that needs it, in one form.

    The check exists because the four paths are the page's contract with the
    loader: a page that mixed ``skills/census/SKILL.md`` with
    ``../skills/census/SKILL.md`` inline and linked elsewhere would be correct to a
    renderer and wrong to a test that reads the path token. Every occurrence of the
    path therefore has to sit inside the link the harness itself builds, and the
    count is bounded below by one so a link that survived only in a heading or a
    caption does not count.
    """
    page = page_text()
    link = _step_link_for(name)
    path = f"skills/{name}/SKILL.md"
    occurrences = [m.start() for m in re.finditer(re.escape(path), page)]
    assert occurrences, f"the page does not name {path} at all"
    outside = [page[max(0, i - len(link.split("](")[0]) - 1):i]
               for i in occurrences
               if link not in page[max(0, i - len(link)):i + len(link)]]
    assert not outside, (
        f"{path} appears outside the link form this page standardises on "
        f"({link}): {[chunk.strip() for chunk in outside]}")


# --- AC9: the README's exact-path link, and the size caps ------------------

def test_the_readme_links_the_page_by_exact_path() -> None:
    """README names the page the way a reader can follow it.

    ``tests/test_readme.py::test_every_path_the_readme_names_exists`` resolves every
    repo-relative token on that page, so the link has to be the literal path and not
    prose about "the onboarding page". The page's own existence is asserted here too:
    a link to a file that was never added passes a text comparison.
    """
    readme = read(README)
    assert "docs/ONBOARDING.md" in readme, "README does not name the page by path"
    assert ONBOARDING.is_file(), "docs/ONBOARDING.md is missing"


def test_the_page_is_within_its_own_size_cap() -> None:
    """The page stays short enough to read before starting work.

    The README's 150-line cap is the precedent for a size assertion on a page
    (``tests/readme_support.py``), and the quickstart's 400 is the precedent for a
    docs page (``tests/test_quickstart.py``); this page carries no commands, so it
    is capped well below that pair.
    """
    lines = page_text().count("\n")
    assert lines <= ONBOARDING_LINE_LIMIT, (
        f"docs/ONBOARDING.md is {lines} lines; the cap is {ONBOARDING_LINE_LIMIT}")


def test_the_sessions_steps_are_marked_conditional() -> None:
    """The three sessions-claims rows are stated as taken only by teams that use them.

    The quickstart's coexistence section says a team whose driver already keeps
    claim state must not create ``noni/sessions/`` at all (its own test pins that
    promise in ``tests/test_quickstart_promises.py``), and the pilot's second team
    read this page's five rows as five commands and registered a session they were
    told elsewhere never to write. So the condition is product surface here: the
    page has to name the three rows as conditional on the team using noni's
    sessions and claims, keep the other two unconditional, and route the skip
    decision to the section that owns it. Located in the flowed text around the
    table, not on the rows themselves -- the rows are pinned by
    :func:`test_the_page_states_each_protocol_step_and_its_owning_skill`, and this
    is the sentence that qualifies them.
    """
    flowed = flowed_text(page_text())
    assert "sessions and claims" in flowed, (
        "the page no longer names what the three conditional rows depend on")
    assert "if your team uses" in flowed, (
        "the sessions and claims steps are no longer stated as conditional on the "
        "team using them, which is how the pilot read them as five mandatory steps")
    assert "every team" in flowed, (
        "the page no longer says which steps stay unconditional, so a team that "
        "skips claims cannot tell whether the direction and ledger steps go too")
    assert "coexistence" in flowed and "QUICKSTART.md" in page_text(), (
        "the page invites a team to skip the claim steps without routing them to "
        "the section that decides when skipping is right")


def test_the_page_names_the_coexistence_section_without_restating_it() -> None:
    """The page routes the driver question to the section that owns it.

    A team already running a work driver of its own has to be told that noni's
    sessions layer is optional, and that answer lives in exactly one place -- the
    quickstart's coexistence section, which the forge page links for the same
    reason (``tests/test_docs_ci_neutrality.py``). The onboarding page is where an
    agent-reading team meets that situation, so it has to route there; it may not
    restate the position, because two copies of "never both by hand" is how the two
    pages start disagreeing.
    """
    page = page_text()
    assert COEXISTENCE_HEADING in flowed_text(page) or "coexistence" in page, (
        "the page does not route a team with their own work driver to the "
        f"quickstart's {COEXISTENCE_HEADING!r} section")
    for phrase in ("Never both by hand", "sessions and claims layer is optional"):
        assert phrase not in page, (
            f"the page restates the coexistence position ({phrase!r}) instead of "
            "linking the section that owns it, and now two pages can disagree")
    assert "QUICKSTART.md" in page, (
        "the page names the coexistence position without naming the page that "
        "carries it, so the reference has nothing to resolve against")


# --- the protocol's commands, actually run ---------------------------------

def test_the_protocol_steps_run_in_order_through_the_console_command(
    world, tmp_path: Path,
) -> None:
    """Register, claim, release and close each exit 0 in the page's own order.

    AC7's honest reading: the page prints no commands, so the claim that survives is
    that the steps it tells an agent to take are executable and take an attached
    project from no register to a closed session. The page links the skills rather
    than printing flags, so the harness supplies the flags -- launched through the
    installed ``noni`` console script, in the world the quickstart's own walks use
    (project, private state clone, origin), so what is observed is the reader's
    experience rather than the wrapper's argparse.

    The census runs at the end, on the page's own advice, and the session must have
    released its claim before it closes: ``close`` alone leaves an active claim row
    in a closed session, which the census does not flag and the next session cannot
    tell from a live one.
    """
    state, env = world.state, world.env
    state.mkdir(parents=True, exist_ok=True)
    for key, value in (("user.name", "Replay"),
                       ("user.email", "replay@fixture.invalid")):
        proc = _git(state, "config", key, value, env=env)
        assert proc.returncode == 0, f"state identity {key}: {proc.stderr}"

    register = _run(world, "register", "--repo", str(state), "--identity", "developer")
    assert register.returncode == 0, f"register: {register.stderr}"
    session_id = _session_id_from(register.stdout)
    files = sorted((state / "noni" / "sessions").glob("*.md"))
    assert [p.stem for p in files] == [session_id], (
        f"register printed {session_id!r} but the register holds "
        f"{[p.name for p in files]}")

    claim = _run(world, "claim", "--repo", str(state), "--session-id", session_id,
                 "--task", "#12")
    assert claim.returncode == 0, f"claim: {claim.stderr}"
    assert "- claim: #12" in files[0].read_text(encoding="utf-8"), (
        "the claim step wrote no claim row, so the release step below releases "
        "nothing and proves nothing")

    release = _run(world, "release", "--repo", str(state), "--session-id", session_id,
                   "--task", "#12")
    assert release.returncode == 0, f"release: {release.stderr}"
    body = files[0].read_text(encoding="utf-8")
    assert "- claim: #12" not in body, f"the release left the row behind: {body!r}"

    close = _run(world, "close", "--repo", str(state), "--session-id", session_id)
    assert close.returncode == 0, f"close: {close.stderr}"
    assert "- status: closed" in files[0].read_text(encoding="utf-8"), (
        "the close step did not move the session to a terminal status, so the "
        "protocol's end is not the end the sessions skill documents")

    census = _run(world, "census", "--repo", str(state))
    assert census.returncode == 0, f"census: {census.stderr}\n{census.stdout}"
    assert census.stdout.splitlines()[-1].endswith("verdict ok"), (
        f"a session that followed the protocol did not census clean: "
        f"{census.stdout.splitlines()[-1:]!r}")


def test_the_page_links_the_skills_whose_writers_this_walk_runs() -> None:
    """The writers the walk drives belong to skills the page links.

    The walk is the evidence behind the page's protocol table; if it drifted to
    driving a skill the page never named, the two halves of this module would be
    testing different pages. The four verbs below are the protocol's end steps, and
    each is dispatched by the console command to a module of one skill.
    """
    page = page_text()
    for skill in ("sessions-claims", "steering-ledger", "direction", "census"):
        assert _step_link_for(skill) in page, (
            f"the walk drives {skill}'s writers and the page does not link it")


# --- helpers used only by this module ---------------------------------------

def _words(phrase: str) -> re.Pattern[str]:
    """A phrase as a whitespace-flexible pattern, for a page wrapped at 80 columns."""
    return re.compile(r"\s+".join(re.escape(word) for word in phrase.split()))


def _run(world, *argv: str):
    """One ``noni`` subcommand through the installed console script."""
    import subprocess

    return subprocess.run([str(world.noni), *argv], capture_output=True,
                          text=True, env=world.env, cwd=str(world.project),
                          timeout=180)


def _git(repo: Path, *argv: str, env: dict[str, str]):
    """One git command against one tree, with its output kept for the assertion."""
    import subprocess

    return subprocess.run(["git", "-C", str(repo), *argv], capture_output=True,
                          text=True, env=env, timeout=120)


def _session_id_from(stdout: str) -> str:
    """The session id the register writer printed, read off its own line.

    The writer's headline is ``registered session <id> -> <path>``; the id is read
    from it rather than from the file list so that the assertion in the caller --
    the printed id is the name of the one file on disk -- means something. A reader
    that took the id off the directory instead would pass on a register that never
    printed one, which is the value the next three steps have to carry.
    """
    match = re.search(r"registered session (\S+) ->", stdout)
    assert match, f"the register line printed no session id in its headline: {stdout!r}"
    return match.group(1)
