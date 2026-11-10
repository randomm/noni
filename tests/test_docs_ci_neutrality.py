"""The census-in-CI recipe: a neutral core page, a forge example under integrations/.

``tests/test_docs_promises.py`` checks what the pages promise about the things a
first run meets. This module holds the four checks the CI recipe adds, split out
because the rule they enforce is one rule with two halves and its own vocabulary:

- **The core stays CI-system-neutral** (AC4, negative half). No core page -- the
  README, CONTRIBUTING, ``docs/*.md``, any skill page -- carries one pipeline's
  vocabulary, and no bash fence on any of them carries a YAML line. A fence with a
  ``runs-on:`` in it fails both this gate and the quickstart's fence census, which
  compares every bash fence against the golden command lists.
- **The forge example exists where the purity rule puts it, and the core names it**
  (AC4, positive half). The example lives under ``integrations/``, is linked by
  path from the generic section, runs the census lines the page prints, and no
  workflow file of this repository was added to carry it -- that file is a gate
  file this ticket does not own.

The two pages are read with the same helpers the rest of the docs suite uses, and
the page's commands are taken from :mod:`quickstart_golden` through
:func:`quickstart_runner.route_commands`, so a step that drifted from the reviewed
line is caught where the line is pinned rather than here.
"""

from __future__ import annotations

import re

from _harness import REPO
from docs_commands import block_commands, fenced_blocks, fenced_pairs, read
from docs_promises import (
    DOC_PAGES,
    FORGE_CI_README,
    QUICKSTART,
    SKILL_PAGES,
    STATE_DIR,
    bash_blocks_text,
    section_body,
)
from quickstart_golden import CI
from quickstart_page import COEXISTENCE_HEADING, product_adapters_section
from quickstart_runner import route_commands

from noni import public_safety

# What one CI system's vocabulary looks like on a page. Each token is matched as a
# word, not as a substring: a gate that flagged the word "uses" in ordinary prose
# would be a gate a writer routes around by rewording. ``steps:`` is deliberately
# absent for that reason -- it is ordinary English -- and ``jobs:`` stays because no
# page here has cause to write it.
CI_TOKENS: tuple[str, ...] = ("runs-on:", "uses:", ".github/workflows",
                              "actions/checkout", "actions/setup-python",
                              "jobs:")

def _core_pages() -> list[tuple[str, str]]:
    """Every core page's text, labelled by its path from the repository root.

    The set is the docs suite's own ``DOC_PAGES`` plus every skill page, so the
    rule cannot be satisfied by leaving the recipe in a page the check does not
    read. ``FORGE_CI_README`` is absent by design: it is the one page the rule
    exempts, so it cannot also be one of the pages the rule clears.
    """
    return [(str(path.relative_to(REPO)), read(path))
            for path in (*DOC_PAGES, *SKILL_PAGES)]


def _ci_token() -> re.Pattern[str]:
    """One alternation of the CI tokens, each bounded on both sides.

    ``runs-on`` already carries a hyphen, so a ``\\b`` on its left would never
    match; the lookaround names the characters that may not touch a token instead.
    """
    return re.compile(r"(?<![\w./-])(?:{})(?![\w-])".format(
        "|".join(re.escape(token) for token in CI_TOKENS)))


# A line that reads as a YAML mapping key: an indent, a key, a colon, and nothing
# after it but a block scalar's indicator. ``#`` lines are excluded because a shell
# comment inside a fence is the page talking, and a fence whose content is comments
# is checked by the quickstart's own golden comparison.
_YAML_KEY = re.compile(r"^\s*[^#\s][^\n]*:\s*(\||>)?\s*$")


def test_no_core_page_carries_ci_system_vocabulary() -> None:
    """AC4, the negative half: the core pages stay neutral about CI systems.

    A page that gained a ``runs-on:`` line would be a page selling one team's
    pipeline to every reader, which is what the purity rule puts under
    ``integrations/`` instead. Read over every page the reader follows, not just
    the quickstart, because the recipe could have been written into any of them.
    """
    token = _ci_token()
    offenders = [(label, line.strip())
                 for label, text in _core_pages()
                 for line in text.splitlines() if token.search(line)]
    assert not offenders, (
        f"core pages carry CI-system vocabulary, which belongs under "
        f"integrations/: {offenders}")


def test_no_core_page_prints_yaml_in_a_bash_fence() -> None:
    """A bash fence holds shell, never a workflow fragment.

    Two gates meet in one rule. The quickstart's fence census compares every bash
    fence against the golden command lists, so a YAML line there would be a command
    no test runs; and a reader who copied YAML out of a shell block would get a
    syntax error. Checking every page's fences rather than the CI section alone is
    what stops the fragment appearing beside a different heading.
    """
    offenders: list[tuple[str, str]] = []
    for label, text in _core_pages():
        for block in bash_blocks_text(text):
            for line in block:
                if _YAML_KEY.match(line):
                    offenders.append((label, line.strip()))
    assert not offenders, (
        f"bash fences on core pages carry a YAML line, which is a CI example "
        f"that belongs under integrations/: {offenders}")


