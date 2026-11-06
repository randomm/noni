"""The census never reads the ledger through the order writer's module.

``orderstate.py`` holds the ``order.py`` writer's reads, and one of them lists
the ledger with ``Path.glob`` — inside the writer's ``_successor``, where the
writer's own rules already answer "a ledger that cannot be listed answers
nothing" (it returns None, and the writer refuses the citation with its exit 4
rather than inventing an answer). That is the writer's business and its honest
one.

It is not the census's. Had the census shared that read, the census's ledger
probe, record pass and ordering readers would have been four callers of a
listing whose ``glob`` swallows the ``OSError`` a readdir raises and yields
nothing: the directory that exists and cannot be read would have reached the
arbiter as a project that has never steered anything, which is the exact
dishonesty ``census_ledger.listing_helper`` exists to prevent. The census has
its own listing; the writer keeps its own.

These two checks pin the seam from both sides, so the day someone "deduplicates"
them the failure names the side that moved.
"""

from __future__ import annotations

import ast

from _harness import REPO, SRC, _harness_source

CENSUS = REPO / "skills" / "census" / "scripts" / "census.py"
ORDERSTATE = SRC / "noni" / "orderstate.py"


def _imported_names(path) -> set[str]:
    """The module names ``path`` imports, from its own ``import`` statements.

    Read off the syntax tree rather than searched as text, so a docstring or a
    comment that mentions a module cannot satisfy the check the way a substring
    assertion would.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_census_never_reads_the_ledger_through_the_order_writer():
    """No census module imports ``orderstate``, or calls its ledger read.

    The direction the deduplication would go is the census reaching for the
    writer's ``_successor`` and its ``glob``. Neither import nor call may exist:
    the census's ledger reads live in ``census_ledger`` and reach the directory
    once, through the probe. The census modules are named here rather than
    globbed, so a module added to the package has to be named in this list to
    escape the check, and the gate's own list (``tests/_harness.py``) is what
    pins the list being complete.
    """
    census_src = _harness_source(CENSUS)
    assert "orderstate" not in census_src, "the census mentions the order writer"
    for name in ("census_hygiene", "census_json", "census_ledger", "census_ordering",
                 "census_ordering_readers", "census_sessions_checks",
                 "census_sessions_probe", "census_text", "census_wrapper"):
        path = SRC / "noni" / f"{name}.py"
        assert "orderstate" not in path.read_text(encoding="utf-8"), \
            f"{name}.py mentions the order writer"
        assert _imported_names(path) & {"orderstate"} == set(), \
            f"{name}.py imports the order writer"


def test_the_order_writer_keeps_its_own_ledger_read_and_its_honest_refusal():
    """The writer's ``glob`` is not a bug to fix while the census is being hardened.

    ``_successor`` lists the ledger with ``glob`` and answers None when the
    listing faults, which is the writer's documented behaviour: a ledger it
    cannot list answers nothing about which record supersedes which, and the
    writer refuses the citation (``tests/test_order_writer_add.py``,
    ``test_a_ledger_that_is_not_a_directory_cannot_be_looked_in`` and
    ``test_add_refuses_a_decision_that_matches_no_record``). The
    census must not acquire that read, and the writer must not be pulled into
    the census's probe for the sake of one shared call — it would give the
    writer's refusal path a dependency on the arbiter's probe.

    This pins the read where it is, so a future "share the helper" change is a
    decision someone has to argue for rather than a refactor that quietly
    changes what a writer run does.
    """
    source = ORDERSTATE.read_text(encoding="utf-8")
    assert "ledger.glob(" in source, \
        "the writer's ledger read moved; say where it went before dropping this"
    assert "census_ledger" not in source, \
        "the writer now depends on the census's listing: it must keep its own"
    assert _imported_names(ORDERSTATE) & {"census_ledger", "census"} == set(), \
        "the writer imports the arbiter's module"
