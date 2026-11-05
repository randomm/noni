"""Reading the CI recipe's two pages, as data.

Two pages carry the census-in-CI recipe: the generic step in
``docs/QUICKSTART.md`` and the copy for one forge under ``integrations/``. Each
states the same two things in its own shape -- the exit codes a build fails on
and the codes it reports without failing -- and both test modules that police the
recipe need them as ``set[int]``, not as a regex each module re-derives. This
module owns that reading, and nothing else: no promise, no assertion about what
the sets must contain.

Why it lives here rather than in ``tests/test_quickstart_ci.py``: the module that
compares the documented sets against ``census_report.CHECKS`` is
``tests/test_census_check_contract.py``, and importing a page reader from a
``test_`` module drags that module's launches -- and through
:mod:`quickstart_runner` the session-scoped fixtures of ``conftest`` -- into a
contract test that runs no command. A non-test helper keeps the reader shareable
without that debt, on the precedent of ``tests/docs_promises.py`` and
``tests/docs_commands.py``.

The imports are deliberately the three page-reading modules and nothing more:
``quickstart_golden`` for the section key and ``quickstart_runner.route_commands``
for the golden-checked command parse. :mod:`quickstart_topology` and pytest are
absent on purpose, so importing this helper costs an import of the page readers.
"""

from __future__ import annotations

import re

from docs_commands import read
from docs_promises import FORGE_CI_README, QUICKSTART, section_body
from quickstart_golden import CI
from quickstart_runner import route_commands

# One bullet of the quickstart's CI section: the set is the run's verdict, so the
# page states it as a labelled pair rather than as prose. Each pattern is anchored
# on the bullet's own wording, so a rewrite that drops the set stops matching here
# rather than leaving the agreement test comparing an empty set against the table.
# Public because the test that pins the section's shape searches the whole page with
# them, to show a stray bullet outside the section is a stray and not a set.
FAIL_SET_PATTERN = re.compile(r"\*\*fail the build\*\* on ([\d, and]+);")
WARN_SET_PATTERN = re.compile(r"\*\*report without failing\*\* on ([\d, and]+)\.")

# The forge page's one clause, which states both sets in a sentence rather than as
# two bullets: "fail on 10, 12, ... and 32, and report without failing on 40, ...
# and 50." Two groups in one pattern, because the two sets sit in one sentence and a
# per-set pattern would match a page that printed only one of them.
#
# ``\s+`` after each lead-in and ``\n`` in each class because the page wraps mid-set
# -- a pattern that insisted on one space would fail on the page exactly as it
# stands -- and lazy because the first set ends at the " and report without failing
# on" that follows it, not at the full stop that ends the sentence. " and " is part
# of the class so a mutation that drops a leading code ("15,") or a trailing one
# ("and 50") still matches and yields a short set the table comparison reddens,
# rather than a shape this reader refuses to parse.
_FORGE_SETS = re.compile(
    r"fail on\s+([\d, and\n]+?), and report without failing on\s+([\d, and\n]+?)\.")


def ci_commands() -> list[list[str]]:
    """The CI section's commands, as the page prints them (golden-checked).

    Public because both consumers check the documented step against the very lines
    the launcher runs: the same parsed argv, not a second reading of the fences.
    """
    return route_commands(CI)


def ci_section() -> str:
    """The CI section's own text, located by its heading.

    Scoped by the heading the golden list keys the section on, so a set written
    beside a different heading is not this section's set.
    """
    return section_body(read(QUICKSTART), CI[0])


def documented_code_set(pattern: re.Pattern[str], *, where: str) -> set[int]:
    """The codes the CI section prints, read out of the page.

    Located by the bullet's own wording, and scoped to the CI section rather than
    searched over the whole page: a third set bullet anywhere on ``QUICKSTART.md``
    -- a set the section never promises -- is caught here rather than silently
    accepted by whichever match came first. Two bullets is therefore the only
    documentable shape, and a page that grows a third fails with this message.
    """
    body = ci_section()
    matches = pattern.findall(body)
    assert len(matches) == 1, (
        f"{where}: the CI section must print its codes exactly once as "
        f"{pattern.pattern!r}, found {len(matches)} in the section")
    tokens = re.findall(r"\d+", matches[0])
    assert tokens, f"{where}: the documented set is empty: {matches[0]!r}"
    return {int(token) for token in tokens}


def documented_fail_codes() -> set[int]:
    """The codes the CI section says fail a build."""
    return documented_code_set(FAIL_SET_PATTERN, where="docs/QUICKSTART.md")


def documented_warn_codes() -> set[int]:
    """The codes the CI section says a build reports without failing."""
    return documented_code_set(WARN_SET_PATTERN, where="docs/QUICKSTART.md")


def forge_documented_codes() -> tuple[set[int], set[int]]:
    """The forge page's ``(fail, warn)`` codes, read out of its own prose.

    The forge page states both sets in one sentence, so one pattern carries both
    groups and the pair is returned together: a page that printed one set without
    the other stops matching and fails here, rather than handing the caller an
    empty set for the missing half. The page sits outside ``docs_promises``'
    ``DOC_PAGES`` on purpose -- it is the page the neutrality gate exempts -- so
    this reader names it explicitly: a gate written over ``DOC_PAGES`` would pass
    while this page drifted.
    """
    match = _FORGE_SETS.search(read(FORGE_CI_README))
    assert match, (
        f"{FORGE_CI_README.name} no longer states both sets in one sentence shaped "
        f"like {_FORGE_SETS.pattern!r}, so the page's exit codes are documented in "
        "a shape no test reads")
    pairs = [(re.findall(r"\d+", group), group) for group in match.groups()]
    for tokens, group in pairs:
        assert tokens, (
            f"{FORGE_CI_README.name}: the documented set is empty: {group!r}")
    return ({int(token) for token in pairs[0][0]},
            {int(token) for token in pairs[1][0]})