def test_the_quickstart_carries_a_census_in_ci_section() -> None:
    """AC1: the section exists, and its commands are the harness's golden ones.

    The heading is located the way the harness locates a section (by prefix, so a
    qualifier may follow it), and ``route_commands`` compares the page's fences
    against :mod:`quickstart_golden` before it returns anything, so this test asks
    only what the section must contain: one census line per route, each naming the
    route's own ``--repo``.
    """
    commands = route_commands(CI)
    census_lines = [argv for argv in commands if argv[:2] == ["noni", "census"]]
    assert len(census_lines) == 2, (
        f"the CI section must print one census line per route, got {census_lines}")
    assert [argv[3] for argv in census_lines] == [".", STATE_DIR], (
        f"the two routes must be the page's own --repo values: {census_lines}")


def test_the_ci_section_links_the_install_section_instead_of_reprinting_it() -> None:
    """AC1, the half that keeps the page from carrying the install twice.

    The clone-and-pip lines are golden-pinned under the Install heading; a second
    printed copy would be a second thing to review and a second thing to drift. The
    section names the install instead, and links it by the heading's own anchor so a
    rename breaks the link rather than quietly orphaning it.
    """
    section = section_body(read(QUICKSTART), CI[0])
    assert "Install" in section, "the CI section no longer points at the install"
    assert "#install-noni" in section, (
        "the CI section does not link the install section by its anchor")
    for fragment in ("git clone", "pip install"):
        assert fragment not in section, (
            f"the CI section reprints the install ({fragment!r}) instead of "
            f"linking the section that owns it")


def test_the_ci_section_names_the_hygiene_row_as_the_expected_first_run() -> None:
    """The row a first CI run prints, named as expected rather than as a failure.

    The hygiene class always reports, and on a CI checkout -- which has no
    deny-list -- its lone row is the inactive notice. A reader who was not told that
    reads exit 0 with a finding as a build that is about to break. The words are the
    product's own rendering, so a rename of the row fails here.
    """
    section = section_body(read(QUICKSTART), CI[0])
    lowered = section.lower()
    assert "deny-list class inactive" in section, (
        "the CI section no longer names the row a first run prints")
    assert "absent" in section, (
        "the CI section does not name the state the first run is in")
    assert "expected" in lowered, (
        "the CI section shows the inactive row without saying it is expected")
    assert "deny-list" in lowered, (
        "the CI section does not route the reader to the deny-list prose")


def test_the_forge_example_lives_under_integrations_and_is_linked() -> None:
    """AC4, the positive half: the forge-specific example exists, and the core names it.

    Three mechanical claims. The page sits under ``integrations/`` (not under
    ``.github/workflows/``, where a workflow file of this repository would be a gate
    file the ticket does not own); the quickstart's CI section names it by path, so a
    reader of the generic step reaches the copy for their own CI; and the example
    really does carry the vocabulary the core pages are kept free of, which is what
    makes it the example the rule allows rather than a copy of the generic step.
    """
    assert FORGE_CI_README.is_file(), (
        "the forge-specific CI example is missing from integrations/github-issues/")
    example = read(FORGE_CI_README)
    token = _ci_token()
    assert any(token.search(line) for line in example.splitlines()), (
        "the integrations/ example no longer carries the CI-system vocabulary the "
        "core pages are kept free of, so it is not the example the rule allows")
    section = section_body(read(QUICKSTART), CI[0])
    assert "integrations/github-issues/README.md" in section, (
        "the generic CI section does not name the forge example it is the reason for")
    assert not [p for p in (REPO / ".github" / "workflows").glob("*")
                if "census" in p.name.lower()], (
        "a census workflow file was added to this repository; the recipe ships as "
        "prose and as an integrations/ example, never as a workflow")


def test_the_forge_example_runs_the_page_s_own_census_commands() -> None:
    """The forge copy runs the step the core page prints, on both routes.

    The purity rule splits the pages, not the commands: the example may say
    ``runs-on:`` where the core may not, but a step that drifted from the census line
    the core sells would leave a reader gated on something no test runs. Both routes
    are checked, because Route B's whole correctness is its ``--repo`` -- an example
    that pointed the census at the code repository would report a clean verdict for a
    state tree it never read.
    """
    page = [argv for argv in route_commands(CI) if argv[:2] == ["noni", "census"]]
    steps = [argv for block in fenced_blocks(read(FORGE_CI_README), info="yaml")
             for argv in block_commands(block)]
    for census_argv in page:
        assert census_argv in steps, (
            f"the forge example does not run the page's census line "
            f"{' '.join(census_argv)}: {steps}")
    assert [argv[3] for argv in steps if argv[:2] == ["noni", "census"]] == [
        ".", STATE_DIR], f"the example's two routes are wrong: {steps}"


