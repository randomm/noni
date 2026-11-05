"""The quickstart's prose promises, checked as text over the page.

``docs/QUICKSTART.md`` is the page a new team follows when the README's five
minutes are not enough. ``tests/test_quickstart.py`` runs its commands and settles
what a command can settle; this module reads the same page for the claims a command
cannot settle, and each of them was the cause of a real first-run failure a pilot hit
by following only the docs:

- **The install names a toolchain that survives an externally-managed Python.**
  ``python3 -m pip install ./noni`` -- the page's old form -- dies on the PEP 668
  marker current distributions put on their system interpreter, with no ``noni`` on
  the path and no hint why. The Install fences are compared against the golden list
  and never launched: :func:`quickstart_runner.install_commands` is the assert-only
  half, and :func:`quickstart_topology.install_venv` is the install the suite really
  runs for every other command on the page.
- **Both routes are named with their commands, and the page says where the writers
  commit before it asks a reader to choose one.** A project whose rules require a
  pull request cannot grant Route A's assumption, and a page that never said so left
  the team discovering it from a rejected push.
- **The deny-list, the ``--issue-state`` note and the three prerequisites are named
  in the words the product itself uses**, so a rename on the product side reddens a
  page rather than leaving it documenting a file nobody reads or a note nobody prints.

The page is this repository's own reviewed file, so nothing here defends against it;
the golden list in :mod:`quickstart_golden` makes the hostile-page question impossible
to ask, and these tests hold the prose to the product's constants.
"""

from __future__ import annotations

from _harness import REPO
from docs_commands import read
from docs_promises import (
    DENYLIST_STATES,
    PRODUCT,
    STATE_DIR,
)
from quickstart_page import ROUTE_CHOICE_CLOSE as _ROUTE_CHOICE_CLOSE
from quickstart_page import ROUTE_CHOICE_START as _ROUTE_CHOICE_START
from quickstart_page import flowed_section, page_text
from quickstart_runner import install_commands

from noni import public_safety


def _page() -> str:
    return page_text()


def test_the_page_covers_both_routes_the_issue_named() -> None:
    """Both state routes are named with their commands, not just described.

    The default route is in-project state; the second is a private state
    repository cloned inside the project as ``.noni-state`` with an ignore rule
    and a one-time first push. A page that dropped the ignore rule or the push
    would still read well and still leave a reader with a writer that fails.
    """
    text = _page()
    lowered = text.lower()
    for phrase in ("noni/", STATE_DIR):
        assert phrase in text, f"the quickstart does not name {phrase!r}"
    assert "gitignore" in lowered, "the ignore rule is not on the page"
    assert ".git/info/exclude" in text, (
        "the page has no ignore-rule variant for a PR-only project")
    assert "push -u origin" in text, "the one-time first push is not on the page"
    assert "--repo " + STATE_DIR in text, "the state-repo route has no --repo form"


def test_the_page_says_where_the_writers_commit_and_who_uses_route_b() -> None:
    """Before the routes are run, the page states the commit rule and its consequence.

    Every writer commits onto whatever branch the ``--repo`` tree has checked out (see
    ``current_branch`` and ``unsafe_branch_reason`` in ``src/noni/_session_push.py``),
    so Route A asks a project for direct commits to that branch. A branch-protected or
    PR-only project cannot grant that, and a page that never said so left a pilot team
    discovering it from a rejected push. Located by the clause's two pinned ends (see
    :mod:`quickstart_page`), so a page that lost the clause fails instead of passing on
    the sentences around it.
    """
    section = flowed_section("The state root")
    start = section.find(_ROUTE_CHOICE_START)
    assert start >= 0, (
        "the state-root section no longer states where the writers commit, in the "
        f"words the docs test pins ({_ROUTE_CHOICE_START!r})")
    clause = section[start:]
    close = clause.find(_ROUTE_CHOICE_CLOSE)
    assert close >= 0, (
        f"the commit-rule clause no longer recommends {_ROUTE_CHOICE_CLOSE!r} "
        "to a branch-protected or PR-only project")
    # Everything the clause says between its two pinned ends: the commit site, the
    # fact it never branches for you, and the two route recommendations it drives.
    between = clause[:close]
    for phrase in ("branch-protected", "PR-only", "Route A", "direct commits",
                   "never opens a branch"):
        assert phrase in between, (
            f"the pinned clause omits {phrase!r}, which is the fact the route "
            f"recommendation rests on: {between!r}")
    # The same rule, on the page the quickstart itself calls binding.
    product = flowed_section("7. State layout", read(PRODUCT))
    assert _ROUTE_CHOICE_START in product and _ROUTE_CHOICE_CLOSE in product, (
        "docs/PRODUCT.md 7 does not state the writers' commit rule the quickstart "
        "defers to it for")


def test_the_page_says_what_is_skipped_without_the_state_file() -> None:
    """The page states the census's own note text, and that it is human-readable
    output only.

    The census prints the note on stdout in human mode and nothing in ``--json``
    mode; a reader told only that "the check does not run" will go looking for it
    in a ``--json`` stream and conclude the census is silent. The literal is the
    product's own, so a rename of the note fails here rather than leaving the page
    quoting a line nobody prints.
    """
    source = (REPO / "src" / "noni" / "census_run.py").read_text(encoding="utf-8")
    assert "ordering-closed was not evaluated" in source, "the note left the product"
    text = _page()
    assert "ordering-closed was not evaluated" in text, "the page does not name the note"
    assert "never contacts a tracker" in text, "the page does not say why"
    assert "json" in text.lower(), "the page does not say the note is human-mode only"


def test_the_page_names_the_deny_list_a_strict_run_needs() -> None:
    """Where the page meets --strict and the hygiene class, it names the file.

    The name, the location and the purpose, plus the state a reader who "just
    created the file" lands in: a file of blanks and comments only is still
    inactive. The name is read from the product's own constant, so a rename fails
    the page rather than letting it document a file that no longer exists.
    """
    text = _page()
    assert public_safety.DENYLIST_FILENAME in text, (
        f"the page does not name {public_safety.DENYLIST_FILENAME!r}")
    assert public_safety.DENYLIST_ENV_VAR in text, (
        f"the page does not name the {public_safety.DENYLIST_ENV_VAR} route")
    assert public_safety.default_denylist_file(REPO).name in text
    lowered = text.lower()
    for phrase in (*DENYLIST_STATES, "#"):
        assert phrase in text or phrase in lowered, (
            f"the deny-list section does not mention {phrase!r}")


def test_the_install_block_installs_without_touching_the_system_python() -> None:
    """The Install fences are the reviewed ones, and none runs pip on a system Python.

    ``python3 -m pip install ./noni`` was the page's form, and on a distribution that
    marks its interpreter externally-managed it dies with no ``noni`` on the path --
    the first-run failure the pilot hit. The page now prints ``uv tool install`` and a
    clean-venv fallback, and the harness compares those fences against
    :mod:`quickstart_golden` without launching them: :func:`install_commands` runs the
    same golden comparison the launched sections pass through, and
    :func:`quickstart_topology.install_venv` is the install the suite really executes
    for every other command on the page.
    """
    commands = install_commands()
    installs = [argv for argv in commands if "install" in argv]
    assert len(installs) == 2, (
        f"the Install section must print the uv form and the clean-venv form, got "
        f"{installs}")
    assert ["uv", "tool", "install", "./noni"] in installs, installs
    for argv in installs:
        runner = argv[0]
        if runner == ".venv/bin/pip":
            continue
        assert runner == "uv", (
            f"an install command runs outside uv or the page's own venv, so it reaches "
            f"the system Python: {argv}")
    venv = [argv for argv in commands if argv[:3] == ["python3", "-m", "venv"]]
    assert venv, "the Install section prints no clean-venv fallback"
    assert any("pip" in argv[0] and argv[0].startswith(str(venv[0][3]))
               for argv in installs), (
        f"the pip form does not install from the venv the section just made: "
        f"{venv[0]} versus {installs}")
    text = _page()
    assert "externally-managed" in text, "the page does not name the failure it avoids"
    assert "python3-venv" in text, "the page omits the Debian/Ubuntu venv package"
    assert "half-made" in text, "the page does not warn about a venv that failed part way"


def test_the_page_says_no_package_index_carries_noni() -> None:
    """The install prose retracts the package-index claim instead of repeating it.

    ``pip install noni`` does not fail: it installs a different project's wheel
    and leaves the reader with a ``noni`` that has no census in it. The page has to
    say so, and give the forms that do work -- each of which names the clone, never
    an index.
    """
    lowered = _page().lower()
    assert "not published" in lowered, "the page does not say noni is absent from the index"
    installs = [argv for argv in install_commands() if "install" in argv]
    assert installs, "the Install section prints no install command"
    for argv in installs:
        assert "./noni" in argv, (
            f"an install command does not name the clone, so it names an index: {argv}")
    assert "PYTHONPATH" in _page(), "the page does not name the PYTHONPATH route"


def test_the_page_names_the_three_prerequisites() -> None:
    """jq, an identity in the state tree, and a Python 3 the wrapper can exec.

    Each one decides whether a first run works, and none of them is something noni
    can check for the reader before they type the command.
    """
    text = _page()
    assert "jq" in text, "the page does not name jq"
    assert "user.name" in text and "user.email" in text, "the page omits the git identity"
    assert "NONI_PYTHON" in text, "the page does not name the wrapper's interpreter variable"