def test_the_forge_page_names_where_the_deny_list_lives_for_a_strict_run() -> None:
    """The forge copy tells a reader where the deny-list goes before it offers
    ``--strict``, and names both places the census will look.

    The step the page prints runs without ``--strict``, and the page says so; the
    half that was missing is what a team who later adds the flag has to do first.
    Under ``--strict`` the hygiene class fails the job on a tree with no usable
    deny-list entry, so an example that invites the opt-in without saying where the
    file lives leaves a reader with a red job and nothing to fix. Both sources are
    required -- the tree's own default file, at the root of the tree ``--repo``
    names, and the env var for a tree that carries no default -- because
    ``public_safety.load_denylist`` tries exactly those two, in that order. The
    names come from the product's constants, so a rename reddens the page rather
    than leaving it pointing at a file the census never opens.
    """
    text = read(FORGE_CI_README)
    assert public_safety.DENYLIST_FILENAME in text, (
        f"the forge page does not name {public_safety.DENYLIST_FILENAME!r}, so a "
        "team that adds --strict is told to create a file the page never locates")
    assert public_safety.DENYLIST_ENV_VAR in text, (
        f"the forge page does not name the {public_safety.DENYLIST_ENV_VAR} route, "
        "the one source available to a tree with no default deny-list of its own")
    # The location, not just the name: on Route B the audited tree is the state
    # clone, so the path the reader needs is the clone's own root.
    assert f"{STATE_DIR}/{public_safety.DENYLIST_FILENAME}" in text, (
        f"the forge page does not say the deny-list goes at the root of the tree "
        f"--repo names, as {STATE_DIR}/{public_safety.DENYLIST_FILENAME}")
    assert "usable entry" in text.lower(), (
        "the forge page offers --strict without naming its precondition, an "
        "inactive hygiene row fails the job however many files are present")
    # Ordering: the reader meets the flag's name before the location that unlocks
    # it -- the step is documented un-strict, and the deny-list is its opt-in.
    assert text.index(public_safety.DENYLIST_ENV_VAR) > text.index("`--strict`"), (
        "the forge page names the deny-list location before it introduces "
        "--strict, which reads as though the flag were the default step")


def test_the_coexistence_position_names_no_driver_and_stays_prose() -> None:
    """The coexistence position is written in driver-neutral words, and runs nothing.

    The section exists to tell a team with a work driver of their own which of
    noni's layers they still run, so the temptation it lives beside is the one this
    gate closes: naming the driver, and pasting that driver's commands onto a core
    page. Both halves are the purity rule's (docs/PRODUCT.md 3), and both are
    mechanical. The vocabulary sweep reuses :func:`_ci_token` over the one page set
    the neutrality gate already reads -- the same rule that keeps a pipeline's
    ``uses:`` off the core now keeps any driver's own verbs off it, and the section
    is written so a reader who brings a different driver still recognises it. The
    fence check is the section's own: its position is documentation, and a command
    line grown under this heading is one the launcher never runs.
    """
    token = _ci_token()
    # Located by the heading rather than asserted section-by-section: only the
    # quickstart carries this section, and ``docs_promises.section_body`` asserts a
    # page has the heading it was asked for -- a helper that keeps every other core
    # page's own sections honest would here fail on a README that never promised one.
    carrying = [(label, section_body(text, COEXISTENCE_HEADING))
                for label, text in _core_pages() if COEXISTENCE_HEADING in text]
    assert len(carrying) == 1, (
        f"exactly one core page carries the coexistence section, got "
        f"{len(carrying)}: the position belongs on the quickstart alone")
    offenders = [(label, line.strip())
                 for label, body in carrying for line in body.splitlines()
                 if token.search(line)]
    assert not offenders, (
        f"the coexistence section carries driver or CI-system vocabulary, which "
        f"belongs under integrations/: {offenders}")

    body = section_body(read(QUICKSTART), COEXISTENCE_HEADING)
    commands = [argv for info, lines in fenced_pairs(body) if info == "bash"
                for argv in block_commands(lines)]
    assert not commands, (
        f"the coexistence section prints {len(commands)} command(s) no golden list "
        f"covers, so the position has become a step nothing runs: {commands}")


def test_the_product_page_links_the_coexistence_position_in_one_paragraph() -> None:
    """The product page's adapters section points at the coexistence position.

    The adapters section is the binding page's own statement of what the adapters
    owe, so the coexistence line belongs inside it rather
    than as a free-floating note the reader meets somewhere else: a sentence about
    the adapter planted under a different heading would let the position be dropped
    from the adapters section while the page still read as if it were promised.
    Located word by word over the section, because the page wraps at its own
    column: the words are the contract and the line they broke on is not.
    """
    import re

    from quickstart_page import flowed_text

    section = flowed_text(product_adapters_section())
    heading = r"\s+".join(re.escape(word) for word in COEXISTENCE_HEADING.split())
    assert re.search(heading, section), (
        f"docs/PRODUCT.md's adapters section no longer names the coexistence "
        f"section, so the page does not point a reader at the position: {section!r}")
    assert "docs/QUICKSTART.md" in section, (
        "the adapters section names the section without naming the page that "
        "carries it, so the reference has nothing to resolve against")
    assert "driver" in section, (
        "the adapters section no longer names the driver whose coexistence this "
        f"is: {section!r}")

